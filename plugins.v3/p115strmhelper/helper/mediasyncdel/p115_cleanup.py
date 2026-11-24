"""
115 视频库同步删除的计划、复核与执行

只删除确认的视频、独占字幕及已识别的刮削文件，未知文件阻止目录清理
目录删除需完整快照复核，保留映射根；底层递归删除不提供原子快照，
最后一次复核至删除之间的外部写入仍可能被一并删除
"""

from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Iterable, List, Optional, Set, Tuple

MAX_SUBTITLE_TAGS = 3
# 只清理媒体刮削文件与字幕，未知文件保护所在目录及祖先
# 根本身永远不删；根下的片名目录/中间分类目录按同一规则处理
MIN_PURGE_DEPTH_BELOW_ROOT = 1
# 目录级（季/剧集）删除的边界
MIN_DIR_DEPTH_BELOW_ROOT = (
    1  # 目录必须严格位于媒体库根之下（映射根应为 Emby 媒体库根目录）
)
MAX_DIR_DEPTH = 6
MAX_DIR_ENTRIES = 10000
MAX_DIR_VIDEOS = 2000


def _norm_exts(exts: Optional[Iterable[str]]) -> Set[str]:
    return {e.strip().lstrip(".").lower() for e in (exts or []) if e and e.strip()}


def _ext_of(name: str) -> str:
    return PurePosixPath(name).suffix.lstrip(".").lower()


def _stem_of(name: str) -> str:
    return PurePosixPath(name).stem


def _posix(path: Any) -> str:
    return str(path).replace("\\", "/").rstrip("/") or "/"


# 仅限视频库：只处理这些 Emby 条目类型（MoviePilot 会把 MusicAlbum/Photo/Book/BoxSet 等
# 其余类型统一标成 MOV，不能靠 item_type 区分，必须看 Item.Type）
VIDEO_LIBRARY_ITEM_TYPES = frozenset(
    {"Movie", "Episode", "Season", "Series", "Video", "MusicVideo"}
)


def is_video_library_item(item_type: Any) -> bool:
    """
    仅视频库条目允许同步删除；类型缺失或为音乐/照片/图书/合集等一律拒绝
    """
    return isinstance(item_type, str) and item_type in VIDEO_LIBRARY_ITEM_TYPES


def path_is_canonical(path: Any) -> bool:
    """
    必须是规范绝对 POSIX 路径：不含 ``..``、``.``、空段、反斜杠
    """
    t = str(path)
    if not t.startswith("/") or "\\" in t or "\x00" in t:
        return False
    parts = [x for x in t.split("/")[1:] if x != ""]
    if any(x in ("..", ".") for x in parts):
        return False
    return "//" not in t


def dir_event_allowed(item_type: Any, is_folder: Any) -> bool:
    """
    仅 Emby 明确的 Season/Series 且 IsFolder 为真时允许目录级删除
    """
    return str(item_type) in ("Season", "Series") and is_folder is True


def looks_like_media_file(path: str, video_exts: Iterable[str]) -> bool:
    """
    路径后缀是视频或 strm（用于区分 Description 里的逐文件路径与目录）
    """
    ext = PurePosixPath(str(path).replace("\\", "/")).suffix.lstrip(".").lower()
    return bool(ext) and (ext == "strm" or ext in _norm_exts(video_exts))


def subtitle_belongs_to(sub_name: str, video_stem: str, sub_exts: Set[str]) -> bool:
    """
    字幕文件名是否按名字边界归属于某视频主名

    :param sub_name (str): 字幕文件名
    :param video_stem (str): 视频主名（不含扩展名）
    :param sub_exts (Set): 字幕扩展名集合（小写、无点）
    """
    if _ext_of(sub_name) not in sub_exts:
        return False
    body = _stem_of(sub_name)
    stem_cf = video_stem.casefold()
    body_cf = body.casefold()
    if body_cf == stem_cf:
        return True
    if not body_cf.startswith(stem_cf + "."):
        return False
    tags = body[len(video_stem) + 1 :].split(".")
    return 1 <= len(tags) <= MAX_SUBTITLE_TAGS and all(tags)


@dataclass
class CleanupPlan:
    """
    单视频删除计划及已确认的关联字幕
    """

    ok: bool = False
    reason: str = ""
    video_path: str = ""
    video_item: Any = None
    video_present: bool = False
    parent_item: Any = None
    subtitles: List[Any] = field(default_factory=list)
    subtitles_kept: List[str] = field(default_factory=list)
    root: Optional[str] = None
    cleanup_dirs: bool = False


@dataclass
class CleanupResult:
    """
    删除结果及已确认成功和失败的项目
    """

    ok: bool = False
    reason: str = ""
    video_path: str = ""
    video_deleted: bool = False
    video_already_absent: bool = False
    subtitles_deleted: List[str] = field(default_factory=list)
    subtitles_kept: List[str] = field(default_factory=list)
    dirs_deleted: List[str] = field(default_factory=list)
    dir_stop_reason: str = ""
    errors: List[str] = field(default_factory=list)
    mode: str = "file"
    files_deleted: List[str] = field(default_factory=list)  # 复核确认已不存在
    leftovers_deleted: List[str] = field(
        default_factory=list
    )  # 视频/strm 全无后清理的其余文件


@dataclass
class DirPlan:
    """
    季或剧集的完整目录快照
    """

    ok: bool = False
    reason: str = ""
    dir_path: str = ""
    dir_item: Any = None
    present: bool = False
    root: Optional[str] = None
    files: List[Any] = field(default_factory=list)  # 子树内全部文件
    dirs: List[Any] = field(default_factory=list)  # 子树内全部子目录
    video_paths: Set[str] = field(default_factory=set)
    videos: int = 0
    snapshot: Set[Tuple[Any, ...]] = field(default_factory=set)


class P115Cleaner:
    """
    基于 MoviePilot StorageChain 接口的精确清理器
    """

    def __init__(
        self,
        storagechain: Any,
        video_exts: Iterable[str],
        sub_exts: Iterable[str],
        audio_exts: Iterable[str] = (),
        dir_cleanup_storages: Iterable[str] = (
            "u115",
            "115网盘Plus",
            "CloudDrive储存",
        ),
        purge_leftovers: bool = True,
    ) -> None:
        self.purge_leftovers = purge_leftovers
        self.sc = storagechain
        # 仅对已验证“列表失败会抛异常、空列表即真空”的存储做目录清理
        self.dir_cleanup_storages = set(dir_cleanup_storages)
        self.sub_exts = _norm_exts(sub_exts)
        self.audio_exts = _norm_exts(audio_exts)
        # strm 始终视为视频（本地 strm 或 115 上的 strm 都不能被残留清理误当杂项）
        self.video_exts = (_norm_exts(video_exts) - self.sub_exts - self.audio_exts) | {
            "strm"
        }

    def _get_item(self, storage: str, path: str) -> Optional[Any]:
        strict = getattr(self.sc, "get_file_item_strict", None)
        if callable(strict):
            item = strict(storage=storage, path=PurePosixPath(path))
            if item is not None and (
                _posix(getattr(item, "path", "")) != _posix(path)
                or getattr(item, "storage", None) != storage
                or getattr(item, "type", None) not in {"file", "dir"}
                or not getattr(item, "fileid", None)
            ):
                raise ValueError(f"查询返回了不匹配的文件项: {path}")
            return item
        raise RuntimeError("存储链不支持严格查询，无法区分不存在与查询失败")

    def _list(self, item: Any) -> List[Any]:
        items = self.sc.list_files(item)
        if items is None:
            raise RuntimeError(f"目录列表失败: {item.path}")
        result = list(items)
        parent = PurePosixPath(_posix(item.path))
        seen = set()
        for child in result:
            path = _posix(getattr(child, "path", ""))
            if (
                getattr(child, "type", None) not in {"file", "dir"}
                or not path_is_canonical(path)
                or PurePosixPath(path).parent != parent
                or PurePosixPath(path).name != getattr(child, "name", None)
                or getattr(child, "storage", None) != item.storage
                or not getattr(child, "fileid", None)
                or path in seen
            ):
                raise ValueError(f"目录返回了无效或重复条目: {path}")
            seen.add(path)
        return result

    @staticmethod
    def _identity(item: Any) -> Tuple[Any, ...]:
        return (
            _posix(item.path),
            item.type,
            str(item.fileid),
            item.storage,
            getattr(item, "size", None) if item.type == "file" else None,
            getattr(item, "modify_time", None) if item.type == "file" else None,
            getattr(item, "pickcode", None),
        )

    def _snapshot(self, items: List[Any]) -> Set[Tuple[Any, ...]]:
        return {self._identity(item) for item in items}

    def _is_sidecar(self, name: str) -> bool:
        return (
            _ext_of(name)
            in {"nfo", "jpg", "jpeg", "png", "webp", "bmp", "gif", "tbn"}
            | self.sub_exts
        )

    def _is_video(self, name: str) -> bool:
        return _ext_of(name) in self.video_exts

    def plan(
        self,
        storage: str,
        video_path: str,
        root: Optional[str] = None,
        resolve_missing: bool = False,
    ) -> CleanupPlan:
        """
        只读阶段：确认目标、父目录列表和字幕归属；不做任何写入
        """
        p = CleanupPlan(video_path=_posix(video_path))
        if not path_is_canonical(video_path) or (root and not path_is_canonical(root)):
            p.reason = f"路径不规范（含 .. 或相对路径），拒绝: {video_path}"
            return p
        name = PurePosixPath(p.video_path).name
        if not self._is_video(name):
            p.reason = f"目标扩展名不是视频（目录级/季/剧集删除不支持），拒绝: {name}"
            return p
        if root and storage in self.dir_cleanup_storages:
            root_p = _posix(root)
            try:
                PurePosixPath(p.video_path).relative_to(root_p)
                p.root = root_p
                p.cleanup_dirs = True
            except ValueError:
                p.reason = "目标不在媒体库根下，拒绝删除"
                return p
        try:
            item = self._get_item(storage, p.video_path)
            if item is not None and getattr(item, "type", "file") != "file":
                p.reason = f"目标是目录（季/剧集级删除不支持），拒绝: {p.video_path}"
                return p
            p.video_item = item
            p.video_present = item is not None
            parent_path = str(PurePosixPath(p.video_path).parent)
            parent = self._get_item(storage, parent_path)
            if parent is None:
                if item is not None:
                    p.reason = "视频存在但父目录查询为空，状态矛盾，拒绝"
                    return p
                p.ok = True  # 视频与目录均已不存在：幂等完成
                p.cleanup_dirs = False
                return p
            if parent.type != "dir":
                raise ValueError("父路径不是目录")
            p.parent_item = parent
            siblings = self._list(parent)
        except Exception as e:
            p.reason = f"前置查询失败: {e}"
            return p

        files = [i for i in siblings if getattr(i, "type", "") == "file"]
        other_videos = [
            i
            for i in files
            if self._is_video(i.name) and _posix(i.path) != p.video_path
        ]
        listed_target = [i for i in files if _posix(i.path) == p.video_path]
        if not p.video_present and listed_target:
            p.reason = "查询不存在但列表中有目标，拒绝删除"
            return p
        if p.video_present and (
            len(listed_target) != 1
            or self._identity(listed_target[0]) != self._identity(p.video_item)
        ):
            p.reason = "父目录列表中找不到目标视频，状态矛盾，拒绝"
            return p
        target_stem = _stem_of(name)
        if not p.video_present and resolve_missing:
            candidates = [
                v
                for v in other_videos
                if _stem_of(v.name).casefold() == target_stem.casefold()
            ]
            if len(candidates) > 1:
                p.reason = "同主名存在多个视频，无法确认删除目标"
                return p
            if candidates:
                p.video_item = candidates[0]
                p.video_path = _posix(p.video_item.path)
                p.video_present = True
                target_stem = _stem_of(p.video_item.name)
                other_videos = [
                    v for v in other_videos if _posix(v.path) != p.video_path
                ]
        if not p.video_present and any(
            _stem_of(v.name).casefold() == target_stem.casefold() for v in other_videos
        ):
            p.reason = "目标不存在但同主名存在其他容器的视频，后缀可能不符，拒绝"
            return p
        for f in files:
            if not subtitle_belongs_to(f.name, target_stem, self.sub_exts):
                continue
            claimed_by_other = any(
                subtitle_belongs_to(f.name, _stem_of(v.name), self.sub_exts)
                for v in other_videos
            )
            if claimed_by_other:
                p.subtitles_kept.append(f.name)
            else:
                p.subtitles.append(f)
        p.ok = True
        return p

    def execute(self, storage: str, plan: CleanupPlan) -> CleanupResult:
        """
        复核单视频及独占字幕并执行删除
        """
        r = CleanupResult(
            video_path=plan.video_path,
            subtitles_kept=list(plan.subtitles_kept),
        )
        if not plan.ok:
            r.reason = plan.reason
            return r

        try:
            current = self._get_item(storage, plan.video_path)
            if (current is None) != (not plan.video_present) or (
                current is not None
                and self._identity(current) != self._identity(plan.video_item)
            ):
                raise ValueError("目标在计划后发生变化")
        except Exception as e:
            r.errors.append(f"写入前复核失败: {e}")
            return r

        if not plan.video_present:
            r.video_already_absent = True
        else:
            try:
                deleted = self.sc.delete_file(plan.video_item)
            except Exception as e:
                deleted = False
                r.errors.append(f"视频删除异常: {e}")
            if not deleted:
                r.reason = "视频删除失败，未处理字幕与目录"
                r.errors.append(r.reason)
                return r
            r.video_deleted = True

        for sub in plan.subtitles:
            try:
                current_sub = self._get_item(storage, sub.path)
                if current_sub is None:
                    continue
                if self._identity(current_sub) != self._identity(sub):
                    raise ValueError("字幕在计划后发生变化")
                siblings = self._list(plan.parent_item)
                if any(
                    self._is_video(other.name)
                    and subtitle_belongs_to(
                        sub.name, _stem_of(other.name), self.sub_exts
                    )
                    for other in siblings
                ):
                    r.subtitles_kept.append(sub.name)
                    continue
                ok = self.sc.delete_file(sub)
            except Exception as e:
                ok = False
                r.errors.append(f"字幕 {sub.name} 删除异常: {e}")
            if ok:
                r.subtitles_deleted.append(sub.name)
            else:
                r.errors.append(f"字幕 {sub.name} 删除失败")

        if plan.parent_item is None:
            r.ok = not r.errors
            r.dir_stop_reason = "父目录已不存在"
            return r

        # 重新列表，验证目标确已消失（日志“完成”不等于存在性）
        try:
            remaining = self._list(plan.parent_item)
        except Exception as e:
            r.errors.append(f"删除后复核列表失败，不清理目录: {e}")
            r.dir_stop_reason = "复核失败"
            return r
        names = {i.name for i in remaining}
        if PurePosixPath(plan.video_path).name in names:
            r.errors.append("复核发现视频仍存在")
        for n in list(r.subtitles_deleted):
            if n in names:
                r.subtitles_deleted.remove(n)
                r.errors.append(f"复核发现字幕仍存在: {n}")
        if not r.errors and r.video_deleted:
            r.files_deleted.append(plan.video_path)
        if r.errors:
            r.dir_stop_reason = "存在失败项，不清理目录"
            return r

        if not plan.cleanup_dirs:
            r.ok = True
            r.dir_stop_reason = "未提供有效媒体库根，不清理目录"
            return r

        self._cleanup_dirs(storage, plan, remaining, r)
        r.ok = not r.errors
        return r

    def _depth_below_root(self, path: str, root: Optional[str]) -> int:
        if not root:
            return 0
        try:
            return len(PurePosixPath(_posix(path)).relative_to(_posix(root)).parts)
        except ValueError:
            return 0

    def _scan_tree(
        self, d: Any, stop_on_video: bool = False
    ) -> Optional[Tuple[List[Any], List[Any]]]:
        """
        遍历子树，返回 (所有文件, 所有子目录)，列表失败、类型未知、嵌套过深、条目过多均抛异常，
        调用方一律视为失败（绝不当作空目录）；stop_on_video=True 时一旦发现视频/strm 立即返回
        None（用于判断“是否已无视频”：大合集目录不必为此遍历整棵树，避免大量 115 请求）
        """
        files: List[Any] = []
        dirs: List[Any] = []
        stack = [(d, 0)]
        entries = 0
        while stack:
            cur, depth = stack.pop()
            if depth > MAX_DIR_DEPTH:
                raise ValueError(f"目录嵌套过深: {cur.path}")
            listing = self._list(cur)
            if stop_on_video and any(
                getattr(it, "type", "") == "file"
                and _ext_of(it.name) in self.video_exts
                for it in listing
            ):
                return None
            for it in listing:
                entries += 1
                if entries > MAX_DIR_ENTRIES:
                    raise ValueError(f"目录条目过多(>{MAX_DIR_ENTRIES})")
                t = getattr(it, "type", "")
                if t == "dir":
                    dirs.append(it)
                    stack.append((it, depth + 1))
                elif t == "file":
                    files.append(it)
                else:
                    raise ValueError(f"条目类型未知: {it.path}")
        return files, dirs

    def _video_paths(self, files: List[Any]) -> Set[str]:
        return {_posix(f.path) for f in files if _ext_of(f.name) in self.video_exts}

    def _dead_tree(
        self, d: Any, root: Optional[str]
    ) -> Optional[Tuple[List[Any], List[Any]]]:
        """
        子树内已没有任何视频/strm（扩展名取 MoviePilot 媒体扩展名，已含 strm）时返回
        (其余文件, 子目录)，否则 None；写入前连续两次扫描且结果一致；列表失败、超限、
        层级不足（目录即媒体库根）均返回 None
        """
        if (
            not self.purge_leftovers
            or self._depth_below_root(d.path, root) < MIN_PURGE_DEPTH_BELOW_ROOT
        ):
            return None
        try:
            first = self._scan_tree(d, stop_on_video=True)
            if first is None:
                return None
            f1, d1 = first
            second = self._scan_tree(d, stop_on_video=True)
            if second is None:
                return None
            f2, d2 = second
        except Exception:
            return None
        same = self._snapshot(f1 + d1) == self._snapshot(f2 + d2)
        if (
            self._video_paths(f2)
            or not same
            or any(not self._is_sidecar(f.name) for f in f2)
        ):
            return None
        return f2, d2

    def _remove_tree(
        self, storage: str, d: Any, files: List[Any], dirs: List[Any], r: CleanupResult
    ) -> bool:
        """
        对授权目录复核完整快照后发起一次递归删除

        复核目录及已知子项均不存在后才记录成功，最终复核后的外部写入仍有竞态风险
        """
        dp = _posix(d.path)
        if not getattr(d, "fileid", None):
            r.dir_stop_reason = f"目录缺少标识，保留: {dp}"
            return False
        try:
            current = self._get_item(storage, dp)
            if current is None or self._identity(current) != self._identity(d):
                raise ValueError("目录标识已变化")
            latest_files, latest_dirs = self._scan_tree(current)
            if self._snapshot(latest_files + latest_dirs) != self._snapshot(
                files + dirs
            ):
                raise ValueError("目录内容已变化")
            ok = self.sc.delete_file(d)
        except Exception as e:
            ok = False
            r.errors.append(f"目录删除异常 {dp}: {e}")
        if not ok:
            r.errors.append(f"目录删除失败: {dp}")
            r.dir_stop_reason = "目录删除失败"
            return False
        try:
            if self._get_item(storage, dp) is not None:
                r.errors.append(f"复核发现目录仍存在: {dp}")
                return False
        except Exception as e:
            r.errors.append(f"目录删除后复核失败 {dp}: {e}")
            return False
        try:
            for child in files + dirs:
                if self._get_item(storage, _posix(child.path)) is not None:
                    raise ValueError(f"子项仍存在: {child.path}")
        except Exception as e:
            r.errors.append(f"目录子项删除复核失败: {e}")
            return False
        r.leftovers_deleted.extend(
            _posix(f.path) for f in files if not self._is_video(f.name)
        )
        r.dirs_deleted.extend(_posix(x.path) for x in dirs)
        r.dirs_deleted.append(dp)
        return True

    def _cleanup_dirs(
        self, storage: str, plan: CleanupPlan, remaining: List[Any], r: CleanupResult
    ) -> None:
        cur = plan.parent_item
        listing = remaining
        root = plan.root
        while True:
            cur_path = _posix(cur.path)
            if cur_path == root or not PurePosixPath(cur_path).is_relative_to(root):
                r.dir_stop_reason = "到达媒体库根"
                return
            if listing:
                dead = self._dead_tree(cur, root)
                if dead is None:
                    r.dir_stop_reason = f"目录非空保留: {cur_path}"
                    return
                if not self._remove_tree(storage, cur, dead[0], dead[1], r):
                    return
            else:
                try:  # 删除前最后一次独立确认真空
                    if self._list(cur):
                        r.dir_stop_reason = f"目录非空保留(删前复核): {cur_path}"
                        return
                except Exception as e:
                    r.dir_stop_reason = f"删前复核失败，保留: {cur_path}: {e}"
                    return
                if not self._remove_tree(storage, cur, [], [], r):
                    return
            parent_path = str(PurePosixPath(cur_path).parent)
            try:
                parent = self._get_item(storage, parent_path)
                if parent is None:
                    r.dir_stop_reason = "上级目录查询为空，停止"
                    return
                listing = self._list(parent)
            except Exception as e:
                r.dir_stop_reason = f"上级目录查询失败，停止: {e}"
                return
            cur = parent

    def plan_dir(self, storage: str, dir_path: str, root: Optional[str]) -> DirPlan:
        """
        只读扫描视频目录并保存完整快照
        """
        p = DirPlan(dir_path=_posix(dir_path))
        if not path_is_canonical(dir_path) or (root and not path_is_canonical(root)):
            p.reason = f"路径不规范（含 .. 或相对路径），拒绝: {dir_path}"
            return p
        if (
            storage not in self.dir_cleanup_storages
            or not root
            or not self.purge_leftovers
        ):
            p.reason = "目录级删除需要已验证的存储、媒体库根且启用残留清理，拒绝"
            return p
        root_p = _posix(root)
        try:
            rel = PurePosixPath(p.dir_path).relative_to(root_p)
        except ValueError:
            p.reason = f"目录不在媒体库根之下，拒绝: {p.dir_path}"
            return p
        if len(rel.parts) < MIN_DIR_DEPTH_BELOW_ROOT:
            p.reason = f"目录即媒体库根或层级过浅，拒绝: {p.dir_path}"
            return p
        p.root = root_p
        try:
            item = self._get_item(storage, p.dir_path)
            if item is None:
                p.ok = True  # 已不存在：幂等
                return p
            if getattr(item, "type", "") != "dir":
                p.reason = f"目标不是目录，拒绝: {p.dir_path}"
                return p
            p.present = True
            p.dir_item = item
            p.files, p.dirs = self._scan_tree(item)
        except Exception as e:
            p.reason = f"前置查询失败: {e}"
            return p
        p.video_paths = self._video_paths(p.files)
        p.videos = len(p.video_paths)
        p.snapshot = self._snapshot(p.files + p.dirs)
        if not p.videos:
            p.reason = "目录没有可确认的视频，保留目录"
            return p
        if any(
            not self._is_video(f.name) and not self._is_sidecar(f.name) for f in p.files
        ):
            p.reason = "目录包含未知文件，拒绝递归删除"
            return p
        if p.videos > MAX_DIR_VIDEOS:
            p.reason = f"视频数量超过上限 {MAX_DIR_VIDEOS}，拒绝"
            return p
        p.ok = True
        return p

    def execute_dir(self, storage: str, plan: DirPlan) -> CleanupResult:
        """
        复核完整快照后递归删除并校验所有已知子项
        """
        r = CleanupResult(video_path=plan.dir_path, mode="dir")
        if not plan.ok:
            r.reason = plan.reason
            return r
        if not plan.present:
            try:
                if self._get_item(storage, plan.dir_path) is not None:
                    raise ValueError("目录在计划后重新出现")
            except Exception as e:
                r.errors.append(f"缺失目录复核失败: {e}")
                return r
            r.video_already_absent = True
            r.ok = True
            r.dir_stop_reason = "目录已不存在"
            return r
        # 写入前二次扫描：视频/strm 集合必须与计划一致，新增视频不在本次删除授权内
        try:
            files2, dirs2 = self._scan_tree(plan.dir_item)
        except Exception as e:
            r.reason = f"写入前复核失败，零写入: {e}"
            return r
        if self._snapshot(files2 + dirs2) != plan.snapshot:
            r.reason = "目录内容或文件标识在计划后发生变化，零写入"
            return r
        if not self._remove_tree(storage, plan.dir_item, files2, dirs2, r):
            r.reason = r.reason or "目录删除未完成"
            return r
        r.files_deleted = [_posix(f.path) for f in files2]
        parent_path = str(PurePosixPath(plan.dir_path).parent)
        try:
            parent = self._get_item(storage, parent_path)
            if parent is None:
                r.dir_stop_reason = "上级目录查询为空，停止"
                r.ok = not r.errors
                return r
            remaining = self._list(parent)
        except Exception as e:
            r.dir_stop_reason = f"上级目录查询失败，停止: {e}"
            r.ok = not r.errors
            return r
        cp = CleanupPlan(parent_item=parent, root=plan.root, cleanup_dirs=True)
        self._cleanup_dirs(storage, cp, remaining, r)
        r.ok = not r.errors
        return r

    def delete_group(
        self,
        storage: str,
        path: str,
        root: Optional[str] = None,
        allow_dir: bool = False,
    ) -> CleanupResult:
        """
        统一入口：视频扩展名走单文件；其余仅在 allow_dir 时按目录级处理，否则拒绝
        """
        name = PurePosixPath(_posix(path)).name
        if self._is_video(name) or not allow_dir:
            return self.execute(
                storage, self.plan(storage, path, root, resolve_missing=True)
            )
        return self.execute_dir(storage, self.plan_dir(storage, path, root))

    def delete_video_group(
        self, storage: str, video_path: str, root: Optional[str] = None
    ) -> CleanupResult:
        """
        计划并执行；计划失败时不做任何写入
        """
        plan = self.plan(storage, video_path, root)
        return self.execute(storage, plan)


def select_video_suffix(
    items: Optional[List[Any]],
    basename: str,
    video_exts: Iterable[str],
    sub_exts: Iterable[str] = (),
    audio_exts: Iterable[str] = (),
) -> Optional[str]:
    """
    从目录列表中确定与主名完全一致的视频扩展名

    仅接受视频扩展名；无候选或候选多于一个（歧义）返回 None
    """
    if items is None:
        return None
    vids = _norm_exts(video_exts) - _norm_exts(sub_exts) - _norm_exts(audio_exts)
    found = []
    for it in items:
        if getattr(it, "type", None) != "file":
            continue
        name = getattr(it, "name", None) or PurePosixPath(getattr(it, "path", "")).name
        if _stem_of(name).casefold() == basename.casefold() and _ext_of(name) in vids:
            found.append(PurePosixPath(name).suffix.lstrip("."))
    if len(found) == 1:
        return found.pop()
    return None


def valid_container_suffix(
    container: Optional[str],
    video_exts: Iterable[str],
    sub_exts: Iterable[str] = (),
    audio_exts: Iterable[str] = (),
) -> Optional[str]:
    """
    Emby 报文的 Container 可能是 ffprobe 格式名（如 ``mov,mp4,m4a``）或非扩展名；
    仅当它恰好是单个视频扩展名时才采用，否则返回 None 以便回退到目录查询
    """
    if not container or not isinstance(container, str):
        return None
    c = container.strip().lstrip(".")
    if not c or "," in c or "/" in c:
        return None
    vids = _norm_exts(video_exts) - _norm_exts(sub_exts) - _norm_exts(audio_exts)
    return c if c.lower() in vids else None
