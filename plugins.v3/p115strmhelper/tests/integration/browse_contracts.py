import asyncio
import importlib
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Dict
from unittest.mock import patch

import httpx
from fastapi import FastAPI


def check_browse_contracts(instance: Any, check: Any) -> Dict[str, Any]:
    """
    验证目录与账号 HTTP 模型、真实 SDK 转换及禁用查询

    :param instance (Any): 已启用的隔离插件实例
    :param check (Any): 测试断言对象

    :return Dict: 前端契约验证使用的实际响应
    """
    api = importlib.import_module(type(instance).__module__ + ".api")
    service = api.servicer
    client = service.client
    app = FastAPI()
    paths = ("/user_storage_status", "/browse_dir")
    for route in instance.get_api():
        if route["path"] in paths:
            app.add_api_route(
                route["path"], route["endpoint"], methods=route["methods"]
            )
    records = {}

    def account(**kwargs):
        return {
            "state": True,
            "data": {
                "uname": type(instance).__name__,
                "vip": {"is_vip": True, "is_forever": True},
                "face": {"face_s": "https://isolated.invalid/avatar.png"},
            },
        }

    def space(payload, **kwargs):
        check.assertEqual(payload, 0)
        return {
            "state": True,
            "data": {
                "space_info": {
                    "all_total": {"size_format": "10 TB"},
                    "all_use": {"size_format": "2 TB"},
                    "all_remain": {"size_format": "8 TB"},
                }
            },
        }

    def listing(payload, **kwargs):
        check.assertEqual(payload["cid"], 42)
        check.assertEqual(payload["offset"], 0)
        check.assertFalse(kwargs["async_"])
        return {
            "state": True,
            "cid": 42,
            "offset": 0,
            "count": 3,
            "data": [
                {"cid": "52", "pid": "42", "n": "目录10"},
                {"cid": "53", "pid": "42", "n": "目录2"},
                {"fid": "54", "cid": "42", "n": "file.mkv", "s": "123"},
            ],
        }

    async def request(path, params=None, target=app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=target),
            base_url="https://isolated.invalid",
        ) as transport:
            response = await transport.get(path, params=params)
            check.assertEqual(response.status_code, 200)
            return response.json()

    with ExitStack() as stack:
        info = stack.enter_context(
            patch.object(client, "user_my_info", autospec=True, side_effect=account)
        )
        capacity = stack.enter_context(
            patch.object(client, "fs_index_info", autospec=True, side_effect=space)
        )
        resolve = stack.enter_context(
            patch.object(
                client,
                "fs_dir_getid",
                autospec=True,
                return_value={"state": True, "id": 42},
            )
        )
        files = stack.enter_context(
            patch.object(client, "fs_files", autospec=True, side_effect=listing)
        )
        params = {"path": "/媒体 库", "is_local": False}
        records["status"] = asyncio.run(request(paths[0]))
        check.assertTrue(records["status"]["success"])
        check.assertEqual(
            records["status"]["user_info"]["name"], type(instance).__name__
        )
        check.assertEqual(records["status"]["user_info"]["vip_expire_date"], "永久")
        check.assertEqual(
            records["status"]["storage_info"],
            {
                "total": "10 TB",
                "used": "2 TB",
                "remaining": "8 TB",
            },
        )
        check.assertEqual(asyncio.run(request(paths[0])), records["status"])
        check.assertEqual(info.call_count, 1)
        check.assertEqual(capacity.call_count, 1)
        records["cloud"] = asyncio.run(request(paths[1], params))
        check.assertEqual(records["cloud"]["code"], 0, records["cloud"])
        check.assertEqual(
            records["cloud"]["data"],
            {
                "path": params["path"],
                "items": [
                    {"name": "目录10", "path": "/媒体 库/目录10", "is_dir": True},
                    {"name": "目录2", "path": "/媒体 库/目录2", "is_dir": True},
                ],
            },
        )
        instance.api.browse_dir_pan_api_last = 0
        check.assertEqual(asyncio.run(request(paths[1], params)), records["cloud"])
        check.assertEqual(files.call_count, 1)
        check.assertEqual(resolve.call_count, 1)
        check.assertEqual(
            api.idpathcacher.get_id_by_dir(directory="/媒体 库/目录2"), 53
        )
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            for name in ("目录10", "目录2"):
                (root / name).mkdir()
            (root / "file.txt").write_text("isolated")
            records["local_plugin"] = asyncio.run(
                request(paths[1], {"path": str(root), "is_local": True})
            )
            check.assertEqual(
                [item["name"] for item in records["local_plugin"]["data"]["items"]],
                ["目录10", "目录2"],
            )

    check.assertTrue(instance.stop_service())
    check_disabled_account_contract(instance, check)
    return records


def check_disabled_account_contract(instance: Any, check: Any) -> None:
    """
    验证停止服务后无绑定客户端的原账号查询回退

    :param instance (Any): 隔离插件实例
    :param check (Any): 测试断言对象
    """
    api = importlib.import_module(type(instance).__module__ + ".api")
    check.assertTrue(api.servicer._sync_stopping)
    endpoint = api.Api(None)
    app = FastAPI()
    app.add_api_route(
        "/user_storage_status", endpoint.get_user_storage_status, methods=["GET"]
    )

    async def request():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://isolated.invalid"
        ) as transport:
            response = await transport.get("/user_storage_status")
            check.assertEqual(response.status_code, 200)
            return response.json()

    with patch.object(api, "P115Client", autospec=True) as factory:
        factory.return_value.user_my_info.return_value = {
            "state": True,
            "data": {"uname": "temporary-account"},
        }
        factory.return_value.fs_index_info.return_value = {
            "state": True,
            "data": {"space_info": {}},
        }
        result = asyncio.run(request())
        if api.configer.get_config("cookies"):
            check.assertTrue(result["success"])
            check.assertEqual(result["user_info"]["name"], "temporary-account")
            factory.assert_called_once_with(api.configer.get_config("cookies"))
        else:
            check.assertFalse(result["success"])
            check.assertIn("Cookies 未配置", result["error_message"])
            factory.assert_not_called()
        check.assertEqual(api.servicer._sync_operations, {})
