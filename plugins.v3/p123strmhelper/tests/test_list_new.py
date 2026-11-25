from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any, Dict
from unittest import TestCase
from unittest.mock import Mock, patch

from p123client import P123Client
from p123client.tool import iterdir


def _file(file_id: int, name: str, is_dir: bool = False) -> Dict[str, Any]:
    return {
        "FileId": file_id,
        "FileName": name,
        "Type": int(is_dir),
        "Etag": "test-md5",
        "Size": 1024,
        "S3KeyFlag": "test-key",
    }


def _response(*items: Dict[str, Any], next_id: str = "-1") -> Dict[str, Any]:
    return {"code": 0, "data": {"InfoList": list(items), "Next": next_id}}


class TestP123ListNew(TestCase):
    """
    验证目录列表参数兼容性及真实遍历器的分页和递归行为
    """

    def setUp(self) -> None:
        """
        加载当前版本包装类，以模拟客户端隔离认证和网络请求
        """
        path = Path(__file__).resolve().parents[1] / "tool.py"
        spec = spec_from_file_location("p123strmhelper_tool", path)
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        self.backend = Mock()
        self.backend.request.return_value = _response()
        constructor_patch = patch.object(
            module, "P123Client", return_value=self.backend
        )
        self.constructor = constructor_patch.start()
        self.addCleanup(constructor_patch.stop)
        self.client = module.P123AutoClient("test-account", "test-password")
        self.constructor.assert_not_called()

    def test_directory_id_and_parameter_case(self) -> None:
        """
        整数和字符串目录 ID 均保留接口要求的参数大小写
        """
        for parent_id in (0, 48428736, "48428736"):
            with self.subTest(parent_id=parent_id):
                result = self.client.fs_list_new(parent_id)
                self.assertEqual(result["code"], 0)
                call = self.backend.request.call_args
                self.assertEqual(call.args, ("file/list/new",))
                params = call.kwargs["params"]
                self.assertEqual(params["parentFileId"], parent_id)
                self.assertEqual(params["driveId"], 0)
                self.assertEqual(params["Page"], 1)
                self.assertFalse(params["trashed"])
                self.assertTrue(
                    {
                        "orderBy",
                        "orderDirection",
                        "inDirectSpace",
                        "fileCategory",
                        "OnlyLookAbnormalFile",
                    }.issubset(params)
                )
                for key in ("driveid", "parentfileid", "page", "orderby"):
                    self.assertNotIn(key, params)
        self.constructor.assert_called_once_with(
            passport="test-account", password="test-password"
        )
        self.backend.fs_list_new.assert_not_called()

    def test_payload_overrides_and_request_options(self) -> None:
        """
        保留分页和调用方参数且不修改原始字典，透传请求选项
        """
        payload = {
            "driveId": 1,
            "parentFileId": 42,
            "Page": 3,
            "next": "cursor",
            "limit": 50,
            "orderDirection": "desc",
            "SearchData": "电影",
        }
        original = payload.copy()
        self.client.fs_list_new(
            payload,
            base_url="https://example.invalid/api",
            headers={"platform": "web"},
            timeout=15,
        )
        kwargs = self.backend.request.call_args.kwargs
        self.assertEqual(payload, original)
        self.assertIsNot(kwargs["params"], payload)
        for key, value in original.items():
            self.assertEqual(kwargs["params"][key], value)
        self.assertEqual(kwargs["base_url"], "https://example.invalid/api")
        self.assertEqual(kwargs["headers"], {"platform": "web"})
        self.assertEqual(kwargs["timeout"], 15)
        self.assertFalse(kwargs["async_"])

    def test_recycle_event_and_explicit_trashed(self) -> None:
        """
        回收站事件推导默认标志并尊重调用方显式指定的值
        """
        for payload, event, expected in (
            ({}, "recycleListFile", True),
            ({"trashed": False}, "recycleListFile", False),
            ({"event": "recycleListFile", "trashed": None}, "homeListFile", True),
        ):
            with self.subTest(payload=payload):
                self.client.fs_list_new(payload, event=event)
                self.assertEqual(
                    self.backend.request.call_args.kwargs["params"]["trashed"], expected
                )

    def test_real_iterator_pagination_and_recursion(self) -> None:
        """
        真实遍历器保留网页请求头、翻页游标、子目录路径和原始文件信息
        """
        first = _file(1, "首集.mkv")
        directory = _file(2, "电影", is_dir=True)
        second = _file(3, "续集.mkv")
        nested = _file(4, "正片.mkv")
        self.backend.request.side_effect = [
            _response(first, directory, next_id="cursor"),
            _response(second),
            _response(nested),
        ]
        items = list(
            iterdir(
                client=self.client,
                payload={"parentFileId": 42, "limit": 2},
                max_depth=-1,
                keep_raw=True,
            )
        )
        self.assertEqual(
            [item["relpath"] for item in items],
            ["首集.mkv", "电影", "续集.mkv", "电影/正片.mkv"],
        )
        self.assertEqual(items[-1]["raw"], nested)
        calls = self.backend.request.call_args_list
        self.assertEqual(len(calls), 3)
        self.assertEqual(
            [
                (call.kwargs["params"]["parentFileId"], call.kwargs["params"]["Page"])
                for call in calls
            ],
            [(42, 1), (42, 2), (2, 1)],
        )
        self.assertEqual(calls[1].kwargs["params"]["next"], "cursor")
        self.assertNotIn("next", calls[2].kwargs["params"])
        for call in calls:
            self.assertEqual(call.kwargs["headers"]["platform"], "web")
            self.assertEqual(call.kwargs["params"]["driveId"], 0)

    def test_empty_directory_and_api_error(self) -> None:
        """
        空目录正常结束，接口错误继续向调用方抛出
        """
        self.assertEqual(list(iterdir(self.client, payload=42)), [])
        self.backend.request.return_value = {
            "code": 400,
            "message": "driveId is required",
        }
        with self.assertRaises(OSError):
            list(iterdir(self.client, payload=42))

    def test_token_limit_reconnect(self) -> None:
        """
        Token 超限后重建客户端并使用相同参数重试一次
        """
        self.backend.request.return_value = {
            "code": 401,
            "message": "tokens number has exceeded the limit",
        }
        replacement = Mock()
        replacement.request.return_value = _response(_file(1, "影片.mkv"))
        self.constructor.side_effect = [self.backend, replacement]
        result = self.client.fs_list_new(42)
        self.assertEqual(result["code"], 0)
        self.assertEqual(self.constructor.call_count, 2)
        self.backend.request.assert_called_once()
        replacement.request.assert_called_once_with(
            *self.backend.request.call_args.args,
            **self.backend.request.call_args.kwargs,
        )

    def test_download_info_keeps_upstream_normalization(self) -> None:
        """
        下载接口继续使用依赖自身的小写字段转换
        """
        self.backend.download_info.side_effect = lambda payload: (
            P123Client.download_info(self.backend, payload)
        )
        self.backend.request.return_value = {
            "code": 0,
            "data": {"DownloadUrl": "https://example.invalid/video"},
        }
        payload = {"Etag": "test-md5", "S3KeyFlag": "test-key", "FileID": 1}
        result = self.client.download_info(payload)
        self.assertEqual(result["code"], 0)
        call = self.backend.request.call_args
        self.assertEqual(call.args, ("file/download_info", "POST"))
        self.assertEqual(call.kwargs["json"]["etag"], "test-md5")
        self.assertEqual(call.kwargs["json"]["filename"], "test-md5")
        self.assertIn("Etag", payload)
