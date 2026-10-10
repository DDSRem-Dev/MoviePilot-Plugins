from re import sub as re_sub
from typing import Any, Dict

_POINTS_PREFIX_RE = r"^\d+\s*积分\s*"


def strip_hdhive_title_points_prefix(title: str) -> str:
    """
    去掉标题行首的「N 积分」前缀，积分仅在元数据行展示

    :param title (str): 原始标题
    :return str: 清理后的标题；若清理后为空则返回原标题
    """
    t = (title or "").strip()
    if not t:
        return t
    cleaned = re_sub(_POINTS_PREFIX_RE, "", t).strip()
    return cleaned or t


def format_list_block_impl(data: Dict[str, Any], line_prefix: str) -> str:
    """
    HDHive 单行序号前缀 + 一行元数据（Markdown），不调用解锁接口
    """
    row = data.get("hdhive_raw") or {}
    title = strip_hdhive_title_points_prefix(
        (data.get("taskname") or "未知名称").strip()
    )
    lines: list[str] = [f"{line_prefix}【HDHive】{title}"]
    pts = row.get("unlock_points")
    if pts is None:
        pts_str = ""
    else:
        pts_str = f"积分: {pts}"
    bits: list[str] = []
    if pts_str:
        bits.append(pts_str)
    ss = row.get("share_size")
    if ss:
        bits.append(f"大小: {ss}")
    vr = row.get("video_resolution")
    if isinstance(vr, list) and vr:
        bits.append(f"分辨率: {', '.join(str(x) for x in vr)}")
    src = row.get("source")
    if isinstance(src, list) and src:
        bits.append(f"片源: {', '.join(str(x) for x in src)}")
    sub_l = row.get("subtitle_language")
    if isinstance(sub_l, list) and sub_l:
        bits.append(f"字幕: {', '.join(str(x) for x in sub_l)}")
    st = row.get("subtitle_type")
    if isinstance(st, list) and st:
        bits.append(f"字幕类型: {', '.join(str(x) for x in st)}")
    if "is_official" in row and row.get("is_official") is not None:
        bits.append(f"官方: {'是' if row.get('is_official') else '否'}")
    if bits:
        lines.append(f"  {' ｜ '.join(bits)}")
    return "\n".join(lines)
