from importlib import import_module
from pathlib import Path
from sys import modules
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest import TestCase
from unittest.mock import MagicMock

from pydantic import ValidationError


def _module(name: str, **attributes: Any) -> ModuleType:
    module = ModuleType(name)
    module.__dict__.update(attributes)
    return module


class TestConfigAddress(TestCase):
    """
    校验空地址配置恢复及普通和分享 STRM 的生成边界
    """

    def setUp(self) -> None:
        """
        加载当前版本的真实配置与链接生成器，隔离宿主和网盘登录
        """
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        root = Path(__file__).resolve().parents[1]
        prefix = "_p115_v3_address_test"
        replacements = {}
        for suffix in ("", ".core", ".schemas", ".utils"):
            name = prefix + suffix
            path = root.joinpath(*suffix.strip(".").split(".")) if suffix else root
            replacements[name] = _module(name, __path__=[str(path)])
        settings = SimpleNamespace(
            PLUGIN_DATA_PATH=self.directory, ROOT_PATH=self.directory
        )
        replacements.update(
            {
                "app": _module("app", __path__=[]),
                "app.sdk": _module("app.sdk", __path__=[]),
                "app.sdk.logging": _module("app.sdk.logging", logger=MagicMock()),
                "app.sdk.config": _module("app.sdk.config", settings=settings),
                "app.sdk.utilities": _module(
                    "app.sdk.utilities", SystemUtils=MagicMock()
                ),
                f"{prefix}.core.aliyunpan": _module(
                    f"{prefix}.core.aliyunpan",
                    AliyunPanLogin=SimpleNamespace(get_token=lambda path: None),
                ),
                f"{prefix}.utils.user_agent": _module(
                    f"{prefix}.utils.user_agent", UserAgentUtils=MagicMock()
                ),
            }
        )
        originals = {name: modules.get(name) for name in replacements}

        def restore_modules() -> None:
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
        config_module = import_module(f"{prefix}.core.config")
        self.config_type = config_module.ConfigManager
        self.config = config_module.configer
        owner = type("P115StrmHelper", (), {})()
        owner.is_clone = False
        owner.get_data_path = lambda: self.directory / "P115StrmHelper"
        owner.update_config = MagicMock(return_value=True)
        self.config.bind_plugin(owner)
        self.url_module = import_module(f"{prefix}.utils.strm")

    def test_empty_address_load_preserves_following_settings(self) -> None:
        """
        历史空地址不会中断后续配置加载
        """
        for value in (None, "", " \t\n"):
            with self.subTest(value=value):
                self.config.notify = False
                self.assertTrue(
                    self.config.load_from_dict(
                        {"moviepilot_address": value, "notify": True}
                    )
                )
                self.assertIsNone(self.config.moviepilot_address)
                self.assertTrue(self.config.notify)

    def test_clear_address_update_and_reload(self) -> None:
        """
        清空地址后保存为 null，重新加载不恢复旧地址或丢失其他配置
        """
        for value in (None, "", " \t\n"):
            with self.subTest(value=value):
                self.config.moviepilot_address = "https://old.example"
                self.assertTrue(
                    self.config.update_config(
                        {"moviepilot_address": value, "notify": True}
                    )
                )
                payload = self.config.model_dump(mode="json")
                self.assertIsNone(payload["moviepilot_address"])
                self.config.moviepilot_address = "https://stale.example"
                self.assertTrue(self.config.load_from_dict(payload))
                self.assertIsNone(self.config.moviepilot_address)
                self.assertTrue(self.config.notify)

    def test_address_normalization_keeps_type_validation(self) -> None:
        """
        裁剪有效地址的首尾空白，同时保留对错误类型的拒绝
        """
        config = self.config_type(moviepilot_address="  https://mp.example/base/ \n")
        self.assertEqual(config.moviepilot_address, "https://mp.example/base/")
        with self.assertRaises(ValidationError):
            self.config_type(moviepilot_address=123)

    def test_missing_address_rejects_both_url_types(self) -> None:
        """
        未配置地址时允许构造生成器，但禁止输出无域名链接
        """
        for value in (None, "", " \t\n"):
            with self.subTest(value=value):
                self.assertTrue(
                    self.config.load_from_dict({"moviepilot_address": value})
                )
                getter = self.url_module.StrmUrlGetter()
                with self.assertRaisesRegex(ValueError, "STRM 文件内链接地址"):
                    getter.get_strm_url("pickcode", "电影.mkv", "/电影.mkv")
                with self.assertRaisesRegex(ValueError, "STRM 文件内链接地址"):
                    getter.get_share_strm_url(
                        "share", "code", "123", "电影.mkv", "/电影.mkv"
                    )

    def test_valid_address_preserves_url_formats(self) -> None:
        """
        有效地址仍支持子路径、普通与分享链接以及文件名编码
        """
        self.config.moviepilot_address = "  https://mp.example/base///  "
        self.config.strm_url_format = "pickname"
        self.config.strm_url_encode = True
        getter = self.url_module.StrmUrlGetter()
        base = "https://mp.example/base/api/v1/plugin/P115StrmHelper/redirect_url"
        self.assertEqual(
            getter.get_strm_url("pickcode", "a b.mkv", "/a b.mkv"),
            f"{base}?pickcode=pickcode&file_name=a%20b.mkv",
        )
        self.assertEqual(
            getter.get_share_strm_url("share", "code", "123", "a.mkv", "/a.mkv"),
            f"{base}?share_code=share&receive_code=code&id=123&file_name=a.mkv",
        )

    def test_valid_address_keeps_custom_template(self) -> None:
        """
        配置地址后保留分享链接自定义模板
        """
        self.config.moviepilot_address = "https://mp.example/"
        self.config.strm_url_template_enabled = True
        self.config.strm_url_template = "{{ base_url }}?id={{ file_id }}"
        getter = self.url_module.StrmUrlGetter()
        self.assertEqual(
            getter.get_share_strm_url("share", "code", "123", "a.mkv", "/a.mkv"),
            "https://mp.example/api/v1/plugin/P115StrmHelper/redirect_url?id=123",
        )
