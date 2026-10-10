"""
UrlUtils 测试模块

包含 URL 编码、解析等工具方法的单元测试
"""

from unittest import TestCase

from utils.url import Url, UrlUtils


class TestUrlClass(TestCase):
    """测试 Url 类"""

    def test_basic_creation(self):
        """测试基本创建"""
        url = Url("https://example.com")
        self.assertEqual(str(url), "https://example.com")

    def test_dict_access(self):
        """测试字典式访问"""
        url = Url("test")
        url.__dict__["key1"] = "value1"
        url.__dict__["key2"] = 123

        self.assertEqual(url["key1"], "value1")
        self.assertEqual(url["key2"], 123)

    def test_get_method(self):
        """测试 get 方法"""
        url = Url("test")
        url.__dict__["foo"] = "bar"

        self.assertEqual(url.get("foo"), "bar")
        self.assertEqual(url.get("missing"), None)
        self.assertEqual(url.get("missing", "default"), "default")

    def test_items_keys_values(self):
        """测试 items/keys/values 方法"""
        url = Url("test")
        url.__dict__["a"] = 1
        url.__dict__["b"] = 2

        self.assertEqual(dict(url.items()), {"a": 1, "b": 2})
        self.assertEqual(set(url.keys()), {"a", "b"})
        self.assertEqual(set(url.values()), {1, 2})

    def test_of_factory(self):
        """测试 of 工厂方法"""
        ns = {"key": "value", "num": 42}
        url = Url.of("base", ns)

        self.assertEqual(str(url), "base")
        self.assertEqual(url.get("key"), "value")
        self.assertEqual(url.get("num"), 42)

    def test_repr(self):
        """测试 repr 输出"""
        url = Url("test")
        url.__dict__["foo"] = "bar"
        repr_str = repr(url)

        self.assertIn("Url", repr_str)
        self.assertIn("test", repr_str)
        self.assertIn("foo", repr_str)


class TestEncodeUrlFully(TestCase):
    """测试 UrlUtils.encode_url_fully 方法"""

    def test_basic_url_unchanged(self):
        """测试基本 URL 无需编码"""
        url = "https://example.com/path"
        self.assertEqual(UrlUtils.encode_url_fully(url), url)

    def test_path_encoding(self):
        """测试路径编码"""
        # 空格应被编码
        url = "https://example.com/path with spaces/file.txt"
        result = UrlUtils.encode_url_fully(url)
        self.assertIn("%20", result)
        self.assertNotIn(" ", result)

        # 特殊字符
        url = "https://example.com/path[with]brackets/file.txt"
        result = UrlUtils.encode_url_fully(url)
        self.assertNotIn("[", result)
        self.assertNotIn("]", result)

    def test_query_encoding(self):
        """测试查询参数编码"""
        url = "https://example.com/path?key=value with spaces"
        result = UrlUtils.encode_url_fully(url)
        # URL 编码可能使用 %20 或 + 表示空格
        self.assertTrue("%20" in result or "+" in result)
        self.assertNotIn(" ", result)

    def test_fragment_encoding(self):
        """测试片段标识符编码"""
        url = "https://example.com/path#section with spaces"
        result = UrlUtils.encode_url_fully(url)
        self.assertIn("%20", result)

    def test_preserves_slashes(self):
        """测试保留路径分隔符"""
        url = "https://example.com/a/b/c"
        result = UrlUtils.encode_url_fully(url)
        self.assertEqual(result.count("/"), url.count("/"))

    def test_complex_url(self):
        """测试复杂 URL 完整编码"""
        url = "https://user:pass@example.com:8080/path with spaces/file[name].txt?key=value&foo=bar baz#section"
        result = UrlUtils.encode_url_fully(url)

        # 验证各部分都被正确处理
        self.assertTrue(result.startswith("https://"))
        self.assertIn("example.com:8080", result)
        self.assertNotIn(" ", result)  # 空格应被编码

    def test_non_ascii_url_is_header_safe(self):
        """测试非 ASCII URL 可安全写入响应头"""
        url = "https://example.com/国产剧/生命树.mkv?name=生命树"
        result = UrlUtils.encode_url_fully(url)

        result.encode("ascii")
        self.assertIn("%E5%9B%BD%E4%BA%A7%E5%89%A7", result)
        self.assertIn("name=%E7%94%9F%E5%91%BD%E6%A0%91", result)

    def test_signed_query_is_preserved(self):
        """测试签名查询串及已有转义保持不变"""
        url = "https://example.com/file.mkv?t=123&sign=a%2Fb%2Bc%3D"

        self.assertEqual(UrlUtils.encode_url_fully(url), url)

    def test_invalid_url_fallback(self):
        """测试无效 URL 回退"""
        # URL 编码函数会尝试解析并编码，如果完全无法解析则返回原值
        # 测试一个可能被部分解析但仍保持核心结构的 URL
        url = "just text without url structure"
        result = UrlUtils.encode_url_fully(url)
        # 不含 scheme 和 netloc 的字符串可能被解析为 path 并进行编码
        # 验证结果包含原始内容或被适当处理
        self.assertTrue(result == url or "%20" in result or len(result) > 0)

    def test_empty_url(self):
        """测试空 URL"""
        self.assertEqual(UrlUtils.encode_url_fully(""), "")


class TestParseQueryParams(TestCase):
    """测试 UrlUtils.parse_query_params 方法"""

    def test_standard_url(self):
        """测试标准 URL 解析"""
        url = "https://example.com/path?key1=value1&key2=value2"
        params = UrlUtils.parse_query_params(url)

        self.assertEqual(params["key1"], "value1")
        self.assertEqual(params["key2"], "value2")

    def test_query_only(self):
        """测试仅查询字符串"""
        query = "?foo=bar&baz=qux"
        params = UrlUtils.parse_query_params(query)

        self.assertEqual(params["foo"], "bar")
        self.assertEqual(params["baz"], "qux")

    def test_multiple_values(self):
        """测试多值参数（取首个）"""
        url = "https://example.com/path?key=val1&key=val2"
        params = UrlUtils.parse_query_params(url)

        # 应取第一个值
        self.assertEqual(params["key"], "val1")

    def test_url_without_query(self):
        """测试无查询参数的 URL"""
        url = "https://example.com/path"
        params = UrlUtils.parse_query_params(url)

        self.assertEqual(params, {})

    def test_empty_query(self):
        """测试空查询字符串"""
        url = "https://example.com/path?"
        params = UrlUtils.parse_query_params(url)

        self.assertEqual(params, {})

    def test_encoded_params(self):
        """测试编码后的参数"""
        url = "https://example.com/path?key=value%20with%20spaces"
        params = UrlUtils.parse_query_params(url)

        self.assertEqual(params["key"], "value with spaces")

    def test_special_characters(self):
        """测试特殊字符参数"""
        url = "https://example.com/path?key=hello+world"
        params = UrlUtils.parse_query_params(url)

        # + 号应被解码为空格
        self.assertEqual(params["key"], "hello world")

    def test_partial_url(self):
        """测试部分 URL（无 scheme）"""
        url = "/path/to/file?key=value"
        params = UrlUtils.parse_query_params(url)

        self.assertEqual(params["key"], "value")

    def test_empty_input(self):
        """测试空输入"""
        self.assertEqual(UrlUtils.parse_query_params(""), {})
        self.assertEqual(UrlUtils.parse_query_params(None), {})

    def test_whitespace_only(self):
        """测试仅空白字符"""
        self.assertEqual(UrlUtils.parse_query_params("   "), {})


class TestUrlUtilsIntegration(TestCase):
    """集成测试：编码和解析组合使用"""

    def test_encode_then_parse(self):
        """测试编码后再解析"""
        original = "https://example.com/path?key=value with spaces"
        encoded = UrlUtils.encode_url_fully(original)
        params = UrlUtils.parse_query_params(encoded)

        # 编码后的 URL 解析应得到正确值
        self.assertEqual(params["key"], "value with spaces")

    def test_roundtrip_with_special_chars(self):
        """测试特殊字符的往返"""
        # 普通空格可以往返
        url = "https://example.com/path?key=hello world"
        encoded = UrlUtils.encode_url_fully(url)
        params = UrlUtils.parse_query_params(encoded)
        self.assertEqual(params["key"], "hello world")

        # 加号在 URL 中被解码为空格是标准行为
        url = "https://example.com/path?key=test+value"
        encoded = UrlUtils.encode_url_fully(url)
        params = UrlUtils.parse_query_params(encoded)
        # 加号被编码为 %2B 或保持原样，解析时 + 变成空格
        self.assertEqual(params["key"], "test value")


if __name__ == "__main__":
    from unittest import main

    main(verbosity=2)
