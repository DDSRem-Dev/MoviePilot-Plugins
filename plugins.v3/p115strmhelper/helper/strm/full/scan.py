from itertools import batched
from typing import Any, Callable, Dict, Iterator, Set, Tuple


def _is_missing_directory(error: Exception) -> bool:
    if (
        not isinstance(error, KeyError)
        or len(error.args) != 1
        or not str(error.args[0]).isdigit()
    ):
        return False
    traceback = error.__traceback__
    while traceback is not None:
        frame = traceback.tb_frame
        module_name = frame.f_globals.get("__name__")
        if module_name == "p115client.tool.iterdir" and frame.f_code.co_name in (
            "get_ancestors",
            "get_path",
        ):
            return True
        traceback = traceback.tb_next
    return False


class DirectoryScanError(RuntimeError):
    """
    目录扫描恢复失败，携带可直接展示的错误说明
    """


class FullScanIterator:
    """
    分批扫描网盘文件，目录节点缺失时重建任务缓存并重试一次

    Attributes:
        retried: 是否已执行缓存重建重试，用于禁止不稳定扫描后的删除操作
    """

    def __init__(
        self,
        client: Any,
        iter_func: Callable[..., Iterator[Dict[str, Any]]],
        iter_kwargs: Dict[str, Any],
        batch_size: int,
        path: str,
        warn: Callable[[str], None],
    ) -> None:
        """
        保存扫描参数与用户提示回调
        """
        self._client = client
        self._iter_func = iter_func
        self._kwargs = dict(iter_kwargs)
        self._batch_size = batch_size
        self._path = path
        self._warn = warn
        self.retried = False

    def __iter__(self) -> Iterator[Tuple[Dict[str, Any], ...]]:
        """
        只交付完整读取的批次，重试时跳过已经交付的文件

        :raises DirectoryScanError: 清理缓存后扫描仍然失败

        :yields Tuple: 待处理的文件批次
        """
        delivered: Set[str] = set()
        for attempt in range(2):
            # 使用新的任务缓存，避免共享缓存清理或旧扫描后台线程影响重试
            kwargs = dict(self._kwargs, id_to_dirnode={})
            source = None
            batches = None
            try:
                while True:
                    try:
                        if batches is None:
                            source = iter(self._iter_func(self._client, **kwargs))
                            batches = iter(batched(source, self._batch_size))
                        batch = next(batches)
                    except StopIteration:
                        return
                    except Exception as error:
                        missing_directory = _is_missing_directory(error)
                        if attempt:
                            detail = (
                                f"仍缺少目录信息（目录 ID：{error.args[0]}）"
                                if missing_directory
                                else f"遇到新的错误（{type(error).__name__}：{error}）"
                            )
                            raise DirectoryScanError(
                                f"网盘目录“{self._path}”清理目录缓存并重试 1 次后，{detail}，"
                                "本次扫描已停止，已提交的文件仍会完成处理。"
                                "请在 115 网页端检查目录是否可访问、是否有移动或删除，"
                                "待网盘整理完成后重新运行；若持续失败，请附完整日志反馈。"
                                "本次不会清理该目录的失效文件"
                            ) from error
                        if not missing_directory:
                            raise
                        self.retried = True
                        self._warn(
                            f"【全量STRM生成】网盘目录“{self._path}”的目录信息不完整"
                            f"（缺失目录 ID：{error.args[0]}），正在清理本次任务的目录缓存"
                            "并从头重试（1/1），已提交的文件会自动跳过"
                        )
                        break
                    pending = []
                    for item in batch:
                        file_id = str(item["id"])
                        if file_id not in delivered:
                            pending.append(item)
                            delivered.add(file_id)
                    if pending:
                        yield tuple(pending)
            finally:
                close = getattr(source, "close", None)
                if close is not None:
                    close()
