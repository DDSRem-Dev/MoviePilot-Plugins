"""
``app.modules.filemanager.storages.u115`` 替身。

``U115Pan`` 是 ``patch/u115_open.py`` 的补丁目标类。补丁会在 ``enable()``
时校验以下方法的**存在性、可调用性与参数名**（``expected_params``）：

    upload          (target_dir, local_path)
    create_folder   (parent_item, name)
    get_item        (path)
    get_folder      (path)
    rename          (fileitem, name)

因此替身必须严格复刻这些签名，否则补丁会在自检阶段拒绝打桩——这正是
本桩要验证的行为。``__module__`` 也指向宿主路径，以通过 ``module_hint`` 校验。
"""

from pathlib import Path
from typing import Any, List, Optional

__all__ = ["U115Pan", "U115AuthRequiredError"]

#: 让补丁的 module_hint 前缀匹配通过
_HOST_MODULE = "app.modules.filemanager.storages.u115"


class U115AuthRequiredError(Exception):
    """需要重新授权时抛出（宿主同名异常替身）。"""


class U115Pan:
    """115 开放平台存储实现替身。"""

    schema = "u115"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._client: Any = None
        self._user_id: Optional[str] = None

    # ------------------------------------------------------------------
    # 会话（替身不联网）
    # ------------------------------------------------------------------
    def _init_session(self) -> None:
        """初始化会话。替身无操作。"""

    def close(self) -> None:
        """关闭客户端。"""

    def _check_session(self) -> None:
        """检查会话有效性。"""

    # ------------------------------------------------------------------
    # 补丁目标方法（签名必须与宿主一致）
    # ------------------------------------------------------------------
    def create_folder(self, parent_item: Any, name: str) -> Optional[Any]:
        """创建目录。"""
        from ....schemas import FileItem

        base = getattr(parent_item, "path", "") or ""
        return FileItem(
            storage=self.schema,
            path=str(Path(base) / name),
            name=name,
            basename=name,
            type="dir",
        )

    def upload(
        self,
        target_dir: Any,
        local_path: Path,
        new_name: Optional[str] = None,
    ) -> Optional[Any]:
        """上传文件。"""
        from ....schemas import FileItem

        file_path = Path(local_path)
        name = new_name or file_path.name
        base = getattr(target_dir, "path", "") or ""
        return FileItem(
            storage=self.schema,
            path=str(Path(base) / name),
            name=name,
            basename=file_path.stem,
            extension=file_path.suffix.lstrip(".").lower(),
            type="file",
            size=file_path.stat().st_size if file_path.exists() else 0,
        )

    def get_item(self, path: Path) -> Optional[Any]:
        """获取指定路径的文件/目录项。"""
        return None

    def get_folder(self, path: Path) -> Optional[Any]:
        """获取指定路径的文件夹，不存在则创建。"""
        from ....schemas import FileItem

        folder_path = Path(path)
        return FileItem(
            storage=self.schema,
            path=folder_path.as_posix(),
            name=folder_path.name,
            basename=folder_path.name,
            type="dir",
        )

    def rename(self, fileitem: Any, name: str) -> bool:
        """重命名文件/目录。"""
        if fileitem is None:
            return False
        fileitem.name = name
        fileitem.basename = Path(name).stem
        return True

    # ------------------------------------------------------------------
    # 其余宿主接口（替身给出空实现，保证接口面完整）
    # ------------------------------------------------------------------
    def list(self, *args: Any, **kwargs: Any) -> Optional[List[Any]]:
        return []

    def download(self, *args: Any, **kwargs: Any) -> Optional[Any]:
        return None

    def check(self, *args: Any, **kwargs: Any) -> bool:
        return True

    def delete(self, *args: Any, **kwargs: Any) -> bool:
        return True

    def detail(self, *args: Any, **kwargs: Any) -> Optional[Any]:
        return None

    def copy(self, *args: Any, **kwargs: Any) -> bool:
        return True

    def move(self, *args: Any, **kwargs: Any) -> bool:
        return True

    def link(self, *args: Any, **kwargs: Any) -> Optional[str]:
        return None

    def softlink(self, *args: Any, **kwargs: Any) -> Optional[str]:
        return None

    def usage(self, *args: Any, **kwargs: Any) -> Optional[Any]:
        return None


#: 把补丁自检要看的 ``__module__`` 改成宿主模块路径
for _name in ("create_folder", "upload", "get_item", "get_folder", "rename"):
    getattr(U115Pan, _name).__module__ = _HOST_MODULE
del _name
