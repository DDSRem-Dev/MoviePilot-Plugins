from threading import Lock, Timer
from random import choice
from typing import List, Optional
from base64 import b64decode

from app.core.config import settings
from app.log import logger
from app.schemas import Notification, NotificationType, MessageChannel
from app.utils.string import StringUtils

from ..core.config import configer
from ..core.i18n import i18n
from ..core.plunins import PluginChian
from ..schemas.upload import UploadResult


_BATCH_DELAY = 60


def post_message(
    channel: MessageChannel = None,
    mtype: NotificationType = None,
    title: Optional[str] = None,
    text: Optional[str] = None,
    image: Optional[str] = None,
    link: Optional[str] = None,
    userid: Optional[str] = None,
    username: Optional[str] = None,
    **kwargs,
):
    """
    发送消息
    """
    chain = PluginChian()
    if not link:
        link = settings.MP_DOMAIN(
            f"#/plugins?tab=installed&id={configer.get_config('PLUSIN_NAME')}"
        )
    if configer.get_config("language") == "zh_CN_catgirl":
        message = b64decode(choice(i18n.get("fuck")).encode("utf-8")).decode("utf-8")
        if text:
            if text.endswith("\n"):
                text += f"\n{message}\n"
            else:
                text += f"\n{message}"
        else:
            text = f"\n{message}\n"
    chain.post_message(
        Notification(
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
    )


class UploadNotifyAggregator:
    """
    上传结果通知聚合器
    """

    _instance: Optional["UploadNotifyAggregator"] = None
    _class_lock: Lock = Lock()

    def __new__(cls) -> "UploadNotifyAggregator":
        if cls._instance is None:
            with cls._class_lock:
                if cls._instance is None:
                    obj = super().__new__(cls)
                    obj._results: List[UploadResult] = []
                    obj._results_lock = Lock()
                    obj._timer: Optional[Timer] = None
                    obj._timer_lock = Lock()
                    cls._instance = obj
        return cls._instance

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

        :param success: 是否成功
        :param target_name: 文件名
        :param file_size: 文件大小
        :param elapsed_time: 耗时（秒）
        :param error_msg: 错误信息
        """
        with self._results_lock:
            self._results.append(
                UploadResult(
                    success=success,
                    target_name=target_name,
                    file_size=file_size,
                    elapsed_time=elapsed_time,
                    error_msg=error_msg,
                )
            )
        self._reset_timer()

    def flush(self) -> None:
        """
        立即刷新并发送通知
        """
        with self._timer_lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        self._send_batch()

    @classmethod
    def shutdown(cls) -> None:
        """
        插件停止时调用：刷新待发通知并重置单例，避免热重载后旧 Timer 残留
        """
        with cls._class_lock:
            instance = cls._instance
            cls._instance = None
        if instance is not None:
            instance.flush()

    def _reset_timer(self) -> None:
        delay = _BATCH_DELAY
        with self._timer_lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = Timer(delay, self._on_timer)
            self._timer.daemon = True
            self._timer.start()

    def _on_timer(self) -> None:
        with self._timer_lock:
            self._timer = None
        self._send_batch()

    def _send_batch(self) -> None:
        with self._results_lock:
            if not self._results:
                return
            results = self._results.copy()
            self._results.clear()

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
        post_message(
            mtype=NotificationType.Plugin,
            title=title,
            text=f"\n{text}\n",
        )
        logger.info(
            f"【上传通知】已发送聚合通知：共 {total} 个文件，"
            f"成功 {success_count} 个，失败 {fail_count} 个"
        )


upload_notifier = UploadNotifyAggregator()
