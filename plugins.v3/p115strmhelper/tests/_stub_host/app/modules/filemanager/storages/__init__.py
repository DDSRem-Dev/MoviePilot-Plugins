"""
``app.modules.filemanager.storages`` 替身。

插件从此处导入 ``transfer_process``（上传进度回调工厂）与 ``U115Pan``
（115 开放平台存储实现，是 ``patch/u115_open.py`` 的补丁目标）。

``U115Pan`` 的方法签名与宿主严格一致，补丁的 ``expected_params`` 自检依赖它们。
"""

from typing import Any, Callable, Optional, Union

__all__ = ["transfer_process", "U115Pan"]

from .u115 import U115Pan


def transfer_process(path: str) -> Callable[[Union[int, float]], None]:
    """返回一个进度回调。

    宿主会启动 tqdm 进度条并向 ProgressHelper 上报；替身只做记录，
    保证调用方拿到「可调用对象」即可。

    :param path: 传输目标路径，用于生成进度标识
    :return: 接受百分比数值的回调函数
    """
    state = {"path": path, "percent": 0.0}

    def update_progress(percent: Union[int, float]) -> None:
        try:
            state["percent"] = float(percent)
        except (TypeError, ValueError):
            state["percent"] = 0.0

    # 便于测试断言
    update_progress.state = state  # type: ignore[attr-defined]
    return update_progress
