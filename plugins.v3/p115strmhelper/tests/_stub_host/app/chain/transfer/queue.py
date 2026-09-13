"""``app.chain.transfer.queue`` 替身：提供全局 ``task_lock``。"""

import threading

__all__ = ["task_lock", "downloader_lock"]

#: 与宿主一致的模块级全局锁，插件补丁通过它做多任务串行
task_lock = threading.Lock()
downloader_lock = threading.Lock()
