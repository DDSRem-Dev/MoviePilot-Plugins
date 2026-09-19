__all__ = ["OfflineLinkResolver"]


from re import IGNORECASE, compile as re_compile, finditer as re_finditer
from typing import List, Tuple


class OfflineLinkResolver:
    """
    离线下载链接解析工具

    负责从消息文本中提取磁力、ed2k 与种子链接
    """

    _ED2K_FILE_LINK = re_compile(
        r"(ed2k://\|file\|[^|]+\|\d+\|[0-9A-Fa-f]{32}(?:\|(?:h|p)=[^|]+)?\|/)",
        IGNORECASE,
    )

    _STRIP_INVISIBLE = dict.fromkeys(
        (0x200B, 0x200C, 0x200D, 0x200E, 0x200F, 0xFEFF),
    )

    @staticmethod
    def _sanitize_offline_url(url: str) -> str:
        """
        去掉链接中的零宽与方向标记字符
        """
        if not url:
            return url
        return url.translate(OfflineLinkResolver._STRIP_INVISIBLE)

    @staticmethod
    def parse_offline_input(raw: str) -> List[str]:
        """
        从一段文本解析全部离线下载链接

        换行可能被主程序去掉，故依赖正则按出现顺序提取；ed2k 多条可同一行空格分隔

        :param raw (str): arg_str、用户消息全文等

        :return List: 按出现顺序去重后的链接列表
        """
        if not raw or not isinstance(raw, str):
            return []
        s = raw.replace("\uff5c", "|").strip()
        if not s:
            return []
        spans: List[Tuple[int, int, str]] = []
        for m in OfflineLinkResolver._ED2K_FILE_LINK.finditer(s):
            spans.append((m.start(), m.end(), m.group(1)))
        for m in re_finditer(r"(magnet:\?[^\s]+)", s, IGNORECASE):
            spans.append((m.start(), m.end(), m.group(1)))
        for m in re_finditer(r"(https?://[^\s]+\.torrent(?:\?[^\s]*)?)", s, IGNORECASE):
            spans.append((m.start(), m.end(), m.group(1)))
        spans.sort(key=lambda x: x[0])
        seen = set()
        out: List[str] = []
        last_end = -1
        for st, en, txt in spans:
            if st < last_end:
                continue
            c = OfflineLinkResolver._sanitize_offline_url(txt)
            if not c or c in seen:
                continue
            seen.add(c)
            out.append(c)
            last_end = en
        return out
