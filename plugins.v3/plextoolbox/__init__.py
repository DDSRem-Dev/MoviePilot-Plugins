"""PLEX 工具箱插件：Plex 302 反向代理 + STRM 媒体流信息补全。"""

import json
from threading import Lock, Thread
from time import monotonic, time
from typing import Any, Dict, List, Optional, Tuple

from fastapi import Request
from uvicorn import Config, Server

from app.sdk.logging import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType, NotificationType

try:
    from apscheduler.triggers.interval import IntervalTrigger
except Exception:
    IntervalTrigger = None

from .proxy_app import create_app
from .emby_client import EmbyClient
from .ffprobe_source import FfprobeSource
from .helper_client import HelperClient
from .mediainfo import MediaInfoCompleter
from .plex_client import PlexClient
from .poster_fixer import PosterFixer
from .scrape_tools import ScrapeTools


PIN_RULES_SEP = " => "


def _parse_pin_rules(raw: str) -> List[Tuple[str, str]]:
    """
    解析顶置路径规则字符串为 (路径前缀, 目标URL) 列表。

    :param raw: 多行文本，每行「路径前缀 => 目标URL」
    :return: 合法规则列表；非法行忽略并打日志
    """
    result: List[Tuple[str, str]] = []
    for line in (raw or "").strip().splitlines():
        line = line.strip()
        if not line:
            continue
        if PIN_RULES_SEP not in line:
            logger.warning('顶置规则格式错误，已忽略: %s', line)
            continue
        parts = line.split(PIN_RULES_SEP, 1)
        path_prefix = parts[0].strip()
        target_url = parts[1].strip()
        if not path_prefix or not target_url:
            logger.warning("顶置规则路径或目标为空，已忽略: %s", line)
            continue
        if not target_url.startswith(("http://", "https://")):
            logger.warning("顶置规则目标需以 http/https 开头，已忽略: %s", line)
            continue
        result.append((path_prefix, target_url))
    return result


class PlexToolbox(_PluginBase):
    """PLEX 工具箱：302 反向代理与 STRM 媒体流信息补全。"""

    plugin_name = "PLEX 工具箱"
    plugin_desc = "Plex 302 反向代理、STRM 媒体流信息补全（支持无 Emby 的 ffprobe 数据源）、缺海报修复与 TMDB 重复条目合并。"
    plugin_icon = "https://raw.githubusercontent.com/jxxghp/MoviePilot-Plugins/refs/heads/main/icons/Plex_A.png"
    plugin_version = "1.1.0"
    plugin_author = "shyblacktea,MoviePilot助手"
    author_url = "https://github.com/shyblacktea"
    plugin_config_prefix = "plextoolbox_"
    plugin_order = 20
    auth_level = 1

    # ---- 反代配置 ----
    _enabled = False
    _proxy_enabled = False
    _plex_host = ""
    _plex_token = ""
    _host = "0.0.0.0"
    _port = 32401
    _pin_rules: List[Tuple[str, str]] = []
    _pin_rules_raw = ""
    _force_direct_play = True
    _server = None
    _thread = None

    # ---- 媒体信息补全配置 ----
    _mediainfo_enabled = False
    _plex_direct_host = ""
    _helper_url = ""
    _helper_token = ""
    _emby_url = ""
    _emby_apikey = ""
    _use_emby = True
    _use_ffprobe = True
    # Plex 主机路径 => MoviePilot 容器路径；默认值适配当前部署
    _ffprobe_path_map = "/Volumes/data=/media"
    _ffprobe_timeout = 40
    _overwrite_streams = True
    _only_missing = True
    _concurrency = 3
    _sections = ""
    _running = False

    # ---- 自动补全触发配置 ----
    _webhook_enabled = False
    _dedup_window = 300
    _forward_episodes = 5
    # ratingKey -> 上次触发的单调时间戳，用于去重
    _recent_triggers: Dict[str, float] = {}
    _trigger_lock = Lock()
    _helper_health_failures = 0
    _helper_health_alerted = False
    _helper_health_ok: Optional[bool] = None

    def _proxy_signature(self) -> Tuple:
        """
        构建反代相关配置的签名，用于判断保存配置后是否需要重启代理。

        :return: 反代配置签名元组
        """
        return (
            self._enabled,
            self._proxy_enabled,
            self._plex_host,
            self._plex_token,
            self._host,
            self._port,
            self._pin_rules_raw,
            self._force_direct_play,
            self._dedup_window,
        )

    def init_plugin(self, config: Optional[Dict[str, Any]] = None) -> None:
        """
        初始化插件：解析配置，按需启动 302 代理。

        仅当反代相关配置发生变化（或代理未在运行）时才重启代理，
        避免每次保存补全配置都导致 Plex 播放断链。

        :param config: 插件配置字典
        """
        old_sig = self._proxy_signature()
        if config:
            self._enabled = config.get("enabled", False)
            # 反代
            self._proxy_enabled = config.get("proxy_enabled", False)
            self._plex_host = (config.get("plex_host") or "").strip()
            self._plex_token = (config.get("plex_token") or "").strip()
            self._host = (config.get("host") or "0.0.0.0").strip() or "0.0.0.0"
            try:
                self._port = int(config.get("port") or 32401)
            except (TypeError, ValueError):
                self._port = 32401
            self._pin_rules_raw = (config.get("pin_rules") or "").strip()
            self._pin_rules = _parse_pin_rules(self._pin_rules_raw)
            self._force_direct_play = config.get("force_direct_play", True)
            # 媒体信息补全
            self._mediainfo_enabled = config.get("mediainfo_enabled", False)
            self._plex_direct_host = (config.get("plex_direct_host") or "").strip()
            self._helper_url = (config.get("helper_url") or "").strip()
            self._helper_token = (config.get("helper_token") or "").strip()
            self._emby_url = (config.get("emby_url") or "").strip()
            self._emby_apikey = (config.get("emby_apikey") or "").strip()
            self._use_emby = config.get("use_emby", True)
            self._use_ffprobe = config.get("use_ffprobe", True)
            ffprobe_path_map = config.get("ffprobe_path_map")
            self._ffprobe_path_map = (
                "/Volumes/data=/media"
                if ffprobe_path_map is None
                else str(ffprobe_path_map).strip()
            )
            try:
                self._ffprobe_timeout = max(
                    1, min(300, int(config.get("ffprobe_timeout") or 40))
                )
            except (TypeError, ValueError):
                self._ffprobe_timeout = 40
            self._overwrite_streams = config.get("overwrite_streams", True)
            self._only_missing = config.get("only_missing", True)
            try:
                self._concurrency = int(config.get("concurrency") or 3)
            except (TypeError, ValueError):
                self._concurrency = 3
            self._sections = (config.get("sections") or "").strip()
            # 自动补全触发
            self._webhook_enabled = config.get("webhook_enabled", False)
            try:
                self._dedup_window = int(config.get("dedup_window") or 300)
            except (TypeError, ValueError):
                self._dedup_window = 300
            try:
                self._forward_episodes = int(config.get("forward_episodes") or 5)
            except (TypeError, ValueError):
                self._forward_episodes = 5
            self._update_config()

        # 仅当反代相关配置变化或代理未运行时才重启代理，避免保存补全配置导致断链
        new_sig = self._proxy_signature()
        proxy_running = self._server is not None
        if new_sig != old_sig or not proxy_running:
            self.stop_service()
            self._start_proxy()

    def _start_proxy(self) -> None:
        """按配置启动 302 反向代理服务。"""
        if not (self._enabled and self._proxy_enabled and self._plex_host):
            if self._enabled and self._proxy_enabled and not self._plex_host:
                logger.warning("PlexToolbox 反代已启用但未配置 Plex 地址")
            return
        if not self._plex_host.startswith(("http://", "https://")):
            self._plex_host = "http://" + self._plex_host
        app = create_app(
            self._plex_host,
            plex_token=self._plex_token,
            pin_rules=self._pin_rules,
            force_direct_play=self._force_direct_play,
            preplay_cooldown_seconds=self._dedup_window,
            on_pre_play=self._on_pre_play_from_proxy,
        )
        try:
            uv_config = Config(app=app, host=self._host, port=self._port, log_config=None)
            self._server = Server(uv_config)
            self._thread = Thread(target=self._server.run, daemon=True)
            self._thread.start()
            logger.info(
                "PlexToolbox 302 代理已启动: %s:%s -> %s",
                self._host, self._port, self._plex_host,
            )
        except Exception as e:
            logger.error("PlexToolbox 代理启动失败: %s", e, exc_info=True)
            self._server = None
            self._thread = None

    def _update_config(self) -> None:
        """将当前配置写回插件配置存储。"""
        self.update_config(
            {
                "enabled": self._enabled,
                "proxy_enabled": self._proxy_enabled,
                "plex_host": self._plex_host,
                "plex_token": self._plex_token,
                "host": self._host,
                "port": self._port,
                "pin_rules": self._pin_rules_raw,
                "force_direct_play": self._force_direct_play,
                "mediainfo_enabled": self._mediainfo_enabled,
                "plex_direct_host": self._plex_direct_host,
                "helper_url": self._helper_url,
                "helper_token": self._helper_token,
                "emby_url": self._emby_url,
                "emby_apikey": self._emby_apikey,
                "use_emby": self._use_emby,
                "use_ffprobe": self._use_ffprobe,
                "ffprobe_path_map": self._ffprobe_path_map,
                "ffprobe_timeout": self._ffprobe_timeout,
                "overwrite_streams": self._overwrite_streams,
                "only_missing": self._only_missing,
                "concurrency": self._concurrency,
                "sections": self._sections,
                "webhook_enabled": self._webhook_enabled,
                "dedup_window": self._dedup_window,
                "forward_episodes": self._forward_episodes,
            }
        )

    def _build_completer(self, force_write: bool = False) -> Optional[MediaInfoCompleter]:
        """
        根据配置构建媒体信息补全器。

        :param force_write: 是否忽略 Plex 繁忙强制写入
        :return: 补全器实例，配置不全返回 None
        """
        plex_host = self._plex_direct_host or self._plex_host
        if not plex_host or not self._plex_token:
            logger.warning("PlexToolbox 补全缺少 Plex 直连地址或 token")
            return None
        if not self._helper_url:
            logger.warning("PlexToolbox 补全缺少 helper 地址")
            return None
        if not plex_host.startswith(("http://", "https://")):
            plex_host = "http://" + plex_host
        plex = PlexClient(plex_host, self._plex_token)
        helper = HelperClient(self._helper_url, self._helper_token)
        emby = None
        if self._use_emby and self._emby_url and self._emby_apikey:
            emby = EmbyClient(self._emby_url, self._emby_apikey)
        ffprobe = (
            FfprobeSource(
                path_map=self._ffprobe_path_map,
                timeout=self._ffprobe_timeout,
            )
            if self._use_ffprobe
            else None
        )
        return MediaInfoCompleter(
            plex=plex,
            helper=helper,
            emby=emby,
            use_emby=self._use_emby,
            overwrite_streams=self._overwrite_streams,
            concurrency=self._concurrency,
            force_write=force_write,
            ffprobe=ffprobe,
            use_ffprobe=self._use_ffprobe,
        )

    def run_completion(
        self, source: str = "manual", force_write: bool = False,
        section_keys: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        执行媒体信息补全流程并持久化最近结果。

        :param source: 触发来源（manual/schedule/api）
        :param force_write: 是否忽略 Plex 繁忙强制写入
        :param section_keys: 指定分区 key；缺省用配置中的 sections
        :return: 汇总结果
        """
        if self._running:
            return {"success": False, "error": "已有补全任务在运行"}
        completer = self._build_completer(force_write=force_write)
        if not completer:
            return {"success": False, "error": "补全配置不完整"}
        keys = section_keys or [
            s.strip() for s in self._sections.split(",") if s.strip()
        ]
        if not keys:
            return {"success": False, "error": "未指定要处理的 Plex 媒体库"}
        self._running = True
        try:
            summary = completer.run(keys, only_missing=self._only_missing)
            summary["success"] = True
            summary["source"] = source
            self.save_data("last_result", summary)
            logger.info("PlexToolbox 补全完成: %s", summary)
            return summary
        except Exception as e:
            logger.error("PlexToolbox 补全异常: %s", e, exc_info=True)
            return {"success": False, "error": str(e)}
        finally:
            self._running = False

    def _should_trigger(self, rating_key: str) -> bool:
        """
        判断某 ratingKey 是否可触发补全（去重窗口内不重复触发）。

        :param rating_key: Plex 条目 ratingKey
        :return: True 表示允许触发并已记录时间戳
        """
        now = monotonic()
        with self._trigger_lock:
            # 顺带清理过期记录
            expired = [
                k for k, ts in self._recent_triggers.items()
                if now - ts > self._dedup_window
            ]
            for k in expired:
                self._recent_triggers.pop(k, None)
            last = self._recent_triggers.get(rating_key)
            if last is not None and now - last <= self._dedup_window:
                return False
            self._recent_triggers[rating_key] = now
            return True

    def _append_play_history(self, summary: Dict[str, Any]) -> None:
        """
        将一次增量补全结果追加到播放补全历史（保留最近若干条），供数据页展示。

        :param summary: run_rating_key 的汇总结果
        """
        try:
            history = self.get_data("play_history") or []
            if not isinstance(history, list):
                history = []
            entry = {
                "ts": int(summary.get("ts") or time()),
                "rating_key": summary.get("rating_key"),
                "label": summary.get("label") or "",
                "source": summary.get("source"),
                "strm_parts": summary.get("strm_parts", 0),
                "resolved": summary.get("resolved", 0),
                "emby_hits": summary.get("emby_hits", 0),
                "ffprobe_hits": summary.get("ffprobe_hits", 0),
                "written_ok": summary.get("written_ok", 0),
                "write_failed": summary.get("write_failed", 0),
                "unresolved": summary.get("unresolved", 0),
                "helper_busy": summary.get("helper_busy", False),
                # 逐条明细（label+状态），最多留 20 条防膨胀
                "items": (summary.get("items") or [])[:20],
            }
            history.insert(0, entry)
            self.save_data("play_history", history[:50])
        except Exception as exc:
            logger.debug("PlexToolbox 记录播放补全历史失败: %s", exc)

    def _rating_key_in_selected_sections(self, rating_key: str) -> bool:
        """检查单条播放补全是否属于用户已选择的 Plex 媒体库。"""
        selected = {item.strip() for item in self._sections.split(",") if item.strip()}
        if not selected:
            logger.info("PlexToolbox 跳过单条补全：未选择 Plex 媒体库 ratingKey=%s", rating_key)
            return False
        plex_host = self._plex_direct_host or self._plex_host
        if not plex_host or not self._plex_token:
            return False
        if not plex_host.startswith(("http://", "https://")):
            plex_host = "http://" + plex_host
        section_key = PlexClient(plex_host, self._plex_token).item_section_key(rating_key)
        if not section_key:
            logger.warning("PlexToolbox 无法确认条目所属媒体库，跳过补全 ratingKey=%s", rating_key)
            return False
        if section_key not in selected:
            logger.info(
                "PlexToolbox 跳过单条补全：条目不在已选媒体库 ratingKey=%s section=%s",
                rating_key, section_key,
            )
            return False
        return True

    def complete_rating_key(self, rating_key: str, source: str = "webhook") -> None:
        """
        针对单个条目 ratingKey 触发补全，带去重，在后台线程执行。

        :param rating_key: Plex 条目 ratingKey
        :param source: 触发来源（webhook）
        """
        if not rating_key:
            return
        if not (self._enabled and self._mediainfo_enabled):
            return
        if not self._rating_key_in_selected_sections(str(rating_key)):
            return
        if not self._should_trigger(str(rating_key)):
            logger.debug("PlexToolbox 去重窗口内跳过 ratingKey=%s", rating_key)
            return

        def _worker() -> None:
            """后台线程执行单条补全。"""
            completer = self._build_completer(force_write=False)
            if not completer:
                return
            try:
                summary = completer.run_rating_key(
                    str(rating_key),
                    only_missing=self._only_missing,
                    forward=self._forward_episodes,
                )
                summary["success"] = True
                summary["source"] = source
                self.save_data("last_play_result", summary)
                self._append_play_history(summary)
                logger.info(
                    "PlexToolbox 条目补全完成 (%s) %s: 处理 %s, 写入 %s, 未命中 %s",
                    source,
                    summary.get("label") or f"ratingKey={rating_key}",
                    summary.get("strm_parts", 0),
                    summary.get("written_ok", 0),
                    summary.get("unresolved", 0),
                )
            except Exception as exc:
                logger.error(
                    "PlexToolbox 单条补全异常 ratingKey=%s: %s",
                    rating_key, exc, exc_info=True,
                )

        Thread(target=_worker, daemon=True).start()

    def _on_pre_play_from_proxy(self, rating_key: str) -> None:
        """
        反代播前回调（同步阻塞）：播放/继续观看起播前，先补全该条目媒体流信息。

        覆盖「继续观看」点击即播不经过详情页的场景。仅补当前条目本身
        当前条目与配置的后续集都在播放前处理。反代侧带等待预算，
        超时自动放行播放，补全任务转后台继续。

        :param rating_key: 即将播放条目的 ratingKey
        """
        if not (self._enabled and self._mediainfo_enabled):
            return
        if not self._rating_key_in_selected_sections(str(rating_key)):
            return
        completer = self._build_completer(force_write=True)
        if not completer:
            return
        try:
            summary = completer.run_rating_key(
                str(rating_key), only_missing=True, forward=self._forward_episodes,
            )
            summary["success"] = True
            summary["source"] = "pre_play"
            summary["ts"] = int(time())
            self.save_data("last_play_result", summary)
            self._append_play_history(summary)
            if summary.get("written_ok"):
                logger.info(
                    "PlexToolbox 播前补全 %s: 写入 %s 条",
                    summary.get("label") or f"ratingKey={rating_key}",
                    summary.get("written_ok"),
                )
        except Exception as exc:
            logger.debug("PlexToolbox 播前补全异常 ratingKey=%s: %s", rating_key, exc)

    def get_state(self) -> bool:
        """返回插件启用状态。"""
        return self._enabled

    @staticmethod
    def get_render_mode() -> Tuple[str, Optional[str]]:
        """声明使用 Vue 联邦组件渲染。"""
        return "vue", "dist/assets"

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """返回插件远程命令列表。"""
        return [
            {
                "cmd": "/ptbox",
                "event": EventType.PluginAction,
                "desc": "PLEX 工具箱媒体信息补全",
                "category": "PLEX 工具箱",
                "data": {"action": "plextoolbox_complete"},
            }
        ]

    def get_service(self) -> List[Dict[str, Any]]:
        """返回 Helper 健康检查服务。"""
        if not (self._enabled and self._mediainfo_enabled and self._helper_url):
            return []
        trigger = IntervalTrigger(minutes=5) if IntervalTrigger else "*/5 * * * *"
        return [
            {
                "id": "plextoolbox_helper_health",
                "name": "PLEX 工具箱 Helper 健康检查",
                "trigger": trigger,
                "func": self.check_helper_health,
            }
        ]

    def check_helper_health(self) -> None:
        """每 5 分钟检查 Helper；连续失败 3 次后仅告警一次。"""
        healthy = HelperClient(self._helper_url, self._helper_token).health()
        self._helper_health_ok = healthy
        if healthy:
            if self._helper_health_failures:
                logger.info("PlexToolbox Helper 已恢复正常")
            self._helper_health_failures = 0
            self._helper_health_alerted = False
            return
        self._helper_health_failures += 1
        logger.warning("PlexToolbox Helper 健康检查失败：连续 %s 次", self._helper_health_failures)
        if self._helper_health_failures >= 3 and not self._helper_health_alerted:
            self.post_message(
                mtype=NotificationType.Plugin,
                title="PLEX 工具箱 Helper 异常",
                text="Helper 连续 3 次检测失败（约 15 分钟），请检查 Helper 服务和网络连接。",
            )
            self._helper_health_alerted = True

    def get_api(self) -> List[Dict[str, Any]]:
        """返回插件前端调用的 API 列表。"""
        return [
            {"path": "/status", "endpoint": self.status_api, "methods": ["GET"], "auth": "bear", "summary": "工具箱状态"},
            {"path": "/config", "endpoint": self.get_config_api, "methods": ["GET"], "auth": "bear", "summary": "获取插件配置"},
            {"path": "/config", "endpoint": self.save_config_api, "methods": ["POST"], "auth": "bear", "summary": "保存插件配置"},
            {"path": "/sections", "endpoint": self.sections_api, "methods": ["GET"], "auth": "bear", "summary": "获取 Plex 媒体库"},
            {"path": "/helper_check", "endpoint": self.helper_check_api, "methods": ["GET"], "auth": "bear", "summary": "检查 helper 连通与数据库"},
            {"path": "/complete", "endpoint": self.complete_api, "methods": ["POST"], "auth": "bear", "summary": "手动触发媒体信息补全"},
            {"path": "/result", "endpoint": self.result_api, "methods": ["GET"], "auth": "bear", "summary": "获取最近补全结果"},
            {"path": "/webhook", "endpoint": self.webhook_api, "methods": ["POST"], "auth": "apikey", "summary": "Plex Webhook 接收"},
            {"path": "/unmatch", "endpoint": self.unmatch_api, "methods": ["POST"], "auth": "bear", "summary": "一键取消匹配（重读 NFO）"},
            {"path": "/scan_cover", "endpoint": self.scan_cover_api, "methods": ["POST"], "auth": "bear", "summary": "扫描缺封面条目"},
            {"path": "/scrape", "endpoint": self.scrape_api, "methods": ["POST"], "auth": "bear", "summary": "对缺封面条目触发 MP 刮削"},
            {"path": "/fix_poster", "endpoint": self.fix_poster_api, "methods": ["POST"], "auth": "bear", "summary": "补全缺失的 poster.jpg（季海报复制/TMDB）"},
            {"path": "/clear_completion_data", "endpoint": self.clear_completion_data_api, "methods": ["POST"], "auth": "bear", "summary": "一键清理补全结果/播放补全历史"},
            {"path": "/merge_scan", "endpoint": self.merge_scan_api, "methods": ["GET"], "auth": "bear", "summary": "扫描重复条目"},
            {"path": "/merge_execute", "endpoint": self.merge_execute_api, "methods": ["POST"], "auth": "bear", "summary": "执行重复条目合并"},
        ]

    def get_config_api(self) -> Dict[str, Any]:
        """返回当前完整配置，供配置页与数据页共用。"""
        return {"success": True, "data": self.get_form()[1]}

    def save_config_api(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """保存完整配置并重新初始化插件，使新配置立即生效。"""
        payload = payload or {}
        try:
            merged = {**self.get_form()[1], **payload}
            self.update_config(merged)
            self.init_plugin(merged)
            return {"success": True, "message": "配置已保存"}
        except Exception as exc:
            logger.error("PlexToolbox 保存配置失败: %s", exc, exc_info=True)
            return {"success": False, "message": str(exc)}

    def status_api(self) -> Dict[str, Any]:
        """返回工具箱运行状态与配置概要。"""
        return {
            "success": True,
            "enabled": self._enabled,
            "proxy_enabled": self._proxy_enabled,
            "proxy_running": self._server is not None,
            "mediainfo_enabled": self._mediainfo_enabled,
            "running": self._running,
            "use_emby": self._use_emby,
            "use_ffprobe": self._use_ffprobe,
            "helper_health_ok": self._helper_health_ok,
            "helper_health_failures": self._helper_health_failures,
        }

    def sections_api(self) -> Dict[str, Any]:
        """获取 Plex 媒体库分区列表，供前端勾选。"""
        plex_host = self._plex_direct_host or self._plex_host
        if not plex_host or not self._plex_token:
            return {"success": False, "error": "未配置 Plex 直连地址或 token", "sections": []}
        if not plex_host.startswith(("http://", "https://")):
            plex_host = "http://" + plex_host
        try:
            sections = PlexClient(plex_host, self._plex_token).list_sections()
            return {"success": True, "sections": sections}
        except Exception as e:
            return {"success": False, "error": str(e), "sections": []}

    def helper_check_api(self) -> Dict[str, Any]:
        """检查 helper 连通性与数据库探测结果。"""
        if not self._helper_url:
            return {"success": False, "error": "未配置 helper 地址"}
        client = HelperClient(self._helper_url, self._helper_token)
        if not client.health():
            return {"success": False, "error": "helper 不可达"}
        info = client.dbinfo()
        return {"success": True, "health": True, "dbinfo": info}

    def complete_api(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """手动触发媒体信息补全。"""
        payload = payload or {}
        keys = payload.get("sections")
        force = bool(payload.get("force"))
        return self.run_completion(source="api", force_write=force, section_keys=keys)

    def result_api(self) -> Dict[str, Any]:
        """获取最近一次补全结果与播放增量补全历史。"""
        return {
            "success": True,
            "result": self.get_data("last_result") or {},
            "last_play_result": self.get_data("last_play_result") or {},
            "play_history": self.get_data("play_history") or [],
        }

    async def webhook_api(self, request: Request) -> Dict[str, Any]:
        """
        接收 Plex Webhook，识别 media.stop 事件并触发针对性补全。

        Plex Webhook 以 multipart/form-data 提交，payload 字段为 JSON 文本。
        仅当 webhook 开关开启时处理；只对 media.stop（可选 media.scrobble）触发。

        :param request: FastAPI 请求对象
        :return: 处理结果
        """
        if not (self._enabled and self._mediainfo_enabled and self._webhook_enabled):
            return {"success": False, "error": "webhook 未启用"}
        payload_text = ""
        try:
            form = await request.form()
            payload_text = form.get("payload") or ""
        except Exception:
            try:
                payload_text = (await request.body()).decode("utf-8", "replace")
            except Exception:
                payload_text = ""
        if not payload_text:
            return {"success": False, "error": "空 payload"}
        try:
            data = json.loads(payload_text)
        except Exception:
            return {"success": False, "error": "payload 非 JSON"}
        event = data.get("event") or ""
        if event not in ("media.stop", "media.scrobble"):
            return {"success": True, "skipped": event}
        rating_key = (data.get("Metadata") or {}).get("ratingKey")
        if not rating_key:
            return {"success": False, "error": "无 ratingKey"}
        self.complete_rating_key(str(rating_key), source="webhook")
        return {"success": True, "event": event, "ratingKey": rating_key}

    def _plex_direct(self) -> Optional[PlexClient]:
        """构建用于枚举/写操作的 Plex 直连客户端。"""
        plex_host = self._plex_direct_host or self._plex_host
        if not plex_host or not self._plex_token:
            return None
        if not plex_host.startswith(("http://", "https://")):
            plex_host = "http://" + plex_host
        return PlexClient(plex_host, self._plex_token)

    def _scrape_dir(self, dir_path: str) -> Dict[str, Any]:
        """
        调用 MoviePilot 对本地目录刮削生成 NFO+图片。

        :param dir_path: STRM 媒体目录绝对路径
        :return: {success: bool}
        """
        try:
            from pathlib import Path
            from app import schemas
            from app.chain.media import MediaChain

            p = Path(dir_path)
            if not p.is_dir():
                return {"success": False, "error": "目录不存在"}
            chain = MediaChain()
            context = chain.recognize_by_path(p.as_posix(), obtain_images=True)
            if not context or not context.media_info:
                return {"success": False, "error": "无法识别"}
            chain.scrape_metadata(
                fileitem=schemas.FileItem(
                    storage="local",
                    type="dir",
                    path=p.as_posix() + "/",
                    name=p.name,
                    basename=p.stem,
                    modify_time=p.stat().st_mtime,
                ),
                meta=context.meta_info,
                mediainfo=context.media_info,
                overwrite=False,
            )
            return {"success": True}
        except Exception as exc:
            logger.error("MP 刮削目录失败 %s: %s", dir_path, exc, exc_info=True)
            return {"success": False, "error": str(exc)}

    def unmatch_api(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        一键取消匹配 API：dry-run 统计或执行 unmatch（可选 rematch）。

        :param payload: {section, dry_run, rematch, limit}
        :return: 结果
        """
        payload = payload or {}
        section = str(payload.get("section") or "").strip()
        if not section:
            return {"success": False, "error": "未指定分区"}
        plex = self._plex_direct()
        if not plex:
            return {"success": False, "error": "未配置 Plex 直连地址或 token"}
        tools = ScrapeTools(plex)
        res = tools.unmatch_section(
            section,
            dry_run=bool(payload.get("dry_run", True)),
            rematch=bool(payload.get("rematch", True)),
            limit=int(payload.get("limit") or 0),
        )
        res["success"] = True
        return res

    def scan_cover_api(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        扫描分区缺封面条目 API。

        :param payload: {section}
        :return: 结果
        """
        payload = payload or {}
        section = str(payload.get("section") or "").strip()
        if not section:
            return {"success": False, "error": "未指定分区"}
        plex = self._plex_direct()
        if not plex:
            return {"success": False, "error": "未配置 Plex 直连地址或 token"}
        tools = ScrapeTools(plex)
        res = tools.scan_missing_cover(section)
        res["success"] = True
        # missing 列表可能较长，仅返回前 50 条明细
        res["missing"] = res.get("missing", [])[:50]
        return res

    def scrape_api(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        对缺封面条目调用 MP 刮削 API：dry-run 列目录或执行。

        :param payload: {section, dry_run, limit, unmatch_after}
        :return: 结果
        """
        payload = payload or {}
        section = str(payload.get("section") or "").strip()
        if not section:
            return {"success": False, "error": "未指定分区"}
        plex = self._plex_direct()
        if not plex:
            return {"success": False, "error": "未配置 Plex 直连地址或 token"}
        tools = ScrapeTools(plex)
        res = tools.scrape_missing(
            section,
            scrape_cb=self._scrape_dir,
            dry_run=bool(payload.get("dry_run", True)),
            limit=int(payload.get("limit") or 0),
            unmatch_after=bool(payload.get("unmatch_after", False)),
        )
        res["success"] = True
        return res

    def fix_poster_api(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        缺 poster.jpg 补全 API：dry-run 列出待修复条目或执行补全。

        电影从 TMDB 取海报（原产语言→zh→无字→任意）；剧集优先复制季内
        Season X/poster.jpg 到剧根，无则回退 TMDB。修复后自动 refresh。

        :param payload: {section, dry_run, limit}
        :return: 结果
        """
        payload = payload or {}
        section = str(payload.get("section") or "").strip()
        if not section:
            return {"success": False, "error": "未指定分区"}
        plex = self._plex_direct()
        if not plex:
            return {"success": False, "error": "未配置 Plex 直连地址或 token"}
        try:
            fixer = PosterFixer(plex)
            res = fixer.fix(
                section,
                dry_run=bool(payload.get("dry_run", True)),
                limit=int(payload.get("limit") or 0),
            )
            res["success"] = True
            # 明细可能较长，限制返回条数
            if "targets" in res:
                res["targets"] = res["targets"][:50]
            if "details" in res:
                res["details"] = res["details"][:50]
            return res
        except Exception as exc:
            logger.error("缺 poster 补全异常: %s", exc, exc_info=True)
            return {"success": False, "error": str(exc)}

    def clear_completion_data_api(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        清理补全数据 API：清理最近一次补全结果、播放补全结果或播放补全历史。

        :param payload: {target}，target 可选 'last_result'、'last_play_result'、'play_history'、'all'
        :return: 结果
        """
        payload = payload or {}
        target = str(payload.get("target") or "all").strip()
        cleared = []
        if target in ("last_result", "all"):
            self.save_data("last_result", None)
            cleared.append("last_result")
        if target in ("last_play_result", "all"):
            self.save_data("last_play_result", None)
            cleared.append("last_play_result")
        if target in ("play_history", "all"):
            self.save_data("play_history", [])
            cleared.append("play_history")
        if not cleared:
            return {"success": False, "error": f"未知的清理目标: {target}"}
        return {"success": True, "cleared": cleared, "message": f"已清理: {', '.join(cleared)}"}

    def merge_scan_api(self) -> Dict[str, Any]:
        """扫描 Plex 媒体库中 tmdb id 相同的重复条目。"""
        plex = self._plex_direct()
        if not plex:
            return {"success": False, "error": "未配置 Plex 直连地址或 token"}
        try:
            groups = plex.scan_duplicate_items(media_types=("movie", "show"))
            return {"success": True, "groups": groups, "total_groups": len(groups)}
        except Exception as exc:
            logger.error("PlexToolbox 扫描重复条目异常: %s", exc, exc_info=True)
            return {"success": False, "error": str(exc)}

    def merge_execute_api(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        执行重复条目合并 API。

        :param payload: {merges: [{primary, others: [ratingKey...]}]}
        :return: 合并结果
        """
        payload = payload or {}
        merges = payload.get("merges") or []
        if not merges:
            return {"success": False, "error": "未指定合并计划"}
        plex = self._plex_direct()
        if not plex:
            return {"success": False, "error": "未配置 Plex 直连地址或 token"}
        merged = 0
        failed: List[str] = []
        for m in merges:
            primary = str(m.get("primary") or "").strip()
            others = [str(x) for x in (m.get("others") or []) if str(x)]
            if not primary or not others:
                continue
            if plex.merge_items(primary, others):
                merged += 1
            else:
                failed.append(primary)
        return {"success": True, "merged": merged, "failed": failed}

    def get_form(self) -> Tuple[Optional[List[dict]], Dict[str, Any]]:
        """Vue 模式下返回默认配置模型。"""
        return None, {
            "enabled": self._enabled,
            "proxy_enabled": self._proxy_enabled,
            "plex_host": self._plex_host,
            "plex_token": self._plex_token,
            "host": self._host,
            "port": self._port,
            "pin_rules": self._pin_rules_raw,
            "force_direct_play": self._force_direct_play,
            "mediainfo_enabled": self._mediainfo_enabled,
            "plex_direct_host": self._plex_direct_host,
            "helper_url": self._helper_url,
            "helper_token": self._helper_token,
            "emby_url": self._emby_url,
            "emby_apikey": self._emby_apikey,
            "use_emby": self._use_emby,
            "use_ffprobe": self._use_ffprobe,
            "ffprobe_path_map": self._ffprobe_path_map,
            "ffprobe_timeout": self._ffprobe_timeout,
            "overwrite_streams": self._overwrite_streams,
            "only_missing": self._only_missing,
            "concurrency": self._concurrency,
            "sections": self._sections,
            "webhook_enabled": self._webhook_enabled,
            "dedup_window": self._dedup_window,
            "forward_episodes": self._forward_episodes,
        }

    def get_page(self) -> Optional[List[dict]]:
        """Vue 模式下详情页由远程组件渲染。"""
        return None

    def stop_service(self) -> None:
        """停止代理服务并释放资源。"""
        if self._server is not None:
            try:
                self._server.should_exit = True
                if self._thread is not None and self._thread.is_alive():
                    self._thread.join(timeout=5.0)
                logger.info("PlexToolbox 302 代理已停止")
            except Exception as e:
                logger.error("PlexToolbox 停止异常: %s", e, exc_info=True)
            finally:
                self._server = None
                self._thread = None
