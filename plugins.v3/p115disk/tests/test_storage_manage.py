"""
P115Disk storage_manage 容量查询回归测试
"""

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict
from unittest import TestCase


def _load_storage_manage() -> Any:
    """
    从插件源码加载 storage_manage 方法，避免测试依赖 MoviePilot 宿主

    :return Any: storage_manage 未绑定方法
    """
    source_path = Path(__file__).resolve().parents[1] / "__init__.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    plugin_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "P115Disk"
    )
    method = next(
        node
        for node in plugin_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "storage_manage"
    )
    module = ast.Module(
        body=[
            ast.parse("from __future__ import annotations").body[0],
            ast.ClassDef(
                name="P115Disk",
                bases=[],
                keywords=[],
                decorator_list=[],
                body=[ast.copy_location(method, method)],
            ),
        ],
        type_ignores=[],
    )
    ast.fix_missing_locations(module)
    namespace: Dict[str, Any] = {}
    exec(compile(module, str(source_path), "exec"), namespace)
    return namespace["P115Disk"].storage_manage


class TestStorageManage(TestCase):
    """
    测试存储容量查询的成功和失败响应
    """

    @classmethod
    def setUpClass(cls) -> None:
        """
        加载待测方法
        """
        cls.storage_manage = staticmethod(_load_storage_manage())

    def test_usage_failure_returns_structured_error(self) -> None:
        """
        usage 返回 None 时不应调用 model_dump 或抛出异常
        """
        api = SimpleNamespace(usage=lambda: None)
        disk = SimpleNamespace(_disk_name="115网盘Plus", _p115_api=api)

        result = self.storage_manage(disk, "115网盘Plus", "usage")

        self.assertEqual(
            result,
            {
                "success": False,
                "message": "无法获取 115 存储容量，请检查 Cookie 是否有效并重新登录",
                "data": None,
            },
        )

    def test_usage_success_serializes_storage_usage(self) -> None:
        """
        usage 返回容量对象时保持原有成功响应
        """
        usage = SimpleNamespace(model_dump=lambda: {"total": 100, "available": 75})
        api = SimpleNamespace(usage=lambda: usage)
        disk = SimpleNamespace(_disk_name="115网盘Plus", _p115_api=api)

        result = self.storage_manage(disk, "115网盘Plus", "usage")

        self.assertEqual(
            result,
            {"success": True, "message": "", "data": {"total": 100, "available": 75}},
        )
