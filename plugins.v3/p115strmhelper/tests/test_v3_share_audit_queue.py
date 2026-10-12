import ast
import importlib
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock

from test_share_audit_download_queue import _Downloader, _load_queue_module


class TestV3ShareAuditQueue(TestCase):
    """
    验证原有分享审核队列与 V3 公开整理入口的调用兼容性
    """

    def setUp(self) -> None:
        """
        创建独立队列并隔离云端和通知发送
        """
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.module = _load_queue_module()
        self.module.configer.PLUGIN_CONFIG_PATH = self.root
        self.queue = self.module.ShareAuditDownloadQueue()
        self.addCleanup(self.queue.stop)
        self.queue._share_state_limiter = MagicMock()
        self.downloader = _Downloader(state=1)
        self.queue.bind_downloader(self.downloader)

    def test_actual_host_transfer_entry_and_file_schema(self) -> None:
        """
        真实 V3 入口接受原有文件字段并保留默认后台提交方式
        """
        root = Path(__file__).resolve().parents[1]
        host = Path(os.environ.get("MOVIEPILOT_SOURCE", root.parents[2] / "MoviePilot"))
        workflow = host / "app/chain/transfer/workflow.py"
        if not workflow.exists():
            self.skipTest("需要 MOVIEPILOT_SOURCE 指向 V3 主程序")
        originals = {
            name: value
            for name, value in sys.modules.items()
            if name == "app" or name.startswith("app.")
        }
        for name in originals:
            sys.modules.pop(name)

        def restore() -> None:
            for name in list(sys.modules):
                if name == "app" or name.startswith("app."):
                    sys.modules.pop(name)
            sys.modules.update(originals)

        self.addCleanup(restore)
        for name in ("app", "app.schemas"):
            package = ModuleType(name)
            package.__path__ = [str(host.joinpath(*name.split(".")))]
            sys.modules[name] = package
        self.module.FileItem = importlib.import_module("app.schemas.file").FileItem
        source = ast.parse(workflow.read_text())
        owner = next(
            node
            for node in source.body
            if isinstance(node, ast.ClassDef) and node.name == "TransferWorkflowOwner"
        )
        method = next(
            node
            for node in owner.body
            if isinstance(node, ast.FunctionDef) and node.name == "do_transfer"
        )
        code = ast.Module(
            body=[
                ast.ImportFrom(
                    module="__future__", names=[ast.alias(name="annotations")], level=0
                ),
                method,
            ],
            type_ignores=[],
        )
        namespace = {}
        exec(compile(ast.fix_missing_locations(code), str(workflow), "exec"), namespace)
        chain = SimpleNamespace(_run_transfer_workflow=MagicMock())
        chain.do_transfer = namespace["do_transfer"].__get__(chain)
        self.module.TransferChain = MagicMock(return_value=chain)
        path = self.root / "subtitle.srt"
        path.write_bytes(b"x" * 2048)
        chain._run_transfer_workflow.return_value = (True, "")
        self.assertTrue(self.queue.transfer_local_file(path))
        call = chain._run_transfer_workflow.call_args.kwargs
        self.assertIs(call["background"], True)
        self.assertIsInstance(call["fileitem"], self.module.FileItem)
        self.assertEqual(call["fileitem"].path, path.as_posix())
        self.assertEqual(call["fileitem"].size, 2048)
        chain._run_transfer_workflow.side_effect = RuntimeError("host failure")
        self.assertFalse(self.queue.transfer_local_file(path))
