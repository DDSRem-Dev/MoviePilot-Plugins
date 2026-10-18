"""
按宿主版本构建插件前端并复制到对应后端发布目录
"""

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List


FRONTEND_ROOTS = {
    "plugins": "frontend",
    "plugins.v2": "frontend.v2",
    "plugins.v3": "frontend.v3",
}
REPOSITORY = Path(__file__).resolve().parents[2]


def get_frontend_path(source_directory: str, plugin: str) -> str:
    """
    将后端发布目录映射到同版本前端，不回退到其他版本
    """
    if source_directory not in FRONTEND_ROOTS:
        raise ValueError(f"不支持的插件目录: {source_directory}")
    if not re.fullmatch(r"[a-z][a-z0-9_]*", plugin):
        raise ValueError(f"无效的插件目录名: {plugin}")
    return f"{FRONTEND_ROOTS[source_directory]}/{plugin}"


def list_frontends(repository: Path) -> List[Dict[str, str]]:
    """
    为持续集成列出具有独立依赖清单的插件前端
    """
    result = []
    for source_directory, frontend_root in FRONTEND_ROOTS.items():
        for package in sorted((repository / frontend_root).glob("*/package.json")):
            plugin = package.parent.name
            result.append(
                {
                    "source_directory": source_directory,
                    "plugin": plugin,
                    "frontend_path": get_frontend_path(source_directory, plugin),
                }
            )
    return result


def build_frontend(
    repository: Path, source_directory: str, plugin: str, install: bool = True
) -> Path:
    """
    构建指定版本前端，验证联邦模块入口后更新对应插件的 dist

    :param repository (Path): 仓库根目录
    :param source_directory (str): 后端版本目录
    :param plugin (str): 插件小写目录名
    :param install (bool): 是否使用 npm ci 安装锁定依赖

    :return Path: 后端前端产物目录
    """
    frontend = repository / get_frontend_path(source_directory, plugin)
    backend = repository / source_directory / plugin
    for required in (
        frontend / "package.json",
        frontend / "package-lock.json",
        backend / "__init__.py",
    ):
        if not required.is_file():
            raise FileNotFoundError(f"缺少构建文件: {required}")
    npm = shutil.which("npm")
    if not npm:
        raise RuntimeError("未找到 npm，请先安装 Node.js")
    if install:
        subprocess.run([npm, "ci", "--no-audit", "--no-fund"], cwd=frontend, check=True)
    dist = frontend / "dist"
    if dist.exists():
        shutil.rmtree(dist)
    subprocess.run([npm, "run", "build"], cwd=frontend, check=True)
    if not (dist / "assets/remoteEntry.js").is_file():
        raise RuntimeError(f"构建产物缺少 dist/assets/remoteEntry.js: {frontend}")
    destination = backend / "dist"
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(dist, destination)
    return destination


def main() -> None:
    """
    提供本地与持续集成共用的构建及矩阵发现入口
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="输出前端构建矩阵")
    parser.add_argument("--source-directory", choices=FRONTEND_ROOTS)
    parser.add_argument("--plugin", help="插件小写目录名")
    parser.add_argument(
        "--skip-install", action="store_true", help="复用当前版本已安装的依赖"
    )
    args = parser.parse_args()
    if args.list:
        print(json.dumps(list_frontends(REPOSITORY)))
        return
    if not args.source_directory or not args.plugin:
        parser.error("构建时必须指定 --source-directory 和 --plugin")
    destination = build_frontend(
        REPOSITORY, args.source_directory, args.plugin, install=not args.skip_install
    )
    print(f"前端构建完成: {destination.relative_to(REPOSITORY)}")


if __name__ == "__main__":
    main()
