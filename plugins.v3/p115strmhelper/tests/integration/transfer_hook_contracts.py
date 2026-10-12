import importlib
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Condition, Event, Thread, current_thread
from typing import Any
from unittest.mock import patch


def check_transfer_hook_contracts(instance: Any, check: Any) -> None:
    """
    验证真实 V3 整理事件回写、广播快照和在途回调停止反馈

    :param instance (Any): 已启用的隔离插件实例
    :param check (Any): 测试断言对象
    """
    from app.modules.filemanager import transhandler
    from app.runtime.event.binding import EventHandlerBinding
    from app.schemas import FileItem, TransferInfo
    from app.schemas.event import TransferInterceptEventData, TransferOverwriteCheckEventData
    from app.schemas.mediaserver import ExistMediaInfo
    from app.schemas.types import ChainEventType, EventType, MediaType
    from app.sdk.events import EventManager
    from app.sdk.media import MediaInfo

    entry = importlib.import_module(type(instance).__module__)
    service = entry.servicer
    bus = object.__new__(EventManager)
    EventManager.__init__(bus)
    bus.register_handler_instance_resolver(
        "isolated-transfer-hooks",
        lambda cls: (
            EventHandlerBinding(instance=instance, owner_name=type(instance).__name__)
            if cls is type(instance) else None
        ),
    )
    for kind, name in (
        (ChainEventType.TransferRenameBuild, "rename_dict_supplement"),
        (ChainEventType.TransferIntercept, "intercept_if_exists_in_library"),
        (ChainEventType.TransferOverwriteCheck, "share_strm_overwrite_check"),
        (EventType.TransferFailed, "auto_delete_inferior_source"),
    ):
        bus.add_event_listener(kind, getattr(instance, name))
    with TemporaryDirectory() as directory, ExitStack() as stack:
        root = Path(directory).resolve()
        source = FileItem(storage="local", type="file", path=str(root / "video.mkv"), name="video.mkv", extension="mkv")
        target = root / "target.strm"
        target.write_text("https://isolated.invalid/P115StrmHelper?share_code=share&receive_code=abcd&id=42")
        movie = MediaInfo(media_source="bangumi", media_id="42", title="synthetic", type=MediaType.MOVIE)
        exists = ExistMediaInfo(type=MediaType.MOVIE, server="isolated", seasons={1: [1, 2]})
        for key in (
            "rename_dict_supplement_enabled", "transfer_intercept_exists_enabled",
            "share_strm_overwrite_check_enabled", "auto_delete_inferior_source_enabled", "notify",
        ):
            stack.enter_context(patch.object(entry.configer, key, True))
        stack.enter_context(patch.object(entry.configer, "rename_dict_supplement_overwrite_mode", "fill_missing"))
        stack.enter_context(patch.object(transhandler, "eventmanager", bus))
        module_call = stack.enter_context(patch.object(instance.chain, "run_module", return_value=exists))
        empty_directory = FileItem(storage="local", type="dir", path=str(root), name=root.name)
        stack.enter_context(patch.object(entry.DirectoryHelper, "get_media_root_path", return_value=root))
        stack.enter_context(patch.object(entry.StorageChain, "get_file_item", autospec=True, return_value=empty_directory))
        stack.enter_context(patch.object(entry.StorageChain, "list_files", autospec=True, return_value=[]))
        delete_empty = stack.enter_context(patch.object(entry.StorageChain, "delete_file", autospec=True, return_value=True))
        delete_source = stack.enter_context(patch.object(entry.StorageChain, "delete_media_file", autospec=True, return_value=True))
        notify = stack.enter_context(patch.object(entry, "post_message"))
        fields = {"videoCodec": "H265", "audioCodec": "EAC3 5.1", "file_size": 4096}
        probe = stack.enter_context(patch.object(entry.RenameDictUtils, "ffprobe_get_media_info", return_value=(fields, "")))
        cache = type(instance)._rename_media_fields_cache
        cache.clear()
        stack.callback(cache.clear)
        bus.start()
        stack.callback(bus.stop)

        def rename():
            return transhandler.TransHandler.get_rename_path(
                "{{ videoCodec }}-{{ audioCodec }}.mkv", {"videoCodec": "H264", "audioCodec": "AAC"},
                source_path=source.path, source_item=source,
            )

        def intercept(episode: str = "movie.mkv", media=movie):
            return TransferInterceptEventData(
                fileitem=source, mediainfo=media, target_storage="local",
                target_path=root / episode, transfer_type="copy",
            )

        def overwrite():
            return TransferOverwriteCheckEventData(
                fileitem=source, target_item=FileItem(storage="local", type="file", path=str(target), size=1),
                target_storage="local", target_path=target, overwrite_mode="size", transfer_type="copy",
            )

        def failed():
            return {"fileitem": source, "transferinfo": TransferInfo(success=False, message="同名文件质量更好")}

        check.assertEqual(rename(), Path("H264-EAC3 5.1.mkv"))
        probe.assert_called_once()
        check.assertEqual(rename(), Path("H264-EAC3 5.1.mkv"))
        probe.assert_called_once()
        with patch.object(entry.configer, "rename_dict_supplement_overwrite_mode", "always"):
            check.assertEqual(rename(), Path("H265-EAC3 5.1.mkv"))
        intercepted = intercept()
        check.assertIs(bus.send_event(ChainEventType.TransferIntercept, intercepted).event_data, intercepted)
        check.assertTrue(intercepted.cancel)
        check.assertEqual(intercepted.source, "P115StrmHelper")
        check.assertEqual(intercepted.reason, "媒体库已存在：synthetic（isolated）")
        check.assertIs(module_call.call_args.kwargs["mediainfo"], movie)
        check.assertEqual(module_call.call_args.args, ("media_exists",))
        delete_empty.assert_called_once()
        tv = MediaInfo(media_source="bangumi", media_id="43", title="series", type=MediaType.TV)
        for episode, expected in (("series.S01E01.mkv", True), ("series.S01E03.mkv", False)):
            payload = intercept(episode, tv)
            bus.send_event(ChainEventType.TransferIntercept, payload)
            check.assertEqual(payload.cancel, expected)
        check.assertEqual(delete_empty.call_count, 2)
        with patch.dict(entry.sharestrmcacher.file_item_dict, {"share:abcd:42": {"size": 2048}}):
            payload = overwrite()
            bus.send_event(ChainEventType.TransferOverwriteCheck, payload)
            check.assertEqual(payload.target_size, 2048)
            check.assertIn("缓存", payload.reason)
        payload = overwrite()
        bus.send_event(ChainEventType.TransferOverwriteCheck, payload)
        check.assertEqual(payload.target_size, 4096)
        check.assertIsNone(payload.overwrite)
        bus.send_event_strict(EventType.TransferFailed, failed())
        delete_source.assert_called_once()
        check.assertIsInstance(delete_source.call_args.kwargs["fileitem"], FileItem)
        check.assertEqual(delete_source.call_args.kwargs["fileitem"].path, source.path)
        notify.assert_called_once()
        check.assertEqual(notify.call_args.kwargs["mtype"], entry.MessageType.Plugin)

        cache.clear()
        condition = Condition()
        release = Event()
        entered = []
        results = []
        errors = []
        workers = []

        def hold(result):
            with condition:
                entered.append(current_thread())
                condition.notify_all()
            if not release.wait(timeout=5):
                raise AssertionError("宿主测试未释放整理扩展回调")
            return result

        probe.side_effect = lambda **kwargs: hold((fields, ""))
        module_call.side_effect = lambda *args, **kwargs: hold(exists)
        delete_source.side_effect = lambda *args, **kwargs: hold(True)
        inflight_intercept = intercept()
        inflight_overwrite = overwrite()
        callbacks = (
            rename,
            lambda: bus.send_event(ChainEventType.TransferIntercept, inflight_intercept),
            lambda: bus.send_event(ChainEventType.TransferOverwriteCheck, inflight_overwrite),
            lambda: bus.send_event_strict(EventType.TransferFailed, failed()),
        )

        def run(callback) -> None:
            try:
                results.append(callback())
            except Exception as error:
                errors.append(error)

        try:
            for callback in callbacks:
                worker = Thread(target=run, args=(callback,))
                workers.append(worker)
                worker.start()
            with condition:
                check.assertTrue(condition.wait_for(lambda: len(entered) == 4, timeout=3))
            for worker in entered:
                check.assertEqual(service._sync_operations.get(worker), 1)
            bus.disable_event_handler(type(instance))
            stop = service._stop_sync_operations
            old_client = service.client
            with patch.object(service, "_stop_sync_operations", side_effect=lambda: stop(0)):
                check.assertFalse(instance.stop_service())
                with check.assertRaisesRegex(RuntimeError, "旧插件任务尚未退出"):
                    instance.init_plugin(dict(instance.get_config(), cookies="new-account"))
            check.assertIs(service.client, old_client)
            check.assertEqual(instance.get_data("enabled-cycle"), 3)
            bus.enable_event_handler(type(instance))
            check.assertEqual(rename(), Path("H264-AAC.mkv"))
            callbacks[1]()
            callbacks[2]()
            check.assertFalse(inflight_intercept.cancel)
            check.assertIsNone(inflight_overwrite.target_size)
            with check.assertRaisesRegex(RuntimeError, "同步服务已停止"):
                callbacks[3]()
            check.assertEqual(len(entered), 4)
        finally:
            release.set()
            for worker in workers:
                worker.join(timeout=2)
        check.assertTrue(all(not worker.is_alive() for worker in workers))
        check.assertEqual(errors, [])
        check.assertEqual(len(results), 4)
        check.assertTrue(inflight_intercept.cancel)
        check.assertEqual(inflight_overwrite.target_size, 4096)
        check.assertEqual(notify.call_count, 2)
        check.assertEqual(service._sync_operations, {})
