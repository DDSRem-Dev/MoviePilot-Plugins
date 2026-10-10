mod query;
mod scan;

use pyo3::prelude::*;
use pyo3::wrap_pyfunction;
use std::collections::HashMap;
use std::path::PathBuf;

#[pyfunction]
#[pyo3(signature = (root, *, max_file_bytes=262_144u32, num_threads=None))]
fn scan_share_strm_pairs(
    py: Python<'_>,
    root: PathBuf,
    max_file_bytes: u32,
    num_threads: Option<usize>,
) -> PyResult<Vec<(String, String)>> {
    let max = max_file_bytes as usize;
    py.detach(|| {
        scan::scan_share_strm_pairs_inner(&root, max, num_threads)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyOSError, _>(e.to_string()))
    })
}

#[pyfunction]
#[pyo3(signature = (root, *, max_file_bytes=262_144u32, num_threads=None))]
fn scan_share_strm_index(
    py: Python<'_>,
    root: PathBuf,
    max_file_bytes: u32,
    num_threads: Option<usize>,
) -> PyResult<(
    Vec<(String, String)>,
    HashMap<(String, String), Vec<String>>,
)> {
    let max = max_file_bytes as usize;
    py.detach(|| {
        scan::scan_share_strm_index_inner(&root, max, num_threads)
            .map(|(pairs, ahash_map)| {
                let map: HashMap<_, _> = ahash_map.into_iter().collect();
                (pairs, map)
            })
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyOSError, _>(e.to_string()))
    })
}

#[pymodule]
fn _share_strm_scan(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    m.add_function(wrap_pyfunction!(scan_share_strm_pairs, m)?)?;
    m.add_function(wrap_pyfunction!(scan_share_strm_index, m)?)?;
    Ok(())
}
