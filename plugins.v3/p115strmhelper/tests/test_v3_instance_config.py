import ast
import __future__
from importlib import import_module
from json import dumps, loads
from os import environ
from pathlib import Path
from sys import modules
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
from typing import Any, Dict, Optional
from unittest import TestCase
from unittest.mock import MagicMock


def _module(name: str, **attributes: Any) -> ModuleType:
    result = ModuleType(name)
    result.__dict__.update(attributes)
    return result


class TestV3InstanceConfig(TestCase):
    """
    校验真实配置模型经插件实例接口持久化，避免分身写入本体数据
    """

    def setUp(self) -> None:
        """
        加载真实配置与子模型，仅隔离宿主和云端客户端
        """
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        root = Path(__file__).resolve().parents[1]
        self.root = root
        prefix = "_p115_v3_config_test"
        replacements = {}
        for suffix in ("", ".core", ".schemas", ".utils"):
            name = prefix + suffix
            path = root.joinpath(*suffix.strip(".").split(".")) if suffix else root
            replacements[name] = _module(name, __path__=[str(path)])
        replacements.update(
            {
                "app": _module("app", __path__=[]),
                "app.sdk": _module("app.sdk", __path__=[]),
                "app.sdk.logging": _module("app.sdk.logging", logger=MagicMock()),
                "app.sdk.config": _module(
                    "app.sdk.config",
                    settings=SimpleNamespace(
                        PLUGIN_DATA_PATH=Path(temporary.name),
                        ROOT_PATH=Path(temporary.name),
                    ),
                ),
                "app.sdk.utilities": _module(
                    "app.sdk.utilities", SystemUtils=MagicMock()
                ),
                f"{prefix}.core.aliyunpan": _module(
                    f"{prefix}.core.aliyunpan", AliyunPanLogin=MagicMock()
                ),
                f"{prefix}.utils.user_agent": _module(
                    f"{prefix}.utils.user_agent", UserAgentUtils=MagicMock()
                ),
                f"{prefix}.utils.strm": _module(
                    f"{prefix}.utils.strm", StrmGenerater=MagicMock()
                ),
            }
        )
        originals = {name: modules.get(name) for name in replacements}

        def restore_modules() -> None:
            # 保留第三方惰性加载的模块，避免原生扩展重载和 Pydantic 类型身份分裂
            for name in list(modules):
                if name == prefix or name.startswith(f"{prefix}."):
                    modules.pop(name, None)
            for name, original in originals.items():
                if original is None:
                    modules.pop(name, None)
                else:
                    modules[name] = original

        modules.update(replacements)
        self.addCleanup(restore_modules)
        self.config_type = import_module(f"{prefix}.core.config").ConfigManager
        self.login = replacements[f"{prefix}.core.aliyunpan"].AliyunPanLogin
        self.login.get_token.side_effect = lambda path: (
            loads(path.read_text()).get("refresh_token") if path.exists() else None
        )
        self.settings = replacements["app.sdk.config"].settings
        self.strm_generator = replacements[f"{prefix}.utils.strm"].StrmGenerater

    def _owner(
        self,
        instance_id: str = "P115StrmHelper",
        source_config: Optional[Dict[str, Any]] = None,
    ) -> Any:
        host = Path(
            environ.get("MOVIEPILOT_SOURCE", self.root.parents[2] / "MoviePilot")
        )
        source = host / "app/sdk/plugin/base.py"
        if not source.exists():
            self.skipTest("需要 MOVIEPILOT_SOURCE 指向 V3 主程序")
        tree = ast.parse(source.read_text())
        cls = next(
            n
            for n in tree.body
            if isinstance(n, ast.ClassDef) and n.name == "_PluginBase"
        )
        method = next(
            n
            for n in cls.body
            if isinstance(n, ast.FunctionDef) and n.name == "get_data_path"
        )
        namespace = {"settings": self.settings, "Optional": Optional, "Path": Path}
        exec(
            compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"),
            namespace,
        )
        owner = type(
            instance_id,
            (),
            {
                "get_data_path": namespace["get_data_path"],
                "is_clone": instance_id != "P115StrmHelper",
                "plugin_source_id": "P115StrmHelper",
            },
        )()
        owner.get_config = MagicMock(return_value=source_config or {})
        owner.update_config = MagicMock(return_value=True)
        return owner

    def test_config_uses_bound_instance_and_excludes_runtime_owner(self) -> None:
        """
        保存使用宿主实例接口且不会序列化运行时插件对象
        """
        config = self.config_type(PLUSIN_NAME="untrusted-config-value")
        owner = type("P115StrmHelperCloneA", (), {})()
        owner.update_config = MagicMock(return_value=True)
        config.bind_plugin(owner)
        self.assertEqual(config.plugin_id, "P115StrmHelperCloneA")
        self.assertTrue(config.update_plugin_config())
        payload = owner.update_config.call_args.args[0]
        self.assertNotIn("_plugin", payload)
        self.assertNotIn("plugin_id", payload)
        self.assertEqual(payload, config.model_dump(mode="json"))

    def test_data_is_scoped_to_each_bound_owner(self) -> None:
        """
        本体和分身通过各自实例保存与读取相同数据键
        """
        for instance_id in ("P115StrmHelper", "P115StrmHelperCloneA"):
            with self.subTest(instance_id=instance_id):
                config = self.config_type()
                owner = type(instance_id, (), {})()
                owner.save_data = MagicMock()
                owner.get_data = MagicMock(return_value=instance_id)
                owner.del_data = MagicMock(return_value=True)
                config.bind_plugin(owner)
                config.save_plugin_data("token", instance_id)
                owner.save_data.assert_called_once_with(
                    "token", instance_id, plugin_id=None
                )
                self.assertEqual(config.get_plugin_data("token"), instance_id)
                owner.get_data.assert_called_once_with("token", plugin_id=None)
                self.assertTrue(config.del_plugin_data("token"))
                owner.del_data.assert_called_once_with("token", plugin_id=None)

    def test_explicit_cross_plugin_access_is_preserved(self) -> None:
        """
        显式指定插件的数据读取仍传递原目标标识
        """
        config = self.config_type()
        owner = MagicMock()
        config.bind_plugin(owner)
        config.get_plugin_data("history", plugin_id="OtherPlugin")
        owner.get_data.assert_called_once_with("history", plugin_id="OtherPlugin")

    def test_unbound_access_fails_without_legacy_fallback(self) -> None:
        """
        未绑定实例时拒绝持久化，不回退写入旧系统配置键
        """
        config = self.config_type()
        with self.assertRaisesRegex(RuntimeError, "尚未绑定"):
            config.update_plugin_config()
        with self.assertRaisesRegex(RuntimeError, "尚未绑定"):
            config.get_plugin_data("token")

    def test_fresh_instance_uses_sdk_directory_and_keeps_legacy_database_source(
        self,
    ) -> None:
        """
        新安装使用真实 SDK 实例目录，旧数据库来源独立保留
        """
        for name in ("P115StrmHelper", "P115StrmHelperCloneA"):
            with self.subTest(instance=name):
                config = self.config_type()
                config.bind_plugin(self._owner(name))
                self.assertTrue(config.load_from_dict({}))
                self.assertEqual(config.PLUGIN_CONFIG_PATH, self.directory / name)
                self.assertEqual(
                    config.PLUGIN_TEMP_PATH, self.directory / name / "temp"
                )
                self.assertEqual(config.data_path_owner, name)
                self.assertEqual(
                    config.PLUGIN_DB_PATH,
                    self.directory / "p115strmhelper/p115strmhelper_file.db",
                )

    def test_legacy_main_retains_credentials_identity_queue_and_temp_in_place(
        self,
    ) -> None:
        """
        本体升级保留原目录及所有文件，不复制或改写待执行队列
        """
        legacy = self.directory / "p115strmhelper"
        (legacy / "aligo").mkdir(parents=True)
        (legacy / "temp").mkdir()
        values = {
            "aligo/aligo.json": dumps({"refresh_token": "legacy-token"}),
            "machine_id.txt": dumps({"machine_id": "a" * 64}),
            "share_audit_download_queue.json": '[{"task_id":"pending"}]',
            "temp/export_dir.lock": "retained-state",
        }
        for filename, content in values.items():
            (legacy / filename).write_text(content)
        before = {name: (legacy / name).read_bytes() for name in values}
        config = self.config_type()
        owner = self._owner()
        config.bind_plugin(owner)
        self.assertTrue(config.load_from_dict({}))
        self.assertEqual(config.PLUGIN_CONFIG_PATH, legacy)
        self.assertEqual(config.PLUGIN_TEMP_PATH, legacy / "temp")
        self.assertEqual(config.aliyundrive_token, "legacy-token")
        self.assertEqual(config.machine_id, "a" * 64)
        self.assertEqual(
            before, {name: (legacy / name).read_bytes() for name in values}
        )
        config.update_plugin_config()
        restored = self.config_type()
        restored.bind_plugin(owner)
        self.assertTrue(restored.load_from_dict(owner.update_config.call_args.args[0]))
        self.assertEqual(restored.PLUGIN_CONFIG_PATH, legacy)

    def test_clone_discards_copied_owned_paths_without_copying_persistent_files(
        self,
    ) -> None:
        """
        分身复制配置只继承业务值，不读取本体路径中的 token 或恢复本体队列
        """
        source = self.directory / "custom-main"
        (source / "aligo").mkdir(parents=True)
        (source / "aligo/aligo.json").write_text(dumps({"refresh_token": "file-token"}))
        (source / "share_audit_download_queue.json").write_text('[{"task_id":"main"}]')
        copied = {
            "PLUGIN_CONFIG_PATH": str(source),
            "PLUGIN_TEMP_PATH": str(source / "work"),
            "PLUGIN_DB_PATH": str(source / "legacy.db"),
            "data_path_owner": "P115StrmHelper",
            "aliyundrive_token": "configured-token",
        }
        config = self.config_type()
        config.bind_plugin(self._owner("P115StrmHelperCloneA", copied))
        self.assertTrue(config.load_from_dict(copied))
        expected = self.directory / "P115StrmHelperCloneA"
        self.assertEqual(config.PLUGIN_CONFIG_PATH, expected)
        self.assertEqual(config.PLUGIN_TEMP_PATH, expected / "temp")
        self.assertEqual(config.PLUGIN_DB_PATH, source / "legacy.db")
        self.assertEqual(config.aliyundrive_token, "configured-token")
        self.login.get_token.assert_called_once_with(expected / "aligo/aligo.json")
        self.assertFalse((expected / "share_audit_download_queue.json").exists())
        self.assertFalse((expected / "machine_id.txt").exists())
        self.assertEqual(copied["data_path_owner"], "P115StrmHelper")

    def test_unmarked_clone_recognizes_legacy_source_and_canonical_paths(self) -> None:
        """
        旧分身配置没有归属标识时识别默认路径和本体自定义路径
        """
        source = self.directory / "custom-main"
        owner = self._owner(
            "P115StrmHelperCloneA",
            {
                "PLUGIN_CONFIG_PATH": str(source),
                "PLUGIN_TEMP_PATH": str(source / "work"),
            },
        )
        for root, temp in (
            (self.directory / "p115strmhelper", self.directory / "p115strmhelper/temp"),
            (self.directory / "P115StrmHelper", self.directory / "P115StrmHelper/temp"),
            (source / "sub/..", source / "work"),
        ):
            with self.subTest(root=root):
                config = self.config_type()
                config.bind_plugin(owner)
                self.assertTrue(
                    config.load_from_dict(
                        {"PLUGIN_CONFIG_PATH": root, "PLUGIN_TEMP_PATH": temp}
                    )
                )
                self.assertEqual(
                    config.PLUGIN_CONFIG_PATH, self.directory / "P115StrmHelperCloneA"
                )
                self.assertEqual(
                    config.PLUGIN_TEMP_PATH,
                    self.directory / "P115StrmHelperCloneA/temp",
                )

    def test_explicit_instance_custom_paths_survive_save_and_reload(self) -> None:
        """
        实例自身的自定义目录保持原值，归属标识不会覆盖后续显式配置
        """
        for instance in ("P115StrmHelper", "P115StrmHelperCloneA"):
            with self.subTest(instance=instance):
                owner = self._owner(instance)
                config = self.config_type()
                config.bind_plugin(owner)
                values = {
                    "PLUGIN_CONFIG_PATH": self.directory / (instance + "-data"),
                    "PLUGIN_TEMP_PATH": self.directory / (instance + "-work"),
                }
                self.assertTrue(config.load_from_dict(values))
                config.update_plugin_config()
                self.assertTrue(
                    config.load_from_dict(owner.update_config.call_args.args[0])
                )
                self.assertEqual(
                    config.PLUGIN_CONFIG_PATH, values["PLUGIN_CONFIG_PATH"]
                )
                self.assertEqual(config.PLUGIN_TEMP_PATH, values["PLUGIN_TEMP_PATH"])
                self.assertIs(config.plugin_instance, owner)

    def test_partial_reloads_preserve_omitted_owned_paths(self) -> None:
        """
        已归属实例的配置再次部分加载时保留未提供的自定义目录
        """
        for instance in (
            "P115StrmHelper",
            "P115StrmHelperCloneA",
            "P115StrmHelperCloneB",
        ):
            data_path = self.directory / (instance + "-data")
            temp_path = self.directory / (instance + "-work")
            for name, values in (
                ("empty_dict", {}),
                ("empty_json", {}),
                ("language", {"language": "zh_CN"}),
                ("config_path", {"PLUGIN_CONFIG_PATH": str(data_path / "new")}),
                ("temp_path", {"PLUGIN_TEMP_PATH": str(temp_path / "new")}),
                ("same_owner", {"data_path_owner": instance}),
            ):
                with self.subTest(instance=instance, input=name):
                    config = self.config_type()
                    config.bind_plugin(self._owner(instance))
                    self.assertTrue(
                        config.load_from_dict(
                            {
                                "PLUGIN_CONFIG_PATH": data_path,
                                "PLUGIN_TEMP_PATH": temp_path,
                                "language": "en_US",
                            }
                        )
                    )
                    before = config.model_dump()
                    supplied = dict(values)
                    if name == "empty_json":
                        self.assertTrue(config.load_from_json("{}"))
                    else:
                        self.assertTrue(config.load_from_dict(supplied))
                    self.assertEqual(supplied, values)
                    self.assertEqual(config.model_dump(), dict(before, **values))

    def test_repeated_import_still_relocates_copied_clone_paths(self) -> None:
        """
        分身已有配置时再次导入本体目录仍按原归属规则重定位
        """
        source = {
            "PLUGIN_CONFIG_PATH": self.directory / "source-data",
            "PLUGIN_TEMP_PATH": self.directory / "source-work",
        }
        for instance in ("P115StrmHelperCloneA", "P115StrmHelperCloneB"):
            for marked in (False, True):
                with self.subTest(instance=instance, marked=marked):
                    config = self.config_type()
                    config.bind_plugin(self._owner(instance, source))
                    self.assertTrue(
                        config.load_from_dict(
                            {
                                "PLUGIN_CONFIG_PATH": self.directory / "own-data",
                                "PLUGIN_TEMP_PATH": self.directory / "own-work",
                            }
                        )
                    )
                    copied = dict(source)
                    if marked:
                        copied["data_path_owner"] = "P115StrmHelper"
                    self.assertTrue(config.load_from_dict(copied))
                    self.assertEqual(
                        config.PLUGIN_CONFIG_PATH, self.directory / instance
                    )
                    self.assertEqual(
                        config.PLUGIN_TEMP_PATH, self.directory / instance / "temp"
                    )
                    self.assertEqual(config.data_path_owner, instance)

    def test_rebound_model_resolves_new_instance_paths(self) -> None:
        """
        模型重新绑定不同实例后不沿用前一个实例的自定义目录
        """
        config = self.config_type()
        config.bind_plugin(self._owner())
        self.assertTrue(
            config.load_from_dict(
                {
                    "PLUGIN_CONFIG_PATH": self.directory / "main-data",
                    "PLUGIN_TEMP_PATH": self.directory / "main-work",
                }
            )
        )
        config.bind_plugin(self._owner("P115StrmHelperCloneA"))
        self.assertTrue(config.load_from_dict({}))
        self.assertEqual(
            config.PLUGIN_CONFIG_PATH, self.directory / "P115StrmHelperCloneA"
        )
        self.assertEqual(
            config.PLUGIN_TEMP_PATH, self.directory / "P115StrmHelperCloneA/temp"
        )
        self.assertEqual(config.data_path_owner, "P115StrmHelperCloneA")

    def test_clone_reload_does_not_revert_to_changed_source_paths(self) -> None:
        """
        分身完成首次保存后，本体改目录不影响分身自身目录
        """
        config = self.config_type()
        owner = self._owner("P115StrmHelperCloneA")
        config.bind_plugin(owner)
        self.assertTrue(config.load_from_dict({}))
        values = config.model_dump(mode="json")
        owner.get_config.side_effect = AssertionError("不应再次读取本体配置")
        self.assertTrue(config.load_from_dict(values))
        self.assertEqual(
            config.PLUGIN_CONFIG_PATH, self.directory / "P115StrmHelperCloneA"
        )

    def test_explicit_token_clear_only_removes_the_current_instance_file(self) -> None:
        """
        宿主清空 token 时只删除已解析到当前实例的登录文件
        """
        main = self.directory / "main/aligo/aligo.json"
        clone = self.directory / "P115StrmHelperCloneA/aligo/aligo.json"
        for path in (main, clone):
            path.parent.mkdir(parents=True)
            path.write_text(dumps({"refresh_token": "token"}))
        config = self.config_type()
        config.bind_plugin(self._owner("P115StrmHelperCloneA"))
        self.assertTrue(
            config.update_config(
                {
                    "PLUGIN_CONFIG_PATH": str(main.parent.parent),
                    "data_path_owner": "P115StrmHelper",
                    "aliyundrive_token": None,
                },
            )
        )
        self.assertFalse(clone.exists())
        self.assertTrue(main.exists())
        self.assertIsNone(config.aliyundrive_token)

    def test_preflight_update_does_not_publish_or_delete_login(self) -> None:
        """
        配置预校验不发布配置也不提前删除登录文件
        """
        config = self.config_type()
        config.bind_plugin(self._owner())
        self.assertTrue(config.load_from_dict({}))
        token = config.plugin_aligo_path / "aligo.json"
        token.parent.mkdir(parents=True, exist_ok=True)
        token.write_text('{"refresh_token":"original"}')
        before = config.model_dump()
        self.assertTrue(
            config.validate_updates({"aliyundrive_token": "", "cookies": "new"})
        )
        self.assertEqual(config.model_dump(), before)
        self.assertTrue(token.exists())
        self.assertFalse(
            config.validate_updates({"share_audit_retry_interval_seconds": -1})
        )
        self.assertEqual(config.model_dump(), before)
        self.assertTrue(token.exists())

    def test_empty_address_survives_host_construction_and_initialization(self) -> None:
        """
        已保存的空地址配置可重新构造和初始化插件，且持久化为 null
        """
        for value in (None, "", " \t\n"):
            with self.subTest(value=value):
                persisted = {"moviepilot_address": value, "notify": True}
                entry_type, config, _, api_factory, _ = self._entry_type(persisted)
                entry = entry_type()
                entry.init_plugin(persisted)
                self.assertIsNone(config.moviepilot_address)
                self.assertTrue(config.notify)
                self.assertIsNotNone(entry.action_handler)
                api_factory.assert_called_once_with(client=None)
                payload = entry.update_config.call_args.args[0]
                self.assertIsNone(payload["moviepilot_address"])
                self.assertTrue(payload["notify"])

    def test_reinitialize_refuses_config_change_while_stop_is_pending(self) -> None:
        """
        初始化入口关停未完成时保留旧配置和服务归属
        """
        entry_type, config, events, api_factory, service = self._entry_type(
            {"cookies": "old"}
        )
        entry = entry_type()
        before = config.model_dump()
        entry.stop_service = MagicMock(return_value=False)
        with self.assertRaisesRegex(RuntimeError, "尚未退出"):
            entry.init_plugin({"cookies": "new"})
        self.assertEqual(config.model_dump(), before)
        service.init_service.assert_not_called()
        api_factory.assert_not_called()

    def _entry_type(self, persisted: Dict[str, Any]) -> Any:
        config = self.config_type()
        owner = self._owner("P115StrmHelperCloneA", persisted)
        tree = ast.parse((self.root / "__init__.py").read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
        cls.name = "P115StrmHelperCloneA"
        cls.decorator_list = []
        cls.body = [
            n
            for n in cls.body
            if isinstance(n, ast.FunctionDef) and n.name in ("__init__", "init_plugin")
        ]
        base = type(
            "Base",
            (type(owner),),
            {"get_config": lambda self, plugin_id=None: persisted},
        )
        events = []
        api_factory = MagicMock(
            side_effect=lambda **kwargs: events.append(
                ("api", config.PLUGIN_CONFIG_PATH)
            )
        )
        service = MagicMock()
        namespace = {
            "_PluginBase": base,
            "configer": config,
            "Path": Path,
            "ActionHandler": MagicMock(),
            "ViewRenderer": MagicMock(),
            "i18n": MagicMock(),
            "sentry_manager": MagicMock(),
            "Api": api_factory,
            "servicer": service,
            "MCPManager": MagicMock(),
            "upload_notifier": MagicMock(),
            "U115Patcher": MagicMock(),
            "P115DiskPatcher": MagicMock(),
            "AppVerPatcher": MagicMock(),
            "logger": MagicMock(),
        }
        exec(
            compile(
                ast.Module(body=[cls], type_ignores=[]),
                "__init__.py",
                "exec",
                flags=__future__.annotations.compiler_flag,
            ),
            namespace,
        )
        entry = namespace[cls.name]
        entry.stop_service = lambda self: events.append(
            ("stop", config.PLUGIN_CONFIG_PATH)
        )
        entry.init_database = lambda self: True
        entry.update_config = MagicMock(return_value=True)
        return entry, config, events, api_factory, service

    def test_host_no_argument_construction_resolves_paths_before_login_reads(
        self,
    ) -> None:
        """
        按宿主无参构造再初始化的顺序执行真实入口，首次读文件即使用分身目录
        """
        persisted = {
            "PLUGIN_CONFIG_PATH": str(self.directory / "main-data"),
            "PLUGIN_TEMP_PATH": str(self.directory / "main-work"),
            "data_path_owner": "P115StrmHelper",
        }
        entry_type, config, events, api_factory, service = self._entry_type(persisted)
        entry = entry_type()
        expected = self.directory / "P115StrmHelperCloneA"
        self.assertEqual(config.PLUGIN_CONFIG_PATH, expected)
        self.assertTrue((expected / "temp").is_dir())
        entry.init_plugin(persisted)
        self.assertEqual([event[0] for event in events], ["stop", "api"])
        self.assertEqual(events[-1][1], expected)
        self.assertTrue(
            all(
                call.args[0] == expected / "aligo/aligo.json"
                for call in self.login.get_token.call_args_list
            )
        )
        self.assertIs(config.plugin_instance, entry)
        self.assertEqual(
            entry.update_config.call_args.args[0]["data_path_owner"],
            "P115StrmHelperCloneA",
        )
        api_factory.assert_called_once_with(client=None)
        service.init_service.assert_not_called()

    def test_failed_path_owner_persistence_aborts_startup(self) -> None:
        """
        宿主拒绝保存目录归属时停止启动，避免重启重新解释目录
        """
        entry_type, config, events, api_factory, service = self._entry_type({})
        entry = entry_type()
        entry.update_config.return_value = False
        with self.assertRaisesRegex(RuntimeError, "目录配置保存失败"):
            entry.init_plugin({})
        api_factory.assert_not_called()
        service.init_service.assert_not_called()
