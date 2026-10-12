import asyncio
import importlib
from contextlib import ExitStack
from time import time
from typing import Any
from unittest.mock import patch

import httpx
from fastapi import FastAPI


def check_life_diagnostic_contracts(instance: Any, check: Any) -> None:
    """
    验证启用和禁用状态的诊断 HTTP 模型及 SDK 工具调用

    :param instance (Any): 隔离插件实例
    :param check (Any): 测试断言对象
    """
    api = importlib.import_module(type(instance).__module__ + ".api")
    service = api.servicer
    client = service.client
    stopping = service._sync_stopping
    enabled = instance.get_state()
    route = next(route for route in instance.get_api() if route["path"] == "/check_life_event_status")
    app = FastAPI()
    app.add_api_route(route["path"], route["endpoint"], methods=route["methods"])
    protocol_calls = []

    def account(**kwargs):
        return {"state": True, "data": {"uname": type(instance).__name__}}

    def calendar(**kwargs):
        check.assertEqual(kwargs["timeout"], 10)
        check.assertFalse(kwargs["async_"])
        protocol_calls.append("calendar")
        return {"state": True}

    def behavior(payload, **kwargs):
        check.assertFalse(kwargs["async_"])
        check.assertEqual(payload["offset"], 0)
        protocol_calls.append("behavior")
        return {"state": True, "data": {"count": 1, "list": [{
            "id": "42", "file_id": "42", "type": 1,
            "update_time": int(time()) + 60, "file_name": "synthetic.mkv", "pick_code": "isolated",
        }]}}

    async def request(payload=None):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://isolated.invalid"
        ) as transport:
            response = await transport.post(route["path"], json=payload)
            check.assertEqual(response.status_code, 200)
            return response.json()

    if client is None:
        for payload in (None, {"start_time": 123}):
            result = asyncio.run(request(payload))
            check.assertEqual(result["code"], 1)
            check.assertIn("115客户端未初始化", result["data"]["error_messages"])
            check.assertIn("MonitorLife实例不存在", result["data"]["error_messages"])
            check.assertEqual(result["data"]["summary"], {
                "plugin_enabled": enabled, "client_initialized": False,
                "monitorlife_initialized": False, "thread_running": False, "config_valid": False,
            })
            check.assertEqual(service._sync_stopping, stopping)
        return

    with ExitStack() as stack:
        stack.enter_context(patch.object(client, "user_my_info", autospec=True, side_effect=account))
        stack.enter_context(patch.object(client, "life_calendar_setoption", autospec=True, side_effect=calendar))
        for method in ("life_behavior_detail", "life_behavior_detail_app"):
            stack.enter_context(patch.object(client, method, autospec=True, side_effect=behavior))
        for payload in (None, {"start_time": 123}):
            result = asyncio.run(request(payload))
            check.assertEqual(result["code"], 0, result["data"]["debug_info"])
            check.assertTrue(result["data"]["success"])
            check.assertEqual(result["data"]["error_messages"], [])
            check.assertIn(type(instance).__name__, result["data"]["debug_info"])
            check.assertEqual(result["data"]["summary"], {
                "plugin_enabled": enabled, "client_initialized": True,
                "monitorlife_initialized": True, "thread_running": False, "config_valid": False,
            })
            if payload:
                check.assertIn("synthetic.mkv", result["data"]["debug_info"])
                check.assertIn("1970-01-01 00:02:03 UTC", result["data"]["debug_info"])
        check.assertEqual(protocol_calls, ["calendar", "behavior", "calendar", "behavior", "behavior"])
        check.assertEqual(service._sync_stopping, stopping)
