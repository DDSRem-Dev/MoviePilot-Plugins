from datetime import date, datetime, timedelta
from random import uniform
from re import fullmatch as re_fullmatch
from typing import Optional, Tuple

from pytz import timezone as pytz_timezone

from app.log import logger
from app.core.config import settings

from ...core.config import configer

_KEY_NEXT_RUN = "hdhive_checkin_next_run_ts"
_KEY_LAST_DONE = "hdhive_checkin_last_done_date"


def _tz():
    return pytz_timezone(settings.TZ)


def _parse_window_for_date(d: date, tz) -> Tuple[datetime, datetime]:
    """
    将配置的 HH:MM-HH:MM 转为当日本地时区起止时间
    """
    s = (configer.hdhive_checkin_time_range or "06:00-09:00").strip()
    m = re_fullmatch(
        r"([01]\d|2[0-3]):([0-5]\d)-([01]\d|2[0-3]):([0-5]\d)",
        s,
    )
    if not m:
        h1, m1, h2, m2 = 6, 0, 9, 0
    else:
        h1, m1, h2, m2 = (
            int(m.group(1)),
            int(m.group(2)),
            int(m.group(3)),
            int(m.group(4)),
        )
    start = tz.localize(datetime(d.year, d.month, d.day, h1, m1, 0))
    end = tz.localize(datetime(d.year, d.month, d.day, h2, m2, 0))
    return start, end


def _random_epoch_for_date(d: date, tz) -> float:
    """
    在指定日期的窗口内均匀随机一个时刻
    """
    ws, we = _parse_window_for_date(d, tz)
    return uniform(ws.timestamp(), we.timestamp())


def _pick_next_run_epoch(now: datetime, tz) -> float:
    """
    根据当前时刻，在「当日或次日」窗口内随机下一次执行时间
    """
    today = now.date()
    ws, we = _parse_window_for_date(today, tz)
    tomorrow = today + timedelta(days=1)
    wsn, wen = _parse_window_for_date(tomorrow, tz)

    if now < ws:
        return uniform(ws.timestamp(), we.timestamp())
    if now < we:
        return uniform(max(now.timestamp(), ws.timestamp()), we.timestamp())
    return uniform(wsn.timestamp(), wen.timestamp())


def _should_schedule() -> bool:
    if not configer.enabled:
        return False
    user = (configer.hdhive_checkin_username or "").strip()
    pwd = (configer.hdhive_checkin_password or "").strip()
    if not user or not pwd:
        return False
    if (
        not configer.hdhive_checkin_daily_enabled
        and not configer.hdhive_checkin_gamble_enabled
    ):
        return False
    return True


def hdhive_checkin_scheduler_tick() -> None:
    """
    由 cron（如每 5 分钟）调用：维护 next_run 并在到期时执行签到
    """
    if not _should_schedule():
        return

    tz = _tz()
    now = datetime.now(tz=tz)
    today_str = now.strftime("%Y-%m-%d")

    last_done = configer.get_plugin_data(_KEY_LAST_DONE)
    if isinstance(last_done, str):
        last_done = last_done.strip()
    else:
        last_done = None

    raw_next = configer.get_plugin_data(_KEY_NEXT_RUN)
    next_ts: Optional[float]
    try:
        if raw_next is None:
            next_ts = None
        elif isinstance(raw_next, (int, float)):
            next_ts = float(raw_next)
        else:
            next_ts = float(str(raw_next).strip())
    except (TypeError, ValueError):
        next_ts = None

    if last_done == today_str:
        if next_ts is not None:
            nr = datetime.fromtimestamp(next_ts, tz=tz)
            if nr.date() > now.date():
                return
        tomorrow_d = (now + timedelta(days=1)).date()
        configer.save_plugin_data(_KEY_NEXT_RUN, _random_epoch_for_date(tomorrow_d, tz))
        return

    if next_ts is None:
        nxt = _pick_next_run_epoch(now, tz)
        configer.save_plugin_data(_KEY_NEXT_RUN, nxt)
        logger.debug("【HDHive 签到】已安排下次执行时间戳 %s", nxt)
        next_ts = nxt

    if now.timestamp() < next_ts:
        return

    from .job import run_hdhive_checkin_once

    ok, _detail = run_hdhive_checkin_once(manual=False, send_notify=True)
    if ok:
        configer.save_plugin_data(_KEY_LAST_DONE, today_str)
        tomorrow_d = (now + timedelta(days=1)).date()
        configer.save_plugin_data(
            _KEY_NEXT_RUN,
            _random_epoch_for_date(tomorrow_d, tz),
        )
    else:
        configer.save_plugin_data(_KEY_NEXT_RUN, None)
