use std::borrow::Cow;

use memchr::memmem;
use url::Url;

const NEEDLE_P115: &[u8] = b"P115StrmHelper";
const NEEDLE_SHARE: &[u8] = b"share_code=";
const NEEDLE_RECV: &[u8] = b"receive_code=";

pub fn gate_share_strm(line: &[u8]) -> bool {
    if memmem::find(line, NEEDLE_P115).is_none() {
        return false;
    }
    if memmem::find(line, NEEDLE_SHARE).is_none() {
        return false;
    }
    memmem::find(line, NEEDLE_RECV).is_some()
}

pub fn extract_query_string(line: &str) -> Option<Cow<'_, str>> {
    if let Ok(u) = Url::parse(line) {
        if let Some(q) = u.query() {
            if !q.is_empty() {
                return Some(Cow::Owned(q.to_string()));
            }
        }
    }
    if line.contains('?') {
        let rest = line.split_once('?').map(|(_, r)| r)?;
        let end = rest.find('#').unwrap_or(rest.len());
        return Some(Cow::Borrowed(&rest[..end]));
    }
    None
}

pub fn parse_share_pair_from_query(query: &str) -> Option<(String, String)> {
    let mut share: Option<String> = None;
    let mut recv: Option<String> = None;
    for (k, v) in url::form_urlencoded::parse(query.as_bytes()) {
        if k == "share_code" && share.is_none() {
            share = Some(v.into_owned());
        } else if k == "receive_code" && recv.is_none() {
            recv = Some(v.into_owned());
        }
        if share.is_some() && recv.is_some() {
            break;
        }
    }
    let s = share?;
    let r = recv?;
    if s.is_empty() || r.is_empty() {
        return None;
    }
    Some((s, r))
}

pub fn parse_share_strm_line(line: &str) -> Option<(String, String)> {
    if !gate_share_strm(line.as_bytes()) {
        return None;
    }
    let q = extract_query_string(line)?;
    parse_share_pair_from_query(q.as_ref())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn gate_requires_plugin_name() {
        assert!(!gate_share_strm(b"http://x?share_code=a&receive_code=b"));
        assert!(gate_share_strm(
            b"http://h/api/v1/plugin/P115StrmHelper/x?share_code=a&receive_code=b"
        ));
    }

    #[test]
    fn extract_query_fallback_like_python() {
        let line_with_plugin = "fooP115StrmHelper?share_code=x&receive_code=y";
        assert!(gate_share_strm(line_with_plugin.as_bytes()));
        let q = extract_query_string(line_with_plugin).unwrap();
        assert_eq!(q.as_ref(), "share_code=x&receive_code=y");
    }

    #[test]
    fn full_url_parse() {
        let line = "http://127.0.0.1:3000/api/v1/plugin/P115StrmHelper/redirect_url?share_code=sc&receive_code=rc&id=1";
        let p = parse_share_strm_line(line).unwrap();
        assert_eq!(p.0, "sc");
        assert_eq!(p.1, "rc");
    }
}
