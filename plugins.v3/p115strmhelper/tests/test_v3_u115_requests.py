import os
import runpy
from collections import ChainMap
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from types import MethodType, SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock

from httpx import Client, MockTransport, Request, Response

from test_v3_share_queue_lifecycle import _method
from test_v3_worker_queue import _compile


class TestV3U115Requests(TestCase):
    """
    使用真实 V3 存储请求引擎验证插件 Open API 调用
    """

    def setUp(self) -> None:
        """
        加载宿主与插件真实类，隔离配置存储、网络和等待
        """
        self.plugin_root = Path(__file__).resolve().parents[1]
        self.host_root = Path(
            os.environ.get(
                "MOVIEPILOT_SOURCE", self.plugin_root.parents[2] / "MoviePilot"
            )
        )
        host_path = self.host_root / "app/modules/filemanager/storages/u115.py"
        if not host_path.exists():
            self.skipTest("需要 MOVIEPILOT_SOURCE 指向 V3 主程序")
        self.now = 1700000000
        self.delays = []
        self.requests = []
        self.tokens = {
            "access_token": "test-access",
            "refresh_token": "test-refresh",
            "expires_in": 3600,
            "refresh_time": self.now,
        }
        self.responses = []
        self.http = Client(transport=MockTransport(self._respond))
        self.addCleanup(self.http.close)
        self.adapter = SimpleNamespace(
            _headers={},
            _session=SimpleNamespace(request=self._request),
            _cookies=None,
            _proxies=None,
            _timeout=20,
            _verify=True,
        )
        request_namespace = {
            "CORRELATION_ID_HEADER": "X-Correlation-ID",
            "get_correlation_id": lambda: "test-correlation",
        }
        _method(
            self.host_root / "app/runtime/correlation.py",
            "with_correlation_header",
            request_namespace,
        )
        for name in ("request", "update_headers", "post_res"):
            method = _method(
                self.host_root / "app/adapters/network/http.py", name, request_namespace
            )
            setattr(self.adapter, name, MethodType(method, self.adapter))
        singleton = runpy.run_path(str(self.host_root / "app/foundation/singleton.py"))[
            "WeakSingleton"
        ]
        base = type(
            "_StorageBase",
            (),
            {
                "get_conf": lambda owner: self.tokens,
                "set_config": lambda owner, conf: self.tokens.update(conf),
            },
        )
        host_namespace = {
            "StorageBase": base,
            "WeakSingleton": singleton,
            "StorageSchema": SimpleNamespace(U115="u115"),
            "U115_DEFAULT_ACCEPTED_CODES": (0, 20004),
            "U115_GET_INFO_ACCEPTED_CODES": (0, 20004, 430004),
            "Lock": Lock,
            "lock": Lock(),
            "RequestUtils": lambda **kwargs: self.adapter,
            "QpsRateLimiter": MagicMock(side_effect=lambda qps: MagicMock()),
            "RateStats": MagicMock(side_effect=lambda **kwargs: MagicMock()),
            "time": SimpleNamespace(time=lambda: self.now, sleep=self._sleep),
            "logger": MagicMock(),
        }
        no_login = _compile(host_path, host_namespace, "NoCheckInException")
        self.host_class = _compile(host_path, host_namespace, "U115Pan")
        self.host = self.host_class()
        self.plugin_error = type("U115NoCheckInException", (Exception,), {})
        config = MagicMock()
        config.cookies = ""
        namespace = {
            "ChainMap": ChainMap,
            "U115Pan": self.host_class,
            "NoCheckInException": no_login,
            "U115NoCheckInException": self.plugin_error,
            "P115Center": MagicMock(),
            "FileDbHelper": MagicMock(),
            "create_client": MagicMock(),
            "configer": config,
            "logger": MagicMock(),
            "Path": Path,
            "randint": lambda *args: 0,
        }
        self.helper_class = _compile(
            self.plugin_root / "core/u115_open.py", namespace, "U115OpenHelper"
        )
        self.helper = self.helper_class()

    def _sleep(self, seconds: float) -> None:
        self.delays.append(seconds)
        self.now += seconds

    def _respond(self, request: Request) -> Response:
        self.requests.append(request)
        if self.responses:
            return self.responses.pop(0)
        return Response(200, json={"code": 0, "data": {"value": 1}})

    def _request(self, method, url, **kwargs):
        for key in ("proxies", "verify", "stream"):
            kwargs.pop(key, None)
        if "allow_redirects" in kwargs:
            kwargs["follow_redirects"] = kwargs.pop("allow_redirects")
        return self.http.request(method, url, **kwargs)

    def test_helpers_share_host_storage_and_request_limits(self) -> None:
        """
        多个插件 helper 与宿主共享同一存储实例及接口限流和统计
        """
        second = self.helper_class()
        self.assertIs(self.helper._storage, self.host)
        self.assertIs(second._storage, self.host)
        self.assertEqual(
            self.helper._request_api(
                "GET", "/open/ufile/files", "data", params={"cid": 1}
            ),
            {"value": 1},
        )
        second._request_api("POST", "/open/ufile/downurl", data={"pick_code": "test"})
        self.host._api_limiter.acquire.assert_called_once()
        self.host._download_limiter.acquire.assert_called_once()
        self.assertEqual(self.host._rate_stats.record.call_count, 2)
        self.assertEqual(
            self.requests[0].headers["Authorization"], "Bearer test-access"
        )
        self.assertEqual(self.requests[0].url.params["cid"], "1")

    def test_expired_token_refresh_is_owned_by_host(self) -> None:
        """
        并发 helper 只通过宿主的令牌锁刷新一次并复用刷新结果
        """
        self.tokens["refresh_time"] = self.now - 7200
        self.responses = [
            Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "access_token": "new-access",
                        "refresh_token": "new-refresh",
                        "expires_in": 3600,
                    },
                },
            )
        ]
        second = self.helper_class()
        with ThreadPoolExecutor(max_workers=2) as executor:
            values = list(
                executor.map(lambda helper: helper.access_token, [self.helper, second])
            )
        self.assertEqual(values, ["new-access", "new-access"])
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.requests[0].url.path, "/open/refreshToken")
        self.assertEqual(self.tokens["refresh_token"], "new-refresh")
        self.assertEqual(self.tokens["refresh_time"], self.now)
        self.assertEqual(self.adapter._headers["Authorization"], "Bearer new-access")

    def test_missing_authorization_preserves_plugin_error_contract(self) -> None:
        """
        宿主未授权异常转换为插件原有异常且不发出请求
        """
        self.tokens.clear()
        with self.assertRaises(self.plugin_error):
            self.helper._request_api("GET", "/open/ufile/files")
        self.assertEqual(self.requests, [])
        self.assertIsNone(self.helper.access_token)

    def test_rate_limit_uses_host_cooldown_and_bounded_retry(self) -> None:
        """
        429 使用宿主统一冷却及重试预算，不再无限递归
        """
        self.responses = [Response(429), Response(429)]
        result = self.helper._request_api("GET", "/open/ufile/files", retry_limit=1)
        self.assertIsNone(result)
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(self.delays, [self.host.limit_sleep_seconds])
        self.assertEqual(self.host._limit_until, self.now)
        self.assertEqual(self.host._api_limiter.acquire.call_count, 2)

    def test_business_codes_are_accepted_only_by_explicit_callers(self) -> None:
        """
        未知业务码仍返回失败，目录已存在只在显式允许的调用中透传
        """
        for code, accepted, success in (
            (20004, (0,), False),
            (20004, (0, 20004), True),
            (430004, (0,), False),
            (999, (0,), False),
        ):
            with self.subTest(code=code, accepted=accepted):
                payload = {"code": code, "message": "test", "state": False}
                self.responses = [Response(200, json=payload)]
                result = self.helper._request_api(
                    "POST", "/open/folder/add", accepted_codes=accepted
                )
                self.assertEqual(result, payload if success else None)

    def test_existing_folder_response_reaches_existing_path_lookup(self) -> None:
        """
        创建目录遇到已存在业务码时复用原路径查询，不被请求层提前丢弃
        """
        folder = object()
        self.helper.get_item = MagicMock(return_value=folder)
        self.responses = [
            Response(
                200, json={"code": 20004, "state": False, "message": "already exists"}
            )
        ]
        result = self.helper.create_folder(
            SimpleNamespace(path="/library", fileid="42"), "movie"
        )
        self.assertIs(result, folder)
        self.helper.get_item.assert_called_once_with(Path("/library/movie"))

    def test_download_uses_host_limiter_and_forwards_user_agent(self) -> None:
        """
        下载地址通过宿主的独立下载限流并保留播放器 User-Agent
        """
        self.responses = [
            Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "42": {"url": {"url": "https://example.invalid/movie.mkv"}}
                    },
                },
            )
        ]
        self.assertEqual(
            self.helper.get_download_url("pickcode", "TestPlayer"),
            "https://example.invalid/movie.mkv",
        )
        self.host._download_limiter.acquire.assert_called_once()
        self.host._api_limiter.acquire.assert_not_called()
        self.assertEqual(self.requests[0].headers["User-Agent"], "TestPlayer")
        self.assertEqual(
            self.requests[0].headers["Authorization"], "Bearer test-access"
        )
        self.assertEqual(
            self.requests[0].headers["X-Correlation-ID"], "test-correlation"
        )
        self.assertEqual(self.adapter._headers["User-Agent"], "W115Storage/2.0")

    def test_custom_headers_follow_token_refresh_during_host_retry(self) -> None:
        """
        带播放器 UA 的请求在宿主重试刷新后读取新授权，不固定旧令牌
        """
        self.tokens["expires_in"] = 1
        self.responses = [
            Response(500),
            Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "access_token": "renewed",
                        "refresh_token": "renewed-refresh",
                        "expires_in": 3600,
                    },
                },
            ),
            Response(200, json={"code": 0, "data": {"ok": True}}),
        ]
        result = self.helper._request_api(
            "POST",
            "/open/ufile/downurl",
            "data",
            headers={"User-Agent": "TestPlayer"},
            retry_limit=1,
        )
        self.assertEqual(result, {"ok": True})
        self.assertEqual(len(self.requests), 3)
        self.assertEqual(
            self.requests[0].headers["Authorization"], "Bearer test-access"
        )
        self.assertEqual(self.requests[-1].headers["Authorization"], "Bearer renewed")
        self.assertEqual(self.requests[-1].headers["User-Agent"], "TestPlayer")
