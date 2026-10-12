from threading import Lock
from random import choice
from typing import Any, Dict, List, Optional, Union
from base64 import b64decode
from types import MethodType
from uuid import uuid4

from app.sdk.logging import logger
from app.schemas import MessageType, NotificationChannel
from app.sdk.utilities import StringUtils
from app.sdk.scheduler import add_plugin_once_job, remove_plugin_once_job

from ..core.config import configer
from ..core.i18n import i18n
from ..schemas.upload import UploadResult


_BATCH_DELAY = 60


def _message_text(text: Optional[str], language: Optional[str]) -> Optional[str]:
    if language != "zh_CN_catgirl":
        return text
    message = b64decode(choice(i18n.get("fuck")).encode("utf-8")).decode("utf-8")
    if text:
        return text + (f"\n{message}\n" if text.endswith("\n") else f"\n{message}")
    return f"\n{message}\n"


def post_message(
    channel: Optional[NotificationChannel] = None,
    mtype: Optional[MessageType] = None,
    title: Optional[str] = None,
    text: Optional[str] = None,
    image: Optional[str] = None,
    link: Optional[str] = None,
    userid: Optional[Union[str, int]] = None,
    username: Optional[Union[str, int]] = None,
    **kwargs: Any,
) -> None:
    """
    通过已绑定的宿主插件实例提交通知，由宿主决定路由和发送时机

    未指定链接时使用宿主生成的当前插件实例页面链接
    返回仅表示已提交，不表示远端渠道已投递成功
    """
    text = _message_text(text, configer.get_config("language"))
    configer.plugin_instance.post_message(
        channel=channel,
        mtype=mtype,
        title=title,
        text=text,
        image=image,
        link=link,
        userid=userid,
        username=username,
        **kwargs,
    )


class UploadNotifyAggregator:
    """
    使用宿主一次性调度的上传结果通知聚合器

    聚合器固定归属一个插件实例，关停后的迟到结果直接向该实例提交通知
    结果沿用原批次发送规则，由宿主记录延迟任务的执行失败
    """

    def __init__(self, plugin: Any = None) -> None:
        """
        创建未启动的聚合器，保留模块引用直至该插件实例卸载
        """
        self._results: List[UploadResult] = []
        self._lock = Lock()
        self._send_lock = Lock()
        self._plugin: Any = plugin
        self._job_id = f"upload_result_notification_{uuid4().hex}"
        self._language = "zh_CN"
        self._active = False
        self._scheduled = False
        self._generation = 0

    def start(self, plugin: Any) -> None:
        """
        绑定当前插件实例并恢复聚合，配置重载继续使用同一聚合器

        :param plugin (Any): 当前宿主插件实例，不允许替换为其他实例

        :raises RuntimeError: 尝试将同一聚合器绑定到另一插件实例
        """
        with self._lock:
            if self._plugin is not None and self._plugin is not plugin:
                raise RuntimeError("上传通知聚合器不能跨插件实例复用")
            self._plugin = plugin
            self._language = configer.get_config("language") or "zh_CN"
            self._active = True
            flush_now = bool(self._results) and not self._schedule_locked()
        if flush_now:
            self.flush()

    def add(
        self,
        success: bool,
        target_name: str,
        file_size: int,
        elapsed_time: Optional[float] = None,
        error_msg: Optional[str] = None,
    ) -> None:
        """
        添加上传结果

        :param success (bool): 是否成功
        :param target_name (str): 文件名
        :param file_size (int): 文件大小
        :param elapsed_time (float): 耗时（秒）
        :param error_msg (str): 错误信息
        """
        with self._lock:
            self._results.append(
                UploadResult(
                    success=success,
                    target_name=target_name,
                    file_size=file_size,
                    elapsed_time=elapsed_time,
                    error_msg=error_msg,
                )
            )
            if self._plugin is None:
                logger.error("【上传通知】聚合器尚未绑定插件，保留结果等待启动")
                return
            flush_now = not self._active or not self._schedule_locked()
        if flush_now:
            self.flush()

    def flush(self) -> bool:
        """
        取消待执行任务并串行提交当前结果

        :return bool: 结果已向宿主提交或当前无结果时返回 True
        """
        with self._send_lock:
            with self._lock:
                self._generation += 1
                self._cancel_locked()
            return self._drain()

    def shutdown(self) -> bool:
        """
        停止追加延迟任务并等待当前发送收口，再刷新待发结果

        :return bool: 当前可见结果均已向宿主提交时返回 True
        """
        with self._lock:
            self._active = False
            self._generation += 1
            self._cancel_locked()
        return self.flush()

    def _schedule_locked(self) -> bool:
        self._generation += 1
        generation = self._generation

        def execute(_plugin: Any) -> None:
            self._run(generation)

        try:
            accepted = add_plugin_once_job(
                plugin_id=self._plugin.__class__.__name__,
                job_id=self._job_id,
                func=MethodType(execute, self._plugin),
                name="上传结果聚合通知",
                delay_seconds=_BATCH_DELAY,
            )
            if accepted:
                self._scheduled = True
                return True
            logger.error("【上传通知】宿主未接受聚合任务")
        except Exception:
            logger.error("【上传通知】注册聚合任务失败", exc_info=True)
        return False

    def _cancel_locked(self) -> None:
        if not self._scheduled:
            return
        try:
            remove_plugin_once_job(
                plugin_id=self._plugin.__class__.__name__, job_id=self._job_id
            )
            self._scheduled = False
        except Exception:
            logger.error("【上传通知】移除待执行任务失败，旧回调已失效", exc_info=True)

    def _run(self, generation: int) -> None:
        with self._send_lock:
            with self._lock:
                if not self._active or generation != self._generation:
                    return
                self._scheduled = False
            if not self._drain():
                raise RuntimeError("上传聚合通知提交失败")

    def _drain(self) -> bool:
        with self._lock:
            if not self._results:
                return True
            if self._plugin is None:
                return False
            results = self._results.copy()
            self._results.clear()
        try:
            self._send_batch(results)
        except Exception:
            logger.error("【上传通知】提交失败", exc_info=True)
            return False
        return True

    def _send_batch(self, results: List[UploadResult]) -> None:
        successes = [r for r in results if r.success]
        failures = [r for r in results if not r.success]
        total = len(results)
        success_count = len(successes)
        fail_count = len(failures)

        if fail_count == 0:
            title = i18n.translate("upload_batch_title_success", count=total)
        elif success_count == 0:
            title = i18n.translate("upload_batch_title_fail", count=total)
        else:
            title = i18n.translate(
                "upload_batch_title_mixed",
                total=total,
                success=success_count,
                fail=fail_count,
            )

        lines: List[str] = []
        lines.append(
            i18n.translate(
                "upload_batch_summary",
                total=total,
                success=success_count,
                fail=fail_count,
            )
        )

        if successes:
            lines.append("")
            lines.append(
                i18n.translate("upload_batch_success_section", count=success_count)
            )
            for r in successes:
                size_str = StringUtils.str_filesize(r.file_size)
                time_str = (
                    i18n.translate("upload_time_seconds", sec=f"{r.elapsed_time:.1f}")
                    if r.elapsed_time
                    else i18n.translate("upload_time_unknown")
                )
                lines.append(f"  · {r.target_name}（{size_str}，耗时 {time_str}）")

        if failures:
            lines.append("")
            lines.append(i18n.translate("upload_batch_fail_section", count=fail_count))
            for r in failures:
                size_str = StringUtils.str_filesize(r.file_size)
                lines.append(f"  · {r.target_name}（{size_str}）")
                if r.error_msg:
                    lines.append(f"    {r.error_msg}")

        text = "\n".join(lines)
        self._plugin.post_message(
            mtype=MessageType.Plugin,
            title=title,
            text=_message_text(f"\n{text}\n", self._language),
        )
        logger.info(
            f"【上传通知】已发送聚合通知：共 {total} 个文件，"
            f"成功 {success_count} 个，失败 {fail_count} 个"
        )


class UploadNotificationManager:
    """
    按宿主对象管理聚合器，上传开始时捕获其通知所有者
    """

    def __init__(self) -> None:
        """
        创建实例聚合器索引
        """
        self._lock = Lock()
        self._notifiers: Dict[int, UploadNotifyAggregator] = {}

    def _get(self, plugin: Any) -> UploadNotifyAggregator:
        key = id(plugin)
        with self._lock:
            if key not in self._notifiers:
                self._notifiers[key] = UploadNotifyAggregator(plugin)
            return self._notifiers[key]

    def start(self, plugin: Any) -> None:
        """
        停止相同插件 ID 的旧对象，再启动当前对象的聚合器

        :param plugin (Any): 当前宿主插件实例
        """
        current = self._get(plugin)
        with self._lock:
            previous = [
                notifier
                for notifier in self._notifiers.values()
                if notifier is not current
                and notifier._plugin.__class__.__name__ == plugin.__class__.__name__
            ]
        for notifier in previous:
            notifier.shutdown()
        current.start(plugin)

    def capture(self) -> UploadNotifyAggregator:
        """
        在上传开始时取得当前实例的聚合器，后续始终使用该对象

        :return UploadNotifyAggregator: 固定所有者的上传通知聚合器
        """
        return self._get(configer.plugin_instance)

    def shutdown(self, plugin: Any) -> bool:
        """
        仅停止指定宿主对象的通知，不取消替换实例的任务

        :param plugin (Any): 要停止的宿主插件实例

        :return bool: 未创建聚合器或已成功提交当前批次时返回 True
        """
        with self._lock:
            notifier = self._notifiers.get(id(plugin))
        return notifier.shutdown() if notifier is not None else True


upload_notifier = UploadNotificationManager()
