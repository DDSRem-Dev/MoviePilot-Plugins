from datetime import datetime
from typing import Any, Dict, List, Set

from p115client import P115Client, check_response

from app.sdk.logging import logger

from ...core.config import configer


class OfflineRetryManager:
    """
    按插件实例和网盘账号持久化离线重试预算及待整理任务

    调用方须串行访问，重试请求发出前保存次数以防进程退出后重复提交
    """

    def __init__(self, client: P115Client) -> None:
        self.client = client
        self._key = f"offline_tasks_{client.user_id}"
        state = configer.get_plugin_data(self._key) or {}
        self.records: Dict[str, Dict[str, Any]] = state.get("retries", {})
        self.transfers: List[Dict[str, Any]] = state.get("transfers", [])

    def save(self) -> None:
        """
        保存重试记录与原下载目录的整理关联
        """
        configer.save_plugin_data(
            self._key, {"retries": self.records, "transfers": self.transfers}
        )

    def prune(self, hashes: Set[str]) -> None:
        """
        在完整获取列表后清理已删除任务的本地记录
        """
        removed = set(self.records) - hashes
        transfers = [item for item in self.transfers if item["hash"] in hashes]
        if removed or len(transfers) != len(self.transfers):
            for info_hash in removed:
                del self.records[info_hash]
            self.transfers[:] = transfers
            self.save()

    def process(self, task: Dict[str, Any], now: float) -> bool:
        """
        处理单个任务，返回是否需要保留失败任务的整理关联

        :param task (Dict): 115 返回的原始任务
        :param now (float): 当前时间戳

        :return bool: 等待重试或已提交重试时为 True
        """
        info_hash = str(task["info_hash"])
        status = int(task.get("status", -1))
        if status == 2:
            if self.records.pop(info_hash, None) is not None:
                self.save()
            return False
        if status != 1 or not configer.offline_retry_enabled:
            return False
        record = self.records.get(info_hash)
        if record and record["exhausted"]:
            return False
        if record:
            if now < record["next_retry_at"]:
                return True
            if record["attempts"] >= configer.offline_retry_max_attempts:
                record["exhausted"] = True
                self.save()
                logger.warning(
                    f"【离线下载】{info_hash} 自动重试 {record['attempts']} 次后仍失败，停止重试"
                )
                return False
        if "retry" not in (task.get("available_actions") or []):
            return False

        interval = configer.offline_retry_interval_hours * 3600
        if record is None:
            self.records[info_hash] = {
                "attempts": 0,
                "next_retry_at": now + interval,
                "exhausted": False,
            }
            self.save()
            return True
        record["attempts"] += 1
        record["next_retry_at"] = now + interval
        # 超时也消耗次数，因为服务器可能已执行请求而客户端未收到响应
        self.save()
        try:
            check_response(
                self.client.clouddownload_task_restart(
                    info_hash, type="web", **configer.get_ios_ua_app(app=False)
                )
            )
            logger.info(
                f"【离线下载】{info_hash} 已提交第 {record['attempts']} 次自动重试"
            )
        except Exception:
            logger.error(
                f"【离线下载】{info_hash} 第 {record['attempts']} 次自动重试请求失败",
                exc_info=True,
            )
        return True

    def status_text(self, task: Dict[str, Any], fallback: str) -> str:
        """
        为失败任务展示等待时间、已用次数或重试终止原因

        :return str: 离线任务列表中的状态文本
        """
        if int(task.get("status", -1)) != 1:
            return fallback
        record = self.records.get(str(task.get("info_hash", "")))
        if record and record["exhausted"]:
            return f"下载失败（已重试 {record['attempts']} 次，停止重试）"
        if not configer.offline_retry_enabled:
            return fallback
        if "retry" not in (task.get("available_actions") or []):
            return "下载失败（115 不支持重试）"
        if record:
            scheduled = datetime.fromtimestamp(record["next_retry_at"]).strftime(
                "%m-%d %H:%M"
            )
            return f"下载失败（已重试 {record['attempts']} 次，{scheduled} 后检查重试）"
        return "下载失败（等待安排重试）"
