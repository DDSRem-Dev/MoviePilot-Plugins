import importlib
import importlib.util
import sys
import unittest
from contextlib import ExitStack
from io import StringIO
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import patch


def check_original_utility_contracts(instance: Any, check: unittest.TestCase) -> None:
    """
    将原工具测试的短模块路径绑定到真实 V3 实例并隔离测试替身

    :param instance (Any): 已加载的插件实例
    :param check (TestCase): 宿主集成测试断言对象
    """
    prefix = type(instance).__module__
    tests = Path(__file__).resolve().parents[1]
    cases = {
        "test_cache": "core.cache",
        "test_cron_utils": "utils.cron",
        "test_exception_utils": "utils.exception",
        "test_limiter": "utils.limiter",
        "test_path_utils": "utils.path",
        "test_time_utils": "utils.time",
        "test_url_utils": "utils.url",
        "test_tree": "utils.tree",
        "test_webhook_utils": "utils.webhook",
    }
    for name, target in cases.items():
        module = importlib.import_module(f"{prefix}.{target}")
        parent, child = target.split(".")
        package = ModuleType(parent)
        package.__path__ = []
        setattr(package, child, module)
        aliases = {parent: package, target: module}
        originals = {key: sys.modules.get(key) for key in (*aliases, "version")}
        try:
            sys.modules.update(aliases)
            with ExitStack() as stack:
                if name == "test_tree":
                    stack.enter_context(patch.object(module, "RedisHelper"))
                spec = importlib.util.spec_from_file_location(
                    f"{prefix}.tests.{name}", tests / f"{name}.py"
                )
                check.assertIsNotNone(spec)
                check.assertIsNotNone(spec.loader)
                test = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(test)
                suite = unittest.defaultTestLoader.loadTestsFromModule(test)
                output = StringIO()
                result = unittest.TextTestRunner(stream=output, verbosity=2).run(suite)
                check.assertGreater(result.testsRun, 0, name)
                check.assertTrue(result.wasSuccessful(), output.getvalue())
                check.assertEqual(result.skipped, [], output.getvalue())
                print(f"{type(instance).__name__}: {name}: {result.testsRun} passed")
        finally:
            for key, original in originals.items():
                if original is None:
                    sys.modules.pop(key, None)
                else:
                    sys.modules[key] = original
        for key, original in originals.items():
            check.assertIs(sys.modules.get(key), original, key)
