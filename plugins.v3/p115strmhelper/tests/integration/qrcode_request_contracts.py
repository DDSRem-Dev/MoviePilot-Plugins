import asyncio
import importlib
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import patch

import httpx
from fastapi import FastAPI


def check_qrcode_request_contracts(instance: Any, check: Any) -> int:
    """
    验证扫码后尚未保存配置时的账号、目录和同步 STRM 请求

    :param instance (Any): 隔离的宿主插件实例
    :param check (Any): 测试断言对象

    :return int: 已验证的后续业务请求数
    """
    prefix = type(instance).__module__
    module = importlib.import_module(prefix + ".api")
    helper = importlib.import_module(prefix + ".helper.strm.api")
    service = module.servicer
    saved = dict(instance.get_config())
    cases = 0
    try:
        for enabled in (True, False):
            instance.init_plugin(dict(saved, enabled=enabled))
            endpoint = instance.api
            old_client = service.client
            with TemporaryDirectory() as temporary, ExitStack() as stack:
                root = Path(temporary).resolve()
                files, paths, cleanup, scratch = (
                    root / name for name in ("files", "paths", "cleanup", "scratch")
                )
                for directory in (files, paths, cleanup, scratch):
                    directory.mkdir()
                valid = cleanup / "directory.strm"
                orphan = cleanup / "orphan.strm"
                valid.write_text("keep")
                orphan.write_text("remove")
                for name, value in {
                    "PLUGIN_TEMP_PATH": scratch,
                    "user_rmt_mediaext": "mkv,mp4",
                    "user_download_mediaext": "srt,nfo",
                    "api_strm_scrape_metadata_enabled": False,
                    "api_strm_media_server_refresh_enabled": False,
                    "moviepilot_address": "https://moviepilot.invalid/",
                    "strm_url_encode": True,
                    "strm_url_format": "pickname",
                    "strm_url_template_enabled": False,
                    "fuse_strm_takeover_enabled": False,
                }.items():
                    stack.enter_context(patch.object(helper.configer, name, value))
                stack.enter_context(
                    patch.object(
                        helper.StrmGenerater, "_filename_template_resolver", False
                    )
                )
                open_factory = stack.enter_context(
                    patch.object(helper, "U115OpenHelper")
                )
                stack.enter_context(patch.object(helper, "sleep"))
                stack.enter_context(
                    patch.object(
                        module.P115Client,
                        "login_qrcode_scan_status",
                        return_value={"state": True, "data": {"status": 2}},
                    )
                )
                stack.enter_context(
                    patch.object(
                        module.P115Client,
                        "login_qrcode_scan_result",
                        return_value={
                            "state": True,
                            "data": {
                                "cookie": {
                                    "UID": "2_A1",
                                    "CID": "synthetic",
                                    "SEID": "synthetic",
                                }
                            },
                        },
                    )
                )

                def resolve(client: Any, *args: Any, **kwargs: Any) -> int:
                    check.assertIs(client, endpoint._client)
                    return 42

                def directories(client: Any, *args: Any, **kwargs: Any) -> Any:
                    check.assertIs(client, endpoint._client)
                    return iter(
                        [{"data": [{"cid": "53", "pid": "42", "n": "new-account-dir"}]}]
                    )

                def listing(client: Any, *args: Any, **kwargs: Any) -> Any:
                    check.assertIs(client, endpoint._client)
                    return iter(
                        [
                            {
                                "id": 43,
                                "pickcode": "isolated43",
                                "name": "directory.mkv",
                                "sha1": "ABC",
                                "size": 123,
                                "path": "/cloud/directory.mkv",
                            }
                        ]
                    )

                stack.enter_context(
                    patch.object(module, "get_pid_by_path", side_effect=resolve)
                )
                stack.enter_context(
                    patch.object(module, "fs_files_iter", side_effect=directories)
                )
                stack.enter_context(
                    patch.object(helper, "get_pid_by_path", side_effect=resolve)
                )
                stack.enter_context(
                    patch.object(helper, "iter_files_skim", side_effect=listing)
                )
                app = FastAPI()
                for path, name, method in (
                    ("/check_qrcode", "check_qrcode_api", "GET"),
                    ("/account", "get_user_storage_status", "GET"),
                    ("/browse", "browse_dir_api", "GET"),
                    ("/files", "api_strm_sync_creata", "POST"),
                    ("/paths", "api_strm_sync_create_by_path", "POST"),
                    ("/remove", "api_strm_sync_remove", "POST"),
                ):
                    app.add_api_route(path, getattr(endpoint, name), methods=[method])
                payloads = {
                    "/files": {
                        "data": [
                            {
                                "id": 42,
                                "pick_code": "isolated42",
                                "sha1": "ABC",
                                "size": 123,
                                "pan_path": "/cloud/movie.mkv",
                                "pan_media_path": "/cloud",
                                "local_path": str(files),
                            }
                        ]
                    },
                    "/paths": {
                        "data": [{"pan_media_path": "/cloud", "local_path": str(paths)}]
                    },
                    "/remove": {
                        "data": [
                            {"pan_media_path": "/cloud", "local_path": str(cleanup)}
                        ]
                    },
                }

                async def exercise() -> int:
                    completed = 0
                    async with httpx.AsyncClient(
                        transport=httpx.ASGITransport(
                            app=app, raise_app_exceptions=False
                        ),
                        base_url="https://isolated.invalid",
                    ) as client:
                        response = await client.get(
                            "/check_qrcode",
                            params={
                                "uid": "isolated",
                                "time": "1",
                                "sign": "synthetic",
                                "client_type": "alipaymini",
                            },
                        )
                        check.assertEqual(response.status_code, 200, response.text)
                        check.assertEqual(response.json()["data"]["status"], "success")
                        check.assertIn("UID=2_A1", instance.get_config()["cookies"])
                        check.assertIs(service.client, old_client)
                        check.assertIsNot(endpoint._client, service.client)
                        info = stack.enter_context(
                            patch.object(
                                endpoint._client,
                                "user_my_info",
                                return_value={
                                    "state": True,
                                    "data": {"uname": "new-account"},
                                },
                            )
                        )
                        stack.enter_context(
                            patch.object(
                                endpoint._client,
                                "fs_index_info",
                                return_value={
                                    "state": True,
                                    "data": {"space_info": {}},
                                },
                            )
                        )
                        response = await client.get("/account")
                        check.assertEqual(response.status_code, 200, response.text)
                        check.assertTrue(response.json()["success"], response.text)
                        check.assertEqual(
                            response.json()["user_info"]["name"], "new-account"
                        )
                        info.assert_called_once()
                        completed += 1
                        response = await client.get(
                            "/browse", params={"path": "/review", "is_local": False}
                        )
                        check.assertEqual(response.status_code, 200, response.text)
                        check.assertEqual(response.json()["code"], 0, response.text)
                        check.assertEqual(
                            response.json()["data"]["items"][0]["name"],
                            "new-account-dir",
                        )
                        completed += 1
                        for route, payload in payloads.items():
                            response = await client.post(route, json=payload)
                            check.assertEqual(response.status_code, 200, response.text)
                            check.assertEqual(
                                response.json()["code"], 10200, response.text
                            )
                            field = (
                                "remove_strm_count"
                                if route == "/remove"
                                else "success_count"
                            )
                            check.assertEqual(response.json()["data"][field], 1)
                            completed += 1
                    return completed

                cases += asyncio.run(exercise())
                for generated in (files / "movie.strm", paths / "directory.strm"):
                    check.assertTrue(
                        generated.read_text().startswith("https://moviepilot.invalid/")
                    )
                check.assertEqual(valid.read_text(), "keep")
                check.assertFalse(orphan.exists())
                open_factory.return_value.get_item_info.assert_not_called()
    finally:
        instance.init_plugin(saved)
        check.assertTrue(instance.stop_service())
        check.assertEqual(instance.get_config(), saved)
    return cases
