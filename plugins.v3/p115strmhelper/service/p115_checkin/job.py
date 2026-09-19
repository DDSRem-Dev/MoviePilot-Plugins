from time import sleep
from typing import Tuple

from p115client import check_response

from app.log import logger
from app.schemas import NotificationType

from ...core.config import configer
from ...core.message import post_message
from ...utils.sentry import sentry_manager

_P115_CHECKIN_MAX_RETRIES = 3
_P115_CHECKIN_RETRY_DELAY = 3


@sentry_manager.capture_plugin_exceptions
def run_p115_checkin_once(
    client,
    manual: bool = False,
    send_notify: bool = True,
) -> Tuple[bool, str]:
    """
    调用 115 签到 API 执行每日签到

    :param client: P115Client 实例
    :param manual: 为 True 时表示远程命令触发，不强制要求已开启每日签到
    :param send_notify: 是否在结果时按全局通知开关发送插件消息
    :return: (是否成功, 说明文案)
    """
    if not configer.enabled:
        return False, "插件未启用"

    if not configer.p115_checkin_enabled and not manual:
        return False, "115 每日签到未启用"

    if not client:
        return False, "115 客户端未初始化"

    try:
        logger.info("【115 签到】查询今日签到状态...")
        status_resp = check_response(client.user_points_sign())
        if status_resp.get("data", {}).get("is_sign_today") == 1:
            msg = "今日已签到，无需重复签到"
            logger.info("【115 签到】%s", msg)
            return True, msg

        logger.info("【115 签到】执行签到...")
        ok = False
        detail = ""
        for attempt in range(1, _P115_CHECKIN_MAX_RETRIES + 1):
            try:
                resp = check_response(client.user_points_sign_post())
                data = resp.get("data", {})
                continuous_day = data.get("continuous_day", 0)
                points_num = data.get("points_num", 0)
                detail = (
                    f"签到成功，连续签到 {continuous_day} 天，获得 {points_num} 积分"
                )
                logger.info("【115 签到】%s", detail)
                ok = True
                break
            except Exception as e:
                logger.warning(
                    "【115 签到】第 %d/%d 次尝试失败：%s，%d 秒后重试",
                    attempt,
                    _P115_CHECKIN_MAX_RETRIES,
                    e,
                    _P115_CHECKIN_RETRY_DELAY,
                )
                detail = str(e)
                if attempt < _P115_CHECKIN_MAX_RETRIES:
                    sleep(_P115_CHECKIN_RETRY_DELAY)

        if send_notify and configer.notify:
            post_message(
                mtype=NotificationType.Plugin,
                title="115 签到" + ("成功" if ok else "失败"),
                text="\n" + detail + "\n",
            )
        return ok, detail

    except Exception as e:
        logger.error("【115 签到】执行异常：%s", e, exc_info=True)
        err = str(e)
        if send_notify and configer.notify:
            post_message(
                mtype=NotificationType.Plugin,
                title="115 签到异常",
                text="\n" + err + "\n",
            )
        return False, err
