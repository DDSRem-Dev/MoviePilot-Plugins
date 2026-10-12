"""
生成 115 STRM 助手 V3 全文件清单和逐调用核查输入
"""

import argparse
import ast
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List
from zipfile import ZipFile


def scan_python(path: Path) -> Dict[str, Any]:
    """
    提取所有导入、函数签名和调用位置，不将静态扫描视为兼容验证

    :param path (Path): Python 源文件

    :return Dict: 模块核查输入
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports = []
    functions = []
    calls = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.append({"line": node.lineno, "statement": ast.unparse(node)})
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(
                {
                    "line": node.lineno,
                    "end_line": node.end_lineno,
                    "name": node.name,
                    "arguments": ast.unparse(node.args),
                    "async": isinstance(node, ast.AsyncFunctionDef),
                }
            )
        elif isinstance(node, ast.Call):
            calls.append(
                {
                    "line": node.lineno,
                    "target": ast.unparse(node.func),
                    "positional": [ast.unparse(arg) for arg in node.args],
                    "keywords": [
                        {"name": item.arg, "value": ast.unparse(item.value)}
                        for item in node.keywords
                    ],
                }
            )
    return {
        "imports": sorted(imports, key=lambda item: item["line"]),
        "functions": sorted(functions, key=lambda item: item["line"]),
        "calls": sorted(calls, key=lambda item: item["line"]),
    }


def scan_repository(repository: Path) -> List[Dict[str, Any]]:
    """
    覆盖 V3 插件全部受管文件及未忽略新文件，并记录原生包元数据

    :param repository (Path): 插件仓库根目录

    :return List: 按相对路径排序的文件清单
    """
    targets = [
        "plugins.v3/p115strmhelper",
        "frontend/p115strmhelper",
        "dev/p115strmhelper",
        "dev/prepare_plugin_deps.py",
        ".github/workflows/test-p115strmhelper.yml",
        ".github/workflows/rust_build_share_strm_scan.yml",
        ".github/workflows/rust_build_txt_tree_storage.yml",
        ".github/workflows/rust_build_full_sync_strm.yml",
    ]
    names = (
        subprocess.check_output(
            [
                "git",
                "ls-files",
                "-z",
                "--cached",
                "--others",
                "--exclude-standard",
                *targets,
            ],
            cwd=repository,
        )
        .decode()
        .split("\0")
    )
    entries = []
    for name in sorted(set(filter(None, names))):
        path = repository / name
        if not path.is_file():
            continue
        entry = {
            "path": str(path.relative_to(repository)),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "size": path.stat().st_size,
        }
        if path.suffix == ".py":
            entry.update(scan_python(path))
        elif path.suffix == ".whl":
            with ZipFile(path) as wheel:
                entry["wheel_metadata"] = {
                    item: wheel.read(item).decode("utf-8")
                    for item in wheel.namelist()
                    if item.endswith((".dist-info/WHEEL", ".dist-info/METADATA"))
                }
        entries.append(entry)
    return entries


def main() -> None:
    """
    写出可重建的调用清单供逐模块对照宿主源码
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="JSON 输出文件路径")
    args = parser.parse_args()
    repository = Path(__file__).resolve().parents[1]
    entries = scan_repository(repository)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"文件 {len(entries)}；Python {sum('calls' in entry for entry in entries)}；"
        f"调用 {sum(len(entry.get('calls', [])) for entry in entries)}；"
        f"输出 {args.output}"
    )


if __name__ == "__main__":
    main()
