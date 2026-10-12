import importlib
import importlib.util
import unittest
from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import patch


def check_original_life_contracts(instance: Any, check: unittest.TestCase) -> None:
    """
    在已加载的真实 V3 实例上执行原生活事件路径和等待回归

    :param instance (Any): 已加载的插件实例
    :param check (TestCase): 宿主集成测试断言对象
    """
    prefix = type(instance).__module__
    tests = Path(__file__).resolve().parents[1]
    for name, target, loader in (
        ("test_life_path_sync", "helper.life.client", "_load_life_module"),
        (
            "test_life_transfer_wait",
            "helper.life.transfer_wait",
            "_load_transfer_wait_module",
        ),
    ):
        module = importlib.import_module(f"{prefix}.{target}")
        spec = importlib.util.spec_from_file_location(
            f"{prefix}.tests.{name}", tests / f"{name}.py"
        )
        check.assertIsNotNone(spec)
        check.assertIsNotNone(spec.loader)
        test = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(test)
        with patch.object(test, loader, return_value=module):
            suite = unittest.defaultTestLoader.loadTestsFromModule(test)
            output = StringIO()
            result = unittest.TextTestRunner(stream=output, verbosity=2).run(suite)
        check.assertEqual(result.testsRun, 3, output.getvalue())
        check.assertTrue(result.wasSuccessful(), output.getvalue())
        check.assertEqual(result.skipped, [], output.getvalue())
        print(f"{type(instance).__name__}: {name}: {result.testsRun} passed")
