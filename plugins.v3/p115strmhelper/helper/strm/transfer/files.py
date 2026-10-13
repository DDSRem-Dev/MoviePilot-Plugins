from contextlib import contextmanager, ExitStack
from hashlib import sha256
from os import fstat, fsync, name as os_name, replace
from pathlib import Path
from tempfile import gettempdir
from time import monotonic, sleep
from typing import Any, Dict, Generator, List, Optional

from ....db_manager.transfer_postprocess import resource_key


@contextmanager
def lock_libraries(roots: List[str]) -> Generator[None, None, None]:
    """
    锁定媒体库所在卷，避免嵌套映射及分身使用不同根目录时并发修改
    """
    directory = Path(gettempdir()) / "p115strmhelper-transfer-locks"
    directory.mkdir(exist_ok=True)
    with ExitStack() as stack:
        for key in sorted({resource_key(Path(Path(root).anchor)) for root in roots}):
            handle = stack.enter_context(open(directory / key, "a+b"))
            if os_name == "nt":
                import msvcrt

                if not handle.seek(0, 2):
                    handle.write(b"0")
                    handle.flush()
                deadline = monotonic() + 120
                while True:
                    handle.seek(0)
                    try:
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError:
                        if monotonic() >= deadline:
                            raise TimeoutError("整理后处理等待媒体库锁超时")
                        sleep(0.05)

                def unlock(file: Any = handle) -> None:
                    file.seek(0)
                    msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)

                stack.callback(unlock)
            else:
                import fcntl

                deadline = monotonic() + 120
                while True:
                    try:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        if monotonic() >= deadline:
                            raise TimeoutError("整理后处理等待媒体库锁超时")
                        sleep(0.05)
                stack.callback(fcntl.flock, handle.fileno(), fcntl.LOCK_UN)
        yield


def fingerprint(path: Path) -> Optional[Dict[str, Any]]:
    """
    同时记录文件内容与文件系统身份，拒绝跟随符号链接
    """
    if path.is_symlink():
        raise RuntimeError(f"后处理路径是符号链接，拒绝修改: {path}")
    try:
        with path.open("rb") as source:
            before = fstat(source.fileno())
            digest = sha256()
            while block := source.read(1024 * 1024):
                digest.update(block)
            after = path.stat()
    except FileNotFoundError:
        return None
    if (before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise RuntimeError(f"后处理读取期间文件发生变化: {path}")
    return {
        "sha256": digest.hexdigest(),
        "size": after.st_size,
        "mtime_ns": after.st_mtime_ns,
        "inode": after.st_ino,
        "device": after.st_dev,
    }


def validate_path(path: Path, roots: List[str]) -> None:
    """
    每次操作前确认固定路径仍在原媒体库内且未被符号链接替换
    """
    absolute = path.absolute()
    if absolute != path.resolve() or not any(
        absolute.is_relative_to(Path(root)) and absolute != Path(root) for root in roots
    ):
        raise RuntimeError(f"后处理路径越界或包含符号链接: {path}")


def publish_file(staged: Path, target: Path) -> None:
    """
    刷新暂存文件后原子替换目标，避免中断留下半个字幕或 STRM
    """
    with staged.open("r+b") as source:
        fsync(source.fileno())
    replace(staged, target)
