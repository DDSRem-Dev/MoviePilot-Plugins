"""
猴子补丁目标存在性自检。

补丁失效最危险的形态不是报错，而是**静默失效**：宿主把方法改名、挪到别的
owner、或改变签名之后，``getattr(cls, name)`` 仍可能取到某个同名但语义不同的
对象，补丁照常套上去，直到用户发现整理行为异常才暴露。

因此在 ``enable()`` 前先做一次显式自检：

1. 目标属性必须存在（``hasattr``）；
2. 目标必须是可调用的；
3. 若给了 ``expected_params``，则形参名必须完整包含（允许宿主新增可选参数，
   也允许 ``**kwargs``，但不允许我们依赖的形参被删掉或改名）；
4. 目标模块名必须与 ``module_hint`` 一致（防止宿主把方法挪走后我们打到别处）。

自检失败时抛 ``PatchTargetError`` 并给出可读的修复线索，绝不静默跳过。
"""

from inspect import Parameter, signature
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

__all__ = ["PatchTargetError", "check_patch_target", "check_patch_targets"]


class PatchTargetError(RuntimeError):
    """补丁目标校验失败。"""


def _describe(target: Any) -> str:
    """生成便于定位的目标描述。"""
    module = getattr(target, "__module__", None)
    qualname = getattr(target, "__qualname__", None) or getattr(
        target, "__name__", repr(target)
    )
    return f"{module}.{qualname}" if module else str(qualname)


def check_patch_target(
    owner: Any,
    name: str,
    *,
    expected_params: Optional[Sequence[str]] = None,
    module_hint: Optional[str] = None,
    require_callable: bool = True,
) -> Callable[..., Any]:
    """
    校验单个补丁目标。

    :param owner: 目标类或模块
    :param name: 目标属性名
    :param expected_params: 期望包含的形参名（不含 ``self``）
    :param module_hint: 期望 ``__module__`` 前缀，用于防止目标被挪走
    :param require_callable: 是否要求目标可调用
    :return: 校验通过的目标对象
    :raises PatchTargetError: 任一项校验失败
    """
    owner_name = getattr(owner, "__name__", str(owner))

    if not hasattr(owner, name):
        raise PatchTargetError(
            f"补丁目标缺失：{owner_name}.{name} 不存在。"
            f"宿主可能已重命名或移除该方法，请检查补丁适配。"
        )

    target = getattr(owner, name)

    if require_callable and not callable(target):
        raise PatchTargetError(
            f"补丁目标不可调用：{owner_name}.{name} 是 "
            f"{type(target).__name__}，预期为方法。"
        )

    if module_hint:
        actual_module = getattr(target, "__module__", "") or ""
        if not actual_module.startswith(module_hint):
            raise PatchTargetError(
                f"补丁目标位置变更：{owner_name}.{name} 实际来自 "
                f"{actual_module!r}，预期前缀 {module_hint!r}。"
                f"宿主可能已把该实现挪到其它模块，请检查补丁适配。"
            )

    if expected_params:
        try:
            sig = signature(target)
        except (TypeError, ValueError) as err:
            raise PatchTargetError(
                f"无法读取补丁目标签名：{_describe(target)}（{err}）"
            ) from err

        has_varkw = any(
            p.kind == Parameter.VAR_KEYWORD for p in sig.parameters.values()
        )
        available = set(sig.parameters)
        missing = [p for p in expected_params if p not in available]
        # 宿主可以新增可选参数，但被依赖的形参必须仍在；**kwargs 视为全部满足
        if missing and not has_varkw:
            raise PatchTargetError(
                f"补丁目标签名不兼容：{_describe(target)} 缺少形参 "
                f"{missing}，实际为 {sorted(available)}。"
                f"宿主可能已调整该方法签名，请检查补丁适配。"
            )

    return target


def check_patch_targets(
    targets: Sequence[Tuple[Any, str, Dict[str, Any]]],
) -> List[Callable[..., Any]]:
    """
    批量校验补丁目标，任一失败即抛出。

    :param targets: 元素为 ``(owner, name, kwargs)`` 的序列
    :return: 校验通过的目标对象列表，顺序与入参一致
    """
    return [
        check_patch_target(owner, name, **(kwargs or {}))
        for owner, name, kwargs in targets
    ]
