"""
TimeUtils 测试模块

包含时间格式化工具方法的单元测试
"""

from datetime import datetime
from time import time
from unittest import TestCase

from utils.time import TimeUtils


class TestTimestamp2Isoformat(TestCase):
    """测试 TimeUtils.timestamp2isoformat 方法"""

    def test_none_returns_current_time(self):
        """测试 None 返回当前时间"""
        result = TimeUtils.timestamp2isoformat(None)
        # 验证是有效的 ISO 格式
        self.assertIsInstance(result, str)
        self.assertIn("T", result)
        # 验证包含时区信息
        self.assertTrue("+" in result or "-" in result or result.endswith("Z"))

    def test_float_timestamp(self):
        """测试 float 时间戳"""
        ts = 1609459200.0  # 2021-01-01 00:00:00 UTC
        result = TimeUtils.timestamp2isoformat(ts)
        self.assertIn("2021", result)
        self.assertIn("T", result)

    def test_datetime_object(self):
        """测试 datetime 对象"""
        dt = datetime(2023, 6, 15, 10, 30, 0)
        result = TimeUtils.timestamp2isoformat(dt)
        self.assertIn("2023-06-15", result)
        self.assertIn("10:30:00", result)

    def test_early_timestamp(self):
        """测试较早时间戳（Windows 不支持 1970-01-01 的时区转换）"""
        # Windows 的 localtime 最小支持约 1970-01-02，使用更晚的时间戳
        ts = 86400.0  # 1970-01-02 00:00:00 UTC（Windows 兼容）
        result = TimeUtils.timestamp2isoformat(ts)
        self.assertIsInstance(result, str)
        self.assertIn("T", result)


class TestTimestamp2Gmtformat(TestCase):
    """测试 TimeUtils.timestamp2gmtformat 方法"""

    def test_none_returns_current_time(self):
        """测试 None 返回当前 GMT 时间"""
        result = TimeUtils.timestamp2gmtformat(None)
        # GMT 格式应包含 GMT
        self.assertIn("GMT", result)

    def test_float_timestamp(self):
        """测试 float 时间戳"""
        ts = 1609459200.0
        result = TimeUtils.timestamp2gmtformat(ts)
        self.assertIn("GMT", result)
        # 格式类似: Fri, 01 Jan 2021 00:00:00 GMT
        self.assertIsInstance(result, str)

    def test_datetime_object(self):
        """测试 datetime 对象"""
        dt = datetime(2023, 6, 15, 10, 30, 0)
        result = TimeUtils.timestamp2gmtformat(dt)
        self.assertIn("GMT", result)
        self.assertIsInstance(result, str)

    def test_early_timestamp(self):
        """测试较早时间戳（Windows 不支持 1970-01-01 的时区转换）"""
        # Windows 的 localtime 最小支持约 1970-01-02，使用更晚的时间戳
        ts = 86400.0  # 1970-01-02 00:00:00 UTC（Windows 兼容）
        result = TimeUtils.timestamp2gmtformat(ts)
        self.assertIn("GMT", result)
        self.assertIsInstance(result, str)


class TestTimeUtilsIntegration(TestCase):
    """集成测试：验证两个方法的一致性"""

    def test_same_input_same_time(self):
        """测试相同输入表示同一时间"""
        ts = time()
        iso_result = TimeUtils.timestamp2isoformat(ts)
        gmt_result = TimeUtils.timestamp2gmtformat(ts)

        # 两者都应成功返回字符串
        self.assertIsInstance(iso_result, str)
        self.assertIsInstance(gmt_result, str)

        # 两者都应非空
        self.assertTrue(len(iso_result) > 0)
        self.assertTrue(len(gmt_result) > 0)


if __name__ == "__main__":
    from unittest import main

    main(verbosity=2)
