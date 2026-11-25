from copy import deepcopy
from datetime import datetime
from pathlib import Path
from threading import Barrier, RLock, Thread
from types import SimpleNamespace
from typing import Any, Dict
from unittest import TestCase
from unittest.mock import MagicMock, patch

from p115client import P115Client, check_response

from test_v3_worker_queue import _compile


class TestV3OfflineRetry(TestCase):
    """
    验证真实离线轮询的重试预算、持久化和整理交接，隔离云端及宿主存储
    """

    def setUp(self) -> None:
        """
        加载真实业务类并使用可重启的内存存储与可控时钟
        """
        self.data = {}
        self.config = MagicMock(
            cookies="UID=115_A1; CID=test; SEID=test",
            offline_retry_enabled=True,
            offline_retry_max_attempts=2,
            offline_retry_interval_hours=1,
            pan_transfer_paths="/incoming",
            offline_download_paths=["/incoming"],
        )
        self.config.get_plugin_data.side_effect = lambda key: deepcopy(
            self.data.get(key)
        )
        self.config.save_plugin_data.side_effect = lambda key, value: (
            self.data.__setitem__(key, deepcopy(value))
        )
        self.config.get_ios_ua_app.return_value = {"headers": {"user-agent": "test"}}
        self.config.get_config.return_value = "mkv,mp4"
        self.clock = MagicMock()
        self.clock.time.return_value = 1000
        self.client = MagicMock(spec=P115Client)
        self.client.user_id = 115
        self.client.clouddownload_task_restart.return_value = {"state": True}
        self.monitor = MagicMock()
        self.namespace = {
            "configer": self.config,
            "logger": MagicMock(),
            "datetime": datetime,
            "time": self.clock,
            "Path": Path,
            "RLock": RLock,
            "check_response": check_response,
            "get_attr": MagicMock(
                return_value={
                    "id": 1,
                    "is_dir": True,
                    "parent_id": 10,
                    "size": 1024,
                    "pickcode": "test",
                    "user_utime": 1000,
                    "sha1": "test",
                }
            ),
            "get_pid_by_path": MagicMock(return_value=10),
            "StringUtils": SimpleNamespace(format_size=lambda size: str(size)),
            "OfflineTaskItem": lambda **kwargs: SimpleNamespace(**kwargs),
        }
        root = Path(__file__).resolve().parents[1]
        self.namespace["OfflineRetryManager"] = _compile(
            root / "helper/offline/retry.py", self.namespace, "OfflineRetryManager"
        )
        self.helper_type = _compile(
            root / "helper/offline/__init__.py", self.namespace, "OfflineDownloadHelper"
        )
        self.tasks = [self._task()]
        self.helper = self._helper()

    def _task(self, info_hash: str = "abc", status: int = 1) -> Dict[str, Any]:
        return {
            "info_hash": info_hash,
            "status": status,
            "available_actions": ["retry"],
            "name": "movie",
            "delete_file_id": 1,
            "size": 1024,
            "add_time": 100,
        }

    def _helper(self) -> Any:
        helper = self.helper_type(self.client, self.monitor)
        helper.get_tasks = MagicMock(side_effect=lambda: iter(deepcopy(self.tasks)))
        helper.post_offline_info = MagicMock()
        return helper

    def _poll(self, now: int) -> None:
        self.clock.time.return_value = now
        self.helper.pull_status_to_task()

    def _add_transfer(self) -> None:
        self.client.clouddownload_task_add_urls.return_value = {
            "state": True,
            "data": {"result": [{"info_hash": "abc"}]},
        }
        self.assertEqual(self.helper.add_urls_to_transfer(["magnet:test"]), (True, 1))

    def test_backlog_waits_for_interval_and_survives_restart(self) -> None:
        """
        历史失败任务无需整理关联也可重试，重启后继续原有计时和次数
        """
        self._poll(1000)
        self._poll(4599)
        self.client.clouddownload_task_restart.assert_not_called()
        self.helper = self._helper()
        self._poll(4600)
        self.client.clouddownload_task_restart.assert_called_once_with(
            "abc", type="web", headers={"user-agent": "test"}
        )
        self.helper = self._helper()
        self._poll(4601)
        self.assertEqual(self.client.clouddownload_task_restart.call_count, 1)
        self.assertIn("已重试 1 次", self.helper.get_cached_data()[0].status_text)
        self.monitor.media_transfer.assert_not_called()

    def test_last_attempt_can_finish_before_exhaustion(self) -> None:
        """
        最后一次重试仍可运行并完成，成功后恢复原目录整理且只交接一次
        """
        self._add_transfer()
        self._poll(1000)
        self._poll(4600)
        self.helper = self._helper()
        self._poll(8200)
        self._poll(8201)
        self.assertEqual(len(self.helper.transfer_list), 1)
        self.tasks[0]["status"] = 3
        self._poll(11800)
        self.assertFalse(self.helper._retry.records["abc"]["exhausted"])
        self.tasks[0]["status"] = 2
        self._poll(12000)
        self.helper = self._helper()
        self._poll(12120)
        self.assertEqual(self.client.clouddownload_task_restart.call_count, 2)
        self.monitor.media_transfer.assert_called_once()
        self.assertEqual(
            self.monitor.media_transfer.call_args.kwargs["file_path"],
            Path("/incoming/movie"),
        )
        self.assertEqual(self.helper.transfer_list, [])
        self.assertEqual(self.helper._retry.records, {})

    def test_exhaustion_is_persistent_and_releases_failed_transfer(self) -> None:
        """
        达到上限后标记失败并停止自动重试，重新加载配置也不重置预算
        """
        self._add_transfer()
        for now in (1000, 4600, 8200, 11800, 11920):
            self._poll(now)
        self.assertEqual(self.helper.transfer_list, [])
        self.assertIn("停止重试", self.helper.get_cached_data()[0].status_text)
        self.helper = self._helper()
        self._poll(50000)
        self.assertEqual(self.client.clouddownload_task_restart.call_count, 2)
        self.monitor.media_transfer.assert_not_called()

    def test_disabled_retry_keeps_two_check_failure_cleanup(self) -> None:
        """
        关闭重试时两次失败检测会移除待整理项，避免原临时计数不断重置
        """
        self.config.offline_retry_enabled = False
        self._add_transfer()
        self._poll(1000)
        self.assertEqual(self.helper.transfer_list[0]["count"], 1)
        self.helper = self._helper()
        self._poll(1120)
        self.assertEqual(self.helper.transfer_list, [])
        self.helper.get_tasks.reset_mock()
        self._poll(1240)
        self.helper.get_tasks.assert_not_called()
        self.client.clouddownload_task_restart.assert_not_called()

    def test_only_failed_retryable_tasks_are_restarted(self) -> None:
        """
        下载中、成功、重试中、未知状态及不允许重试的失败项均不提交
        """
        self.tasks = [self._task(str(status), status) for status in (0, 2, 3, -1)]
        self.tasks.extend([self._task("unsupported"), self._task("missing")])
        self.tasks[-2]["available_actions"] = ["delete"]
        self.tasks[-1].pop("available_actions")
        self._poll(1000)
        self._poll(5000)
        self.client.clouddownload_task_restart.assert_not_called()
        self.assertIn("115 不支持重试", self.helper.get_cached_data()[-1].status_text)

    def test_pending_restart_keeps_transfer_without_retry_action(self) -> None:
        """
        重启后的状态尚未更新且暂缺重试动作时，等待窗口内保留整理关联
        """
        self._add_transfer()
        self._poll(1000)
        self._poll(4600)
        self.tasks[0]["available_actions"] = []
        self._poll(4720)
        self._poll(4840)
        self.assertEqual(len(self.helper.transfer_list), 1)
        self.assertEqual(self.client.clouddownload_task_restart.call_count, 1)
        self.tasks[0]["status"] = 2
        self._poll(5000)
        self.monitor.media_transfer.assert_called_once()

    def test_disable_and_list_do_not_reset_or_consume_budget(self) -> None:
        """
        关闭功能或查看到期任务列表不会提交请求，再次启用后继续剩余预算
        """
        self._poll(1000)
        self._poll(4600)
        self.config.offline_retry_enabled = False
        self.helper = self._helper()
        self._poll(9000)
        self.helper.get_cached_data()
        self.assertEqual(self.client.clouddownload_task_restart.call_count, 1)
        self.config.offline_retry_enabled = True
        self.helper = self._helper()
        self.helper.get_cached_data()
        self.assertEqual(self.client.clouddownload_task_restart.call_count, 1)
        self._poll(9000)
        self.assertEqual(self.client.clouddownload_task_restart.call_count, 2)

    def test_explicit_path_download_retries_without_transfer(self) -> None:
        """
        显式目录下载同样参与重试，但不会额外创建网盘整理任务
        """
        self.client.clouddownload_task_add_urls.return_value = {
            "state": True,
            "data": {"result": [{"info_hash": "abc"}]},
        }
        self.assertEqual(
            self.helper.add_urls_to_path(["magnet:test"], "/downloads"), (True, 1)
        )
        self._poll(1000)
        self._poll(4600)
        self.tasks[0]["status"] = 2
        self._poll(4720)
        self.client.clouddownload_task_restart.assert_called_once()
        self.client.clouddownload_task_add_urls.assert_called_once()
        self.monitor.media_transfer.assert_not_called()

    def test_request_errors_consume_budget_and_do_not_block_other_tasks(self) -> None:
        """
        业务拒绝和网络超时均受间隔与上限约束，单项错误不阻塞后续任务
        """
        self.tasks.append(self._task("def"))
        self.client.clouddownload_task_restart.side_effect = [
            TimeoutError("timeout"),
            {"state": False, "errno": 10009},
            {"state": True},
            {"state": True},
        ]
        for now in (1000, 4600, 4720, 8200, 11800, 20000):
            self._poll(now)
        self.assertEqual(self.client.clouddownload_task_restart.call_count, 4)
        self.assertTrue(
            all(r["exhausted"] for r in self.helper._retry.records.values())
        )

    def test_budget_is_saved_before_request_and_storage_failure_blocks_it(self) -> None:
        """
        请求前写入预算，持久化失败时不触发无法记账的重试
        """
        self._poll(1000)

        def assert_saved(*args, **kwargs):
            record = next(iter(self.data.values()))["retries"]["abc"]
            self.assertEqual(record["attempts"], 1)
            self.assertEqual(record["next_retry_at"], 8200)
            return {"state": True}

        self.client.clouddownload_task_restart.side_effect = assert_saved
        self._poll(4600)
        self.config.save_plugin_data.side_effect = OSError("disk full")
        with self.assertRaises(OSError):
            self._poll(8200)
        self.assertEqual(self.client.clouddownload_task_restart.call_count, 1)

    def test_partial_listing_never_restarts_or_prunes(self) -> None:
        """
        分页中途失败时不重试也不把未读取到的任务当成已删除
        """
        self.tasks.append(self._task("def"))
        self._poll(1000)
        original = deepcopy(self.data)

        def partial():
            yield self._task()
            raise OSError("page two failed")

        self.helper.get_tasks.side_effect = partial
        with self.assertRaises(OSError):
            self._poll(4600)
        self.assertEqual(self.data, original)
        self.client.clouddownload_task_restart.assert_not_called()

    def test_deleted_task_is_forgotten_and_account_state_is_isolated(self) -> None:
        """
        删除任务后释放记录，新账号不会继承旧账号的整理路径或重试预算
        """
        self._add_transfer()
        self._poll(1000)
        self.client.user_id = 116
        self.helper = self._helper()
        self._poll(4600)
        self.assertEqual(self.helper.transfer_list, [])
        self.client.clouddownload_task_restart.assert_not_called()
        self.client.user_id = 115
        self.helper = self._helper()
        self.tasks = []
        self._poll(5000)
        self.assertEqual(self.helper._retry.records, {})
        self.assertEqual(self.helper.transfer_list, [])

    def test_concurrent_polls_submit_once(self) -> None:
        """
        同一助手的并发轮询只能消费一次到期的重试预算
        """
        self._poll(1000)
        self.clock.time.return_value = 4600
        barrier = Barrier(3)
        errors = []

        def poll():
            try:
                barrier.wait(timeout=2)
                self.helper.pull_status_to_task()
            except Exception as error:
                errors.append(error)

        workers = [Thread(target=poll) for _ in range(2)]
        for worker in workers:
            worker.start()
        barrier.wait(timeout=2)
        for worker in workers:
            worker.join(timeout=2)
            self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(self.client.clouddownload_task_restart.call_count, 1)

    def test_transfer_lookup_failure_can_recover_on_next_poll(self) -> None:
        """
        下载成功但文件查询暂时失败时保留整理关联，下一轮可继续交接
        """
        self._add_transfer()
        self.tasks[0]["status"] = 2
        attrs = self.namespace["get_attr"]
        attrs.side_effect = [OSError("temporary"), attrs.return_value]
        self._poll(1000)
        self.assertEqual(len(self.helper.transfer_list), 1)
        self._poll(1120)
        self.monitor.media_transfer.assert_called_once()
        self.assertEqual(self.helper.transfer_list, [])

    def test_real_client_restart_uses_original_hash(self) -> None:
        """
        使用锁定版本的真实客户端验证重启请求参数，禁止真实网络请求
        """
        self.client = P115Client("UID=115_A1; CID=test; SEID=test")
        self.helper = self._helper()
        self._poll(1000)
        with patch.object(
            P115Client, "request", return_value={"state": True}
        ) as request:
            self._poll(4600)
        request.assert_called_once()
        kwargs = request.call_args.kwargs
        self.assertEqual(kwargs["data"], {"info_hash": "abc", "ac": "restart"})
        self.assertEqual(kwargs["url"], "https://clouddownload.115.com/web/")
        self.assertEqual(kwargs["method"], "POST")
