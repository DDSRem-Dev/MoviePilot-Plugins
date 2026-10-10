use std::fs::File;
use std::io::Read;
use std::path::{Path, PathBuf};

use ahash::{AHashMap, AHashSet};
use rayon::prelude::*;
use rayon::ThreadPoolBuilder;
use walkdir::WalkDir;

use crate::query::parse_share_strm_line;

fn strip_bom_bytes(buf: &[u8]) -> &[u8] {
    if buf.starts_with(b"\xEF\xBB\xBF") {
        &buf[3..]
    } else {
        buf
    }
}

fn read_bounded(path: &Path, max: usize) -> std::io::Result<Vec<u8>> {
    let f = File::open(path)?;
    let mut buf = Vec::new();
    let meta = f.metadata().ok();
    let hint = meta.map(|m| (m.len() as usize).min(max)).unwrap_or(0);
    if hint > 0 {
        buf.reserve(hint.min(max));
    }
    let mut take = f.take(max as u64);
    take.read_to_end(&mut buf)?;
    Ok(buf)
}

fn is_strm_extension(path: &Path) -> bool {
    path.extension()
        .and_then(|e| e.to_str())
        .map(|e| e.eq_ignore_ascii_case("strm"))
        .unwrap_or(false)
}

pub fn process_file_contents(bytes: &[u8]) -> AHashSet<(String, String)> {
    let mut out = AHashSet::new();
    let bytes = strip_bom_bytes(bytes);
    let s = match std::str::from_utf8(bytes) {
        Ok(s) => s,
        Err(_) => return out,
    };
    let s = s.trim();
    if s.is_empty() {
        return out;
    }
    for line in s.lines() {
        let line = line.trim_end_matches('\r').trim();
        if line.is_empty() {
            continue;
        }
        if let Some(pair) = parse_share_strm_line(line) {
            out.insert(pair);
        }
    }
    out
}

pub fn process_file_pair_paths(
    path: &Path,
    max_file_bytes: usize,
) -> AHashMap<(String, String), Vec<PathBuf>> {
    let buf = match read_bounded(path, max_file_bytes) {
        Ok(b) => b,
        Err(_) => return AHashMap::new(),
    };
    let pairs = process_file_contents(&buf);
    let mut out: AHashMap<(String, String), Vec<PathBuf>> = AHashMap::new();
    for pair in pairs {
        out.entry(pair).or_default().push(path.to_path_buf());
    }
    out
}

fn merge_path_maps(
    mut a: AHashMap<(String, String), Vec<PathBuf>>,
    b: AHashMap<(String, String), Vec<PathBuf>>,
) -> AHashMap<(String, String), Vec<PathBuf>> {
    if a.len() < b.len() {
        return merge_path_maps(b, a);
    }
    for (k, v) in b {
        a.entry(k).or_default().extend(v);
    }
    a
}

fn finalize_pair_paths_map(
    mut map: AHashMap<(String, String), Vec<PathBuf>>,
) -> AHashMap<(String, String), Vec<String>> {
    let mut out: AHashMap<(String, String), Vec<String>> = AHashMap::with_capacity(map.len());
    for (pair, mut paths) in map.drain() {
        paths.sort();
        paths.dedup();
        let strings: Vec<String> = paths
            .into_iter()
            .map(|p| p.to_string_lossy().into_owned())
            .collect();
        out.insert(pair, strings);
    }
    out
}

pub fn collect_strm_paths(root: &Path) -> std::io::Result<Vec<PathBuf>> {
    let mut paths = Vec::new();
    for entry in WalkDir::new(root)
        .follow_links(false)
        .into_iter()
        .filter_map(|e| e.ok())
    {
        if !entry.file_type().is_file() {
            continue;
        }
        let p = entry.path();
        if is_strm_extension(p) {
            paths.push(p.to_path_buf());
        }
    }
    Ok(paths)
}

fn scan_pool_error() -> std::io::Error {
    std::io::Error::new(std::io::ErrorKind::Other, "thread pool build failed")
}

pub fn scan_share_strm_index_inner(
    root: &Path,
    max_file_bytes: usize,
    num_threads: Option<usize>,
) -> Result<
    (
        Vec<(String, String)>,
        AHashMap<(String, String), Vec<String>>,
    ),
    std::io::Error,
> {
    let paths = collect_strm_paths(root)?;
    let merged_map = if let Some(n) = num_threads {
        if n < 1 {
            return Err(std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                "num_threads must be >= 1",
            ));
        }
        let pool = ThreadPoolBuilder::new()
            .num_threads(n)
            .build()
            .map_err(|_| scan_pool_error())?;
        pool.install(|| {
            paths
                .par_iter()
                .map(|p| process_file_pair_paths(p, max_file_bytes))
                .reduce(AHashMap::new, merge_path_maps)
        })
    } else {
        paths
            .par_iter()
            .map(|p| process_file_pair_paths(p, max_file_bytes))
            .reduce(AHashMap::new, merge_path_maps)
    };
    let map = finalize_pair_paths_map(merged_map);
    let mut pairs: Vec<_> = map.keys().cloned().collect();
    pairs.sort();
    Ok((pairs, map))
}

pub fn scan_share_strm_pairs_inner(
    root: &Path,
    max_file_bytes: usize,
    num_threads: Option<usize>,
) -> Result<Vec<(String, String)>, std::io::Error> {
    let (pairs, _) = scan_share_strm_index_inner(root, max_file_bytes, num_threads)?;
    Ok(pairs)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    #[test]
    fn process_multiline_dedup_in_file() {
        let s = b"http://x/P115StrmHelper?share_code=a&receive_code=b\nhttp://x/P115StrmHelper?share_code=a&receive_code=b\n";
        let set = process_file_contents(s);
        assert_eq!(set.len(), 1);
    }

    #[test]
    fn merge_path_maps_two_files_same_pair() {
        let mut a = AHashMap::new();
        a.insert(("sc".into(), "rc".into()), vec![PathBuf::from("/a/x.strm")]);
        let mut b = AHashMap::new();
        b.insert(("sc".into(), "rc".into()), vec![PathBuf::from("/b/y.strm")]);
        let m = merge_path_maps(a, b);
        let paths = m.get(&("sc".into(), "rc".into())).unwrap();
        assert_eq!(paths.len(), 2);
    }

    #[test]
    fn scan_index_nested_two_strm_one_pair() {
        let root = std::env::temp_dir().join(format!(
            "share_strm_scan_test_{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let _ = fs::remove_dir_all(&root);
        let sub = root.join("media").join("a");
        fs::create_dir_all(&sub).unwrap();
        let url = "http://127.0.0.1:3000/api/v1/plugin/P115StrmHelper/redirect_url?share_code=sc1&receive_code=r1&id=99";
        fs::write(sub.join("a.strm"), format!("{url}\n")).unwrap();
        fs::write(sub.join("dup.strm"), format!("{url}\n")).unwrap();
        let (pairs, map) = scan_share_strm_index_inner(&root, 262_144, None).expect("scan");
        let _ = fs::remove_dir_all(&root);
        assert_eq!(pairs, vec![("sc1".into(), "r1".into())]);
        let paths = map.get(&("sc1".into(), "r1".into())).unwrap();
        assert_eq!(paths.len(), 2);
    }
}
