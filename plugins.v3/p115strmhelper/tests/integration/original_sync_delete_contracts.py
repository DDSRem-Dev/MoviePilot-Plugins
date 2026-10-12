import importlib
import importlib.util
import unittest
from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import patch


def check_original_sync_delete_contract(
    instance: Any, check: unittest.TestCase
) -> None:
    """
    将原 ISO 后缀回归绑定到已加载的真实 V3 同步删除模块

    :param instance (Any): 已加载的插件实例
    :param check (TestCase): 宿主集成测试断言对象
    """
    prefix = type(instance).__module__
    module = importlib.import_module(f"{prefix}.helper.mediasyncdel")
    source = Path(__file__).resolve().parents[1] / "test_mediasyncdel.py"
    spec = importlib.util.spec_from_file_location(
        f"{prefix}.tests.test_mediasyncdel", source
    )
    check.assertIsNotNone(spec)
    check.assertIsNotNone(spec.loader)
    test = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(test)
    with patch.object(test, "_load_mediasyncdel_module", return_value=module):
        suite = unittest.defaultTestLoader.loadTestsFromModule(test)
        output = StringIO()
        result = unittest.TextTestRunner(stream=output, verbosity=2).run(suite)
    check.assertGreater(result.testsRun, 0)
    check.assertTrue(result.wasSuccessful(), output.getvalue())
    check.assertEqual(result.skipped, [], output.getvalue())
    print(f"{type(instance).__name__}: test_mediasyncdel: {result.testsRun} passed")
