import asyncio
import importlib
import importlib.util
import json
import os
import socket
import subprocess
import sys
import unittest
from contextlib import ExitStack
from contextvars import ContextVar
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
from typing import Any, Dict, List, Tuple
from unittest.mock import patch

from backup_api_contracts import (
    check_backup_api_contracts,
    check_disabled_backup_listing,
    check_disabled_backup_submission,
)
from batch_transfer_contracts import run_contracts as run_batch_transfer_contracts
from browse_contracts import check_browse_contracts, check_disabled_account_contract
from cleanup_store_contracts import check_cleanup_store_contracts
from life_diagnostic_contracts import check_life_diagnostic_contracts
from original_life_contracts import check_original_life_contracts
from original_sync_delete_contracts import check_original_sync_delete_contract
from original_utils_contracts import check_original_utility_contracts
from qrcode_request_contracts import check_qrcode_request_contracts
from strm_api_contracts import check_strm_api_contracts
from strm_event_contracts import check_strm_event_contracts
from transfer_hook_contracts import check_transfer_hook_contracts
from transfer_postprocess_contracts import check_transfer_postprocess_contracts


ROOT = Path(__file__).resolve().parents[2]
REPOSITORY = ROOT.parents[1]


def _check_running_sync(instance: Any, service: Any, check: unittest.TestCase) -> None:
    entered = Event()
    release = Event()
    cleaner_entered = Event()
    cleaner_release = Event()
    offline_entered = Event()
    offline_release = Event()
    errors = []

    def scan() -> None:
        entered.set()
        if not release.wait(timeout=5):
            raise AssertionError("宿主加载测试未释放同步任务")

    def clean() -> None:
        cleaner_entered.set()
        if not cleaner_release.wait(timeout=5):
            raise AssertionError("宿主加载测试未释放清理任务")

    def poll() -> None:
        offline_entered.set()
        if not offline_release.wait(timeout=5):
            raise AssertionError("宿主加载测试未释放离线轮询")

    def run(method: str) -> None:
        try:
            getattr(service, method)()
        except Exception as error:
            errors.append(error)

    client = service.client
    original_config = instance.get_config()
    real_stop = service._stop_sync_operations
    module = importlib.import_module(type(instance).__module__ + ".service")
    with ExitStack() as stack:
        stack.enter_context(patch.object(service, "_run_full_sync", side_effect=scan))
        stack.enter_context(
            patch.object(module.configer, "clear_receive_path_enabled", True)
        )
        stack.enter_context(
            patch.object(module.configer, "clear_recyclebin_enabled", True)
        )
        stack.enter_context(
            patch.object(module.Cleaner, "clear_receive_path", side_effect=clean)
        )
        recycle = stack.enter_context(patch.object(module.Cleaner, "clear_recyclebin"))
        offline_helper = service.offlinehelper
        offline_poll = stack.enter_context(
            patch.object(offline_helper, "pull_status_to_task", side_effect=poll)
        )
        worker = Thread(target=run, args=("full_sync_strm_files",))
        cleaner = Thread(target=run, args=("main_cleaner",))
        offline = Thread(target=run, args=("offline_status",))
        worker.start()
        cleaner.start()
        offline.start()
        try:
            check.assertTrue(entered.wait(timeout=2))
            check.assertTrue(cleaner_entered.wait(timeout=2))
            check.assertTrue(offline_entered.wait(timeout=2))
            check.assertEqual(service._sync_operations.get(cleaner), 1)
            check.assertEqual(service._sync_operations.get(offline), 1)
            with patch.object(
                service, "_stop_sync_operations", side_effect=lambda: real_stop(0)
            ):
                check.assertFalse(instance.stop_service())
                with check.assertRaisesRegex(RuntimeError, "旧插件任务尚未退出"):
                    instance.init_plugin(dict(original_config, cookies="new-account"))
            check.assertIs(service.client, client)
            check.assertEqual(instance.get_config(), original_config)
            check.assertEqual(instance.get_data("enabled-cycle"), 1)
            check.assertTrue(service._full_sync_running)
            release.set()
            worker.join(timeout=2)
            check.assertFalse(worker.is_alive())
            check.assertFalse(service._full_sync_running)
            check.assertEqual(service._sync_operations, {cleaner: 1, offline: 1})
            with patch.object(
                service, "_stop_sync_operations", side_effect=lambda: real_stop(0)
            ):
                check.assertFalse(instance.stop_service())
                with check.assertRaisesRegex(RuntimeError, "旧插件任务尚未退出"):
                    instance.init_plugin(dict(original_config, cookies="new-account"))
            check.assertIs(service.client, client)
            check.assertEqual(instance.get_config(), original_config)
            recycle.assert_not_called()
            cleaner_release.set()
            cleaner.join(timeout=2)
            check.assertFalse(cleaner.is_alive())
            check.assertEqual(service._sync_operations, {offline: 1})
            with patch.object(
                service, "_stop_sync_operations", side_effect=lambda: real_stop(0)
            ):
                check.assertFalse(instance.stop_service())
                with check.assertRaisesRegex(RuntimeError, "旧插件任务尚未退出"):
                    instance.init_plugin(dict(original_config, cookies="new-account"))
            check.assertIs(service.client, client)
            check.assertIs(service.offlinehelper, offline_helper)
            check.assertEqual(instance.get_config(), original_config)
        finally:
            release.set()
            cleaner_release.set()
            offline_release.set()
            worker.join(timeout=2)
            cleaner.join(timeout=2)
            offline.join(timeout=2)
        check.assertFalse(worker.is_alive())
        check.assertFalse(cleaner.is_alive())
        check.assertFalse(offline.is_alive())
        offline_poll.assert_called_once_with()
        recycle.assert_called_once_with()
        check.assertEqual(errors, [])
        check.assertEqual(service._sync_operations, {})


def _check_enabled_cycles(instance: Any, check: unittest.TestCase) -> Tuple[int, int]:
    prefix = type(instance).__module__
    service_module = importlib.import_module(prefix + ".service")
    downloader_module = importlib.import_module(prefix + ".helper.mediainfo_download")
    open_patch = importlib.import_module(prefix + ".patch.u115_open")
    user_agent = importlib.import_module(prefix + ".utils.user_agent")
    service = service_module.servicer
    queues = (
        service_module.emby_mediainfo_queue,
        service_module.sync_del_webhook_queue,
        service_module.share_audit_download_queue,
    )
    config = dict(
        instance.get_config(),
        enabled=True,
        cookies="UID=1_A1; CID=isolated; SEID=isolated",
        share_audit_queue_enabled=True,
    )
    previous = None
    qrcode_request_cases = 0
    previous_workers = []
    model = importlib.import_module(prefix + ".db_manager.models.file").File
    expected_file_name = None
    with ExitStack() as boundaries:
        boundaries.enter_context(
            patch.object(
                user_agent.P115Client,
                "app_version_list2",
                return_value={
                    "state": True,
                    "data": {
                        "iOS-iPhone": {"version_code": "38.0.2"},
                        "115wangpan_iOS": {"version_code": "36.2.20"},
                    },
                },
            )
        )
        center = boundaries.enter_context(patch.object(open_patch, "P115Center"))
        center.return_value.check_feature.return_value = {"enabled": False}
        boundaries.enter_context(patch.object(downloader_module, "P115Center"))
        for cycle in range(7):
            instance.init_plugin(config)
            check.assertTrue(instance.get_state())
            check.assertIsNotNone(service.client)
            check.assertIs(instance.api._client, service.client)
            check.assertIsNotNone(instance.mcp_manager)
            for helper in (
                service.offlinehelper,
                service.sharetransferhelper,
                service.redirect,
                service.backup_service,
                service.webdav_core,
            ):
                check.assertIs(helper.client, service.client)
            check.assertIs(service.monitorlife._client, service.client)
            check.assertIs(service.offlinehelper.monitorlife, service.monitorlife)
            check.assertIs(
                service.monitorlife.mediainfodownloader, service.mediainfodownloader
            )
            check.assertIs(
                service.share_interactive_gen_strm_queue.mediainfodownloader,
                service.mediainfodownloader,
            )
            check.assertIs(queues[-1]._downloader, service.mediainfodownloader)
            check.assertFalse(service.monitorlife._stopping)
            check.assertFalse(service.sharetransferhelper._stopping)
            check.assertFalse(service.backup_service._stopping)
            current = (
                service.client,
                service.monitorlife,
                service.mediainfodownloader,
                service.sharetransferhelper,
                service.backup_service,
            )
            if previous is not None:
                for old, new in zip(previous, current):
                    check.assertIsNot(old, new)
                check.assertTrue(previous[1]._stopping)
                check.assertTrue(previous[3]._stopping)
                check.assertTrue(previous[4]._stopping)
                check.assertTrue(
                    all(not worker.is_alive() for worker in previous_workers)
                )
                check.assertEqual(model.get_by_id(file_id=1).name, expected_file_name)
                check.assertEqual(instance.get_data("enabled-cycle"), cycle - 1)
            else:
                expected_file_name = model.get_by_id(file_id=1).name
            workers = [queue._worker_thread for queue in queues]
            check.assertTrue(all(worker and worker.is_alive() for worker in workers))
            instance.save_data("enabled-cycle", cycle)
            check.assertEqual(instance.get_data("enabled-cycle"), cycle)
            check.assertFalse(service._sync_stopping)
            if cycle == 0:
                check_strm_api_contracts(instance, check)
                check_transfer_postprocess_contracts(instance, check)
                _check_running_cleanup(instance, service_module, check)
            if cycle == 1:
                _check_running_sync(instance, service, check)
                _check_running_backup(instance, service_module, check)
            if cycle == 2:
                check_strm_event_contracts(instance, check)
            if cycle == 3:
                check_transfer_hook_contracts(instance, check)
            if cycle == 4:
                check_backup_api_contracts(instance, check)
            if cycle == 5:
                check_life_diagnostic_contracts(instance, check)
            if cycle == 6:
                check_original_utility_contracts(instance, check)
                check_original_sync_delete_contract(instance, check)
                check_original_life_contracts(instance, check)
                check_browse_contracts(instance, check)
                qrcode_request_cases = check_qrcode_request_contracts(instance, check)
                check.assertEqual(qrcode_request_cases, 10)
            if cycle != 1:
                check.assertTrue(instance.stop_service())
                check.assertTrue(all(not worker.is_alive() for worker in workers))
                check.assertTrue(service.monitorlife._stopping)
                check.assertTrue(service.sharetransferhelper._stopping)
                check.assertTrue(service.backup_service._stopping)
                check.assertTrue(service._sync_stopping)
            previous = current
            previous_workers = workers
    return 7, qrcode_request_cases


def _check_running_cleanup(
    instance: Any, service_module: Any, check: unittest.TestCase
) -> None:
    service = service_module.servicer
    api_module = importlib.import_module(type(instance).__module__ + ".api")
    entered = Event()
    release = Event()

    def scan() -> None:
        entered.set()
        if not release.wait(timeout=5):
            raise AssertionError("宿主加载测试未释放分享清理任务")

    real_stop = service._stop_sync_operations
    with patch.object(
        api_module.share_strm_cleaner, "run_full_cleanup", side_effect=scan
    ):
        response = api_module.Api.share_strm_cleanup_scan_api()
        workers = list(service._sync_operations)
        try:
            check.assertEqual(response.code, 0)
            check.assertTrue(entered.wait(timeout=2))
            check.assertEqual(len(workers), 1)
            check_cleanup_store_contracts(instance, check)
            with patch.object(
                service, "_stop_sync_operations", side_effect=lambda: real_stop(0)
            ):
                check.assertFalse(instance.stop_service())
            check.assertEqual(instance.get_data("enabled-cycle"), 0)
            check.assertTrue(
                service_module.emby_mediainfo_queue._worker_thread.is_alive()
            )
        finally:
            release.set()
            for worker in workers:
                worker.join(timeout=2)
        check.assertTrue(all(not worker.is_alive() for worker in workers))
        check.assertEqual(service._sync_operations, {})


def _check_running_backup(
    instance: Any, service_module: Any, check: unittest.TestCase
) -> None:
    service = service_module.servicer
    backup = service.backup_service
    client = service.client
    entered = Event()
    release = Event()
    errors = []

    def execute(task_name: str) -> None:
        entered.set()
        if not release.wait(timeout=5):
            raise AssertionError("宿主加载测试未释放备份任务")

    def run() -> None:
        try:
            backup.run_backup_task("isolated-backup")
        except Exception as error:
            errors.append(error)

    with (
        patch.object(service_module.configer, "strm_backup_enabled", True),
        patch.object(backup, "_execute_backup_impl", side_effect=execute),
    ):
        worker = Thread(target=run)
        worker.start()
        try:
            check.assertTrue(entered.wait(timeout=2))
            check.assertFalse(instance.stop_service())
            check.assertFalse(service.init_service())
            with check.assertRaisesRegex(RuntimeError, "旧插件任务尚未退出"):
                instance.init_plugin(dict(instance.get_config(), cookies="new-account"))
            check.assertIs(service.client, client)
            check.assertIs(service.backup_service, backup)
            check.assertEqual(instance.get_data("enabled-cycle"), 1)
            check.assertTrue(
                service_module.emby_mediainfo_queue._worker_thread.is_alive()
            )
        finally:
            release.set()
            worker.join(timeout=2)
        check.assertFalse(worker.is_alive())
        check.assertEqual(errors, [])
        check.assertTrue(backup.stop())


def _check_stopped_offline_listing(instance: Any, check: unittest.TestCase) -> None:
    import httpx
    from fastapi import FastAPI

    api = importlib.import_module(type(instance).__module__ + ".api")
    service = api.servicer
    check.assertFalse(instance.get_state())
    check.assertTrue(service._sync_stopping)
    helper = service.offlinehelper
    check.assertIsNotNone(helper)
    original_cache = helper.offline_list_cache
    route = next(
        route for route in instance.get_api() if route["path"] == "/offline_tasks"
    )
    app = FastAPI()
    app.add_api_route(route["path"], route["endpoint"], methods=route["methods"])

    async def request(page: int, limit: int) -> Any:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://isolated.invalid"
        ) as client:
            response = await client.post(
                route["path"], json={"page": page, "limit": limit}
            )
            check.assertEqual(response.status_code, 200)
            return response.json()

    tasks = [
        {
            "info_hash": "first",
            "name": "one.mkv",
            "size": 1024,
            "status": 0,
            "percentDone": 25,
            "add_time": 1,
        },
        {
            "info_hash": "second",
            "name": "two.mkv",
            "size": 2048,
            "status": 2,
            "percentDone": 100,
            "add_time": 2,
        },
    ]
    try:
        with patch.object(helper, "get_tasks", return_value=tasks) as query:
            for expired in (False, True):
                for page, limit in ((1, -1), (2, 1)):
                    helper.offline_list_cache = {"data": None, "timestamp": 0}
                    helper.get_cached_data()
                    if expired:
                        helper.offline_list_cache["timestamp"] = 0
                    query.reset_mock()
                    response = asyncio.run(request(page, limit))
                    check.assertEqual(response["code"], 0)
                    check.assertEqual(response["data"]["total"], 2)
                    items = response["data"]["tasks"]
                    check.assertEqual(
                        [item["info_hash"] for item in items],
                        ["first", "second"] if limit == -1 else ["second"],
                    )
                    check.assertEqual(query.call_count, int(expired))
                    check.assertEqual(items[-1]["status_text"], "已完成")
                    check.assertTrue(service._sync_stopping)
    finally:
        helper.offline_list_cache = original_cache


def _check_stopped_cleanup_execution(instance: Any, check: unittest.TestCase) -> None:
    import httpx
    from fastapi import FastAPI

    api = importlib.import_module(type(instance).__module__ + ".api")
    check.assertFalse(instance.get_state())
    check.assertTrue(api.servicer._sync_stopping)
    queue = api.share_strm_pending_queue
    workers = []
    app = FastAPI()
    route = next(
        route
        for route in instance.get_api()
        if route["path"] == "/share_strm_cleanup_execute"
    )
    app.add_api_route(route["path"], route["endpoint"], methods=route["methods"])

    def thread(**kwargs: Any) -> Thread:
        worker = Thread(**kwargs)
        workers.append(worker)
        return worker

    async def request() -> Any:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://isolated.invalid"
        ) as client:
            response = await client.post(
                route["path"], json={"request_id": "disabled-batch"}
            )
            check.assertEqual(response.status_code, 200)
            return response.json()

    with TemporaryDirectory() as directory:
        sample = Path(directory) / "sample.strm"
        sample.write_text("https://isolated.invalid/media")
        queue.replace_single_batch("disabled-batch", [str(sample)], False, False, False)
        with (
            patch.object(api.configer, "notify", False),
            patch.object(api, "Thread", side_effect=thread),
        ):
            try:
                response = asyncio.run(request())
                check.assertEqual(response["code"], 0, response)
                check.assertEqual(len(workers), 1)
                workers[0].join(timeout=2)
                check.assertFalse(workers[0].is_alive())
                check.assertFalse(sample.exists())
                check.assertFalse(
                    queue.pending_batch_paths_page("disabled-batch", 1, 50)[0]
                )
                missing = asyncio.run(request())
                check.assertEqual(missing["code"], 1)
                check.assertEqual(missing["msg"], "未找到该批次或已处理")
                check.assertEqual(len(workers), 1)
                check.assertTrue(api.servicer._sync_stopping)
            finally:
                for worker in workers:
                    worker.join(timeout=2)
                queue.clear_all_batches()


def _check_stopped_offline_submission(instance: Any, check: unittest.TestCase) -> None:
    import httpx
    from fastapi import FastAPI

    prefix = type(instance).__module__
    api = importlib.import_module(prefix + ".api")
    helper_module = importlib.import_module(prefix + ".helper.offline")
    helper = api.servicer.offlinehelper
    check.assertFalse(instance.get_state())
    check.assertTrue(api.servicer._sync_stopping)
    check.assertIsNotNone(helper)
    app = FastAPI()
    route = next(
        route for route in instance.get_api() if route["path"] == "/add_offline_task"
    )
    app.add_api_route(route["path"], route["endpoint"], methods=route["methods"])

    async def request(path: Any) -> Any:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://isolated.invalid"
        ) as client:
            response = await client.post(
                route["path"], json={"links": ["magnet:isolated"], "path": path}
            )
            check.assertEqual(response.status_code, 200)
            return response.json()

    with ExitStack() as stack:
        stack.enter_context(patch.object(api.configer, "upload_offline_info", False))
        stack.enter_context(
            patch.object(api.configer, "offline_download_paths", ["/isolated-default"])
        )
        stack.enter_context(patch.object(api.configer, "pan_transfer_paths", ""))
        resolve = stack.enter_context(
            patch.object(helper_module, "get_pid_by_path", return_value=42)
        )
        add = stack.enter_context(
            patch.object(
                helper,
                "add_urls",
                return_value={
                    "state": True,
                    "data": {"result": [{"info_hash": "isolated"}]},
                },
            )
        )
        for path in (None, "/isolated-explicit"):
            resolve.reset_mock()
            add.reset_mock()
            response = asyncio.run(request(path))
            check.assertEqual(response["code"], 0, response)
            check.assertIn("1 个新任务已成功添加", response["msg"])
            add.assert_called_once_with(url_list=["magnet:isolated"], cid=42)
            check.assertEqual(
                resolve.call_args.kwargs["path"], path or "/isolated-default"
            )
            check.assertTrue(api.servicer._sync_stopping)


def _block_network(stack: ExitStack) -> List[bool]:
    network_attempts = []
    creating_socketpair = ContextVar("creating_socketpair", default=False)
    original_connect = socket.socket.connect
    original_socketpair = socket.socketpair

    def block_network(*args: Any, **kwargs: Any) -> None:
        network_attempts.append(True)
        raise AssertionError("宿主加载测试禁止真实网络请求")

    def connect(sock: socket.socket, address: Any) -> None:
        if creating_socketpair.get():
            return original_connect(sock, address)
        block_network(sock, address)

    def socketpair(*args: Any, **kwargs: Any) -> Tuple[socket.socket, socket.socket]:
        # Windows 的事件循环通过本机 TCP 连接创建内部唤醒通道
        token = creating_socketpair.set(True)
        try:
            return original_socketpair(*args, **kwargs)
        finally:
            creating_socketpair.reset(token)

    stack.enter_context(patch.object(socket, "socketpair", socketpair))
    stack.enter_context(patch.object(socket.socket, "connect", connect))
    for target, name in (
        (socket.socket, "connect_ex"),
        (socket.socket, "sendto"),
        (socket, "getaddrinfo"),
    ):
        stack.enter_context(patch.object(target, name, block_network))
    return network_attempts


def _probe(host: Path) -> Dict[str, Any]:
    sys.path.insert(0, str(host))
    check = unittest.TestCase()
    with ExitStack() as stack:
        network_attempts = _block_network(stack)
        import sentry_sdk.transport

        stack.enter_context(
            patch.object(sentry_sdk.transport.HttpTransport, "capture_envelope")
        )
        from app.testing.bootstrap import prepare_v3_backend

        prepare_v3_backend(REPOSITORY)
        from app.db.engine import peek_sync_engine
        from app.db.plugin.registry import release_all_databases
        from app.runtime.log import logger, shutdown_log_writer

        stack.callback(shutdown_log_writer)
        stack.callback(lambda: peek_sync_engine().dispose())
        stack.callback(release_all_databases)
        spec = importlib.util.spec_from_file_location(
            "_p115_host_test_bootstrap", host / "tests/conftest.py"
        )
        harness = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(harness)
        services = harness.configure_plugin_system_services.__wrapped__()
        next(services)
        stack.callback(lambda: next(services, None))

        imported = []
        for path in sorted(ROOT.rglob("*.py")):
            relative = path.relative_to(ROOT)
            if any(
                part in {"tests", "rust_utils", "wheels", "__pycache__", "database"}
                for part in relative.parts
            ):
                continue
            parts = list(relative.with_suffix("").parts)
            if parts[-1] == "__init__":
                parts.pop()
            name = ".".join(["app.plugins.p115strmhelper", *parts])
            importlib.import_module(name)
            imported.append(name)

        from app.plugins.p115strmhelper import P115StrmHelper
        from app.runtime.extensions.plugin.loader import PluginLoader
        from app.schemas.plugin import PluginInstance
        from app.sdk.plugin import _PluginBase

        loader = PluginLoader(
            plugins_root=REPOSITORY / "plugins.v3",
            import_preparer=lambda **kwargs: None,
            import_scanner=lambda **kwargs: None,
            log=logger,
        )
        classes = [P115StrmHelper]
        for clone_id in ("P115StrmHelperCloneA", "P115StrmHelperCloneB"):
            definition = PluginInstance(
                instance_id=clone_id,
                source_plugin_id="P115StrmHelper",
                display_name=clone_id,
            )
            loaded = loader.load_instance(
                definition,
                lambda cls: issubclass(cls, _PluginBase) and cls is not _PluginBase,
            )
            check.assertEqual(len(loaded), 1)
            classes.extend(loaded)

        instances = []
        configs = []
        models = []
        paths = set()
        routes = []
        for index, cls in enumerate(classes):
            config = {"enabled": False, "error_info_upload": False}
            instance = cls(config=config)
            stack.callback(instance.stop_service)
            instance.init_plugin(config)
            check.assertFalse(instance.get_state())
            _check_stopped_cleanup_execution(instance, check)
            check_cleanup_store_contracts(instance, check)
            check_disabled_backup_listing(instance, check)
            check_disabled_backup_submission(instance, check)
            check_disabled_account_contract(instance, check)
            check_life_diagnostic_contracts(instance, check)
            check.assertIsNotNone(instance.mcp_manager)
            prefix = cls.__module__
            configer = importlib.import_module(prefix + ".core.config").configer
            check.assertIs(configer.plugin_instance, instance)
            check.assertTrue(
                instance.get_data_path().is_relative_to(os.environ["CONFIG_DIR"])
            )
            check.assertEqual(
                Path(configer.PLUGIN_CONFIG_PATH), instance.get_data_path()
            )
            paths.add(instance.get_data_path())
            check.assertTrue(configer.update_config({"language": f"probe-{index}"}))
            check.assertIsNot(configer.update_plugin_config(), False)
            instance.save_data("loading-probe", index)
            model = importlib.import_module(prefix + ".db_manager.models.file").File
            model.upsert_batch_by_list(
                batch=[
                    {
                        "id": 1,
                        "parent_id": 0,
                        "name": f"instance-{index}",
                        "path": "/probe",
                    }
                ]
            )
            declarations = instance.get_api()
            check.assertTrue(all(callable(route["endpoint"]) for route in declarations))
            routes.append(len(declarations))
            instances.append(instance)
            configs.append(configer)
            models.append(model)

        check.assertEqual(len(paths), 3)
        check.assertEqual(len({id(config) for config in configs}), 3)
        check.assertEqual(len({id(model.metadata) for model in models}), 3)
        for index, (instance, configer, model) in enumerate(
            zip(instances, configs, models)
        ):
            check.assertEqual(instance.get_config()["language"], f"probe-{index}")
            check.assertEqual(configer.language, f"probe-{index}")
            check.assertEqual(instance.get_data("loading-probe"), index)
            check.assertEqual(model.get_by_id(file_id=1).name, f"instance-{index}")
            check.assertTrue(instance.stop_service())
        cycle_results = [
            _check_enabled_cycles(instance, check) for instance in instances
        ]
        for instance in instances:
            instance.init_plugin(dict(instance.get_config(), enabled=False))
            _check_stopped_offline_listing(instance, check)
            _check_stopped_cleanup_execution(instance, check)
            _check_stopped_offline_submission(instance, check)
            check_disabled_backup_submission(instance, check)
            check_life_diagnostic_contracts(instance, check)
        batch_transfer_cases = run_batch_transfer_contracts()
        check.assertEqual(network_attempts, [])
        return {
            "runtime_modules": len(imported),
            "batch_transfer_cases": batch_transfer_cases,
            "instances": len(instances),
            "routes": routes,
            "enabled_cycles": sum(result[0] for result in cycle_results),
            "qrcode_request_cases": sum(result[1] for result in cycle_results),
        }


class TestV3HostLoading(unittest.TestCase):
    """
    在独立进程内验证真实 V3 宿主加载和插件分身资源隔离
    """

    def test_network_guard_allows_only_internal_socketpair(self) -> None:
        """
        Windows 唤醒通道可用，普通连接和域名解析仍被阻止
        """
        with ExitStack() as stack:
            stack.enter_context(
                patch.object(socket, "socketpair", socket._fallback_socketpair)
            )
            attempts = _block_network(stack)
            reader, writer = socket.socketpair()
            with reader, writer:
                reader.settimeout(2)
                writer.sendall(b"wake")
                self.assertEqual(reader.recv(4), b"wake")
            self.assertEqual(attempts, [])
            with socket.socket() as client:
                with self.assertRaisesRegex(AssertionError, "禁止真实网络请求"):
                    client.connect(("127.0.0.1", 9))
                with self.assertRaisesRegex(AssertionError, "禁止真实网络请求"):
                    client.connect_ex(("127.0.0.1", 9))
            with self.assertRaisesRegex(AssertionError, "禁止真实网络请求"):
                socket.getaddrinfo("isolated.invalid", 443)
            self.assertEqual(len(attempts), 3)

    def test_instances_load_isolate_and_restart_services(self) -> None:
        """
        验证模块加载、实例资源隔离及启用服务的停止和重启
        """
        host = Path(
            os.environ.get("MOVIEPILOT_SOURCE", REPOSITORY.parent / "MoviePilot")
        )
        self.assertTrue((host / "app/testing/bootstrap.py").is_file())
        with TemporaryDirectory(prefix="p115-v3-loading-") as temporary:
            environment = dict(
                os.environ,
                CONFIG_DIR=temporary,
                CACHE_BACKEND_TYPE="memory",
                DB_TYPE="sqlite",
                API_TOKEN="p115-v3-isolated-loading-test-token",
                MOVIEPILOT_AUTO_UPDATE="false",
            )
            try:
                result = subprocess.run(
                    [
                        sys.executable,
                        str(Path(__file__).resolve()),
                        "--probe",
                        str(host.resolve()),
                    ],
                    env=environment,
                    cwd=temporary,
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
            except subprocess.TimeoutExpired as error:
                details = "".join(
                    content.decode("utf-8", errors="replace")
                    if isinstance(content, bytes)
                    else content or ""
                    for content in (error.stdout, error.stderr)
                )
                self.fail(f"宿主加载及批量契约测试超过 300 秒：\n{details}")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = next(
                line.removeprefix("LOADING_REPORT ")
                for line in result.stdout.splitlines()
                if line.startswith("LOADING_REPORT ")
            )
            print("LOADING_REPORT", report)
            self.assertEqual(json.loads(report)["instances"], 3)
            self.assertEqual(json.loads(report)["enabled_cycles"], 21)
            self.assertEqual(json.loads(report)["qrcode_request_cases"], 30)
        self.assertFalse(Path(temporary).exists())


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--probe":
        print("LOADING_REPORT", json.dumps(_probe(Path(sys.argv[2]))))
    else:
        unittest.main()
