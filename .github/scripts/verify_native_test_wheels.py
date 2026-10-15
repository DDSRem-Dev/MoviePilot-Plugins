import argparse
import json
from importlib import import_module
from importlib.metadata import distribution
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import url2pathname


def main() -> None:
    """
    校验原生扩展来自本次测试构建的 wheel 并验证导入
    """
    parser = argparse.ArgumentParser(description="校验原生扩展的测试构建来源")
    parser.add_argument("wheel_directory", type=Path)
    args = parser.parse_args()
    wheel_directory = args.wheel_directory.resolve(strict=True)

    for name in ("full_strm_sync", "txt_tree_storage", "share_strm_scan"):
        installed = distribution(name)
        wheels = list(wheel_directory.glob(f"{name}-{installed.version}-*.whl"))
        if len(wheels) != 1:
            raise RuntimeError(
                f"{name}: 预期一个匹配已安装版本的测试 wheel，实际为 {wheels}"
            )

        direct_url = json.loads(installed.read_text("direct_url.json") or "{}")
        source = urlsplit(direct_url.get("url", ""))
        if (
            source.scheme != "file"
            or Path(url2pathname(source.path)).resolve() != wheels[0].resolve()
        ):
            raise RuntimeError(
                f"{name}: 未安装本次构建的 wheel，安装来源为 {direct_url}"
            )

        module = import_module(name)
        print(f"{name} {installed.version}: {wheels[0]} -> {module.__file__}")


if __name__ == "__main__":
    main()
