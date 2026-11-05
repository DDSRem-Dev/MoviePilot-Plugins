"""
115 网盘同步删除：精确的“视频 + 外挂字幕 + 残留文件 + 空目录”清理计划与执行

契约：
- 单视频：目标为调用方给出的精确视频路径，不做模糊候选选择；目标是目录/非视频则拒绝。
- 外挂字幕仅匹配 ``<视频主名>(.<标记>){0,3}.<字幕扩展名>``，主名后必须紧跟 ``.``，
  因此 E01 不会匹配 E010。被其他视频同样认领的字幕保留。
- 季/剧集（Emby Season/Series，IsFolder）：在 115 枚举子树，逐个删除视频与字幕，不整目录递归删除。
- 目录子树内已没有任何视频/strm 时，其余所有文件和空壳子目录一并删除，目录变空后删除，
  逐级向上，止于媒体库根（根下第一级分类目录只在完全为空时删除）。仍有视频/strm 的目录及祖先不动。
- 目录列表失败（异常/None）一律视为失败，不当作空目录；所有前置检查通过后才写入；
  删除后列表复核，请求成功但仍存在的文件报错并保留目录。
- 幂等：目标已不存在视为已删除，仍继续处理字幕与空目录。
"""

from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Iterable, List, Optional, Set, Tuple

try:  # 插件运行态使用 MoviePilot 日志；离线测试回退标准库
    from app.sdk.logging import logger
except Exception:  # pragma: no cover
    import logging

    logger = logging.getLogger("p115_cleanup")

MAX_SUBTITLE_TAGS = 3
# 目录子树内已没有任何视频/strm 时，其余全部文件都可清理；分类目录（根下一级）只在完全为空时才删
MIN_PURGE_DEPTH_BELOW_ROOT = 2
# 目录级（季/剧集）删除的边界
MIN_DIR_DEPTH_BELOW_ROOT = 2  # 目录必须在媒体库根之下至少两级（根/分类/片名）
MAX_DIR_DEPTH = 6
MAX_DIR_ENTRIES = 3000
MAX_DIR_VIDEOS = 500


def _norm_exts(exts: Optional[Iterable[str]]) -> Set[str]:
    return {e.strip().lstrip(".").lower() for e in (exts or []) if e and e.strip()}


def _ext_of(name: str) -> str:
    return PurePosixPath(name).suffix.lstrip(".").lower()


def _stem_of(name: str) -> str:
    return PurePosixPath(name).stem


def _posix(path: Any) -> str:
    return str(path).replace("\\", "/").rstrip("/") or "/"


def path_is_canonical(path: Any) -> bool:
    """必须是规范绝对 POSIX 路径：不含 ``..``、``.``、空段、反斜杠"""
    t = str(path)
    if not t.startswith("/") or "\\" in t:
        return False
    parts = [x for x in t.split("/")[1:] if x != ""]
    if any(x in ("..", ".") for x in parts):
        return False
    return "//" not in t


def dir_event_allowed(item_type: Any, is_folder: Any) -> bool:
    """仅 Emby 明确的 Season/Series 且 IsFolder 为真时允许目录级删除"""
    return str(item_type) in ("Season", "Series") and is_folder is True


def looks_like_media_file(path: str, video_exts: Iterable[str]) -> bool:
    """路径后缀是视频或 strm（用于区分 Description 里的逐文件路径与目录）"""
    ext = PurePosixPath(str(path).replace("\\", "/")).suffix.lstrip(".").lower()
    return bool(ext) and (ext == "strm" or ext in _norm_exts(video_exts))


def subtitle_belongs_to(sub_name: str, video_stem: str, sub_exts: Set[str]) -> bool:
    """
    字幕文件名是否按名字边界归属于某视频主名

    :param sub_name: 字幕文件名
    :param video_stem: 视频主名（不含扩展名）
    :param sub_exts: 字幕扩展名集合（小写、无点）
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
    delete_requested: List[str] = field(default_factory=list)  # 删除请求返回成功
    leftovers_deleted: List[str] = field(default_factory=list)  # 视频/strm 全无后清理的其余文件


@dataclass
class DirPlan:
    ok: bool = False
    reason: str = ""
    dir_path: str = ""
    dir_item: Any = None
    present: bool = False
    root: Optional[str] = None
    files: List[Any] = field(default_factory=list)  # 待删视频+字幕
    dirs: List[Any] = field(default_factory=list)  # 遍历到的目录（含自身）
    videos: int = 0


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
        dir_cleanup_storages: Iterable[str] = ("u115",),
        purge_leftovers: bool = True,
    ) -> None:
        self.purge_leftovers = purge_leftovers
        self.sc = storagechain
        # 仅对已验证“列表失败会抛异常、空列表即真空”的存储做目录清理
        self.dir_cleanup_storages = set(dir_cleanup_storages)
        self.sub_exts = _norm_exts(sub_exts)
        self.audio_exts = _norm_exts(audio_exts)
        self.video_exts = _norm_exts(video_exts) - self.sub_exts - self.audio_exts

    # ---- 底层查询（失败一律抛出，由上层视为失败） ----
    def _get_item(self, storage: str, path: str) -> Optional[Any]:
        strict = getattr(self.sc, "get_file_item_strict", None)
        if strict is not None:
            return strict(storage=storage, path=PurePosixPath(path))
        raise RuntimeError("存储链不支持严格查询，无法区分不存在与查询失败")

    def _list(self, item: Any) -> List[Any]:
        items = self.sc.list_files(item)
        if items is None:
            raise RuntimeError(f"目录列表失败: {item.path}")
        return list(items)

    def _is_video(self, name: str) -> bool:
        return _ext_of(name) in self.video_exts

    # ---- 计划 ----
    def plan(
        self,
        storage: str,
        video_path: str,
        root: Optional[str] = None,
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
                p.cleanup_dirs = False  # 不在媒体库根下：只删精确文件，不清目录
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
        if p.video_present and not any(_posix(i.path) == p.video_path for i in files):
            p.reason = "父目录列表中找不到目标视频，状态矛盾，拒绝"
            return p
        target_stem = _stem_of(name)
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

    # ---- 执行 ----
    def execute(self, storage: str, plan: CleanupPlan) -> CleanupResult:
        r = CleanupResult(
            video_path=plan.video_path,
            subtitles_kept=list(plan.subtitles_kept),
        )
        if not plan.ok:
            r.reason = plan.reason
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

    def _scan_leftovers(self, d: Any) -> Optional[Tuple[List[Any], List[Any]]]:
        """扫描子树；有视频/strm、类型未知、列表失败、超限均返回 None"""
        files: List[Any] = []
        dirs: List[Any] = []
        stack = [(d, 0)]
        entries = 0
        try:
            while stack:
                cur, depth = stack.pop()
                if depth > MAX_DIR_DEPTH:
                    return None
                for it in self._list(cur):
                    entries += 1
                    if entries > MAX_DIR_ENTRIES:
                        return None
                    t = getattr(it, "type", "")
                    if t == "dir":
                        dirs.append(it)
                        stack.append((it, depth + 1))
                    elif t == "file":
                        if _ext_of(it.name) in self.video_exts:
                            return None  # 仍有视频/strm
                        files.append(it)
                    else:
                        return None
        except Exception:
            return None
        return files, dirs

    def _purge_leftovers(self, storage: str, d: Any, root: Optional[str], r: CleanupResult) -> bool:
        """
        目录子树内已没有任何视频/strm（扩展名取 MoviePilot 媒体扩展名，已含 strm）时，
        删除其余所有文件和空壳子目录，使目录变空。写入前连续两次扫描且结果一致；
        仍有视频/strm、列表失败、条目过多、层级过浅（分类目录）均保持原样并返回 False。
        删除后以列表复核：请求成功但仍存在的文件写入 errors，不计入 leftovers_deleted。
        """
        if not self.purge_leftovers or self._depth_below_root(d.path, root) < MIN_PURGE_DEPTH_BELOW_ROOT:
            return False
        first = self._scan_leftovers(d)
        if first is None:
            return False
        second = self._scan_leftovers(d)
        if second is None or {_posix(x.path) for x in first[0]} != {_posix(x.path) for x in second[0]} or {
            _posix(x.path) for x in first[1]
        } != {_posix(x.path) for x in second[1]}:
            return False
        files, dirs = second
        requested: List[str] = []
        for f in files:
            try:
                ok = self.sc.delete_file(f)
            except Exception as e:
                r.errors.append(f"残留文件删除异常 {f.name}: {e}")
                return False
            if not ok:
                r.errors.append(f"残留文件删除失败: {f.path}")
                return False
            requested.append(_posix(f.path))
        for sd in sorted(dirs, key=lambda x: -len(PurePosixPath(_posix(x.path)).parts)):
            sp = _posix(sd.path)
            try:
                if self._list(sd):
                    break  # 子目录仍有内容（含请求成功但未删除的文件），由下方复核报告
                if not getattr(sd, "fileid", None) or not self.sc.delete_file(sd):
                    r.errors.append(f"空壳子目录删除失败: {sp}")
                    return False
                if self._get_item(storage, sp) is not None:
                    r.errors.append(f"复核发现子目录仍存在: {sp}")
                    return False
            except Exception as e:
                r.errors.append(f"空壳子目录处理失败 {sp}: {e}")
                return False
            r.dirs_deleted.append(sp)
        # 复核：逐个子树列表确认请求删除的文件已不存在
        survivors = set()
        try:
            for dd in [d] + [x for x in dirs if _posix(x.path) not in set(r.dirs_deleted)]:
                for it in self._list(dd):
                    if _posix(it.path) in set(requested):
                        survivors.add(_posix(it.path))
        except Exception as e:
            r.errors.append(f"残留文件清理后复核失败: {e}")
            return False
        for x in requested:
            if x in survivors:
                r.errors.append(f"复核发现残留文件仍存在: {x}")
            else:
                r.leftovers_deleted.append(x)
        if survivors:
            return False
        try:
            return not self._list(d)
        except Exception as e:
            r.errors.append(f"残留文件清理后复核失败: {e}")
            return False

    def _cleanup_dirs(
        self, storage: str, plan: CleanupPlan, remaining: List[Any], r: CleanupResult
    ) -> None:
        cur = plan.parent_item
        listing = remaining
        root = plan.root
        while True:
            cur_path = _posix(cur.path)
            if cur_path == root or not cur_path.startswith(root + "/"):
                r.dir_stop_reason = "到达媒体库根"
                return
            if listing:
                if self._purge_leftovers(storage, cur, root, r):
                    try:
                        listing = self._list(cur)
                    except Exception as e:
                        r.dir_stop_reason = f"清理残留文件后复核失败，保留: {cur_path}: {e}"
                        return
                if r.errors:
                    r.dir_stop_reason = f"残留文件清理失败: {cur_path}"
                    return
                if listing:
                    r.dir_stop_reason = f"目录非空保留: {cur_path}"
                    return
            if not getattr(cur, "fileid", None):
                r.dir_stop_reason = f"目录缺少标识，保留: {cur_path}"
                return
            try:  # 删除前最后一次独立确认真空
                if self._list(cur):
                    r.dir_stop_reason = f"目录非空保留(删前复核): {cur_path}"
                    return
            except Exception as e:
                r.dir_stop_reason = f"删前复核失败，保留: {cur_path}: {e}"
                return
            try:
                ok = self.sc.delete_file(cur)
            except Exception as e:
                ok = False
                r.errors.append(f"目录删除异常 {cur_path}: {e}")
            if not ok:
                r.errors.append(f"目录删除失败: {cur_path}")
                r.dir_stop_reason = "目录删除失败"
                return
            try:
                if self._get_item(storage, cur_path) is not None:
                    r.errors.append(f"复核发现目录仍存在: {cur_path}")
                    return
            except Exception as e:
                r.errors.append(f"目录删除后复核失败 {cur_path}: {e}")
                return
            r.dirs_deleted.append(cur_path)
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

    # ---- 目录级（季/剧集）：逐文件精确删除，不整目录删 ----
    def plan_dir(self, storage: str, dir_path: str, root: Optional[str]) -> DirPlan:
        p = DirPlan(dir_path=_posix(dir_path))
        if not path_is_canonical(dir_path) or (root and not path_is_canonical(root)):
            p.reason = f"路径不规范（含 .. 或相对路径），拒绝: {dir_path}"
            return p
        if storage not in self.dir_cleanup_storages or not root:
            p.reason = "目录级删除需要已验证的存储和媒体库根，拒绝"
            return p
        root_p = _posix(root)
        try:
            rel = PurePosixPath(p.dir_path).relative_to(root_p)
        except ValueError:
            p.reason = f"目录不在媒体库根之下，拒绝: {p.dir_path}"
            return p
        if len(rel.parts) < MIN_DIR_DEPTH_BELOW_ROOT:
            p.reason = f"目录层级过浅（需在根之下至少 {MIN_DIR_DEPTH_BELOW_ROOT} 级），拒绝: {p.dir_path}"
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
            stack = [(item, 0)]
            entries = 0
            while stack:
                cur, depth = stack.pop()
                if depth > MAX_DIR_DEPTH:
                    p.reason = f"目录嵌套过深，拒绝: {cur.path}"
                    return p
                p.dirs.append(cur)
                for it in self._list(cur):
                    entries += 1
                    if entries > MAX_DIR_ENTRIES:
                        p.reason = "目录条目过多，拒绝"
                        return p
                    t = getattr(it, "type", "")
                    if t == "dir":
                        stack.append((it, depth + 1))
                    elif t == "file":
                        ext = _ext_of(it.name)
                        if ext in self.video_exts:
                            p.videos += 1
                            if p.videos > MAX_DIR_VIDEOS:
                                p.reason = f"视频数量超过上限 {MAX_DIR_VIDEOS}，拒绝"
                                return p
                            p.files.append(it)
                        elif ext in self.sub_exts:
                            p.files.append(it)
        except Exception as e:
            p.reason = f"前置查询失败: {e}"
            return p
        p.ok = True
        return p

    def execute_dir(self, storage: str, plan: DirPlan) -> CleanupResult:
        r = CleanupResult(video_path=plan.dir_path, mode="dir")
        if not plan.ok:
            r.reason = plan.reason
            return r
        if not plan.present:
            r.video_already_absent = True
            r.ok = True
            r.dir_stop_reason = "目录已不存在"
            return r
        for f in plan.files:
            try:
                ok = self.sc.delete_file(f)
            except Exception as e:
                ok = False
                r.errors.append(f"{f.name} 删除异常: {e}")
            if ok:
                r.delete_requested.append(_posix(f.path))
            else:
                r.errors.append(f"{f.name} 删除失败")
        requested = set(r.delete_requested)
        still = set()
        # 复核：已请求删除的必须消失；出现计划外的视频/字幕（plan 后新增）则报告未完成
        for d in plan.dirs:
            dp = _posix(d.path)
            try:
                cur = self._list(d)
            except Exception as e:
                r.errors.append(f"删除后复核列表失败 {dp}: {e}")
                continue
            for it in cur:
                ip = _posix(it.path)
                if ip in requested:
                    still.add(ip)
                    r.errors.append(f"复核发现仍存在: {it.path}")
                elif getattr(it, "type", "") == "file" and (
                    _ext_of(it.name) in self.video_exts
                    or _ext_of(it.name) in self.sub_exts
                ):
                    r.errors.append(f"出现计划外媒体/字幕，未清理: {it.path}")
        r.files_deleted = [x for x in r.delete_requested if x not in still]
        if r.errors:
            r.dir_stop_reason = "存在失败项，不清理目录"
            return r
        target = _posix(plan.dir_path)
        for d in sorted(plan.dirs, key=lambda x: -len(PurePosixPath(_posix(x.path)).parts)):
            dp = _posix(d.path)
            if dp == target:
                continue
            # 子目录：其下若已有被保留的子目录/文件则不删；以删子目录后的现状为准
            try:
                cur = self._list(d)
            except Exception as e:
                r.errors.append(f"子目录复核失败 {dp}: {e}")
                return r
            if cur and self._purge_leftovers(storage, d, plan.root, r):
                try:
                    cur = self._list(d)
                except Exception as e:
                    r.errors.append(f"清理残留文件后复核失败 {dp}: {e}")
                    return r
            if r.errors:
                return r
            if cur or not getattr(d, "fileid", None):
                continue
            try:
                ok = self.sc.delete_file(d)
            except Exception as e:
                ok = False
                r.errors.append(f"目录删除异常 {dp}: {e}")
            if not ok:
                r.errors.append(f"目录删除失败: {dp}")
                return r
            try:
                if self._get_item(storage, dp) is not None:
                    r.errors.append(f"复核发现目录仍存在: {dp}")
                    return r
            except Exception as e:
                r.errors.append(f"目录删除后复核失败 {dp}: {e}")
                return r
            r.dirs_deleted.append(dp)
        try:
            remaining = self._list(plan.dir_item)
        except Exception as e:
            r.errors.append(f"目标目录复核失败: {e}")
            return r
        cp = CleanupPlan(parent_item=plan.dir_item, root=plan.root, cleanup_dirs=True)
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
            return self.delete_video_group(storage, path, root)
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

    仅接受视频扩展名；无候选或候选多于一个（歧义）返回 None。
    """
    if items is None:
        return None
    vids = _norm_exts(video_exts) - _norm_exts(sub_exts) - _norm_exts(audio_exts)
    found = set()
    for it in items:
        if getattr(it, "type", "file") != "file":
            continue
        if _stem_of(it.name) == basename and _ext_of(it.name) in vids:
            found.add(_ext_of(it.name))
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
    仅当它恰好是单个视频扩展名时才采用，否则返回 None 以便回退到目录查询。
    """
    if not container or not isinstance(container, str):
        return None
    c = container.strip().lstrip(".")
    if not c or "," in c or "/" in c:
        return None
    vids = _norm_exts(video_exts) - _norm_exts(sub_exts) - _norm_exts(audio_exts)
    return c if c.lower() in vids else None
