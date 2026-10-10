"""
NotifyExceptionFormatter 测试模块

包含异常格式化工具方法的单元测试
"""

from unittest import TestCase

from utils.exception import NotifyExceptionFormatter


class MockHTTPError(Exception):
    """模拟 HTTP 异常"""

    def __init__(self, code=None, reason=None, message=None):
        self.code = code
        self.reason = reason
        self.message = message
        super().__init__(message or reason or str(code))


class TestFormatExceptionForNotify(TestCase):
    """测试 NotifyExceptionFormatter.format_exception_for_notify 方法"""

    def test_basic_exception(self):
        """测试基本异常"""
        exc = ValueError("test error")
        result = NotifyExceptionFormatter.format_exception_for_notify(exc)
        self.assertIn("test error", result)

    def test_empty_exception(self):
        """测试空异常"""
        exc = ValueError()
        result = NotifyExceptionFormatter.format_exception_for_notify(exc)
        self.assertEqual(result, "ValueError")

    def test_http_error_with_all_fields(self):
        """测试 HTTP 异常（完整字段）"""
        exc = MockHTTPError(code=404, reason="Not Found", message="Resource missing")
        result = NotifyExceptionFormatter.format_exception_for_notify(exc)
        self.assertIn("404", result)
        self.assertIn("Not Found", result)
        self.assertIn("Resource missing", result)

    def test_http_error_code_only(self):
        """测试 HTTP 异常（仅状态码）"""
        exc = MockHTTPError(code=500)
        result = NotifyExceptionFormatter.format_exception_for_notify(exc)
        self.assertIn("500", result)

    def test_http_error_reason_only(self):
        """测试 HTTP 异常（仅原因）"""
        exc = MockHTTPError(reason="Bad Request")
        result = NotifyExceptionFormatter.format_exception_for_notify(exc)
        self.assertIn("Bad Request", result)

    def test_http_error_message_only(self):
        """测试 HTTP 异常（仅消息）"""
        exc = MockHTTPError(message="Something went wrong")
        result = NotifyExceptionFormatter.format_exception_for_notify(exc)
        self.assertIn("Something went wrong", result)

    def test_max_length_truncation(self):
        """测试最大长度截断"""
        long_message = "a" * 500
        exc = ValueError(long_message)
        result = NotifyExceptionFormatter.format_exception_for_notify(exc, max_length=100)
        self.assertLessEqual(len(result), 100)

    def test_string_parsing_code_reason_message(self):
        """测试字符串解析 code/reason/message"""
        exc = Exception("code=401 reason='Unauthorized' message='Token expired'")
        result = NotifyExceptionFormatter.format_exception_for_notify(exc)
        self.assertIn("401", result)
        self.assertIn("Unauthorized", result)
        self.assertIn("Token expired", result)

    def test_multiline_exception(self):
        """测试多行异常消息"""
        exc = Exception("First line\nSecond line\nThird line")
        result = NotifyExceptionFormatter.format_exception_for_notify(exc)
        # 应提取有效行
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)


if __name__ == "__main__":
    from unittest import main
    main(verbosity=2)
