import asyncio
import importlib
from contextlib import ExitStack
from inspect import signature
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

import httpx
from fastapi import FastAPI


def check_strm_api_contracts(instance: Any, check: Any) -> None:
    """
    在真实宿主中验证同步 STRM API 的模型、文件生成和临时目录清理

    :param instance (Any): 已启用的隔离插件实例
    :param check (Any): 测试断言对象
    """
    prefix = type(instance).__module__
    helper = importlib.import_module(prefix + ".helper.strm.api")
    schemas = importlib.import_module(prefix + ".schemas.strm_api")
    service = importlib.import_module(prefix + ".service").servicer
    configer = helper.configer
    with TemporaryDirectory() as directory, ExitStack() as stack:
        root = Path(directory).resolve()
        local = root / "direct"
        local.mkdir()
        by_path = root / "by-path"
        scratch = root / "scratch"
        scratch.mkdir()
        stack.enter_context(
            patch.dict(
                service.client.__dict__, pickcode_stable_point="aaaaaaaaaaaaaaaaa"
            )
        )
        for name, value in {
            "PLUGIN_TEMP_PATH": scratch,
            "user_rmt_mediaext": "mkv,mp4",
            "user_download_mediaext": "srt,nfo",
            "api_strm_config": [
                schemas.StrmApiConfig(local_path=str(local), pan_path="/cloud")
            ],
            "api_strm_scrape_metadata_enabled": False,
            "api_strm_media_server_refresh_enabled": False,
            "moviepilot_address": "https://moviepilot.invalid/",
            "strm_url_encode": True,
            "strm_url_format": "pickname",
            "strm_url_template_enabled": False,
            "fuse_strm_takeover_enabled": False,
        }.items():
            stack.enter_context(patch.object(configer, name, value))
        stack.enter_context(
            patch.object(helper.StrmGenerater, "_filename_template_resolver", False)
        )
        open_helper = helper.U115OpenHelper.__new__(helper.U115OpenHelper)
        open_helper._request_api = MagicMock(
            return_value={
                "file_id": 42,
                "pick_code": "isolated42",
                "file_name": "resolved.mkv",
                "sha1": "ABC",
                "size_byte": 123,
                "paths": [{"file_name": "root"}, {"file_name": "cloud"}],
            }
        )
        stack.enter_context(
            patch.object(helper, "U115OpenHelper", return_value=open_helper)
        )
        stack.enter_context(patch.object(helper, "sleep"))
        scrape = stack.enter_context(patch.object(helper, "media_scrape_metadata"))
        refresh = stack.enter_context(patch.object(helper, "MediaServerRefresh"))
        download = stack.enter_context(
            patch.object(
                service.mediainfodownloader,
                "batch_auto_downloader",
                autospec=True,
                return_value=(1, 0, []),
            )
        )
        iterator = helper.iter_files_skim

        def listing(*args, **kwargs):
            signature(iterator).bind(*args, **kwargs)
            check.assertIs(args[0], service.client)
            check.assertTrue(kwargs["with_path"])
            check.assertTrue(kwargs["with_ancestors"])
            return iter(
                [
                    dict(
                        id=43,
                        pickcode="isolated43",
                        name="directory.mkv",
                        sha1="ABC",
                        size=123,
                        path="/cloud/directory.mkv",
                    )
                ]
            )

        iterator_mock = stack.enter_context(
            patch.object(helper, "iter_files_skim", side_effect=listing)
        )
        resolver = stack.enter_context(
            patch.object(helper, "get_pid_by_path", return_value=9)
        )
        app = FastAPI()
        for path, endpoint in (
            ("/files", instance.api.api_strm_sync_creata),
            ("/paths", instance.api.api_strm_sync_create_by_path),
            ("/remove", instance.api.api_strm_sync_remove),
        ):
            app.add_api_route(path, endpoint, methods=["POST"])

        async def exercise() -> None:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://isolated"
            ) as client:

                async def request(path, payload):
                    response = await client.post(path, json=payload)
                    check.assertEqual(response.status_code, 200, response.text)
                    return response.json()

                for path in ("/files", "/paths", "/remove"):
                    check.assertEqual((await request(path, {}))["code"], 10400)
                invalid = await client.post(
                    "/files", json={"data": [{"id": "invalid"}]}
                )
                check.assertEqual(invalid.status_code, 422)
                common = dict(id=42, pick_code="isolated42", sha1="ABC", size=123)
                result = await request(
                    "/files",
                    {
                        "data": [
                            dict(
                                common,
                                pan_path="/cloud/电影.mkv",
                                scrape_metadata=True,
                                media_server_refresh=True,
                            ),
                            {},
                            dict(common, pan_path="/cloud/ignored.txt"),
                            dict(
                                common,
                                pan_path="/cloud/subtitle.srt",
                                auto_download_mediainfo=True,
                            ),
                        ]
                    },
                )
                check.assertEqual(result["code"], 10200)
                check.assertEqual(result["data"]["success_count"], 1)
                check.assertEqual(result["data"]["fail_count"], 2)
                check.assertEqual(result["data"]["download_success_count"], 1)
                check.assertEqual(
                    [item["code"] for item in result["data"]["fail"]], [10422, 10600]
                )
                url = urlsplit((local / "电影.strm").read_text())
                check.assertEqual(
                    url.path, "/api/v1/plugin/P115StrmHelper/redirect_url"
                )
                check.assertEqual(
                    parse_qs(url.query),
                    {"pickcode": ["isolated42"], "file_name": ["电影.mkv"]},
                )
                scrape.assert_called_once_with((local / "电影.strm").as_posix())
                refresh.return_value.refresh_mediaserver.assert_called_once_with(
                    file_path=(local / "电影.strm").as_posix(), file_name="电影.strm"
                )
                check.assertEqual(
                    download.call_args.kwargs["downloads_list"],
                    [
                        {
                            "type": "local",
                            "pickcode": "isolated42",
                            "path": (local / "subtitle.srt").as_posix(),
                            "sha1": "ABC",
                        }
                    ],
                )
                resolved = await request(
                    "/files", {"data": [{"pan_path": "/cloud/resolved.mkv"}]}
                )
                check.assertEqual(resolved["data"]["success_count"], 1)
                check.assertTrue((local / "resolved.strm").exists())
                open_helper._request_api.assert_called_once_with(
                    "POST",
                    "/open/folder/get_info",
                    "data",
                    data={"path": "/cloud/resolved.mkv"},
                )
                by_id = await request("/files", {"data": [{"id": 42}]})
                check.assertEqual(by_id["data"]["success_count"], 1)
                open_helper._request_api.assert_called_with(
                    "GET", "/open/folder/get_info", "data", params={"file_id": 42}
                )
                by_pickcode = await request(
                    "/files",
                    {
                        "data": [
                            {
                                "pick_code": service.client.to_pickcode(42),
                                "pan_path": "/cloud/pickcode.mkv",
                                "sha1": "ABC",
                                "size": 123,
                            }
                        ]
                    },
                )
                check.assertEqual(by_pickcode["data"]["success"][0]["id"], 42)
                check.assertEqual(open_helper._request_api.call_count, 2)
                result = await request(
                    "/paths",
                    {
                        "data": [
                            {
                                "pan_media_path": "/cloud",
                                "local_path": str(by_path),
                                "remove_strm_uuid": True,
                            }
                        ]
                    },
                )
                check.assertEqual(result["data"]["success_count"], 1)
                cached_uuid = result["data"]["paths_info"][0]["remove_strm_uuid"]
                check.assertTrue((scratch / f"{cached_uuid}_pan_tree.txt").exists())
                for use_cache in (True, False):
                    orphan = by_path / "orphan.strm"
                    orphan.write_text("isolated")
                    item = dict(local_path=str(by_path), pan_media_path="/cloud")
                    if use_cache:
                        item["remove_strm_uuid"] = cached_uuid
                    removed = await request("/remove", {"data": [item]})
                    check.assertEqual(removed["data"]["remove_strm_count"], 1)
                    check.assertFalse(orphan.exists())
                    check.assertTrue((by_path / "directory.strm").exists())
                check.assertEqual(iterator_mock.call_count, 2)
                resolver.assert_called_with(
                    service.client, "/cloud", True, False, False
                )
                check.assertEqual(service._sync_operations, {})

        asyncio.run(exercise())
