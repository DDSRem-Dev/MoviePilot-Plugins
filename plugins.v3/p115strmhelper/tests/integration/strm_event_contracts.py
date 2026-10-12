import importlib
from contextlib import ExitStack
from threading import Condition, Event, Thread
from typing import Any
from unittest.mock import MagicMock, patch


def check_strm_event_contracts(instance: Any, check: Any) -> None:
    """
    使用实际 V3 严格事件分发验证生成、签到和交互入口的资源归属

    :param instance (Any): 已启用的隔离插件实例
    :param check (Any): 测试断言对象
    """
    from app.runtime.event.binding import EventHandlerBinding
    from app.sdk.events import EventManager
    from app.schemas.types import EventType, NotificationChannel
    from app.schemas.mediaserver import WebhookEventInfo

    entry = importlib.import_module(type(instance).__module__)
    service_module = importlib.import_module(type(instance).__module__ + ".service")
    views = importlib.import_module(type(instance).__module__ + ".interactive.views")
    handler = importlib.import_module(type(instance).__module__ + ".interactive.handler")
    search = importlib.import_module(
        type(instance).__module__ + ".helper.search.hdhive.search"
    )
    share_module = importlib.import_module(type(instance).__module__ + ".helper.share")
    share_strm_module = importlib.import_module(
        type(instance).__module__ + ".helper.strm.share.create"
    )
    sync_delete_module = importlib.import_module(type(instance).__module__ + ".helper.mediasyncdel")
    service = entry.servicer
    checkin_actions = ("hdhive_checkin_manual", "p115_checkin_manual")
    checkin_schedulers = ("hdhive_checkin_scheduler_tick", "p115_checkin_scheduler_tick")
    bus = object.__new__(EventManager)
    EventManager.__init__(bus)
    bus.register_handler_instance_resolver(
        "isolated-strm",
        lambda cls: (
            EventHandlerBinding(instance=instance, owner_name=type(instance).__name__)
            if cls is type(instance)
            else None
        ),
    )
    for name in (
        "p115_full_sync", "p115_inc_sync", "p115_strm", "p115_search",
        "p115_add_share", "p115_share_strm", *checkin_actions,
    ):
        bus.add_event_listener(EventType.PluginAction, getattr(instance, name))
    bus.add_event_listener(EventType.WebhookMessage, instance.sync_del_by_webhook)
    bus.add_event_listener(EventType.DownloadFileDeleted, instance.download_file_del_sync)
    bus.add_event_listener(EventType.UserMessage, instance.user_add_share)
    bus.add_event_listener(EventType.MessageAction, instance.message_action)
    transfer_types = (
        EventType.TransferComplete,
        EventType.AudioTransferComplete,
        EventType.SubtitleTransferComplete,
    )
    for event_type in transfer_types:
        bus.add_event_listener(event_type, instance.generate_strm)
    release = Event()
    condition = Condition()
    entered = []
    errors = []
    workers = []

    def hold(**kwargs) -> None:
        with condition:
            entered.append(kwargs)
            condition.notify_all()
        if not release.wait(timeout=5):
            raise AssertionError("宿主事件测试未释放业务回调")

    def dispatch(event_type, payload) -> None:
        try:
            bus.send_event_strict(event_type, payload)
        except Exception as error:
            errors.append(error)

    def scheduled(name: str) -> None:
        try:
            getattr(service, name)()
        except Exception as error:
            errors.append(error)

    with ExitStack() as stack:
        for key, value in (
            ("transfer_monitor_enabled", True),
            ("transfer_monitor_paths", "/cloud=>/isolated"),
            ("moviepilot_address", "https://isolated.invalid"),
            ("full_sync_strm_paths", "/cloud=>/isolated"),
            ("user_download_mediaext", "srt"),
        ):
            stack.enter_context(patch.object(entry.configer, key, value))
        stack.enter_context(patch.object(entry, "post_message", side_effect=hold))
        stack.enter_context(
            patch.object(entry, "run_hdhive_checkin_once", return_value=(True, "synthetic"))
        )
        stack.enter_context(
            patch.object(entry, "run_p115_checkin_once", return_value=(True, "synthetic"))
        )
        for name in checkin_schedulers:
            target = "p115_scheduler_tick" if name.startswith("p115_") else name
            stack.enter_context(patch.object(service_module, target, side_effect=hold))
        stack.enter_context(
            patch.object(entry.PathUtils, "get_p115_strm_path", return_value=(True, []))
        )
        full = stack.enter_context(patch.object(entry, "FullSyncStrmHelper"))
        full.return_value.get_generate_total.return_value = (1, 0, 0, 0, 0, 0)
        transfer = stack.enter_context(patch.object(entry, "TransferStrmHelper"))
        transfer.return_value.do_generate.side_effect = hold
        stack.enter_context(patch.object(service, "_run_full_sync", MagicMock()))
        stack.enter_context(patch.object(service, "_run_increment_sync", MagicMock()))
        stack.enter_context(patch.object(entry.configer, "tg_search_channels", []))
        stack.enter_context(patch.object(entry.configer, "hdhive_search_enabled", True))
        stack.enter_context(patch.object(entry, "is_hdhive_search_ready", return_value=True))
        stack.enter_context(patch.object(instance, "post_message"))
        media_search = stack.enter_context(
            patch.object(
                views.MediaSearcher,
                "search_like_api",
                side_effect=lambda *args, **kwargs: (hold(stage="media"), [])[1],
            )
        )
        browser = MagicMock()
        browser.get_resources.side_effect = lambda *args: (hold(stage="resources"), [])[1]
        browser.unlock_resource.side_effect = lambda *args: (
            hold(stage="unlock"),
            {"full_url": "https://115.com/s/synthetic?password=abcd"},
        )[1]
        stack.enter_context(patch.object(search, "get_hdhive_browser_client", return_value=browser))
        stack.enter_context(patch.object(handler, "get_hdhive_browser_client", return_value=browser))
        transfer_request = stack.enter_context(patch.object(handler.httpx, "get"))
        transfer_request.return_value.json.return_value = {"code": 1}
        interactive_events = []
        interactive_sessions = []
        for index, command in enumerate(("resource", "subscribe")):
            payload = {
                "plugin_id": type(instance).__name__,
                "channel": NotificationChannel.Telegram,
                "userid": f"interactive-{index}",
            }
            session = entry.session_manager.get_or_create(payload, type(instance).__name__)
            interactive_sessions.append(session)
            session.business.resource_key_list = [
                {"name": "synthetic", "type": "movie", "tmdb_id": 42}
            ]
            session.business.resource_info = {
                "data": [{"source": handler.HDHiveSearch.SOURCE, "hdhive_slug": "synthetic"}]
            }
            code = "rs" if command == "resource" else "sb"
            payload["text"] = f"{session.session_id}|c:{code}|v:0"
            interactive_events.append((EventType.MessageAction, payload))
        interactive_events.append(
            (
                EventType.PluginAction,
                {
                    "action": "p115_search",
                    "arg_str": "synthetic",
                    "channel": NotificationChannel.Telegram,
                    "userid": "interactive-search",
                },
            )
        )
        stack.enter_context(patch.object(entry.configer, "share_recieve_paths", ["/share"]))
        stack.enter_context(
            patch.object(entry.configer.share_interactive_gen_strm_config, "local_path", "")
        )
        stack.enter_context(
            patch.object(entry.ShareInteractiveGenStrmQueue, "validate_prerequisites", return_value=None)
        )
        share_url = "https://115.com/s/synthetic?password=abcd"
        share_urls = [share_url, "https://115.com/s/second?password=abcd"]
        for method in ("extract_share_url_from_text", "extract_all_u115_share_urls_from_text"):
            resolve = getattr(entry.ShareLinkResolver, method)

            def resolve_after_stop(text, resolve=resolve):
                hold(stage="share-resolution")
                return resolve(text)

            stack.enter_context(
                patch.object(entry.ShareLinkResolver, method, side_effect=resolve_after_stop)
            )
        share_work = stack.enter_context(
            patch.object(service.sharetransferhelper, "_ShareTransferHelper__add_share")
        )
        strm_work = stack.enter_context(
            patch.object(service.share_interactive_gen_strm_queue, "_run_job")
        )
        stack.enter_context(patch.object(share_module, "sleep"))
        stack.enter_context(patch.object(share_strm_module, "sleep"))
        share_events = [
            (EventType.UserMessage, {"text": share_url, "userid": "share-message"}),
            (
                EventType.PluginAction,
                {"action": "p115_add_share", "arg_str": share_url, "userid": "share-command"},
            ),
            (
                EventType.PluginAction,
                {"action": "p115_share_strm", "arg_str": " ".join(share_urls), "userid": "share-strm"},
            ),
        ]
        for key, value in (
            ("sync_del_enabled", True),
            ("sync_del_notify", False),
            ("sync_del_source", True),
            ("sync_del_p115_library_path", "/library=>/cloud"),
            ("sync_del_p115_force_delete_files", False),
        ):
            stack.enter_context(patch.object(entry.configer, key, value))
        stack.enter_context(patch.object(sync_delete_module, "get_transfer_history_repository"))
        deleted = stack.enter_context(
            patch.object(
                entry.MediaSyncDelHelper,
                "download_file_del_sync",
                autospec=True,
                side_effect=lambda helper, event: hold(stage="download-delete"),
            )
        )
        webhook_done = Event()
        webhook = stack.enter_context(
            patch.object(
                entry.MediaSyncDelHelper,
                "sync_del_by_webhook",
                autospec=True,
                side_effect=lambda helper, **kwargs: webhook_done.set(),
            )
        )
        webhook_queue = entry.sync_del_webhook_queue
        enqueue_webhook = webhook_queue.enqueue

        def enqueue_after_stop(task):
            hold(stage="webhook-enqueue")
            return enqueue_webhook(task)

        stack.enter_context(patch.object(webhook_queue, "enqueue", side_effect=enqueue_after_stop))
        webhook_info = WebhookEventInfo(
            event="deep.delete", item_type="Movie", item_path="/library/synthetic.strm",
            tmdb_id="42", json_object={"Item": {"Path": "/library/synthetic.strm"}},
        )
        delete_events = [
            (EventType.WebhookMessage, webhook_info),
            (EventType.DownloadFileDeleted, {"src": "/isolated/file.mkv"}),
        ]
        bus.start()
        try:
            events = [(kind, {"isolated": True}) for kind in transfer_types]
            events.extend(
                (
                    EventType.PluginAction,
                    {"action": action, "arg_str": "/cloud/sub", "userid": "42"},
                )
                for action in ("p115_full_sync", "p115_inc_sync", "p115_strm")
            )
            events.extend(
                (EventType.PluginAction, {"action": action, "userid": "42"})
                for action in checkin_actions
            )
            events.extend(interactive_events)
            events.extend(share_events)
            events.extend(delete_events)
            for event_type, payload in events:
                worker = Thread(target=dispatch, args=(event_type, payload))
                workers.append(worker)
                worker.start()
            for name in checkin_schedulers:
                worker = Thread(target=scheduled, args=(name,))
                workers.append(worker)
                worker.start()
            with condition:
                check.assertTrue(
                    condition.wait_for(
                        lambda: len(entered) == len(events) + len(checkin_schedulers),
                        timeout=3,
                    )
                )
            for worker in workers:
                check.assertEqual(service._sync_operations.get(worker), 1)
            bus.disable_event_handler(type(instance))
            stop = service._stop_sync_operations
            with patch.object(
                service, "_stop_sync_operations", side_effect=lambda: stop(0)
            ):
                check.assertFalse(instance.stop_service())
                with check.assertRaisesRegex(RuntimeError, "旧插件任务尚未退出"):
                    instance.init_plugin(
                        dict(instance.get_config(), cookies="new-account")
                    )
            check.assertEqual(instance.get_data("enabled-cycle"), 2)
            check.assertTrue(
                service_module.emby_mediainfo_queue._worker_thread.is_alive()
            )
            check.assertFalse(webhook_queue._stopping)
            webhook_info.item_path = "/changed"
            webhook_info.json_object["Item"]["Path"] = "/changed"
            check.assertFalse(service.sharetransferhelper._stopping)
            check.assertFalse(service.share_interactive_gen_strm_queue._stopping)
            release.set()
            for worker in workers:
                worker.join(timeout=2)
            check.assertTrue(all(not worker.is_alive() for worker in workers))
            check.assertTrue(service.sharetransferhelper.stop(timeout=2))
            check.assertTrue(service.share_interactive_gen_strm_queue.stop(timeout=2))
            check.assertEqual(share_work.call_count, 2)
            check.assertCountEqual(
                [call.args[3] for call in share_work.call_args_list],
                ["share-message", "share-command"],
            )
            check.assertEqual(
                [call.kwargs["share_url"] for call in strm_work.call_args_list], share_urls
            )
            check.assertEqual(service.sharetransferhelper._add_share_queue.unfinished_tasks, 0)
            check.assertEqual(service.share_interactive_gen_strm_queue._task_queue.unfinished_tasks, 0)
            check.assertTrue(webhook_done.wait(timeout=2))
            check.assertTrue(webhook_queue.stop(timeout=2))
            deleted.assert_called_once()
            check.assertEqual(deleted.call_args.args[1].event_data, {"src": "/isolated/file.mkv"})
            webhook.assert_called_once()
            snapshot = webhook.call_args.kwargs
            check.assertIsInstance(snapshot["event_data"], WebhookEventInfo)
            check.assertIsNot(snapshot["event_data"], webhook_info)
            check.assertEqual(snapshot["event_data"].item_path, "/library/synthetic.strm")
            check.assertEqual(snapshot["event_data"].json_object["Item"]["Path"], "/library/synthetic.strm")
            check.assertEqual(snapshot["event_data"].tmdb_id, "42")
            check.assertTrue(snapshot["enabled"])
            check.assertTrue(snapshot["del_source"])
            check.assertFalse(snapshot["notify"])
            check.assertFalse(snapshot["p115_force_delete_files"])
            check.assertEqual(snapshot["p115_library_path"], "/library=>/cloud")
            check.assertEqual(errors, [])
            check.assertEqual(service._sync_operations, {})
            check.assertEqual(transfer.return_value.do_generate.call_count, 3)
            media_search.assert_called_once_with("synthetic", count=100)
            browser.get_resources.assert_called_once_with("movie", 42)
            browser.unlock_resource.assert_called_once_with("synthetic")
            transfer_request.assert_called_once()
            check.assertEqual(
                transfer_request.call_args.kwargs["params"]["share_url"],
                "https://115.com/s/synthetic?password=abcd",
            )
            check.assertEqual(interactive_sessions[0].view.name, "resource_list")
            check.assertEqual(interactive_sessions[1].view.name, "subscribe_fail")
            bus.enable_event_handler(type(instance))
            with check.assertRaisesRegex(RuntimeError, "同步服务已停止"):
                bus.send_event_strict(EventType.TransferComplete, {"isolated": True})
            check.assertEqual(transfer.return_value.do_generate.call_count, 3)
        finally:
            release.set()
            for worker in workers:
                worker.join(timeout=2)
            service.sharetransferhelper.stop(timeout=2)
            service.share_interactive_gen_strm_queue.stop(timeout=2)
            webhook_queue.stop(timeout=2)
            bus.stop()
