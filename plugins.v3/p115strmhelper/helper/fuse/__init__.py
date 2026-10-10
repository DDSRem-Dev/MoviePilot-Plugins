__author__ = "ChenyangGao <https://chenyanggao.github.io>"
__license__ = "GPLv3 <https://www.gnu.org/licenses/gpl-3.0.txt>"
__all__ = ["P115FuseOperations", "FUSE_AVAILABLE"]

from errno import EIO, ENOENT, ENOTDIR
from collections.abc import Callable, Mapping
from functools import wraps
from itertools import count
from os import PathLike
from os.path import exists
from posixpath import split as splitpath
from shutil import rmtree
from stat import S_IFDIR, S_IFREG
from time import sleep
from typing import Any
from uuid import uuid4

try:
    from mfusepy import FUSE, Operations

    FUSE_AVAILABLE = True
except (ImportError, OSError):
    FUSE = None
    Operations = None
    FUSE_AVAILABLE = False

from orjson import dumps
from p115client import P115Client

from app.log import logger
from app.core.cache import TTLCache

from ...core.cache import IntKeyCacheAdapter
from ...core.config import configer
from ...utils.sentry import sentry_manager


def _safe_repr(obj: Any) -> Any:
    """
    安全地表示对象
    """
    if isinstance(obj, bytes):
        return f"<bytes: {len(obj)} bytes>"
    elif isinstance(obj, (list, tuple)):
        return type(obj)(_safe_repr(item) for item in obj)
    elif isinstance(obj, dict):
        return {k: _safe_repr(v) for k, v in obj.items()}
    else:
        return obj


def log(func=None, *, level=None):
    """
    访问日志装饰器
    """

    def decorator(f):
        """
        为被装饰函数包装访问日志记录

        :param f (Callable): 原始函数
        :return Callable: 包装后的函数
        """

        @wraps(f)
        def wrapper(*args, **kwargs):
            """
            执行原函数并记录调用参数与返回值

            :param args (Tuple): 位置参数
            :param kwargs (Dict): 关键字参数
            :return Any: 原函数的返回值
            """
            try:
                result = f(*args, **kwargs)
                if level is None:
                    safe_args = _safe_repr(args)
                    safe_kwargs = _safe_repr(kwargs)
                    safe_result = _safe_repr(result)
                    logger.debug(
                        f"{f.__name__} called with args={safe_args}, kwargs={safe_kwargs}, result={safe_result}"
                    )
                return result
            except Exception as e:
                try:
                    error_msg = str(e)
                except (UnicodeDecodeError, UnicodeError):
                    error_msg = f"<Exception: {type(e).__name__}>"
                logger.error(f"{f.__name__} failed: {error_msg}", exc_info=True)
                sentry_manager.sentry_hub.capture_exception(e)
                raise

        return wrapper

    if func is None:
        return decorator
    else:
        return decorator(func)


def attr_to_stat(attr: Mapping, /, uid: int = 0, gid: int = 0) -> dict:
    """
    将 115 文件属性转换为 FUSE stat 结构

    :param attr (Mapping): 115 文件属性字典
    :param uid (int): 文件所有者 UID
    :param gid (int): 文件所有者 GID
    :return Dict: FUSE stat 字典
    """
    return {
        "st_mode": (S_IFDIR if attr["is_dir"] else S_IFREG) | 0o777,
        "st_ino": attr["id"],
        "st_dev": 0,
        "st_nlink": 1,
        "st_uid": uid,
        "st_gid": gid,
        "st_size": attr.get("size") or 0,
        "st_atime": attr.get("atime") or attr.get("mtime") or 1.0,
        "st_mtime": attr.get("mtime") or 1.0,
        "st_ctime": attr.get("ctime") or 1.0,
        "xattr": attr,
    }


if not FUSE_AVAILABLE:

    class Operations:
        """
        占位基类，当 mfusepy 不可用时使用
        """

        pass


class P115FuseOperations(Operations):
    """
    115 网盘 FUSE 文件系统操作实现

    继承自 mfusepy.Operations，实现标准的 FUSE 文件系统回调方法。
    支持文件/目录的读取、写入、重命名、删除等操作。
    """

    def __init__(
        self,
        /,
        client: str | PathLike | P115Client = None,
        readdir_ttl: float = 60,
        uid: int = 0,
        gid: int = 0,
    ):
        """
        初始化 FUSE 操作类

        :param client (Any): P115Client 实例或 cookie 字符串/路径
        :param readdir_ttl (float): 目录读取缓存 TTL（秒）
        :param uid (int): 文件所有者 UID
        :param gid (int): 文件所有者 GID
        """
        if not FUSE_AVAILABLE:
            raise ImportError(
                "FUSE 功能不可用。可能的原因："
                "1. mfusepy 未安装，请运行: pip install mfusepy"
                "2. libfuse 未找到，请安装系统 FUSE 库"
            )

        if client is None:
            raise ValueError("client 参数不能为 None，请提供 P115Client 实例或 cookie")

        if not isinstance(client, P115Client):
            client = P115Client(client, check_for_relogin=True)
        self.client = client
        self.uid = uid
        self.gid = gid
        ttl_cache = TTLCache(
            ttl=int(readdir_ttl),
            region="p115strmhelper_fuse_readdir",
            maxsize=8096000,
        )
        id_to_readdir_cache = IntKeyCacheAdapter(ttl_cache)
        self.fs = client.get_fs(id_to_readdir=id_to_readdir_cache)  # type: ignore[arg-type]
        self._opened: dict[int, Any] = {}
        self._get_id: Callable[[], int] = count(1).__next__

    def getattr(self, /, path: str, fh: int = 0) -> dict[str, Any]:
        """
        获取文件或目录的属性信息

        :param path (str): 文件路径
        :param fh (int): 文件句柄（未使用）
        :return Dict: FUSE stat 属性字典
        :raises OSError: 文件不存在或发生 IO 错误
        """
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                return attr_to_stat(
                    self.fs.get_attr(path, **configer.get_ios_ua_app(app=False)),
                    uid=self.uid,
                    gid=self.gid,
                )
            except FileNotFoundError:
                raise OSError(ENOENT, path)
            except OSError:
                raise
            except Exception as e:
                if attempt < max_retries:
                    sleep(1)
                    continue
                sentry_manager.sentry_hub.capture_exception(e)
                logger.error(f"【FUSE】getattr failed ({path}): {e}", exc_info=True)
                raise OSError(EIO, str(e))

    @log
    def getxattr(self, /, path: str, name: str, position: int = 0) -> bytes:
        """
        获取文件的扩展属性值

        :param path (str): 文件路径
        :param name (str): 扩展属性名称
        :param position (int): 偏移位置（未使用）
        :return bytes: 扩展属性的 JSON 字节数据
        """
        attr = self.getattr(path)["xattr"]
        if name in attr:
            return dumps(attr[name])
        return b""

    @log
    def listxattr(self, /, path: str) -> list[str]:
        """
        列出文件的所有扩展属性名

        :param path (str): 文件路径
        :return List: 扩展属性名列表
        """
        attr = self.getattr(path)["xattr"]
        return list(attr)

    @log
    def mkdir(self, /, path: str, mode: int = 0) -> int:
        """
        创建目录

        :param path (str): 目录路径
        :param mode (int): 权限模式（未使用）
        :return int: 始终返回 0
        """
        dir_, name = splitpath(path)
        self.fs.mkdir(dir_, name, **configer.get_ios_ua_app(app=False))
        return 0

    @log
    def open(self, /, path: str, flags: int) -> int:
        """
        打开文件并返回文件句柄

        :param path (str): 文件路径
        :param flags (int): 打开标志
        :return int: 文件句柄 ID
        """
        file = self.fs.open(path, mode="rb", **configer.get_ios_ua_app(app=False))
        fh = self._get_id()
        self._opened[fh] = file
        return fh

    @log
    def opendir(self, /, path: str) -> int:
        """
        打开目录

        :param path (str): 目录路径
        :return int: 始终返回 0
        """
        return 0

    @log
    def read(self, /, path: str, size: int, offset: int, fh: int) -> bytes:
        """
        从文件中读取数据

        :param path (str): 文件路径
        :param size (int): 读取的字节数
        :param offset (int): 起始偏移位置
        :param fh (int): 文件句柄
        :return bytes: 读取的字节数据
        """
        file = self._opened[fh]
        file.seek(offset)
        return file.read(size)

    @log
    def readdir(self, /, path: str, fh: int = 0) -> list[str]:
        """
        读取目录内容，返回目录项名称列表

        :param path (str): 目录路径
        :param fh (int): 目录句柄（未使用）
        :return List: 包含 .、.. 及子条目名称的列表
        """
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                children = self.fs.readdir(path, **configer.get_ios_ua_app(app=False))
                return [".", "..", *(a["name"] for a in children)]
            except FileNotFoundError:
                raise OSError(ENOENT, path)
            except OSError:
                raise
            except Exception as e:
                if attempt < max_retries:
                    sleep(1)
                    continue
                raise OSError(EIO, str(e))

    @log
    def release(self, /, path: str, fh: int) -> int:
        """
        关闭已打开的文件并释放资源

        :param path (str): 文件路径
        :param fh (int): 文件句柄
        :return int: 始终返回 0
        """
        if file := self._opened.pop(fh, None):
            file.close()
        return 0

    @log
    def releasedir(self, /, path: str, fh: int) -> int:
        """
        关闭已打开的目录

        :param path (str): 目录路径
        :param fh (int): 目录句柄
        :return int: 始终返回 0
        """
        return 0

    @log
    def rename(self, /, src: str, dst: str) -> int:
        """
        重命名或移动文件/目录

        :param src (str): 源路径
        :param dst (str): 目标路径
        :return int: 始终返回 0
        """
        if src != dst:
            src_dir, src_name = splitpath(src)
            dst_dir, dst_name = splitpath(dst)
            attr = self.fs.get_attr(src, **configer.get_ios_ua_app(app=False))
            if src_dir != dst_dir:
                if dst_dir == "/":
                    cid = 0
                else:
                    dstdir_attr = self.fs.get_attr(
                        dst_dir, **configer.get_ios_ua_app(app=False)
                    )
                    if not dstdir_attr["is_dir"]:
                        raise NotADirectoryError(ENOTDIR, dst_dir)
                    cid = dstdir_attr["id"]
                self.fs.move(attr, cid, **configer.get_ios_ua_app(app=False))
            if src_name != dst_name:
                self.fs.rename(attr, dst_name, **configer.get_ios_ua_app(app=False))
        return 0

    @log
    def unlink(self, /, path: str) -> int:
        """
        删除文件

        :param path (str): 文件路径
        :return int: 始终返回 0
        """
        self.fs.remove(path, **configer.get_ios_ua_app(app=False))
        return 0

    @log
    def rmdir(self, /, path: str) -> int:
        """
        删除目录

        :param path (str): 目录路径
        :return int: 始终返回 0
        """
        self.fs.remove(path, **configer.get_ios_ua_app(app=False))
        return 0

    def run_forever(self, /, mountpoint: None | str = None, **options):
        """
        启动 FUSE 文件系统并阻塞运行

        :param mountpoint (str): 挂载点路径，为 None 时自动生成临时路径
        :param options (Any): 传递给 FUSE 的额外选项
        :return Any: FUSE 运行结果
        :raises ImportError: FUSE 功能不可用时抛出
        """
        if not FUSE_AVAILABLE:
            raise ImportError(
                "FUSE 功能不可用。可能的原因："
                "1. mfusepy 未安装，请运行: pip install mfusepy"
                "2. libfuse 未找到，请安装系统 FUSE 库"
            )

        if not mountpoint:
            mountpoint = str(uuid4())
        will_remove_mountpoint = not exists(mountpoint)
        try:
            logger.info(f"🏠 mountpoint: \x1b[4;34m{mountpoint!r}\x1b[0m")
            logger.info(f"🔨 options: {options}")
            return FUSE(self, mountpoint, **options)
        finally:
            if will_remove_mountpoint:
                rmtree(mountpoint)
