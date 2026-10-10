from typing import Any, Dict, List


SIDEBAR_NAV_ITEMS: Dict[str, Dict[str, Any]] = {
    "start": {
        "plugin_id": "P115StrmHelper",
        "nav_key": "start",
        "title": "115助手仪表盘",
        "icon": "mdi-speedometer",
        "section": "start",
        "order": 10,
    },
}


def sidebar_nav_keys_known() -> frozenset[str]:
    """
    已注册的 nav_key 集合
    """
    return frozenset(SIDEBAR_NAV_ITEMS.keys())


def build_sidebar_nav(keys: List[str]) -> List[Dict[str, Any]]:
    """
    按 keys 顺序返回导航项（每项为独立副本）
    """
    out: List[Dict[str, Any]] = []
    for k in keys:
        item = SIDEBAR_NAV_ITEMS.get(k)
        if item:
            out.append(dict(item))
    return out
