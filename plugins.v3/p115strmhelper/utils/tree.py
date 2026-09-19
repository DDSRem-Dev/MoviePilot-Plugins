__all__ = ["DirectoryTree"]

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterable, Generator, List, Optional, Union

from app.core.config import settings
from app.helper.redis import RedisHelper

import txt_tree_storage


class DirectoryTreeStorage(ABC):
    """
    目录树存储策略的抽象基类
    """

    @abstractmethod
    def add_paths(self, paths: Iterable[str], append: bool = False):
        """
        从一个迭代器添加多个路径

        :param paths (Iterable): 路径字符串迭代器
        :param append (bool): True 时追加，False 时覆盖
        """
        pass

    @abstractmethod
    def compare_trees(
        self, other_storage: "DirectoryTreeStorage"
    ) -> Generator[str, None, None]:
        """
        比较两个树，返回 self 中存在而 other 中不存在的路径
        """
        pass

    @abstractmethod
    def compare_trees_lines(
        self, other_storage: "DirectoryTreeStorage"
    ) -> Generator[int, None, None]:
        """
        比较两个树，返回差异路径在 self 中的行号
        """
        pass

    @abstractmethod
    def get_path_by_line_number(self, line_number: int) -> Union[str, None]:
        """
        根据行号获取路径
        """
        pass

    @abstractmethod
    def count(self) -> int:
        """
        返回树中的有效条目总数

        :return int: 条目总数
        """
        pass

    @abstractmethod
    def clear(self):
        """
        清理目录树
        """
        pass


class TxtFileStorage(DirectoryTreeStorage):
    """
    使用 TXT 文件作为后端的存储策略
    """

    def __init__(self, file_path: Union[str, Path]):
        """
        初始化 TXT 文件存储

        :param file_path (Union[str, Path]): TXT 文件的路径，父目录会自动创建
        """
        self._rust = txt_tree_storage
        self.file_path = Path(file_path)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

    def add_paths(self, paths: Iterable[str], append: bool = False):
        """
        向 TXT 文件添加路径条目

        :param paths (Iterable): 路径字符串迭代器
        :param append (bool): True 时追加，False 时覆盖
        """
        return self._rust.add_paths(
            self.file_path, (p if isinstance(p, str) else str(p) for p in paths), append
        )

    def compare_trees(
        self, other_storage: "DirectoryTreeStorage"
    ) -> Generator[str, None, None]:
        """
        比较两个 TXT 树，找出本树中存在而另一棵树中不存在的路径

        :param other_storage (DirectoryTreeStorage): 另一个 TxtFileStorage 实例
        :return Generator: 差异路径的生成器
        :raises TypeError: 当 other_storage 不是 TxtFileStorage 时抛出
        """
        if not isinstance(other_storage, TxtFileStorage):
            raise TypeError("TxtFileStorage 只能与同类型的树进行比较")

        diff = self._rust.compare_trees(self.file_path, other_storage.file_path)
        yield from diff

    def compare_trees_lines(
        self, other_storage: "DirectoryTreeStorage"
    ) -> Generator[int, None, None]:
        """
        比较两个 TXT 树，返回差异路径在本树中的行号

        :param other_storage (DirectoryTreeStorage): 另一个 TxtFileStorage 实例
        :return Generator: 差异行号的生成器
        :raises TypeError: 当 other_storage 不是 TxtFileStorage 时抛出
        """
        if not isinstance(other_storage, TxtFileStorage):
            raise TypeError("TxtFileStorage 只能与同类型的树进行比较")

        lines = self._rust.compare_trees_lines(self.file_path, other_storage.file_path)
        yield from lines

    def get_path_by_line_number(self, line_number: int) -> Union[str, None]:
        """
        根据行号获取 TXT 文件中对应行的路径

        :param line_number (int): 行号（从 1 开始）
        :return str: 路径字符串，无效行号时返回 None
        """
        return self._rust.get_path_by_line_number(self.file_path, line_number)

    def count(self) -> int:
        """
        统计 TXT 文件中的有效条目总数

        :return: 条目总数
        """
        return int(self._rust.count(self.file_path))

    def clear(self):
        """
        清空 TXT 文件的所有内容
        """
        return self._rust.clear(self.file_path)


class RedisStorage(DirectoryTreeStorage):
    """
    使用 Redis 作为后端的存储策略
    """

    def __init__(self, tree_name: str):
        """
        初始化 Redis 存储

        :param tree_name (str): 树名称，用于生成 Redis 键名前缀
        """
        self.tree_name = tree_name

        self.redis_helper = RedisHelper()
        self.redis_helper._connect()  # noqa
        self.client = self.redis_helper.client

        self._set_key = f"dirtree:set:{tree_name}"
        self._list_key = f"dirtree:list:{tree_name}"

    def add_paths(self, paths: Iterable[str], append: bool = False):
        """
        向 Redis 添加路径条目（通过 Pipeline 批量操作）

        :param paths (Iterable): 路径字符串迭代器
        :param append (bool): True 时追加，False 时先清空已有数据
        :raises MemoryError: 当 Redis 内存不足时抛出，提示用户调整配置
        """
        pipe = self.client.pipeline()

        if not append:
            pipe.delete(self._set_key, self._list_key)

        chunk_size, path_chunk = 5000, []
        for path in paths:
            if path:
                path_chunk.append(path)
            if len(path_chunk) >= chunk_size:
                pipe.sadd(self._set_key, *path_chunk)
                pipe.rpush(self._list_key, *path_chunk)
                path_chunk = []

        if path_chunk:
            pipe.sadd(self._set_key, *path_chunk)
            pipe.rpush(self._list_key, *path_chunk)

        pipe.expire(self._set_key, 604800)
        pipe.expire(self._list_key, 604800)

        try:
            pipe.execute()
        except Exception as e:
            error_msg = str(e)
            if "used memory > 'maxmemory'" in error_msg or "OOM" in error_msg:
                raise MemoryError(
                    f"Redis 内存不足，无法写入 {self.tree_name} 树数据。"
                    f"请增大 Redis 的 maxmemory 配置，或设置 maxmemory-policy=allkeys-lru。"
                    f"当前键: {self._set_key}, {self._list_key}"
                ) from e
            raise

    def compare_trees(
        self, other_storage: "DirectoryTreeStorage"
    ) -> Generator[str, None, None]:
        """
        使用 Redis SDIFF 命令高效比较两个树，返回本树中存在而另一棵树中不存在的路径

        :param other_storage (DirectoryTreeStorage): 另一个 RedisStorage 实例
        :return Generator: 差异路径的生成器
        :raises TypeError: 当 other_storage 不是 RedisStorage 时抛出
        """
        if not isinstance(other_storage, RedisStorage):
            raise TypeError("RedisStorage 只能与同类型的树进行高性能比较")

        diff_bytes = self.client.sdiff(self._set_key, other_storage._set_key)
        for b_path in diff_bytes:
            yield b_path.decode("utf-8")

    def compare_trees_lines(
        self, other_storage: "DirectoryTreeStorage"
    ) -> Generator[int, None, None]:
        """
        使用 Redis 分批比较两个树，返回差异路径在本树中的行号

        :param other_storage (DirectoryTreeStorage): 另一个 RedisStorage 实例
        :return Generator: 差异行号的生成器
        :raises TypeError: 当 other_storage 不是 RedisStorage 时抛出
        """
        if not isinstance(other_storage, RedisStorage):
            raise TypeError("RedisStorage 只能与同类型的树进行高性能比较")

        chunk_size, line_num = 5000, 0
        while True:
            paths_chunk_bytes = self.client.lrange(
                self._list_key, line_num, line_num + chunk_size - 1
            )
            if not paths_chunk_bytes:
                break

            for path_bytes in paths_chunk_bytes:
                line_num += 1
                if not self.client.sismember(other_storage._set_key, path_bytes):
                    yield line_num

    def get_path_by_line_number(self, line_number: int) -> Union[str, None]:
        """
        根据行号获取 Redis 列表中对应位置的路径

        :param line_number (int): 行号（从 1 开始）
        :return str: 路径字符串，无效行号时返回 None
        """
        if line_number <= 0:
            return None
        path_bytes = self.client.lindex(self._list_key, line_number - 1)
        return path_bytes.decode("utf-8") if path_bytes else None

    def count(self) -> int:
        """
        统计 Redis 集合中的有效条目总数

        :return: 条目总数
        """
        return self.client.scard(self._set_key)

    def clear(self):
        """
        删除 Redis 中与当前树相关的所有键
        """
        self.client.delete(self._set_key, self._list_key)


class DirectoryTree:
    """
    目录树操作的高级接口，支持 TXT 和 Redis 后端
    """

    def __init__(self, file_path: Path, force_backend: Optional[str] = None):
        """
        初始化目录树实例

        :param file_path (Path): 目录树对应的文件路径（其 stem 用于生成 Redis 键名）
        :param force_backend (str): 强制指定后端类型，"redis" 或 "txt"；None 时按 settings.CACHE_BACKEND_TYPE
        """
        backend = force_backend or settings.CACHE_BACKEND_TYPE
        if backend == "redis":
            self._storage: DirectoryTreeStorage = RedisStorage(file_path.stem)
        else:
            self._storage: DirectoryTreeStorage = TxtFileStorage(file_path)
        self._file_path = file_path

    def scan_directory_to_tree(
        self, root_path, append=False, extensions=None, use_posix=True
    ):
        """
        扫描本地目录生成目录树，可过滤后缀

        :param root_path (str): 根目录路径
        :param append (bool): True 时追加，False 时覆盖
        :param extensions (List): 文件后缀过滤列表
        :param use_posix (bool): 是否使用 POSIX 路径格式
        """
        root = Path(root_path).resolve()
        if extensions:
            extensions = {f".{ext.lower().lstrip('.')}" for ext in extensions}

        def path_generator():
            """
            遍历目录并过滤出符合条件的文件路径

            :return: 生成器，逐个产出文件路径字符串
            """
            for path in root.rglob("*"):
                if path.is_file() and (
                    extensions is None or path.suffix.lower() in extensions
                ):
                    yield path.as_posix() if use_posix else str(path)

        self._storage.add_paths(path_generator(), append=append)

    def generate_tree_from_list(self, file_list: List[str], append=False):
        """
        从文件列表生成目录树

        :param file_list (List): 文件路径列表
        :param append (bool): True 时追加，False 时覆盖
        """
        self._storage.add_paths(file_list, append=append)

    def compare_trees(self, other_tree: "DirectoryTree") -> Generator[str, None, None]:
        """
        比较两个目录树，找出本树有而另一颗树没有的文件

        :param other_tree (DirectoryTree): 要比较的另一个目录树实例

        :return Generator: 差异文件路径的生成器
        """
        yield from self._storage.compare_trees(other_tree._storage)

    def compare_trees_lines(
        self, other_tree: "DirectoryTree"
    ) -> Generator[int, None, None]:
        """
        比较两个目录树，返回差异文件在本树中的行号

        :param other_tree (DirectoryTree): 要比较的另一个目录树实例

        :return Generator: 差异行号的生成器
        """
        yield from self._storage.compare_trees_lines(other_tree._storage)

    def get_path_by_line_number(self, line_number: int) -> Union[str, None]:
        """
        通过行号获取路径

        :param line_number (int): 行号（从 1 开始）

        :return str: 路径字符串，无效行号时返回 None
        """
        return self._storage.get_path_by_line_number(line_number)

    def count(self) -> int:
        """
        获取此目录树中的有效条目总数

        :return int: 条目总数
        """
        return self._storage.count()

    def compare_entry_counts(self, other_tree: "DirectoryTree") -> int:
        """
        对比两个目录树的有效条目总数

        :param other_tree (DirectoryTree): 要比较的另一个 DirectoryTree 实例
        :return int: 两个树条目数量的差值绝对值
        """
        return abs(self.count() - other_tree.count())

    def clear(self):
        """
        清除此目录树的所有内容
        - 对于 TXT 后端，会清空文件
        - 对于 Redis 后端，会删除相关的键
        """
        self._storage.clear()

    def switch_storage(self, backend: str):
        """
        运行时切换存储后端，切换前会清空旧后端的数据

        :param backend (str): 目标后端类型，"redis" 或 "txt"
        """
        is_redis = isinstance(self._storage, RedisStorage)
        if backend == "redis" and is_redis:
            return
        if backend != "redis" and not is_redis:
            return
        self._storage.clear()
        if backend == "redis":
            self._storage = RedisStorage(self._file_path.stem)
        else:
            self._storage = TxtFileStorage(self._file_path)
