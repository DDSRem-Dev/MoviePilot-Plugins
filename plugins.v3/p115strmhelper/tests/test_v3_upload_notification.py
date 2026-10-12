import __future__
import ast
import importlib
import os
import sys
from pathlib import Path
from threading import Event, RLock, Thread
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest import TestCase
from unittest.mock import MagicMock, patch

from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.background import BackgroundScheduler


class TestV3UploadNotification(TestCase):
    """
    使用真实 V3 一次性任务注册与取消合同验证聚合通知生命周期
    """

    def setUp(self) -> None:
        """
        隔离宿主消息发送，保留调度门面、任务所有者和暂停的 APScheduler
        """
        root = Path(__file__).resolve().parents[1]
        self.root = root
        host = Path(os.environ.get("MOVIEPILOT_SOURCE", root.parents[2] / "MoviePilot"))
        if not (host / "app/scheduler/oncejob.py").exists():
            self.skipTest("需要 MOVIEPILOT_SOURCE 指向 V3 主程序")
        prefix = "_p115_upload_notification_test"
        originals = {
            name: value
            for name, value in sys.modules.items()
            if name == "app" or name.startswith("app.")
        }
        for name in originals:
            sys.modules.pop(name)

        def restore() -> None:
            for name in list(sys.modules):
                if name == "app" or name.startswith(("app.", prefix)):
                    sys.modules.pop(name)
            sys.modules.update(originals)

        self.addCleanup(restore)

        def module(name: str, **attributes: Any) -> ModuleType:
            value = ModuleType(name)
            value.__dict__.update(attributes)
            sys.modules[name] = value
            return value

        for name in (
            "app",
            "app.schemas",
            "app.sdk",
            "app.application",
            "app.application.plugin",
            "app.runtime",
            "app.scheduler",
        ):
            module(name, __path__=[str(host.joinpath(*name.split(".")))])
        for suffix in ("", ".core", ".schemas"):
            location = root.joinpath(*suffix.strip(".").split(".")) if suffix else root
            module(prefix + suffix, __path__=[str(location)])
        self.logger = MagicMock()
        module("app.sdk.logging", logger=self.logger)
        module(
            "app.runtime.log",
            logger=self.logger,
            wrap_for_plugin_instance=lambda func, pid: func,
        )
        module(
            "app.sdk.utilities",
            StringUtils=SimpleNamespace(str_filesize=lambda size: f"{size}B"),
        )
        self.types = importlib.import_module("app.schemas.types")
        sys.modules["app.schemas"].MessageType = self.types.MessageType
        sys.modules["app.schemas"].NotificationChannel = self.types.NotificationChannel
        self.owner = type("P115StrmHelperCloneA", (), {})()
        self.owner.post_message = MagicMock()
        self.config = SimpleNamespace(
            plugin_instance=self.owner, get_config=lambda key: "zh_CN"
        )
        module(f"{prefix}.core.config", configer=self.config)
        module(
            f"{prefix}.core.i18n",
            i18n=SimpleNamespace(
                translate=lambda key, **kwargs: f"{key}: {kwargs}",
            ),
        )
        self.manager = SimpleNamespace(
            running_plugins={self.owner.__class__.__name__: self.owner},
            get_plugin_attr=lambda pid, key: pid,
        )
        get_manager = lambda: self.manager
        module("app.application.plugin.runtime", get_plugin_manager=get_manager)
        once = importlib.import_module("app.scheduler.oncejob")
        removal_source = host / "app/scheduler/reconcile.py"
        removal = next(
            node
            for node in ast.walk(ast.parse(removal_source.read_text()))
            if isinstance(node, ast.FunctionDef) and node.name == "remove_plugin_job"
        )
        namespace = {
            "get_plugin_manager": get_manager,
            "JobLookupError": JobLookupError,
            "logger": self.logger,
        }
        exec(
            compile(
                ast.Module(body=[removal], type_ignores=[]),
                str(removal_source),
                "exec",
                flags=__future__.annotations.compiler_flag,
            ),
            namespace,
        )
        scheduler_type = type(
            "TestScheduler",
            (once.SchedulerPluginOnceJobOwner,),
            {
                "remove_plugin_job": namespace["remove_plugin_job"],
            },
        )
        self.scheduler = scheduler_type()
        self.scheduler._lock = RLock()
        self.scheduler._jobs = {}
        self.scheduler._accepting_submissions = lambda: True
        self.scheduler._is_job_active = lambda job_id: False
        self.scheduler._assign_job_generation = MagicMock()
        self.scheduler.start = MagicMock()
        self.scheduler._scheduler = BackgroundScheduler(timezone="UTC")
        self.scheduler._scheduler.start(paused=True)
        self.addCleanup(self.scheduler._scheduler.shutdown)
        scheduling = importlib.import_module("app.application.scheduling")
        scheduling.register_scheduler_class(lambda: self.scheduler)
        self.module = importlib.import_module(f"{prefix}.core.message")
        self.registry = self.module.upload_notifier
        self.registry.start(self.owner)
        self.notifier = self.registry.capture()

    def _job(self, owner: Any = None) -> Any:
        owner = owner or self.owner
        return next(
            job
            for job in self.scheduler._jobs.values()
            if job["_plugin_instance"] is owner
        )

    def _add(self, name: str = "video.mkv", success: bool = True) -> None:
        self.notifier.add(
            success,
            name,
            1024,
            elapsed_time=1.5,
            error_msg=None if success else "上传失败",
        )

    def test_debounce_keeps_only_current_callback_and_all_results(self) -> None:
        """
        替换延迟任务后旧代次回调无效，当前批次保留成功及失败条目
        """
        self._add("first.mkv")
        stale = self._job()["func"]
        self._add("second.mkv", success=False)
        current = self._job()["func"]
        stale()
        self.owner.post_message.assert_not_called()
        current()
        self.owner.post_message.assert_called_once()
        message = self.owner.post_message.call_args.kwargs
        self.assertIn("first.mkv", message["text"])
        self.assertIn("second.mkv", message["text"])
        self.assertIn("上传失败", message["text"])
        self.assertIn("upload_batch_title_mixed", message["title"])
        self.assertFalse(self.notifier._results)
        current()
        self.owner.post_message.assert_called_once()

    def test_host_records_actual_owner_and_preserves_only_current_instance_job(
        self,
    ) -> None:
        """
        宿主记录真实插件绑定方法，服务重建只保留当前实例的一次性任务
        """
        self._add()
        job = self._job()
        self.assertIs(job["_plugin_instance"], self.owner)
        self.assertIs(job["func"].__self__, self.owner)
        self.assertEqual(job["owner"], "plugin:P115StrmHelperCloneA")
        retained = self.scheduler._detach_live_plugin_once_jobs(
            self.owner.__class__.__name__
        )
        self.assertEqual(len(retained), 1)
        self.scheduler._jobs.update(retained)
        self.manager.running_plugins[self.owner.__class__.__name__] = object()
        self.assertFalse(
            self.scheduler._detach_live_plugin_once_jobs(self.owner.__class__.__name__)
        )

    def test_shutdown_cancels_job_and_late_results_never_schedule_more_work(
        self,
    ) -> None:
        """
        停止后撤销宿主任务，迟到结果仍向原实例立即提交且旧回调不再发送
        """
        self._add("before.mkv")
        stale = self._job()["func"]
        self.assertTrue(self.notifier.shutdown())
        self.assertFalse(self.scheduler._jobs)
        self.assertFalse(self.scheduler._scheduler.get_jobs())
        self._add("late.mkv")
        stale()
        self.assertEqual(self.owner.post_message.call_count, 2)
        self.assertFalse(self.scheduler._jobs)
        self.assertIn("late.mkv", self.owner.post_message.call_args.kwargs["text"])

    def test_reload_reuses_imported_object_without_reviving_old_callback(self) -> None:
        """
        配置重载保留上传模块持有的对象引用，旧回调不能处理新代次结果
        """
        reference = self.module.upload_notifier.capture()
        self._add("old.mkv")
        stale = self._job()["func"]
        self.notifier.shutdown()
        reference.start(self.owner)
        reference.add(True, "new.mkv", 2048)
        stale()
        self.assertEqual(self.owner.post_message.call_count, 1)
        self._job()["func"]()
        self.assertEqual(self.owner.post_message.call_count, 2)
        self.assertIs(reference, self.module.upload_notifier.capture())

    def test_rejected_or_failed_scheduling_falls_back_to_immediate_submission(
        self,
    ) -> None:
        """
        宿主停止接单或注册异常时直接提交结果，不将通知故障传成上传失败
        """
        self.scheduler._accepting_submissions = lambda: False
        self._add("rejected.mkv")
        self.assertEqual(self.owner.post_message.call_count, 1)
        with patch.object(
            self.module, "add_plugin_once_job", side_effect=RuntimeError("调度不可用")
        ):
            self._add("failed.mkv")
        self.assertEqual(self.owner.post_message.call_count, 2)
        self.assertFalse(self.notifier._results)

    def test_cancel_failure_does_not_revalidate_obsolete_callback(self) -> None:
        """
        宿主取消任务失败时仍用代次校验拒绝旧回调
        """
        self._add()
        stale = self._job()["func"]
        with patch.object(
            self.module, "remove_plugin_once_job", side_effect=RuntimeError("取消失败")
        ):
            self.assertTrue(self.notifier.shutdown())
        stale()
        self.owner.post_message.assert_called_once()

    def test_aggregators_do_not_cross_instance_or_follow_rebound_global_config(
        self,
    ) -> None:
        """
        不同实例的批次、宿主任务和发送目标隔离，配置重绑不改变已绑定所有者
        """
        other = type("P115StrmHelperCloneB", (), {})()
        other.post_message = MagicMock()
        notifier = self.module.UploadNotifyAggregator()
        notifier.start(other)
        self._add("a.mkv")
        notifier.add(True, "b.mkv", 12)
        self.config.plugin_instance = other
        self._job()["func"]()
        self._job(other)["func"]()
        self.assertIn("a.mkv", self.owner.post_message.call_args.kwargs["text"])
        self.assertNotIn("b.mkv", self.owner.post_message.call_args.kwargs["text"])
        self.assertIn("b.mkv", other.post_message.call_args.kwargs["text"])
        with self.assertRaises(RuntimeError):
            self.notifier.start(other)

    def test_results_arriving_during_send_are_not_removed_by_prior_batch(self) -> None:
        """
        正在提交批次期间到达的新结果保留到下一批，不被旧批次清空
        """
        entered, release = Event(), Event()

        def submit(**kwargs: Any) -> None:
            entered.set()
            if not release.wait(2):
                raise RuntimeError("测试发送等待超时")

        self.owner.post_message.side_effect = submit
        self._add("first.mkv")
        worker = Thread(target=self._job()["func"])
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            self._add("second.mkv")
        finally:
            release.set()
            worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(
            [item.target_name for item in self.notifier._results], ["second.mkv"]
        )
        self.owner.post_message.side_effect = None
        self._job()["func"]()
        self.assertFalse(self.notifier._results)
        self.assertNotIn("first.mkv", self.owner.post_message.call_args.kwargs["text"])

    def test_shutdown_waits_for_active_submission_without_duplicate_send(self) -> None:
        """
        关停等待正在提交的批次结束，不并行重复发送同一批次
        """
        entered, release, stopped = Event(), Event(), Event()

        def submit(**kwargs: Any) -> None:
            entered.set()
            if not release.wait(2):
                raise RuntimeError("测试发送等待超时")

        def stop() -> None:
            self.notifier.shutdown()
            stopped.set()

        self.owner.post_message.side_effect = submit
        self._add()
        worker = Thread(target=self._job()["func"])
        shutdown = Thread(target=stop)
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            shutdown.start()
            self.assertFalse(stopped.wait(0.05))
        finally:
            release.set()
            worker.join(2)
            if shutdown.ident is not None:
                shutdown.join(2)
        self.assertFalse(worker.is_alive())
        self.assertTrue(stopped.is_set())
        self.owner.post_message.assert_called_once()
        self.assertFalse(self.notifier._results)

    def test_unbound_results_wait_for_start_without_failing_upload(self) -> None:
        """
        初始化前到达的结果保留在原对象，绑定后正常提交
        """
        notifier = self.module.UploadNotifyAggregator()
        notifier.add(True, "early.mkv", 10)
        self.assertFalse(notifier.flush())
        self.owner.post_message.assert_not_called()
        notifier.start(self.owner)
        self._job()["func"]()
        self.assertIn("early.mkv", self.owner.post_message.call_args.kwargs["text"])
        self.assertFalse(notifier._results)

    def test_entry_preserves_notifications_until_services_stop(
        self,
    ) -> None:
        """
        入口仅在启用时启动聚合，服务未停止时保留通知，资源释放异常仍关闭通知
        """
        source = self.root / "__init__.py"
        entry_class = next(
            node
            for node in ast.parse(source.read_text()).body
            if isinstance(node, ast.ClassDef)
        )
        entry_class.bases = []
        entry_class.decorator_list = []
        entry_class.body = [
            node
            for node in entry_class.body
            if isinstance(node, ast.FunctionDef)
            and node.name in ("init_plugin", "stop_service")
        ]
        services = MagicMock()
        notifier = MagicMock()
        self.config.enabled = True
        self.config.load_from_dict = MagicMock(return_value=True)
        self.config.update_plugin_config = MagicMock(return_value=True)
        self.config.PLUGIN_TEMP_PATH = "/unused/test/path"
        namespace = {
            "configer": self.config,
            "servicer": services,
            "upload_notifier": notifier,
            "ct_db_manager": MagicMock(),
            "Api": MagicMock(),
            "MCPManager": MagicMock(),
            "U115Patcher": MagicMock(),
            "P115DiskPatcher": MagicMock(),
            "AppVerPatcher": MagicMock(),
            "logger": self.logger,
            "Path": MagicMock(),
            "i18n": MagicMock(),
            "sentry_manager": MagicMock(),
        }
        exec(
            compile(
                ast.Module(body=[entry_class], type_ignores=[]),
                str(source),
                "exec",
                flags=__future__.annotations.compiler_flag,
            ),
            namespace,
        )
        entry_type = namespace[entry_class.name]
        entry_type._rename_media_fields_cache = MagicMock()
        entry = entry_type()
        entry.init_database = MagicMock(return_value=True)
        entry.init_plugin()
        notifier.start.assert_called_once_with(entry)
        notifier.shutdown.assert_called_once_with(entry)
        notifier.reset_mock()
        self.config.enabled = False
        entry.init_plugin()
        notifier.start.assert_not_called()
        notifier.shutdown.assert_called_once_with(entry)
        notifier.reset_mock()
        self.config.enabled = True
        entry.init_database.return_value = False
        with self.assertRaises(RuntimeError):
            entry.init_plugin()
        notifier.start.assert_not_called()
        notifier.reset_mock()
        services.stop.side_effect = RuntimeError("其他服务关停失败")
        with self.assertRaises(RuntimeError):
            entry.stop_service()
        notifier.shutdown.assert_not_called()
        services.stop.side_effect = None
        services.stop.return_value = True
        namespace["ct_db_manager"].close_database.side_effect = RuntimeError(
            "资源释放失败"
        )
        with self.assertRaises(RuntimeError):
            entry.stop_service()
        notifier.shutdown.assert_called_once_with(entry)

    def test_replacement_object_keeps_late_results_and_job_cancellation_separate(
        self,
    ) -> None:
        """
        同名宿主对象被替换后旧上传仍归原实例，旧关停不取消新任务
        """
        captured = self.registry.capture()
        self._add("old.mkv")
        stale = self._job()["func"]
        replacement = type(self.owner)()
        replacement.post_message = MagicMock()
        self.config.plugin_instance = replacement
        self.registry.start(replacement)
        current = self.registry.capture()
        self.assertIsNot(current, captured)
        current.add(True, "new.mkv", 10)
        current_job = self._job(replacement)
        captured.add(True, "late.mkv", 10)
        self.registry.shutdown(self.owner)
        stale()
        self.assertIs(self._job(replacement), current_job)
        self.assertEqual(self.owner.post_message.call_count, 2)
        self.assertIn("late.mkv", self.owner.post_message.call_args.kwargs["text"])
        replacement.post_message.assert_not_called()
        current_job["func"]()
        self.assertIn("new.mkv", replacement.post_message.call_args.kwargs["text"])

    def test_both_upload_helpers_capture_owner_before_building_result_callback(
        self,
    ) -> None:
        """
        两种上传入口的实际结果回调使用上传开始时捕获的聚合器
        """
        self.config.notify = True
        self.config.upload_open_result_notify = True
        for relative in ("core/p115disk.py", "core/u115_open.py"):
            with self.subTest(relative=relative):
                source = self.root / relative
                upload = next(
                    node
                    for node in ast.walk(ast.parse(source.read_text()))
                    if isinstance(node, ast.FunctionDef) and node.name == "upload"
                )
                result_callback = next(
                    node
                    for node in upload.body
                    if isinstance(node, ast.FunctionDef)
                    and node.name == "send_upload_result_notify"
                )
                prefix = []
                for node in upload.body:
                    if isinstance(node, ast.FunctionDef):
                        break
                    prefix.append(node)
                upload.decorator_list = []
                upload.body = prefix + [
                    result_callback,
                    ast.Return(value=ast.Name(id=result_callback.name, ctx=ast.Load())),
                ]
                namespace = {"upload_notifier": self.registry, "configer": self.config}
                selected = ast.fix_missing_locations(
                    ast.Module(body=[upload], type_ignores=[])
                )
                exec(
                    compile(
                        selected,
                        str(source),
                        "exec",
                        flags=__future__.annotations.compiler_flag,
                    ),
                    namespace,
                )
                captured = MagicMock()
                wrong = MagicMock()
                with patch.object(
                    self.registry, "capture", return_value=captured
                ) as capture:
                    callback = namespace["upload"](None, None, None)
                    capture.return_value = wrong
                    callback(True, "video.mkv", 12, 1.5, None)
                captured.add.assert_called_once_with(
                    success=True,
                    target_name="video.mkv",
                    file_size=12,
                    elapsed_time=1.5,
                    error_msg=None,
                )
                wrong.add.assert_not_called()

    def test_delayed_submission_failure_reaches_host_scheduler(self) -> None:
        """
        延迟提交失败向 V3 调度器抛错，沿用原批次清空语义且不增加重试
        """
        self.owner.post_message.side_effect = RuntimeError("提交失败")
        self._add("failed.mkv")
        with self.assertRaises(RuntimeError):
            self._job()["func"]()
        self.assertFalse(self.notifier._results)
