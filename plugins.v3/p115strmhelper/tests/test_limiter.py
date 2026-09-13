"""
RateLimiter 和 ApiEndpointCooldown 测试模块

包含速率限制工具类的单元测试
"""

from time import monotonic
from unittest import TestCase

from utils.limiter import ApiEndpointCooldown, RateLimiter


class TestRateLimiter(TestCase):
    """测试 RateLimiter 类"""

    def test_creation_with_positive_qps(self):
        """测试正 QPS 创建"""
        limiter = RateLimiter(qps=10.0)
        self.assertEqual(limiter.interval, 0.1)

    def test_creation_with_zero_qps(self):
        """测试零 QPS 创建（应变为无限）"""
        limiter = RateLimiter(qps=0)
        self.assertEqual(limiter.interval, 0.0)

    def test_creation_with_negative_qps(self):
        """测试负 QPS 创建（应变为无限）"""
        limiter = RateLimiter(qps=-1)
        self.assertEqual(limiter.interval, 0.0)

    def test_acquire_does_not_raise(self):
        """测试 acquire 不抛出异常"""
        limiter = RateLimiter(qps=100.0)  # 100 QPS = 10ms 间隔
        # 第一次调用应无阻塞
        limiter.acquire()
        # 第二次调用可能短暂阻塞
        limiter.acquire()
        # 只要没抛出异常就算通过

    def test_rate_limiting_effect(self):
        """测试速率限制效果"""
        limiter = RateLimiter(qps=10.0)  # 100ms 间隔

        start = monotonic()
        for _ in range(3):
            limiter.acquire()
        elapsed = monotonic() - start

        # 3 次调用至少应有 2 个间隔 = 200ms
        self.assertGreaterEqual(elapsed, 0.15)

    def test_high_qps_no_delay(self):
        """测试高 QPS 几乎无延迟"""
        limiter = RateLimiter(qps=10000.0)  # 0.1ms 间隔

        start = monotonic()
        for _ in range(10):
            limiter.acquire()
        elapsed = monotonic() - start

        # 10 次调用应在短时间内完成
        self.assertLess(elapsed, 0.1)


class MockApi:
    """模拟 API 调用"""

    def __init__(self):
        self.call_count = 0

    def __call__(self, payload: dict) -> dict:
        self.call_count += 1
        return {"result": "ok", "count": self.call_count}


class TestApiEndpointCooldown(TestCase):
    """测试 ApiEndpointCooldown 类"""

    def test_creation(self):
        """测试创建"""
        api = MockApi()
        cooldown = ApiEndpointCooldown(api, cooldown=1.0)
        self.assertEqual(cooldown.cooldown, 1.0)
        self.assertEqual(cooldown.api_callable, api)

    def test_call_without_cooldown(self):
        """测试无冷却时直接调用"""
        api = MockApi()
        cooldown = ApiEndpointCooldown(api, cooldown=0)

        result1 = cooldown({"key": "value1"})
        result2 = cooldown({"key": "value2"})

        self.assertEqual(result1["result"], "ok")
        self.assertEqual(result2["result"], "ok")
        self.assertEqual(api.call_count, 2)

    def test_call_with_cooldown(self):
        """测试有冷却时的调用"""
        api = MockApi()
        cooldown = ApiEndpointCooldown(api, cooldown=0.05)  # 50ms 冷却

        start = monotonic()
        result1 = cooldown({"key": "value1"})
        result2 = cooldown({"key": "value2"})
        elapsed = monotonic() - start

        self.assertEqual(result1["result"], "ok")
        self.assertEqual(result2["result"], "ok")
        # 两次调用之间应有冷却延迟
        self.assertGreaterEqual(elapsed, 0.04)

    def test_initial_call_no_delay(self):
        """测试首次调用无延迟"""
        api = MockApi()
        cooldown = ApiEndpointCooldown(api, cooldown=1.0)

        start = monotonic()
        result = cooldown({"key": "value"})
        elapsed = monotonic() - start

        self.assertEqual(result["result"], "ok")
        # 首次调用应无延迟
        self.assertLess(elapsed, 0.1)


if __name__ == "__main__":
    from unittest import main

    main(verbosity=2)
