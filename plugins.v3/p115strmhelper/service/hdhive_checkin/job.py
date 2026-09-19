from datetime import datetime
from time import sleep
from typing import Tuple

from pytz import timezone as pytz_timezone

from app.core.config import settings
from app.log import logger
from app.schemas import NotificationType

from ...core.config import configer
from ...core.message import post_message
from ...helper.hdhive.browser import HDHiveError, HDHivePlaywrightClient
from ...utils.sentry import sentry_manager
from .scheduler import _KEY_LAST_DONE

_HDHIVE_CHECKIN_MAX_RETRIES = 3
_HDHIVE_CHECKIN_RETRY_DELAY = 3


@sentry_manager.capture_plugin_exceptions
def run_hdhive_checkin_once(
    manual: bool = False,
    send_notify: bool = True,
) -> Tuple[bool, str]:
    """
    使用浏览器自动化登录 HDHive 并执行签到（cloakbrowser 或 Playwright）

    :param manual: 为 True 时表示远程命令触发，不强制要求已开启每日/赌狗开关
    :param send_notify: 是否在结果时按全局通知开关发送插件消息
    :return: (是否成功, 说明文案)
    """
    if not configer.enabled:
        return False, "插件未启用"

    user = (configer.hdhive_checkin_username or "").strip()
    pwd = (configer.hdhive_checkin_password or "").strip()
    if not user or not pwd:
        msg = "未配置 HDHive 账户或密码"
        logger.warning("【HDHive 签到】%s", msg)
        return False, msg

    if not manual:
        if (
            not configer.hdhive_checkin_daily_enabled
            and not configer.hdhive_checkin_gamble_enabled
        ):
            return False, "未启用每日或赌狗签到"

    gamble = bool(configer.hdhive_checkin_gamble_enabled)
    if (
        manual
        and not configer.hdhive_checkin_daily_enabled
        and not configer.hdhive_checkin_gamble_enabled
    ):
        gamble = False
        logger.info("【HDHive 签到】手动触发：每日/赌狗均未开启，按每日签到执行")

    client = HDHivePlaywrightClient(headless=True)
    client.set_credentials(user, pwd)
    try:
        label = "赌狗签到" if gamble else "每日签到"
        ok = False
        detail = ""
        for attempt in range(1, _HDHIVE_CHECKIN_MAX_RETRIES + 1):
            ok, detail = client.checkin(gamble=gamble)
            if ok:
                logger.info("【HDHive 签到】%s 成功：%s", label, detail)
                if manual:
                    tz = pytz_timezone(settings.TZ)
                    today_str = datetime.now(tz=tz).strftime("%Y-%m-%d")
                    configer.save_plugin_data(_KEY_LAST_DONE, today_str)
                break
            if attempt < _HDHIVE_CHECKIN_MAX_RETRIES:
                logger.warning(
                    "【HDHive 签到】%s 第 %d/%d 次尝试失败：%s，%d 秒后重试",
                    label,
                    attempt,
                    _HDHIVE_CHECKIN_MAX_RETRIES,
                    detail,
                    _HDHIVE_CHECKIN_RETRY_DELAY,
                )
                sleep(_HDHIVE_CHECKIN_RETRY_DELAY)
            else:
                logger.warning(
                    "【HDHive 签到】%s 已重试 %d 次仍失败：%s",
                    label,
                    _HDHIVE_CHECKIN_MAX_RETRIES,
                    detail,
                )

        if send_notify and configer.notify:
            post_message(
                mtype=NotificationType.Plugin,
                title=f"HDHive {label} {'成功' if ok else '失败'}",
                text="\n" + detail + "\n",
            )
        return ok, detail
    except HDHiveError as e:
        logger.error("【HDHive 签到】登录异常：%s", e, exc_info=True)
        err = str(e)
        if send_notify and configer.notify:
            post_message(
                mtype=NotificationType.Plugin,
                title="HDHive 签到失败",
                text="\n" + err + "\n",
            )
        return False, err
    except Exception as e:
        logger.error("【HDHive 签到】执行异常：%s", e, exc_info=True)
        err = str(e)
        if send_notify and configer.notify:
            post_message(
                mtype=NotificationType.Plugin,
                title="HDHive 签到异常",
                text="\n" + err + "\n",
            )
        return False, err
