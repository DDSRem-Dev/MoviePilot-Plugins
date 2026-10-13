import importlib
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Dict
from unittest.mock import patch


def check_transfer_postprocess_contracts(instance: Any, check: Any) -> None:
    """
    真实严格事件总线中，其他监听器失败后的重投不破坏较新整理结果

    :param instance (Any): 已启用的真实插件实例
    :param check (Any): 测试断言对象
    """
    from app.application.chain.events import (
        snapshot_transfer_result,
        restore_transfer_result,
    )
    from app.runtime.event.binding import EventHandlerBinding
    from app.sdk.events import EventManager
    from app.schemas import FileItem, TransferInfo
    from app.schemas.types import EventType

    prefix = type(instance).__module__
    entry = importlib.import_module(prefix)
    transfer = importlib.import_module(prefix + ".helper.strm.transfer")
    processor = importlib.import_module(prefix + ".helper.strm.transfer.postprocess")
    bus = object.__new__(EventManager)
    EventManager.__init__(bus)
    bus.register_handler_instance_resolver(
        "isolated-postprocess",
        lambda cls: (
            EventHandlerBinding(instance=instance, owner_name=type(instance).__name__)
            if cls is type(instance)
            else None
        ),
    )
    bus.add_event_listener(EventType.TransferComplete, instance.generate_strm)
    failed = []

    def other_listener(event: Any) -> None:
        failed.append(True)
        raise RuntimeError("other listener failed")

    bus.add_event_listener(EventType.TransferComplete, other_listener)
    bus.start()
    try:
        with TemporaryDirectory() as directory, ExitStack() as stack:
            library = Path(directory).resolve()
            for name, value in {
                "transfer_monitor_enabled": True,
                "transfer_monitor_paths": f"{library}#/cloud",
                "moviepilot_address": "https://moviepilot.invalid",
                "transfer_monitor_remove_stale_strm": False,
                "transfer_monitor_scrape_metadata_enabled": True,
                "transfer_monitor_media_server_refresh_enabled": False,
                "transfer_monitor_emby_mediainfo_enabled": False,
            }.items():
                stack.enter_context(patch.object(entry.configer, name, value))
            stack.enter_context(
                patch.object(
                    transfer.TransferStrmHelper,
                    "_get_overwrite_mode",
                    return_value="latest",
                )
            )
            scrape = stack.enter_context(
                patch.object(transfer, "media_scrape_metadata")
            )
            stack.enter_context(
                patch.object(
                    transfer.StrmUrlGetter,
                    "get_strm_url",
                    return_value="https://isolated.invalid/video",
                )
            )
            remote = {}
            stack.enter_context(
                patch.object(
                    processor.StorageChain,
                    "get_file_item_strict",
                    side_effect=lambda storage, path: remote.get(path.as_posix()),
                )
            )

            def payload(name: str, file_id: str) -> Dict[str, Any]:
                target = FileItem(
                    storage="u115",
                    type="file",
                    path=f"/cloud/{name}",
                    name=name,
                    fileid=file_id,
                    pickcode="a" * 17,
                    parent_fileid="0",
                    size=100,
                    modify_time=1,
                )
                remote[target.path] = target.model_copy(update={"modify_time": 2})
                return {
                    "idempotency_key": f"postprocess:{type(instance).__name__}:{file_id}",
                    "transferinfo": TransferInfo(
                        target_item=target,
                        target_diritem=FileItem(
                            storage="u115", type="dir", path="/cloud"
                        ),
                        transfer_type="copy",
                    ),
                }

            old = payload("Example.S01E01.1080p.mkv", "901")
            frozen = snapshot_transfer_result(old)
            with check.assertRaisesRegex(RuntimeError, "other listener failed"):
                bus.send_event_strict(EventType.TransferComplete, old)
            check.assertEqual(failed, [True])
            check.assertTrue((library / "Example.S01E01.1080p.strm").exists())
            bus.remove_event_listener(EventType.TransferComplete, other_listener)
            remote.pop(old["transferinfo"].target_item.path)
            new = payload("Example.S01E01.2160p.mkv", "902")
            bus.send_event_strict(EventType.TransferComplete, new)
            check.assertFalse((library / "Example.S01E01.1080p.strm").exists())
            bus.send_event_strict(
                EventType.TransferComplete, restore_transfer_result(frozen)
            )
            check.assertEqual(
                [path.name for path in library.glob("*.strm")],
                ["Example.S01E01.2160p.strm"],
            )
            check.assertEqual(scrape.call_count, 2)
    finally:
        bus.stop()
