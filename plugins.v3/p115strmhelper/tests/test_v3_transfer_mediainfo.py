from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock

from test_v3_share_queue_lifecycle import _method


class TestV3TransferMediainfo(TestCase):
    """
    验证整理后原生 Emby 探测允许云端媒体的实际等待时间
    """

    def setUp(self) -> None:
        """
        加载真实探测方法，隔离 HTTP 等待与媒体服务器配置
        """
        self.response = MagicMock(status_code=200)
        self.response.__enter__.return_value = self.response
        self.logger = MagicMock()
        self.minimum_probe_seconds = 60

        def request(timeout=20):
            return SimpleNamespace(
                post_res=lambda **kwargs: (
                    self.response if timeout >= self.minimum_probe_seconds else None
                )
            )

        self.probe = _method(
            Path(__file__).resolve().parents[1] / "helper/mediaserver/emby.py",
            "trigger_mediainfo_refresh",
            {"RequestUtils": request, "logger": self.logger},
        )
        self.helper = SimpleNamespace(
            func_name="test",
            get_emby_info=lambda name: ("http://emby.invalid/", "user", "test-key"),
        )

    def test_native_probe_allows_slow_cloud_media(self) -> None:
        """
        需要一分钟的云端探测不会因宿主默认二十秒超时而被取消
        """
        self.assertTrue(self.probe(self.helper, "Test", "item"))
        self.response.__exit__.assert_called_once()
        self.logger.error.assert_not_called()

    def test_native_probe_handles_missing_response(self) -> None:
        """
        超时或连接失败返回空响应时记录明确失败而不触发上下文管理异常
        """
        self.response = None
        self.assertFalse(self.probe(self.helper, "Test", "item"))
        self.logger.warning.assert_called_once()
        self.logger.error.assert_not_called()

    def test_native_probe_rejects_server_error(self) -> None:
        """
        服务器返回错误状态时保持失败结果并关闭响应
        """
        self.response.status_code = 500
        self.assertFalse(self.probe(self.helper, "Test", "item"))
        self.response.__exit__.assert_called_once()

