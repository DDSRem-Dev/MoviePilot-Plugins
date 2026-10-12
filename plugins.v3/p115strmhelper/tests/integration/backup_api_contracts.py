import asyncio
import importlib
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
from typing import Any
from unittest.mock import patch

import httpx
from fastapi import FastAPI


def check_backup_api_contracts(instance: Any, check: Any) -> None:
    """
    验证备份 HTTP 列表、重复提交与已占位任务的真实实例归属

    :param instance (Any): 已启用的隔离插件实例
    :param check (Any): 测试断言对象
    """
    from app.schemas import FileItem

    prefix = type(instance).__module__
    api = importlib.import_module(prefix + ".api")
    schemas = importlib.import_module(prefix + ".schemas.backup")
    one_shot = importlib.import_module(prefix + ".service.one_shot")
    service = api.servicer
    backup = service.backup_service
    helper = api.backup_helper
    app = FastAPI()
    for route in instance.get_api():
        if route["path"] in ("/trigger_backup", "/list_backups", "/restore_backup"):
            app.add_api_route(route["path"], route["endpoint"], methods=route["methods"])

    async def request(method: str, path: str, **kwargs):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://isolated.invalid"
        ) as client:
            response = await client.request(method, path, **kwargs)
            check.assertEqual(response.status_code, 200)
            return response.json()

    with TemporaryDirectory() as directory, ExitStack() as stack:
        root = Path(directory).resolve()
        local_file = root / "local_20261011.tar.gz"
        local_file.write_bytes(b"isolated-listing")
        (root / "unrelated.tar.gz").write_bytes(b"ignored")
        tasks = [
            schemas.StrmBackupItem(name="local", local_target_path=str(root)),
            schemas.StrmBackupItem(name="cloud", target_type="cloud", cloud_target_path="/isolated"),
            schemas.StrmBackupItem(name="restore", local_target_path=str(root)),
        ]
        stack.enter_context(patch.object(api.configer, "strm_backup_enabled", True))
        stack.enter_context(patch.object(api.configer, "strm_backup_items", tasks))
        folder = FileItem(storage="u115", type="dir", path="/isolated", name="isolated")
        cloud_file = FileItem(
            storage="u115", type="file", path="/isolated/cloud_20261011.tar.gz",
            name="cloud_20261011.tar.gz", size=456,
        )

        def storage(method: str, **kwargs):
            if method == "get_file_item":
                check.assertEqual(kwargs, {"storage": api.configer.storage_module, "path": Path("/isolated")})
                return folder
            check.assertEqual(method, "list_files")
            check.assertEqual(kwargs, {"fileitem": folder, "recursion": False})
            return [cloud_file]

        stack.enter_context(patch.object(helper._storage_chain, "run_module", side_effect=storage))
        for name, filename, size in (
            ("local", local_file.name, local_file.stat().st_size),
            ("cloud", cloud_file.name, 456),
        ):
            result = asyncio.run(request("GET", "/list_backups", params={"task_name": name}))
            check.assertEqual(result["code"], 0)
            check.assertEqual(len(result["data"]), 1)
            check.assertEqual(result["data"][0]["filename"], filename)
            check.assertEqual(result["data"][0]["file_size"], size)
            check.assertEqual(result["data"][0]["target_type"], name)
        registered = []

        def register(**kwargs) -> bool:
            check.assertEqual(kwargs["plugin_id"], type(instance).__name__)
            check.assertIs(kwargs["func"].__self__, instance)
            registered.append(kwargs)
            return True

        stack.enter_context(patch.object(one_shot, "add_plugin_once_job", side_effect=register))
        stack.enter_context(patch.object(backup, "_watch_orphaned_reserved_slot"))
        archive = stack.enter_context(patch.object(
            helper, "execute_backup", return_value=schemas.BackupHistory(
                task_name="local", filename=local_file.name, target_type="local", target_path=str(local_file),
            ),
        ))
        restore = stack.enter_context(patch.object(helper, "restore_from_local", return_value=(True, None)))
        endpoints = (
            ("POST", "/trigger_backup", {"json": {"task_name": "local"}}),
            ("POST", "/restore_backup", {"json": {"task_name": "restore", "backup_path": str(local_file)}}),
        )
        for method, path, kwargs in endpoints:
            result = asyncio.run(request(method, path, **kwargs))
            check.assertEqual(result["code"], 0, result)
            duplicate = asyncio.run(request(method, path, **kwargs))
            check.assertEqual(duplicate["code"], -1, duplicate)
            check.assertIn("正在运行", duplicate["msg"])
        check.assertEqual(service._sync_operations, {})
        check.assertEqual(len(registered), 2)
        check.assertEqual(backup._backup_running_tasks, {"local", "restore"})
        check.assertFalse(instance.stop_service())
        with check.assertRaisesRegex(RuntimeError, "旧插件任务尚未退出"):
            instance.init_plugin(dict(instance.get_config(), cookies="new-account"))
        check.assertIs(service.backup_service, backup)
        try:
            for job in registered:
                check.assertIsNone(job["func"](**job["func_kwargs"]))
        finally:
            backup._release_backup_task("local")
            backup._release_backup_task("restore")
        archive.assert_called_once_with(tasks[0], client=service.client)
        restore.assert_called_once_with(backup_path=str(local_file), source_paths=[])
        check.assertEqual(backup._backup_running_tasks, set())
        check.assertEqual(backup._active_executions, 0)


def check_disabled_backup_listing(instance: Any, check: Any) -> None:
    """
    验证禁用实例仍可列出实际本地备份文件

    :param instance (Any): 已禁用的隔离插件实例
    :param check (Any): 测试断言对象
    """
    prefix = type(instance).__module__
    api = importlib.import_module(prefix + ".api")
    schemas = importlib.import_module(prefix + ".schemas.backup")
    check.assertFalse(instance.get_state())
    check.assertTrue(api.servicer._sync_stopping)
    app = FastAPI()
    route = next(route for route in instance.get_api() if route["path"] == "/list_backups")
    app.add_api_route(route["path"], route["endpoint"], methods=route["methods"])

    async def request() -> Any:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://isolated.invalid"
        ) as client:
            response = await client.get("/list_backups", params={"task_name": "local"})
            check.assertEqual(response.status_code, 200)
            return response.json()

    with TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        archive = root / "local_20261012.tar.gz"
        archive.write_bytes(b"isolated-listing")
        (root / "unrelated.tar.gz").write_bytes(b"ignored")
        task = schemas.StrmBackupItem(name="local", local_target_path=str(root))
        with patch.object(api.configer, "strm_backup_enabled", True), patch.object(
            api.configer, "strm_backup_items", [task]
        ):
            result = asyncio.run(request())
        check.assertEqual(result["code"], 0, result)
        check.assertEqual(len(result["data"]), 1)
        record = result["data"][0]
        check.assertEqual(record["filename"], archive.name)
        check.assertEqual(record["file_size"], archive.stat().st_size)
        check.assertEqual(record["target_type"], "local")
        check.assertTrue(api.servicer._sync_stopping)


def check_disabled_backup_submission(instance: Any, check: Any) -> None:
    """
    验证禁用实例通过真实宿主调度完成临时本地归档和恢复

    :param instance (Any): 已禁用的隔离插件实例
    :param check (Any): 测试断言对象
    """
    from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR
    from apscheduler.schedulers.background import BackgroundScheduler
    from app.application.plugin.runtime import get_plugin_manager
    from app.application.scheduling import register_scheduler_class
    from app.scheduler import Scheduler
    from app.scheduler.catalog import _SchedulerThreadPoolExecutor

    prefix = type(instance).__module__
    api = importlib.import_module(prefix + ".api")
    backup_module = importlib.import_module(prefix + ".service.backup")
    schemas = importlib.import_module(prefix + ".schemas.backup")
    service = api.servicer
    backup = service.backup_service
    plugin_id = api.configer.plugin_id
    check.assertFalse(instance.get_state())
    check.assertTrue(service._sync_stopping)
    check.assertTrue(backup._stopping)
    app = FastAPI()
    for route in instance.get_api():
        if route["path"] in ("/trigger_backup", "/restore_backup"):
            app.add_api_route(route["path"], route["endpoint"], methods=route["methods"])

    async def request(path: str, payload: Any) -> Any:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://isolated.invalid"
        ) as client:
            response = await client.post(path, json=payload)
            check.assertEqual(response.status_code, 200, response.text)
            return response.json()

    release_watchers = Event()
    watchers = []
    watcher_errors = []

    def start_watcher(**kwargs: Any) -> Thread:
        target = kwargs["target"]

        def run() -> None:
            try:
                target()
            except BaseException as error:
                watcher_errors.append(error)

        kwargs["target"] = run
        worker = Thread(**kwargs)
        watchers.append(worker)
        return worker

    def wait_grace(seconds: float) -> None:
        check.assertEqual(seconds, 10)
        if not release_watchers.wait(timeout=10):
            raise AssertionError("测试未释放备份运行槽守护线程")

    scheduler = Scheduler()
    check.assertIn(scheduler._lifecycle_state, ("new", "stopped"))
    check.assertIsNone(scheduler._scheduler)
    saved = scheduler.__dict__.copy()
    scheduler._jobs = {}
    previous = register_scheduler_class(Scheduler)
    manager = get_plugin_manager()
    events = {}
    scheduler_errors = []

    def initialize_catalog(config: Any) -> None:
        scheduler._scheduler = BackgroundScheduler(
            timezone=config.timezone,
            executors={"default": _SchedulerThreadPoolExecutor(2)},
        )

        def observed(event: Any) -> None:
            if event.exception:
                scheduler_errors.append(event.exception)
            events.setdefault(event.job_id, Event()).set()

        scheduler._scheduler.add_listener(observed, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)

    try:
        with TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            archives = root / "archives"
            archives.mkdir()
            sample = source / "sample.strm"
            content = b"https://isolated.invalid/media\n"
            sample.write_bytes(content)
            task = schemas.StrmBackupItem(
                name="local", source_paths=[str(source)], local_target_path=str(archives)
            )
            stack.enter_context(patch.object(api.configer, "strm_backup_enabled", True))
            stack.enter_context(patch.object(api.configer, "strm_backup_items", [task]))
            stack.enter_context(patch.object(backup_module, "Thread", side_effect=start_watcher))
            stack.enter_context(patch.object(backup_module, "sleep", side_effect=wait_grace))
            stack.enter_context(patch.dict(manager.running_plugins, {plugin_id: instance}))
            stack.enter_context(patch.object(manager, "get_plugin_services", return_value=[]))
            stack.enter_context(patch.object(scheduler, "_initialize_catalog", side_effect=initialize_catalog))
            stack.enter_context(patch.object(scheduler, "_reconcile_agent_task_interruptions"))
            scheduler.init()
            for kind, path in (("backup", "/trigger_backup"), ("restore", "/restore_backup")):
                payload = {"task_name": "local"}
                if kind == "restore":
                    files = list(archives.glob("*.tar.gz"))
                    check.assertEqual(len(files), 1)
                    check.assertGreater(files[0].stat().st_size, 0)
                    payload["backup_path"] = str(files[0])
                    sample.unlink()
                response = asyncio.run(request(path, payload))
                check.assertEqual(response["code"], 0, response)
                job_id = f"{plugin_id}_once_strm_{kind}_local"
                check.assertTrue(events.setdefault(job_id, Event()).wait(timeout=5), job_id)
                check.assertFalse(scheduler._is_job_active(job_id))
                check.assertEqual(scheduler.get_progress(job_id).status, "success")
                check.assertEqual(scheduler_errors, [])
                check.assertEqual(backup._backup_running_tasks, set())
                check.assertEqual(backup._active_executions, 0)
                check.assertTrue(backup._stopping)
                check.assertTrue(service._sync_stopping)
                check.assertFalse(instance.get_state())
                if kind == "restore":
                    check.assertEqual(sample.read_bytes(), content)
            release_watchers.set()
            for worker in watchers:
                worker.join(timeout=2)
                check.assertFalse(worker.is_alive())
            check.assertEqual(len(watchers), 2)
            check.assertEqual(watcher_errors, [])
    finally:
        release_watchers.set()
        for worker in watchers:
            worker.join(timeout=2)
        try:
            scheduler.stop()
        finally:
            register_scheduler_class(previous)
            scheduler.__dict__.clear()
            scheduler.__dict__.update(saved)
