"""按目录发现新 STRM 并逐条发送媒体通知。"""

from pathlib import Path
from threading import RLock
from time import time
from typing import Any, Dict, List, Optional, Tuple

from apscheduler.triggers.interval import IntervalTrigger

from app.plugins import _PluginBase
from app.schemas import MessageType, NotificationChannel
from app.sdk.logging import logger

from .engine import metadata, pending_candidates, reconcile, scan


_DEFAULT_CONFIG = {
    "enabled": False,
    "paths": "",
    "interval": 30,
    "wait": 120,
    "batch": 10,
    "channel": "",
    "image": True,
    "year": True,
    "actors": True,
    "tags": True,
    "filename": True,
}


class StrmNotify(_PluginBase):
    """监控新增 STRM，等待元数据就绪后逐条发送通知。"""

    plugin_name = "STRM逐条通知"
    plugin_desc = "监控指定目录中的新 STRM，等待对应 NFO/封面后发送逐条媒体通知"
    plugin_icon = "https://raw.githubusercontent.com/DDSRem-Dev/MoviePilot-Plugins/main/icons/StrmNotify.svg"
    plugin_version = "3.0.4"
    plugin_author = "ranzhigg"
    author_url = "https://github.com/ranzhigg"
    plugin_config_prefix = "strmnotify_"
    plugin_order = 50
    auth_level = 1

    def __init__(self) -> None:
        """创建实例级锁和运行配置，避免多个插件实例共享队列状态。"""
        super().__init__()
        self._lock = RLock()
        self._enabled = False
        self._config: Dict[str, Any] = dict(_DEFAULT_CONFIG)
        self._roots: List[Path] = []

    def init_plugin(self, config: Optional[dict] = None) -> None:
        """载入配置，新增目录首次扫描时只建立存量基线。"""
        with self._lock:
            self._config = self._normalize_config(config or {})
            self._enabled = bool(self._config["enabled"])
            self._roots = self._normalize_roots(self._config["paths"])

    def get_state(self) -> bool:
        """返回插件启用状态。"""
        return self._enabled

    @staticmethod
    def _normalize_roots(raw_paths: Any) -> List[Path]:
        """解析绝对监控目录并移除被父目录覆盖的重复路径。"""
        roots = []
        for line in str(raw_paths or "").splitlines():
            value = line.strip()
            if not value:
                continue
            path = Path(value)
            if path.is_absolute():
                roots.append(path.resolve())
        unique = sorted(set(roots))
        return [path for path in unique if not any(parent in path.parents for parent in unique if parent != path)]

    @staticmethod
    def _normalize_config(config: Dict[str, Any]) -> Dict[str, Any]:
        """合并默认值并清理配置类型，兼容旧版保存的缺省字段。"""
        normalized = dict(_DEFAULT_CONFIG)
        normalized.update(config or {})
        normalized["enabled"] = bool(normalized.get("enabled"))
        normalized["paths"] = str(normalized.get("paths") or "")
        normalized["channel"] = str(normalized.get("channel") or "").strip()
        for key in ("image", "year", "actors", "tags", "filename"):
            normalized[key] = bool(normalized.get(key, True))
        return normalized

    def _number(self, key: str, default: int, low: int, high: int) -> int:
        """读取有界整数配置，异常值回退到安全默认值。"""
        try:
            return max(low, min(high, int(self._config.get(key, default))))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _normalize_state(raw: Any) -> Dict[str, dict]:
        """清理持久化状态，保留旧版本的目录键和待通知记录。"""
        if not isinstance(raw, dict):
            return {}
        state: Dict[str, dict] = {}
        for root, record in raw.items():
            if not isinstance(record, dict):
                continue
            known = sorted({str(path) for path in record.get("known", []) if str(path).strip()})
            raw_pending = record.get("pending", {})
            pending = {}
            if isinstance(raw_pending, dict):
                for path, started in raw_pending.items():
                    value = str(path).strip()
                    if value:
                        pending[value] = started
            state[str(root)] = {"known": known, "pending": dict(sorted(pending.items()))}
        return state

    def get_service(self) -> List[Dict[str, Any]]:
        """注册单实例周期扫描任务。"""
        if not self._enabled or not self._roots:
            return []
        return [{
            "id": "StrmNotify_scan",
            "name": "STRM逐条通知扫描",
            "trigger": IntervalTrigger(seconds=self._number("interval", 30, 10, 3600)),
            "func": self.poll,
            "kwargs": {},
        }]

    def _elapsed(self, started: Any, now: float) -> float:
        """计算待处理记录已等待时间，兼容旧状态中的字符串时间戳。"""
        try:
            return max(0.0, now - float(started))
        except (TypeError, ValueError):
            return float(self._number("wait", 120, 10, 86400))

    def _message_channel(self) -> Optional[NotificationChannel]:
        """把配置的渠道值转换成 V3 通知渠道，非法值跟随宿主配置。"""
        selected = str(self._config.get("channel") or "").strip()
        if not selected:
            return None
        try:
            return NotificationChannel(selected)
        except ValueError:
            logger.warning("STRM逐条通知：忽略未知通知渠道")
            return None

    def _format_message(self, info: Dict[str, Any]) -> str:
        """按开关构造单条媒体通知正文。"""
        lines = [str(info.get("title") or "未命名媒体")]
        for field, label in (("year", "年份"), ("actors", "演员"), ("tags", "标签")):
            if self._config.get(field, True) and info.get(field):
                value = info[field]
                lines.append(f"{label}：{', '.join(value) if isinstance(value, list) else value}")
        if self._config.get("filename", True) and info.get("file"):
            lines.append(f"文件：{info['file']}")
        return "\n".join(lines)

    def _send_notification(self, info: Dict[str, Any]) -> None:
        """提交一条媒体通知，成功返回后调用方才会确认队列记录。"""
        self.post_message(
            channel=self._message_channel(),
            mtype=MessageType.Plugin,
            title=f"{info.get('title') or '媒体'} 已入库",
            text=self._format_message(info),
            image=info.get("image") if self._config.get("image", True) else None,
        )

    def poll(self) -> None:
        """扫描所有目录并公平处理待通知队列，失败记录保留到下一轮重试。"""
        if not self._lock.acquire(blocking=False):
            return
        try:
            if not self._enabled:
                return
            state = self._normalize_state(self.get_data("state") or {})
            budget = self._number("batch", 10, 1, 100)
            wait = self._number("wait", 120, 10, 86400)
            now = time()
            dirty = False

            for root in self._roots:
                key = str(root)
                try:
                    files = scan(root)
                except OSError:
                    logger.warning("STRM逐条通知：目录不可用，本轮保留原记录")
                    continue
                previous = state.get(key)
                updated = reconcile(previous, files, now)
                if updated != previous:
                    state[key] = updated
                    dirty = True

            for started, root_key, name in pending_candidates(state):
                if budget <= 0:
                    break
                record = state.get(root_key) or {}
                pending = record.get("pending") if isinstance(record, dict) else None
                if not isinstance(pending, dict) or name not in pending:
                    continue
                age = self._elapsed(started, now)
                try:
                    info = metadata(Path(name), now)
                    if info is None:
                        if age >= wait:
                            pending.pop(name, None)
                            dirty = True
                            logger.info("STRM逐条通知：等待有效 NFO 超时，跳过一条通知")
                        continue
                    # NFO 可能先落盘、封面稍后才由刮削器补写；窗口内继续轮询，
                    # 到达上限仍无远程封面才发送一条无图通知，避免永久阻塞。
                    if self._config.get("image", True) and not info.get("image"):
                        if age < wait:
                            continue
                        logger.info("STRM逐条通知：等待封面超时，发送无封面通知")
                    self._send_notification(info)
                except Exception as error:
                    logger.warning("STRM逐条通知：处理失败，将重试（%s）", type(error).__name__)
                    continue
                pending.pop(name, None)
                budget -= 1
                dirty = True
                # 每条成功通知立即落盘，重启最多重发当前这一条，不丢后续队列。
                self.save_data("state", state)
                dirty = False

            if dirty:
                self.save_data("state", state)
        finally:
            self._lock.release()

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """返回逐条通知配置表单与默认值。"""
        fields = []
        for key, label in (("enabled", "启用插件"), ("image", "显示封面"),
                           ("year", "显示年份"), ("actors", "显示演员"),
                           ("tags", "显示标签"), ("filename", "显示文件名")):
            fields.append({"component": "VSwitch", "props": {"model": key, "label": label}})
        fields.append({
            "component": "VTextarea",
            "props": {
                "model": "paths",
                "label": "监控目录（MP 容器内绝对路径，每行一个）",
                "hint": "重叠子目录会自动合并；首次扫描只建立存量基线。",
                "persistentHint": True,
                "rows": 3,
                "autoGrow": True,
            },
        })
        for key, label in (("interval", "扫描间隔（秒，10–3600）"),
                           ("wait", "等待 NFO/封面（秒，10–86400）"),
                           ("batch", "每轮最多通知数（1–100）")):
            fields.append({"component": "VTextField", "props": {"model": key, "label": label, "type": "number"}})
        fields.append({
            "component": "VSelect",
            "props": {
                "model": "channel",
                "label": "通知渠道",
                "items": [{"title": "跟随 MP 通知配置", "value": ""}]
                + [{"title": item.name, "value": item.value} for item in NotificationChannel],
            },
        })
        fields.append({
            "component": "VAlert",
            "props": {"type": "info", "variant": "tonal"},
            "content": [{
                "component": "span",
                "text": "新增 STRM 会按进入时间公平轮询各监控目录；仅在同名 NFO 有效后通知。封面缺失会在等待窗口内继续轮询，超时后发送无图通知。通知提交成功才会移除队列，发送异常会自动重试。",
            }],
        })
        return [{"component": "VForm", "content": fields}], dict(_DEFAULT_CONFIG)

    @staticmethod
    def _line(text: str, class_name: str = "mb-2") -> Dict[str, Any]:
        """生成可安全换行的详情页文本节点。"""
        return {"component": "div", "props": {"class": class_name, "style": "overflow-wrap: anywhere"}, "text": text}

    def get_page(self) -> List[dict]:
        """展示运行状态、队列统计和监控目录，不额外扫描或发送通知。"""
        with self._lock:
            enabled = self._enabled
            roots = list(self._roots)
            config = dict(self._config)
            state = self._normalize_state(self.get_data("state") or {})
        active = enabled and bool(roots)
        status = "运行中" if active else ("已启用但未配置目录" if enabled else "未启用")
        known = sum(len((state.get(str(root)) or {}).get("known", [])) for root in roots)
        pending = sum(len((state.get(str(root)) or {}).get("pending", {})) for root in roots)
        interval = self._number("interval", 30, 10, 3600)
        wait = self._number("wait", 120, 10, 86400)
        batch = self._number("batch", 10, 1, 100)
        content = [
            {"component": "VAlert", "props": {"type": "success" if active else "info", "variant": "tonal", "class": "mb-4"},
             "text": f"{status} · 每 {interval} 秒扫描 · 多目录公平轮询"},
            {"component": "VRow", "content": [
                {"component": "VCol", "props": {"cols": 4}, "content": [self._line(f"已记录 STRM\n{known}", "text-subtitle-1 font-weight-medium")]},
                {"component": "VCol", "props": {"cols": 4}, "content": [self._line(f"待处理通知\n{pending}", "text-subtitle-1 font-weight-medium")]},
                {"component": "VCol", "props": {"cols": 4}, "content": [self._line(f"单轮上限\n{batch}", "text-subtitle-1 font-weight-medium")]},
            ]},
            {"component": "h3", "props": {"class": "mb-3 mt-2"}, "text": "监控目录"},
        ]
        for root in roots:
            record = state.get(str(root))
            detail = "等待首次扫描建立基线" if record is None else f"已记录 {len(record.get('known', []))} 个文件 · 待处理 {len(record.get('pending', {}))} 条"
            content.append({
                "component": "VCard",
                "props": {"variant": "outlined", "class": "mb-3"},
                "content": [{"component": "VCardText", "content": [self._line(str(root)), self._line(detail, "text-caption text-medium-emphasis")]}],
            })
        if not roots:
            content.append(self._line("请打开配置，填写 MP 容器内的绝对监控目录并启用插件。", "text-medium-emphasis"))
        content.extend([
            {"component": "h3", "props": {"class": "my-3"}, "text": "通知设置"},
            self._line(f"等待 NFO/封面：{wait} 秒 · 每轮最多通知：{batch} 条"),
            self._line(f"通知渠道：{config.get('channel') or '跟随 MP 通知配置'}"),
            self._line("显示内容：" + ("、".join(label for key, label in (("image", "封面"), ("year", "年份"), ("actors", "演员"), ("tags", "标签"), ("filename", "文件名")) if config.get(key, True)) or "仅标题")),
            {"component": "VAlert", "props": {"type": "info", "variant": "tonal", "class": "mt-4"},
             "text": "首次扫描只记录存量文件；已发送记录和待处理队列会持久化。这里的“已入库”仅表示 STRM 与 NFO 已就绪，不代表 Plex/Emby 已完成扫描。"},
        ])
        return [{"component": "VCardText", "content": content}]

    def get_api(self) -> List[dict]:
        """当前插件不暴露额外 API。"""
        return []

    @staticmethod
    def get_command() -> List[dict]:
        """当前插件不注册聊天命令。"""
        return []

    def stop_service(self) -> None:
        """停用后续轮询，已进入发送流程的调用由锁自然收尾。"""
        with self._lock:
            self._enabled = False
