import asyncio
import importlib
from typing import Any

import httpx
from fastapi import FastAPI


def check_cleanup_store_contracts(instance: Any, check: Any) -> None:
    """
    验证启用和禁用实例的清理管理路由及真实 KV 读写

    :param instance (Any): 隔离插件实例
    :param check (Any): 测试断言对象
    """
    module = importlib.import_module(type(instance).__module__ + ".api")
    stopping = module.servicer._sync_stopping
    pending = module.share_strm_pending_queue
    missing = module.share_strm_missing_media_store
    summary = module.share_strm_cleanup_summary_store
    endpoints = (
        ("GET", "/share_strm_cleanup_pending", {}),
        (
            "GET", "/share_strm_cleanup_batch_paths",
            {"params": {"request_id": "read-batch", "page": 1, "limit": 50}},
        ),
        (
            "POST", "/share_strm_cleanup_cancel",
            {"json": {"request_id": "cancel-batch"}},
        ),
        ("GET", "/share_strm_cleanup_last_summary", {}),
        ("GET", "/share_strm_missing_media_list", {"params": {"page": 1, "limit": 20}}),
        ("POST", "/share_strm_missing_media_clear", {"json": {"uid": "isolated"}}),
        ("POST", "/share_strm_missing_media_clear", {"json": {"clear_all": True}}),
    )
    app = FastAPI()
    routes = {route["path"]: route for route in instance.get_api()}
    for path in dict.fromkeys(path for _, path, _ in endpoints):
        route = routes[path]
        app.add_api_route(path, route["endpoint"], methods=route["methods"])

    async def request(method: str, path: str, kwargs: Any) -> Any:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://isolated.invalid"
        ) as client:
            response = await client.request(method, path, **kwargs)
            check.assertEqual(response.status_code, 200)
            return response.json()

    try:
        for index, (method, path, kwargs) in enumerate(endpoints):
            pending.replace_single_batch("read-batch", ["/isolated/read.strm"], False, False, False)
            pending.append_batch("cancel-batch", ["/isolated/cancel.strm"], False, False, False)
            missing.replace_all([{"uid": "isolated", "media_source": "bangumi", "media_id": "42"}])
            summary.save({"owner": type(instance).__name__})
            response = asyncio.run(request(method, path, kwargs))
            check.assertEqual(response["code"], 0, response)
            if index == 0:
                check.assertEqual(len(response["data"]["batches"]), 2)
            elif index == 1:
                check.assertEqual(response["data"]["paths"], ["/isolated/read.strm"])
                check.assertEqual(response["data"]["total"], 1)
            elif index == 2:
                check.assertFalse(pending.pending_batch_paths_page("cancel-batch", 1, 50)[0])
                check.assertTrue(pending.pending_batch_paths_page("read-batch", 1, 50)[0])
            elif index == 3:
                check.assertEqual(response["data"]["summary"], {"owner": type(instance).__name__})
            elif index == 4:
                check.assertEqual(response["data"]["items"][0]["media_id"], "42")
                check.assertEqual(response["data"]["total"], 1)
            else:
                check.assertEqual(missing.page(1, 20), ([], 0))
            check.assertEqual(module.servicer._sync_stopping, stopping)
    finally:
        pending.clear_all_batches()
        missing.clear(None, True)
        summary.save({})
