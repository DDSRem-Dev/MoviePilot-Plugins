import __future__
import ast
import importlib
import os
import sys
from base64 import b64encode
from contextlib import nullcontext
from dataclasses import asdict
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest import TestCase
from unittest.mock import MagicMock


class TestV3Messaging(TestCase):
    """
    使用真实宿主消息模型和插件发送入口验证通知及交互归属
    """

    def setUp(self) -> None:
        """
        隔离数据库和发送链路，加载真实 V3 基类与插件交互模块
        """
        root = Path(__file__).resolve().parents[1]
        host = Path(os.environ.get("MOVIEPILOT_SOURCE", root.parents[2] / "MoviePilot"))
        if not (host / "app/sdk/plugin/base.py").exists():
            self.skipTest("需要 MOVIEPILOT_SOURCE 指向 V3 主程序")
        prefix = "_p115_messaging_test"
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

        for name in ("app", "app.schemas", "app.sdk", "app.sdk.plugin"):
            module(name, __path__=[str(host.joinpath(*name.split(".")))])
        for suffix in (
            "",
            ".core",
            ".schemas",
            ".interactive",
            ".interactive.framework",
        ):
            location = root.joinpath(*suffix.strip(".").split(".")) if suffix else root
            module(prefix + suffix, __path__=[str(location)])
        self.types = importlib.import_module("app.schemas.types")
        self.message_type = importlib.import_module("app.schemas.message").Message
        sys.modules["app.schemas"].MessageType = self.types.MessageType
        sys.modules["app.schemas"].NotificationChannel = self.types.NotificationChannel
        self.logger = MagicMock()
        module("app.sdk.logging", logger=self.logger)
        module("app.sdk.utilities", StringUtils=MagicMock())
        module(
            "app.sdk.config",
            settings=SimpleNamespace(
                MP_DOMAIN=lambda path: "https://mp.invalid/" + path
            ),
        )
        for name, symbol in (
            ("app.application.messaging.message", "MessageHelper"),
            ("app.chain.base", "ChainBase"),
            ("app.db.oper.plugindata", "PluginDataOper"),
            ("app.db.oper.plugininstance", "PluginInstanceOper"),
            ("app.db.oper.systemconfig", "SystemConfigOper"),
            ("app.db.plugin.container", "PluginDatabaseHandle"),
            ("app.runtime.events", "EventManager"),
        ):
            module(name, **{symbol: type(symbol, (), {})})
        module("app.db.plugin.registry", get_database=MagicMock())
        base = importlib.import_module("app.sdk.plugin.base")._PluginBase
        concrete = type(
            "P115StrmHelperCloneA",
            (base,),
            {name: lambda self: None for name in base.__abstractmethods__},
        )
        self.owner = object.__new__(concrete)
        self.owner.chain = MagicMock()
        self.config = SimpleNamespace(
            plugin_instance=self.owner, get_config=MagicMock(return_value="zh_CN")
        )
        module(f"{prefix}.core.config", configer=self.config)
        self.i18n = MagicMock()
        self.i18n.get.return_value = [b64encode("测试尾句".encode()).decode()]
        module(f"{prefix}.core.i18n", i18n=self.i18n)
        self.sender = importlib.import_module(f"{prefix}.core.message")
        self.schemas = importlib.import_module(
            f"{prefix}.interactive.framework.schemas"
        )
        self.manager_module = importlib.import_module(
            f"{prefix}.interactive.framework.manager"
        )
        self.manager = self.manager_module.BaseSessionManager(self.schemas.BaseSession)
        self.callbacks = importlib.import_module(
            f"{prefix}.interactive.framework.callbacks"
        )
        registry = importlib.import_module(f"{prefix}.interactive.framework.registry")
        registry.command_registry.command("test", "t")(lambda: None)
        registry.view_registry.view("test", "t")(lambda: None)
        self.plugin_id = self.owner.__class__.__name__
        self.context = {
            "channel": self.types.NotificationChannel.Telegram,
            "source": "Telegram A",
            "userid": "42",
            "original_chat_id": "-100",
            "original_message_id": "15",
        }
        self.cleanup = MagicMock()
        self.cleanup.try_handle_message_action.return_value = False
        tree = ast.parse((root / "__init__.py").read_text())
        entry_class = next(n for n in tree.body if isinstance(n, ast.ClassDef))
        methods = [
            n
            for n in entry_class.body
            if isinstance(n, ast.FunctionDef)
            and n.name in ("message_action", "__delete_message", "_get_event_userid")
        ]
        for method in methods:
            if method.name != "_get_event_userid":
                method.decorator_list = []
        entry_class.bases = []
        entry_class.decorator_list = []
        entry_class.body = methods
        namespace = {
            "asdict": asdict,
            "BaseMessage": self.schemas.BaseMessage,
            "session_manager": self.manager,
            "decode_action": self.callbacks.decode_action,
            "strm_cleanup_interaction": self.cleanup,
            "logger": self.logger,
            "servicer": SimpleNamespace(sync_operation=nullcontext),
        }
        exec(
            compile(
                ast.Module(body=[entry_class], type_ignores=[]),
                str(root / "__init__.py"),
                "exec",
                flags=__future__.annotations.compiler_flag,
            ),
            namespace,
        )
        entry_type = type(self.plugin_id, (namespace[entry_class.name],), {})
        self.entry = entry_type()
        self.entry.post_message = MagicMock()
        self.entry.action_handler = MagicMock()
        self.entry.action_handler.process.return_value = []
        self.entry._render_and_send = MagicMock()
        self.entry.chain = MagicMock()

    def _load_views(self) -> Any:
        prefix = "_p115_messaging_test"
        search = ModuleType(f"{prefix}.helper.search")
        search.HDHiveSearch = SimpleNamespace(SOURCE="hdhive")
        search.MediaSearcher = MagicMock()
        search.TgSearcher = MagicMock()
        sys.modules[search.__name__] = search
        registry = importlib.import_module(f"{prefix}.interactive.framework.registry")
        for name, code in (
            ("share_recieve", "dsr"),
            ("offline_download", "dod"),
            ("resource", "rs"),
            ("subscribe", "sb"),
            ("page_next", "pn"),
            ("page_prev", "pp"),
            ("refresh", "rf"),
            ("close", "cl"),
            ("go_back", "gb"),
            ("share_intent_transfer", "sit"),
            ("share_intent_strm", "sis"),
        ):
            registry.command_registry.command(name, code)(lambda: None)
        self.config.share_recieve_paths = [f"/share/{index}" for index in range(20)]
        self.config.offline_download_paths = [
            f"/offline/{index}" for index in range(20)
        ]
        self.i18n.translate.side_effect = lambda key, **kwargs: key
        return importlib.import_module(f"{prefix}.interactive.views")

    def _session(self, **changes: Any) -> Any:
        return self.manager.get_or_create({**self.context, **changes}, self.plugin_id)

    def _callback_event(self, session: Any, **changes: Any) -> Any:
        return SimpleNamespace(
            event_data={
                **self.context,
                "plugin_id": self.plugin_id,
                "text": f"{session.session_id}|c:t|w:t",
                **changes,
            }
        )

    def test_bound_sdk_sender_preserves_message_fields_and_clone_link(self) -> None:
        """
        真实宿主发送入口生成分身链接并保留按钮、路由和编辑上下文
        """
        buttons = [[{"text": "按钮", "callback_data": "test"}]]
        self.sender.post_message(
            **{**self.context, "userid": 0},
            username=0,
            title="标题",
            text="正文",
            buttons=buttons,
            private_delivery=True,
            parse_mode="plain",
            save_history=False,
        )
        message = self.owner.chain.post_message.call_args.args[0]
        self.assertIsInstance(message, self.message_type)
        self.assertEqual(
            message.link,
            f"https://mp.invalid/#/plugins?tab=installed&id={self.plugin_id}",
        )
        self.assertEqual(message.userid, 0)
        self.assertEqual(message.username, 0)
        self.assertEqual(message.original_chat_id, "-100")
        self.assertEqual(message.original_message_id, "15")
        self.assertEqual(message.source, "Telegram A")
        self.assertEqual(message.buttons, buttons)
        self.assertTrue(message.private_delivery)
        self.assertFalse(message.save_history)
        self.assertEqual(message.parse_mode, "plain")

    def test_explicit_link_and_language_suffix_remain_supported(self) -> None:
        """
        明确链接及原有语言尾句行为不被绑定发送入口改变
        """
        self.config.get_config.return_value = "zh_CN_catgirl"
        for source, expected in (
            ("正文", "正文\n测试尾句"),
            ("正文\n", "正文\n\n测试尾句\n"),
            (None, "\n测试尾句\n"),
        ):
            with self.subTest(source=source):
                self.assertIsNone(
                    self.sender.post_message(
                        text=source, link="https://example.invalid/"
                    )
                )
                message = self.owner.chain.post_message.call_args.args[0]
                self.assertEqual(message.link, "https://example.invalid/")
                self.assertEqual(message.text, expected)

    def test_callback_roundtrip_preserves_action_within_normal_byte_budget(
        self,
    ) -> None:
        """
        真实编码器在普通按钮长度内保留命令、视图和参数
        """
        session = self._session()
        action = self.callbacks.Action(command="test", view="test", value="12")
        encoded = self.callbacks.encode_action(session, action)
        self.assertLessEqual(len(encoded.encode("utf-8")), 64)
        session_id, decoded = self.callbacks.decode_action(encoded.split("|", 1)[1])
        self.assertEqual(session_id, session.session_id)
        self.assertEqual(decoded, action)

    def test_entry_plugin_guards_run_before_cleanup_and_action_handlers(self) -> None:
        """
        外来插件目标在进入清理确认或交互处理器前被拒绝
        """
        session = self._session()
        for changes in ({"plugin_id": "Other"}, {"__mp_target_plugin_id": "Other"}):
            self.entry.message_action(self._callback_event(session, **changes))
        self.cleanup.try_handle_message_action.assert_not_called()
        self.entry.action_handler.process.assert_not_called()
        self.entry.post_message.assert_not_called()

    def test_entry_owner_reaches_action_and_render_with_updated_context(self) -> None:
        """
        合法回调更新消息标识后执行业务并渲染
        """
        session = self._session()
        self.entry.message_action(self._callback_event(session, original_message_id=16))
        self.entry.action_handler.process.assert_called_once()
        self.assertIs(self.entry.action_handler.process.call_args.args[0], session)
        self.assertEqual(session.message.original_message_id, 16)
        self.entry._render_and_send.assert_called_once_with(session)
        self.entry.post_message.assert_not_called()

    def test_original_delete_call_remains_compatible(
        self,
    ) -> None:
        """
        原删除接口参数和结果处理在 V3 保持兼容
        """
        remove = self.entry._P115StrmHelper__delete_message
        self.entry.chain.delete_message.return_value = None
        self.assertFalse(remove(self.context["channel"], "Telegram A", 0, -100))
        self.entry.chain.delete_message.assert_called_once_with(
            channel=self.context["channel"],
            source="Telegram A",
            message_id=0,
            chat_id=-100,
        )
        self.entry.chain.delete_message.return_value = True
        self.assertTrue(remove(self.context["channel"], "Telegram A", "1"))

    def test_real_channel_capabilities_drive_all_selection_view_pages(self) -> None:
        """
        V3 真实渠道能力决定目录、媒体及资源选择器的按钮分页
        """
        views = self._load_views()
        capabilities = importlib.import_module(
            "app.schemas.notification"
        ).ChannelCapabilityManager
        self.assertIs(views.ChannelCapabilityManager, capabilities)
        renderer = views.ViewRenderer()
        session_type = importlib.import_module(
            "_p115_messaging_test.interactive.session"
        ).Session
        for channel in (
            self.types.NotificationChannel.Telegram,
            self.types.NotificationChannel.Slack,
            self.types.NotificationChannel.Discord,
        ):
            for view in (
                "share_recieve_paths",
                "offline_download_paths",
                "search_list",
                "resource_list",
            ):
                with self.subTest(channel=channel, view=view):
                    session = session_type("12345678", self.plugin_id)
                    session.update_message_context({**self.context, "channel": channel})
                    session.view.name = view
                    session.business.search_info = {
                        "data": [
                            {"title": f"Test {i}", "type": "电影", "tmdb_id": i}
                            for i in range(20)
                        ]
                    }
                    session.business.resource_info = {
                        "data": [
                            {
                                "taskname": f"File {i}",
                                "shareurl": "https://example.invalid/",
                            }
                            for i in range(20)
                        ]
                    }
                    result = renderer.render(session)
                    self.assertNotEqual(result["title"], "未知视图")
                    self.assertGreater(session.view.total_pages, 1)
                    rows = result["buttons"]
                    self.assertEqual(len(rows), 4)
                    self.assertLessEqual(
                        len(rows), capabilities.get_max_button_rows(channel)
                    )
                    for row in rows:
                        self.assertLessEqual(
                            len(row), capabilities.get_max_buttons_per_row(channel)
                        )
                        for button in row:
                            callback = button["callback_data"]
                            self.assertLessEqual(len(callback.encode()), 64)
                            self.assertTrue(
                                callback.startswith(f"[PLUGIN]{self.plugin_id}|")
                            )
                    self.message_type(**asdict(session.message), **result)
