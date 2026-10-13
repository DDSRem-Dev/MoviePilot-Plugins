from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Dict, List

from .planning import LINKED_ACTION, MAIN_ACTION, restore_skipped_plan


def validate_batch_intent(
    original: Callable,
    checkpoint: Any,
    *,
    phase: str,
    kind: str,
    payload: Dict[str, Any],
    previous_steps: List[Any],
) -> bool:
    """
    仅允许冻结批量计划及已成功步骤证据派生的操作进入宿主账本
    """
    arguments = dict(
        phase=phase, kind=kind, payload=payload, previous_steps=previous_steps
    )
    if original(checkpoint, **arguments):
        return True
    checkpoint = restore_skipped_plan(checkpoint)
    if original(checkpoint, **arguments):
        return True
    if not checkpoint.items or checkpoint.items[0].action != MAIN_ACTION:
        return False
    for item in checkpoint.items:
        if item.action not in {MAIN_ACTION, LINKED_ACTION}:
            return False
        if item.action == LINKED_ACTION:
            child = replace(
                checkpoint,
                planning_input=replace(
                    checkpoint.planning_input, source_fileitem=item.source_fileitem
                ),
                items=(replace(item, sequence=0, action="transfer"),),
                final_target_path=item.target_path,
                overwrite_mode="always",
                need_notify=False,
                need_scrape=False,
            )
            if original(child, **arguments):
                return True
        if phase != "p115_batch":
            continue
        capture = {"source": item.source_fileitem, "target": item.target_path}
        if kind == "capture_destination" and payload == capture:
            return True
        if kind == "materialize":
            for step in previous_steps:
                if (
                    step.phase == "p115_batch"
                    and step.kind == "capture_destination"
                    and step.state == "succeeded"
                    and step.intent_payload == capture
                    and payload
                    == {
                        "source": item.source_fileitem,
                        "target_storage": item.target_storage,
                        "parent": Path(item.target_path).parent.as_posix(),
                        "mode": checkpoint.resolved_transfer_type,
                        "baseline": step.result_payload,
                    }
                ):
                    return True
        if kind == "rename":
            for step in previous_steps:
                if (
                    step.phase == "p115_batch"
                    and step.kind == "materialize"
                    and step.state == "succeeded"
                    and step.intent_payload.get("source") == item.source_fileitem
                    and step.intent_payload.get("parent")
                    == Path(item.target_path).parent.as_posix()
                    and isinstance(step.result_payload, dict)
                    and isinstance(step.result_payload.get("item"), dict)
                    and payload
                    == {
                        "item": step.result_payload["item"],
                        "target": item.target_path,
                    }
                ):
                    return True
    return False
