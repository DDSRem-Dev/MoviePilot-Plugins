from threading import Event, Lock
from time import sleep
from typing import Callable, Dict, Tuple


class _ScanBatch:
    def __init__(self) -> None:
        self.done = Event()
        self.success = False


class LibraryScan:
    """
    合并同一插件实例内并发到达的普通媒体库扫描请求

    同步等待提交结果，不启动后台线程或遗留延迟任务
    扫描开始后到达的请求进入下一批，避免漏掉稍后生成的文件
    """

    def __init__(self) -> None:
        """
        初始化按服务器隔离的扫描批次
        """
        self._lock = Lock()
        self._pending: Dict[Tuple[str, str, str], _ScanBatch] = {}

    def submit(self, key: Tuple[str, str, str], scan: Callable[[], bool]) -> bool:
        """
        合并短时间并发请求并等待普通扫描提交结果

        :param key (Tuple): 服务器名称、地址和认证信息，防止配置变化后误合并
        :param scan (Callable): 提交普通媒体库扫描的回调

        :return bool: 本批扫描请求是否成功提交
        """
        with self._lock:
            batch = self._pending.get(key)
            if batch is None:
                batch = _ScanBatch()
                self._pending[key] = batch
                leader = True
            else:
                leader = False
        if not leader:
            batch.done.wait()
            return batch.success
        try:
            sleep(1)
            with self._lock:
                self._pending.pop(key)
            batch.success = bool(scan())
            return batch.success
        finally:
            with self._lock:
                if self._pending.get(key) is batch:
                    self._pending.pop(key)
            batch.done.set()


library_scan = LibraryScan()
