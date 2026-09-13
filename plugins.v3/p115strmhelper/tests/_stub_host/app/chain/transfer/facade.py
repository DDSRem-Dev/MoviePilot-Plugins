"""
``app.chain.transfer.facade`` 替身：组合出可被插件补丁打桩的 ``TransferChain``。

补丁（``patch/transfer_chain.py``）会向该类注入/替换以下成员，替身必须都提供：

* ``_TransferChain__handle_transfer`` / ``_TransferChain__finish_scrape_batch_task``
* ``transfer`` / ``do_transfer``
* ``jobview``（``JobManager`` 实例，类属性以便共享状态）
* ``_success_target_files``

同时用 ``Singleton`` 元类复刻宿主的单例语义。
"""

from typing import Any, Dict, Optional, Tuple

from ...application.transfer.workflow import JobManager
from ...foundation.singleton import Singleton
from ..base import ChainBase

__all__ = ["TransferChain"]


class TransferChain(ChainBase, metaclass=Singleton):
    """文件整理链替身（稳定类型身份 + 可打桩的方法面）。"""

    #: 与宿主一致：作业视图挂在类上，实例共享
    jobview = JobManager()

    #: 补丁读取该私有属性判断目标文件是否已成功整理
    _success_target_files: Dict[str, Any] = {}

    #: 记录最近一次 transfer 调用，便于测试断言
    last_transfer_args: Tuple = ()
    last_transfer_kwargs: Dict[str, Any] = {}

    def transfer(self, *args: Any, **kwargs: Any) -> Tuple[bool, str]:
        """整理入口。替身记录调用后返回失败占位。"""
        TransferChain.last_transfer_args = args
        TransferChain.last_transfer_kwargs = kwargs
        return False, "stub: transfer not implemented"

    def do_transfer(self, *args: Any, **kwargs: Any) -> Tuple[bool, str]:
        """兼容别名。"""
        return self.transfer(*args, **kwargs)

    # ------------------------------------------------------------------
    # 补丁目标（宿主私有方法，替身提供等价实现）
    # ------------------------------------------------------------------
    def _TransferChain__handle_transfer(
        self,
        task: Any,
        callback: Any = None,
    ) -> Tuple[bool, str]:
        """处理单个整理任务（宿主私有方法替身）。"""
        return False, "stub: handle_transfer"

    def _TransferChain__finish_scrape_batch_task(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """结束刮削批次任务（宿主单下划线方法替身）。"""

    def _TransferChain__rename_subtitles(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> Tuple[bool, str]:
        """重命名字幕（宿主私有方法替身）。"""
        return True, "stub"

    #: 供补丁探测的刮削批次方法（宿主为单下划线公开名）
    _finish_scrape_batch_task = _TransferChain__finish_scrape_batch_task

    def retry_scheduler(self) -> Optional[Any]:
        """重试调度器替身。"""
        return None
