from typing import Any, Dict


def matches_file(identity: Dict[str, Any], current: Any) -> bool:
    """
    核对全部可比文件标识，查询缺少主标识时等待重试
    """
    if current is None:
        return False
    field = "fileid" if identity.get("fileid") else "pickcode"
    if not identity.get(field) or not getattr(current, field, None):
        raise RuntimeError("整理后处理无法确认云端文件身份，等待重试")
    for name in ("fileid", "pickcode"):
        expected = identity.get(name)
        actual = getattr(current, name, None)
        if expected and actual and str(expected) != str(actual):
            return False
    return True


def freeze_size(plan: Dict[str, Any], current: Any) -> None:
    """
    将回源大小固定到计划与输出归属，保留原事件及旧文件清理快照
    """
    size = getattr(current, "size", None)
    identity = plan["identity"]
    if identity.get("size") is not None and size is None:
        raise RuntimeError("整理后处理未取得云端精确大小，等待重试")
    identity.update(size=size, size_source="storage")
    plan["target"]["size"] = size
    for operation in plan["operations"]:
        if operation["kind"] == "write":
            operation["identity"].update(size=size, size_source="storage")


def has_started(plan: Dict[str, Any]) -> bool:
    """
    判断固定计划是否已准备文件或完成任意副作用
    """
    return any(
        operation.get("done") or operation.get("prepared")
        for operation in plan["operations"]
    ) or any(plan["effects"].values())


def is_display_size(expected: Any, actual: Any) -> bool:
    """
    识别旧版 115 两位小数显示值的往返转换，不使用相对误差容差
    """
    if not isinstance(expected, int) or not isinstance(actual, int):
        return False
    if expected <= 0 or actual < 1024 or expected == actual:
        return False
    factor = 1024
    while actual >= factor * 1024 and factor < 1024**5:
        factor *= 1024
    return expected == round(round(actual / factor, 2) * factor)
