"""增量清理目录条目的回归测试"""

import ast
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch


def _load_cleanup():
    # 仅加载实际清理方法，避免导入网盘客户端及 MoviePilot 运行时
    source = Path(__file__).resolve().parents[1] / "helper/strm/increment.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    helper = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "IncrementSyncStrmHelper"
    )
    method = next(
        node for node in helper.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "__remove_unless_strm_path"
    )
    namespace = {"Path": Path, "logger": Mock(), "PathRemoveUtils": Mock()}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), namespace)
    return namespace[method.name], namespace["PathRemoveUtils"]


class TestIncrementCleanup(TestCase):
    """验证目录不会中断文件清理或被递归删除"""

    def test_directory_is_preserved_and_next_file_is_removed(self) -> None:
        """无论空目录清理开关如何，目录内容均保留且不计入文件删除数"""
        for remove_dirs in (False, True):
            with self.subTest(remove_dirs=remove_dirs), TemporaryDirectory() as root:
                cleanup, related = _load_cleanup()
                helper = SimpleNamespace(
                    remove_unless_dir=remove_dirs,
                    remove_unless_file=True,
                    remove_unless_strm_count=0,
                )
                directory = Path(root) / "changed.strm"
                directory.mkdir()
                child = directory / "keep.txt"
                child.write_text("keep", encoding="utf-8")
                cleanup(helper, str(directory))
                self.assertEqual(child.read_text(encoding="utf-8"), "keep")
                self.assertEqual(helper.remove_unless_strm_count, 0)
                related.clean_related_files.assert_not_called()
                related.remove_parent_dir.assert_not_called()
                stale = Path(root) / "stale.strm"
                stale.write_text("obsolete", encoding="utf-8")
                cleanup(helper, str(stale))
                self.assertFalse(stale.exists())
                self.assertEqual(helper.remove_unless_strm_count, 1)
                related.clean_related_files.assert_called_once()
                self.assertEqual(related.remove_parent_dir.call_count, int(remove_dirs))

    def test_permission_error_is_not_hidden(self) -> None:
        """普通文件删除权限错误仍向调用方传播"""
        cleanup, _ = _load_cleanup()
        helper = SimpleNamespace(remove_unless_strm_count=0)
        with patch.object(Path, "is_dir", return_value=False), patch.object(
            Path, "unlink", side_effect=PermissionError("denied")
        ), self.assertRaises(PermissionError):
            cleanup(helper, "file.strm")
        self.assertEqual(helper.remove_unless_strm_count, 0)
