from copy import deepcopy
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List
from urllib.parse import parse_qs, urlsplit

from app.sdk.logging import logger
from app.sdk.media import MetaInfoPath

from ....core.config import configer
from ....db_manager.transfer_postprocess import TransferPostprocessStore
from ....utils.path import PathRemoveUtils, PathUtils
from ....utils.strm import StrmGenerater
from .postprocess import file_identity
from .files import fingerprint, validate_path


def local_path(local_root: str, cloud_root: str, cloud_path: str, strm: bool) -> Path:
    """
    按原映射及文件名规则计算受媒体库根目录约束的本地路径
    """
    relative = PurePosixPath(cloud_path).relative_to(PurePosixPath(cloud_root))
    sanitized = PathUtils.sanitize_path_parts(Path(*relative.parts))
    path = Path(local_root).resolve() / sanitized
    if strm:
        path = path.parent / StrmGenerater.get_strm_filename(Path(sanitized.name))
    validate_path(path, [str(Path(local_root).resolve())])
    return path


class TransferPlanBuilder:
    """
    一次性冻结文件清单，恢复时不重新扫描或重新读取清理配置
    """

    def __init__(self, store: TransferPostprocessStore, roots: List[str]) -> None:
        self.store = store
        self.roots = roots
        self.operations: Dict[str, Dict[str, Any]] = {}
        self.directories: List[str] = []

    def operation(
        self,
        path: Path,
        kind: str,
        identity: Dict[str, Any],
        cloud_paths: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        固定文件指纹及旧归属，使操作只能作用于规划时的版本
        """
        validate_path(path, self.roots)
        return {
            "path": str(path),
            "kind": kind,
            "identity": identity,
            "cloud_paths": cloud_paths,
            "before": fingerprint(path),
            "owner": self.store.owner(path),
            "done": False,
        }

    def cleanup(
        self,
        old: Path,
        output: Path,
        cloud_paths: List[Dict[str, Any]],
        related: bool,
        directories: bool,
        reason: str = "move",
    ) -> None:
        """
        固定旧 STRM、关联文件和共享刮削文件，保留新文件及未知内容

        :param reason (str): 清理来源，move 表示移动源清理，latest 表示旧版本清理，仅用于日志
        """
        if old == output:
            logger.debug(
                "【监控整理STRM生成】重新整理清理：旧 STRM 与新生成路径相同，跳过: %s",
                old,
            )
            return
        if not old.is_file() or old.is_symlink():
            return
        candidates = [old]
        entries = list(old.parent.iterdir())
        if related:
            candidates.extend(
                path
                for path in entries
                if (
                    path.is_file()
                    and not path.is_symlink()
                    and path != output
                    and path.suffix.lower() != ".strm"
                    and old.stem in path.stem
                    and not (path.parent == output.parent and output.stem in path.stem)
                )
            )
            remaining = [path for path in entries if path not in candidates]
            if output.parent != old.parent and all(
                path.is_file()
                and not path.is_symlink()
                and path.suffix.lower() in PathRemoveUtils._SCRAP_EXTENSIONS
                for path in remaining
            ):
                candidates.extend(remaining)
        for path in candidates:
            owner = self.store.owner(path)
            probes = deepcopy(cloud_paths)
            if path != old:
                probes.extend(
                    {
                        "storage": identity["storage"],
                        "path": str(PurePosixPath(identity["path"]).parent / path.name),
                    }
                    for identity in cloud_paths
                )
            if owner and owner["identity"] not in probes:
                probes.append(owner["identity"])
            self.operations[str(path)] = self.operation(
                path, "delete", owner["identity"] if owner else cloud_paths[0], probes
            )
            self.operations[str(path)].update(
                cleanup_reason=reason,
                anchor=str(old),
                anchor_before=fingerprint(old),
                siblings=[entry.name for entry in entries]
                + ([output.name] if output.parent == old.parent else []),
            )
        if directories:
            for parent in list(old.parents)[:3]:
                if str(parent) in self.roots or not any(
                    parent.is_relative_to(Path(root)) for root in self.roots
                ):
                    break
                self.directories.append(str(parent))

    def build_cleanup(self, transfer: Any, output: Path, latest: bool) -> None:
        """
        保留 latest 与移动源清理范围，删除前还需严格确认云端已不存在
        """
        target = transfer.target_item
        if latest and output.parent.is_dir():
            meta = MetaInfoPath(output.with_suffix(""))
            for candidate in output.parent.iterdir():
                if candidate.suffix.lower() != ".strm" or candidate == output:
                    continue
                other = MetaInfoPath(candidate.with_suffix(""))
                if (meta.season, meta.episode) != (other.season, other.episode):
                    continue
                owner = self.store.owner(candidate)
                if owner:
                    probes = [owner["identity"]]
                else:
                    if candidate.is_symlink():
                        continue
                    try:
                        names = parse_qs(
                            urlsplit(candidate.read_text(encoding="utf-8")).query
                        ).get("file_name", [])
                    except (UnicodeError, ValueError):
                        names = []
                    if (
                        len(names) != 1
                        or PurePosixPath(names[0]).name != names[0]
                        or names[0] in {".", ".."}
                    ):
                        logger.warning(
                            f"【监控整理STRM生成】旧 STRM 无归属记录且无法还原云端文件名，保留: {candidate}"
                        )
                        continue
                    cloud_parent = PurePosixPath(target.path).parent
                    probes = [
                        {
                            "storage": target.storage,
                            "path": str(cloud_parent / names[0]),
                        }
                    ]
                self.cleanup(candidate, output, probes, True, True, reason="latest")
        source = getattr(transfer, "fileitem", None)
        if transfer.transfer_type != "move" or not source or not source.path:
            return
        if not configer.transfer_monitor_remove_stale_strm:
            return
        matches, local, cloud = PathUtils.get_media_path(
            configer.transfer_monitor_paths,
            PurePosixPath(source.path).parent.as_posix(),
        )
        if matches and local and cloud:
            old = local_path(local, cloud, source.path, True)
            self.cleanup(
                old,
                output,
                [file_identity(source)],
                configer.transfer_monitor_remove_stale_strm_file,
                configer.transfer_monitor_remove_stale_strm_dir,
            )
