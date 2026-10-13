import importlib.util
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch


class TestV3P115DiskRateLimiter(TestCase):
    """
    验证批量整理并发访问存储时的滑动窗口限流
    """

    def test_waiting_for_lock_does_not_extend_rate_window(self) -> None:
        """
        排队线程必须根据取得锁后的时间计算剩余等待
        """
        source = Path(__file__).resolve().parents[2] / "p115disk" / "tools.py"
        spec = importlib.util.spec_from_file_location("_p115disk_limiter", source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        limiter = module.RateLimiter(max_calls=1, time_window=1)
        clock = [0.0]

        class QueuedLock:
            def __enter__(self):
                clock[0] = 10.0
                limiter._call_times = [9.5]

            def __exit__(self, *args):
                return False

        def advance(seconds: float) -> None:
            clock[0] += seconds

        limiter._lock = QueuedLock()
        with (
            patch.object(module, "monotonic", side_effect=lambda: clock[0]),
            patch.object(module, "sleep", side_effect=advance) as sleep,
        ):
            limiter.acquire()

        sleep.assert_called_once_with(0.5)
        self.assertEqual(limiter._call_times, [10.5])
