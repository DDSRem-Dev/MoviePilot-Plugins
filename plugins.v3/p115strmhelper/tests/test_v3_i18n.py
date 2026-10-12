import importlib
import json
import sys
from base64 import b64decode
from pathlib import Path
from shutil import copy2
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest import TestCase


class TestV3I18N(TestCase):
    """
    验证原语言加载在 V3 安装目录与分身模块中继续兼容
    """

    def setUp(self) -> None:
        """
        按 V3 宿主安装目录加载原语言模块，仅替换配置
        """
        self.source_root = Path(__file__).resolve().parents[1]
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.host_root = Path(temporary.name).resolve()
        self.root = self.host_root / "app/plugins/p115strmhelper"
        (self.root / "core").mkdir(parents=True)
        self.locales = self.root / "locales"
        self.locales.mkdir()
        copy2(self.source_root / "core/i18n.py", self.root / "core/i18n.py")
        self.prefix = "_p115_i18n_test"
        originals = {
            name: value
            for name, value in sys.modules.items()
            if name == "app" or name.startswith(("app.", self.prefix))
        }
        for name in originals:
            sys.modules.pop(name)

        def cleanup() -> None:
            for name in list(sys.modules):
                if name == "app" or name.startswith(("app.", self.prefix)):
                    sys.modules.pop(name)
            sys.modules.update(originals)

        self.addCleanup(cleanup)
        replacements = {}
        for name in ("app", "app.sdk"):
            value = ModuleType(name)
            value.__path__ = []
            replacements[name] = value
        value = ModuleType("app.sdk.config")
        value.settings = SimpleNamespace(ROOT_PATH=self.host_root)
        replacements[value.__name__] = value
        sys.modules.update(replacements)
        self._write("zh_CN", {"greeting": "你好，{name}", "fallback": "默认"})
        self._write("zh_TW", {"greeting": "您好，{name}"})
        self.module, self.config = self._load("a", "zh_TW")
        self.i18n = self.module.i18n

    def _load(self, suffix: str, language: str) -> Any:
        prefix = self.prefix + suffix
        for name, path in ((prefix, self.root), (prefix + ".core", self.root / "core")):
            package = ModuleType(name)
            package.__path__ = [str(path)]
            sys.modules[name] = package
        config = SimpleNamespace(language=language)
        config.get_config = lambda key: getattr(config, key)
        config_module = ModuleType(prefix + ".core.config")
        config_module.configer = config
        sys.modules[config_module.__name__] = config_module
        return importlib.import_module(prefix + ".core.i18n"), config

    def _write(self, language: str, data: Any) -> None:
        (self.locales / f"{language}.json").write_text(
            json.dumps(data), encoding="utf-8"
        )

    def test_host_installation_path_loads_selected_language_and_default_fallback(
        self,
    ) -> None:
        """
        V3 原安装目录可按既有方式加载语言及默认回退
        """
        self.i18n.load_translations()
        self.assertEqual(
            self.i18n.translate("greeting", name="MoviePilot"), "您好，MoviePilot"
        )
        self.assertEqual(self.i18n.translate("fallback"), "默认")
        self.assertEqual(self.i18n.translate("missing", default="回退"), "回退")
        self.assertEqual(self.i18n.translate("missing"), "missing")

    def test_two_module_instances_share_resources_without_sharing_selected_language(
        self,
    ) -> None:
        """
        同一源码的两个实例可以选择不同语言，重载互不覆盖
        """
        second, config = self._load("b", "zh_CN")
        self.i18n.load_translations()
        second.i18n.load_translations()
        self.assertEqual(self.i18n.translate("greeting", name="A"), "您好，A")
        self.assertEqual(second.i18n.translate("greeting", name="B"), "你好，B")
        config.language = "missing"
        second.i18n.load_translations()
        self.assertEqual(self.i18n.translate("greeting", name="A"), "您好，A")

    def test_all_bundled_locales_preserve_text_keys_and_valid_suffix_encoding(
        self,
    ) -> None:
        """
        逐一校验六种实际语言包的文本覆盖及尾句编码
        """
        bundled = self.source_root / "locales"
        defaults = json.loads((bundled / "zh_CN.json").read_text())
        files = list(bundled.glob("*.json"))
        self.assertEqual(len(files), 6)
        for path in files:
            with self.subTest(language=path.stem):
                data = json.loads(path.read_text())
                self.assertTrue(defaults.keys() <= data.keys())
                for key in defaults:
                    self.assertIsInstance(data[key], str)
                for suffix in data.get("fuck", []):
                    self.assertTrue(b64decode(suffix, validate=True).decode("utf-8"))
