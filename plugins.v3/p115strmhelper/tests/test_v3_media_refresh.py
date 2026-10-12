import importlib
import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, Optional, cast
from unittest import TestCase
from unittest.mock import MagicMock, patch

from test_v3_share_queue_lifecycle import _method


class TestV3MediaRefresh(TestCase):
    """
    验证刷新请求使用真实宿主服务目录、刷新模型和一次性调度门面
    """

    def setUp(self) -> None:
        """
        隔离媒体服务器网络和调度执行器，载入真实 V3 合同
        """
        root = Path(__file__).resolve().parents[1]
        host = Path(os.environ.get("MOVIEPILOT_SOURCE", root.parents[2] / "MoviePilot"))
        if not (host / "app/sdk/scheduler.py").exists():
            self.skipTest("需要 MOVIEPILOT_SOURCE 指向 V3 主程序")
        prefix = "_p115_refresh_test"
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
            result = ModuleType(name)
            result.__dict__.update(attributes)
            sys.modules[name] = result
            return result

        for name in (
            "app",
            "app.schemas",
            "app.sdk",
            "app.chain",
            "app.domain",
            "app.foundation",
            "app.application",
            "app.runtime",
        ):
            module(name, __path__=[str(host.joinpath(*name.split(".")))])
        for suffix in (
            "",
            ".core",
            ".helper",
            ".helper.mediaserver",
            ".utils",
            ".service",
        ):
            location = root.joinpath(*suffix.strip(".").split(".")) if suffix else root
            module(prefix + suffix, __path__=[str(location)])

        self.logger = MagicMock()
        module("app.runtime.log", logger=self.logger)
        module("app.sdk.logging", logger=self.logger)
        module("app.sdk.utilities", SystemUtils=MagicMock())
        system = importlib.import_module("app.schemas.system")
        schemas = sys.modules["app.schemas"]
        schemas.ServiceInfo = system.ServiceInfo
        schemas.RefreshMediaItem = importlib.import_module(
            "app.schemas.mediaserver"
        ).RefreshMediaItem
        schemas.MediaInfo = importlib.import_module("app.schemas.context").MediaInfo
        self.types = importlib.import_module("app.schemas.types")
        context = importlib.import_module("app.domain.context")
        parser = importlib.import_module("app.domain.metainfo").MetaInfoPath
        module("app.sdk.media", MetaInfoPath=parser)
        self.media = context.MediaInfo(
            media_source=self.types.MediaSource.Bangumi,
            media_id="42",
            type=self.types.MediaType.TV,
            title="Example",
            year="2026",
            library_category="动画",
        )
        self.chain = MagicMock()
        self.chain._build_recognition_plan.return_value = SimpleNamespace(
            identity_valid=True
        )
        self.chain._finalize_recognition_result.return_value = self.media
        recognize = _method(
            host / "app/chain/_recognition.py",
            "recognize_media",
            {"cast": cast, "Optional": Optional, "MediaInfo": context.MediaInfo},
        )
        self.chain.recognize_media = MagicMock(wraps=recognize.__get__(self.chain))
        module("app.chain.media", MediaChain=MagicMock(return_value=self.chain))

        self.config_type = system.MediaServerConf
        self.configs = []
        self.instances = {}
        self.runtime_module = SimpleNamespace(
            get_instances=lambda: dict(self.instances)
        )
        self.directory = importlib.import_module("app.application.service")
        self.directory.configure_service_directory(
            configs=lambda key, kind: list(self.configs),
            modules=lambda kind: [self.runtime_module],
        )
        helper = importlib.import_module(
            "app.application.mediaserver"
        ).MediaServerHelper
        module("app.sdk.services", MediaServerHelper=helper)

        self.scheduler = MagicMock()
        self.scheduler.add_plugin_once_job.return_value = True
        scheduling = importlib.import_module("app.application.scheduling")
        scheduling.register_scheduler_class(lambda: self.scheduler)
        self.owner = type("P115StrmHelperCloneA", (), {})()
        module(
            f"{prefix}.core.config",
            configer=SimpleNamespace(
                plugin_id=self.owner.__class__.__name__, plugin_instance=self.owner
            ),
        )
        self.native = MagicMock()
        self.native.trigger_refresh_by_path.return_value = True
        module(
            f"{prefix}.helper.mediaserver.emby",
            EmbyOperate=MagicMock(return_value=self.native),
        )
        self.refresh_module = importlib.import_module(
            f"{prefix}.helper.mediaserver.refresh"
        )
        self.refresh_type = self.refresh_module.MediaServerRefresh
        self.server = self._server("Emby", "emby")
        self.refresh = self.refresh_type(
            "【测试】", enabled=True, mediaservers=["Emby"]
        )

    def _server(self, name: str, kind: str, enabled: bool = True) -> Any:
        self.configs.append(self.config_type(name=name, type=kind, enabled=enabled))
        instance = MagicMock()
        instance.is_inactive.return_value = False
        instance.refresh_root_library.return_value = True
        instance.refresh_library_by_items.return_value = True
        self.instances[name] = instance
        return instance

    def test_discovery_filters_disabled_unselected_and_inactive_services(self) -> None:
        """
        服务目录按当前配置过滤未选择、禁用和失联实例，保持原筛选
        """
        excluded = self._server("Other", "emby")
        disabled = self._server("Disabled", "emby", enabled=False)
        inactive = self._server("Offline", "emby")
        inactive.is_inactive.return_value = True
        self.refresh.media_servers.extend(["Disabled", "Offline"])
        self.assertTrue(self.refresh.refresh_mediaserver(refresh_all=True))
        self.server.refresh_root_library.assert_called_once_with()
        for instance in (excluded, disabled, inactive):
            instance.refresh_root_library.assert_not_called()

    def test_original_refresh_payload_accepts_v3_category_alias(self) -> None:
        """
        原刷新模型和 category 字段可直接接受 V3 媒体库分类
        """
        self.refresh.mp_mediaserver = "/server#/local"
        source = "/local/Example/Example.S01E01.strm"
        self.assertTrue(self.refresh.refresh_mediaserver(source, mediainfo=self.media))
        item = self.server.refresh_library_by_items.call_args.args[0][0]
        self.assertEqual(item.target_path, Path("/server/Example/Example.S01E01.strm"))
        self.assertEqual(item.category, "动画")
        self.assertEqual(item.type, self.types.MediaType.TV)
        self.chain.recognize_by_meta.assert_not_called()

    def test_original_recognition_call_accepts_v3_contract(self) -> None:
        """
        原映射后的路径仍经 recognize_media(meta=...) 交给真实 V3 识别入口
        """
        self.refresh.mp_mediaserver = "/server#/local"
        with patch.object(
            self.refresh_module, "MetaInfoPath", wraps=self.refresh_module.MetaInfoPath
        ) as parse:
            self.assertTrue(
                self.refresh.refresh_mediaserver("/local/Example.S01E01.strm")
            )
        parse.assert_called_once_with(path=Path("/server/Example.S01E01.strm"))
        meta = self.chain._build_recognition_plan.call_args.kwargs["meta"]
        self.assertEqual(meta.begin_episode, 1)
        self.chain.recognize_by_meta.assert_not_called()
        item = self.server.refresh_library_by_items.call_args.args[0][0]
        self.assertEqual(item.target_path, Path("/server/Example.S01E01.strm"))

    def test_original_emby_path_fallback_remains_compatible(self) -> None:
        """
        无识别结果时沿用原 Emby 路径回退调用
        """
        self.chain.recognize_media.return_value = None
        self.refresh.mp_mediaserver = "/server#/local"
        self.assertTrue(self.refresh.refresh_mediaserver("/local/unknown.strm"))
        self.native.trigger_refresh_by_path.assert_called_once_with(
            "Emby", "/server/unknown.strm"
        )

    def test_delayed_refresh_is_bound_to_instance_and_has_unique_job_ids(self) -> None:
        """
        不同刷新请求通过真实 SDK 门面交给宿主，保留实例归属且不会相互覆盖
        """
        self.refresh.delay_seconds = 7
        for name in ("one.strm", "two.strm"):
            self.assertTrue(
                self.refresh.refresh_mediaserver("/" + name, mediainfo=self.media)
            )
        first, second = self.scheduler.add_plugin_once_job.call_args_list
        self.assertEqual(first.args[0], "P115StrmHelperCloneA")
        self.assertNotEqual(first.args[1], second.args[1])
        self.assertEqual(first.kwargs["delay_seconds"], 7)
        self.assertIs(first.args[2].__self__, self.owner)
        self.server.refresh_library_by_items.assert_not_called()
        first.args[2](**first.kwargs["func_kwargs"])
        self.server.refresh_library_by_items.assert_called_once()

    def test_rejected_schedule_has_no_unmanaged_fallback(self) -> None:
        """
        宿主关闭或拒绝注册时返回失败，不另建线程继续执行
        """
        self.refresh.delay_seconds = 5
        self.scheduler.add_plugin_once_job.return_value = False
        self.assertFalse(
            self.refresh.refresh_mediaserver("/a.strm", mediainfo=self.media)
        )
        self.server.refresh_library_by_items.assert_not_called()

    def test_delayed_execution_reports_original_refresh_failure(self) -> None:
        """
        原刷新方法失败时延迟回调抛错，使宿主任务记录执行失败
        """
        self.refresh.delay_seconds = 5
        self.assertTrue(
            self.refresh.refresh_mediaserver("/a.strm", mediainfo=self.media)
        )
        submission = self.scheduler.add_plugin_once_job.call_args
        with (
            patch.object(self.refresh, "_do_refresh", return_value=False),
            self.assertRaises(RuntimeError),
        ):
            submission.args[2](**submission.kwargs["func_kwargs"])

    def test_delayed_execution_rediscovers_current_services(self) -> None:
        """
        延迟到期时通过 V3 服务目录取得当前实例，保持原动态发现行为
        """
        self.refresh.delay_seconds = 5
        self.assertTrue(
            self.refresh.refresh_mediaserver("/a.strm", mediainfo=self.media)
        )
        submission = self.scheduler.add_plugin_once_job.call_args
        replacement = MagicMock()
        replacement.is_inactive.return_value = False
        self.instances["Emby"] = replacement
        submission.args[2](**submission.kwargs["func_kwargs"])
        replacement.refresh_library_by_items.assert_called_once()
        self.server.refresh_library_by_items.assert_not_called()

    def test_disabled_refresh_remains_noop(self) -> None:
        """
        未启用时保持成功空操作，不查询服务器或注册任务
        """
        self.refresh.enabled = False
        self.assertTrue(self.refresh.refresh_mediaserver())
        self.server.is_inactive.assert_not_called()
        self.scheduler.add_plugin_once_job.assert_not_called()
