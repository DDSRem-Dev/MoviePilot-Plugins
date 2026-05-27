from time import sleep
from copy import deepcopy
from dataclasses import asdict
from functools import wraps
from pathlib import Path
from re import search as re_search
from typing import Any, List, Dict, Tuple, Optional, Union

from app.core.config import settings
from app.core.event import eventmanager, Event
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import (
    FileItem,
    NotificationType,
)
from app.core.meta import MetaVideo
from app.schemas.types import EventType, MessageChannel, ChainEventType, MediaType
from app.helper.directory import DirectoryHelper
from app.chain.storage import StorageChain

try:
    from app.schemas import TransferRenameBuildEventData
except ImportError:
    TransferRenameBuildEventData = None

try:
    from app.schemas import TransferOverwriteCheckEventData
except ImportError:
    TransferOverwriteCheckEventData = None

try:
    from app.schemas import TransferInterceptEventData
except ImportError:
    TransferInterceptEventData = None

from apscheduler.triggers.cron import CronTrigger
from fastapi import Request
from p115center import P115Center

from .sidebar_nav import build_sidebar_nav
from .version import VERSION
from .api import Api
from .service import servicer
from .service.hdhive_checkin.job import run_hdhive_checkin_once
from .service.p115_checkin.job import run_p115_checkin_once
from .core.cache import pantransfercacher, sharestrmcacher
from .core.config import configer
from .core.i18n import i18n
from .core.message import post_message
from .db_manager import ct_db_manager
from .db_manager.init import init_db, migration_db, init_migration_scripts
from .mcp import MCPManager
from .patch.u115_open import U115Patcher
from .patch.p115disk_upload import P115DiskPatcher
from .core.message import UploadNotifyAggregator
from .interactive.framework.callbacks import decode_action, Action
from .interactive.framework.manager import BaseSessionManager
from .interactive.framework.schemas import TSession
from .interactive.handler import ActionHandler
from .interactive.session import Session
from .interactive.views import ViewRenderer
from .helper.strm import (
    FullSyncStrmHelper,
    ShareInteractiveGenStrmQueue,
    TransferStrmHelper,
)
from .helper.hdhive.open import is_authorized
from .helper.strm.full import strm_cleanup_interaction
from .helper.mediasyncdel import MediaSyncDelHelper
from .helper.mediasyncdel.webhook_queue import (
    SyncDelWebhookTask,
    sync_del_webhook_queue,
)
from .utils.path import PathUtils
from .utils.offline_link import OfflineLinkResolver
from .utils.sentry import sentry_manager
from .helper.share.share_links import ShareLinkResolver
from .utils.rename_dict import RenameDictUtils
from .utils.url import UrlUtils


# 实例化一个该插件专用的 SessionManager
session_manager = BaseSessionManager(session_class=Session)


@sentry_manager.capture_all_class_exceptions
class P115StrmHelper(_PluginBase):
    # 插件名称
    plugin_name = "115网盘STRM助手"
    # 插件描述
    plugin_desc = "115网盘STRM生成一条龙服务"
    # 插件图标
    plugin_icon = "https://raw.githubusercontent.com/jxxghp/MoviePilot-Frontend/refs/heads/v2/src/assets/images/misc/u115.png"
    # 插件版本
    plugin_version = VERSION
    # 插件作者
    plugin_author = "DDSRem"
    # 作者主页
    author_url = "https://github.com/DDSRem"
    # 插件配置项ID前缀
    plugin_config_prefix = "p115strmhelper_"
    # 加载顺序
    plugin_order = 99
    # 可使用的用户级别
    auth_level = 1

    api = None
    mcp_manager = None

    @staticmethod
    def logs_oper(oper_name: str):
        """
        数据库操作汇报装饰器
        - 捕获异常并记录日志
        - 5秒内合并多条消息，避免频繁发送通知
        """

        def decorator(func):
            @wraps(func)
            def wrapper(self, *args, **kwargs):
                level, text = "success", f"{oper_name} 成功"
                try:
                    result = func(self, *args, **kwargs)
                    return result
                except Exception as e:
                    logger.error(f"{oper_name} 失败：{str(e)}", exc_info=True)
                    level, text = "error", f"{oper_name} 失败：{str(e)}"
                    return False
                finally:
                    if hasattr(self, "add_message"):
                        self.add_message(title=oper_name, text=text, level=level)

            return wrapper

        return decorator

    def __init__(self, config: dict = None):
        """
        初始化
        """
        super().__init__()

        # 初始化配置项
        configer.load_from_dict(config or {})

        if not Path(configer.PLUGIN_TEMP_PATH).exists():
            Path(configer.PLUGIN_TEMP_PATH).mkdir(parents=True, exist_ok=True)

        # 初始化数据库
        self.init_database()

        # 实例化处理器和渲染器
        self.action_handler = ActionHandler()
        self.view_renderer = ViewRenderer()

        # 初始化通知语言
        i18n.load_translations()

    def init_plugin(self, config: dict = None):
        """
        初始化插件
        """
        self.api = Api(client=None)

        if config:
            configer.update_config(config)
            configer.update_plugin_config()
            i18n.load_translations()
            sentry_manager.reload_config()

        # 停止现有任务
        self.stop_service()

        if configer.enabled:
            self.init_database()

            if servicer.init_service():
                self.api = Api(client=servicer.client)

            U115Patcher().enable()
            P115DiskPatcher().enable()

            # 目录上传监控服务
            servicer.start_directory_upload()

            servicer.start_monitor_life()

        try:
            self.mcp_manager = MCPManager(api=self.api, servicer=servicer)
        except Exception as e:
            logger.warning(f"MCP 初始化跳过: {e}")
            self.mcp_manager = None

    @logs_oper("初始化数据库")
    def init_database(self) -> bool:
        """
        初始化数据库
        """
        if not Path(configer.PLUGIN_CONFIG_PATH).exists():
            Path(configer.PLUGIN_CONFIG_PATH).mkdir(parents=True, exist_ok=True)
        if not ct_db_manager.is_initialized():
            # 初始化数据库会话
            ct_db_manager.init_database(db_path=configer.PLUGIN_DB_PATH)
            # 表单补全
            init_db(
                engine=ct_db_manager.Engine,
            )
            # 初始化 迁移脚本
            if init_migration_scripts():
                # 更新数据库
                migration_db(
                    db_path=configer.PLUGIN_DB_PATH,
                    script_location=configer.PLUGIN_DATABASE_SCRIPT_LOCATION,
                    version_locations=configer.PLUGIN_DATABASE_VERSION_LOCATIONS,
                )
            else:
                raise Exception("初始化迁移脚本失败")
        return True

    def get_state(self) -> bool:
        """
        插件状态
        """
        return configer.enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """
        定义远程控制命令
        :return: 命令关键字、事件、描述、附带数据
        """
        return [
            {
                "cmd": "/p115_full_sync",
                "event": EventType.PluginAction,
                "desc": "全量同步115网盘文件",
                "category": "",
                "data": {"action": "p115_full_sync"},
            },
            {
                "cmd": "/p115_inc_sync",
                "event": EventType.PluginAction,
                "desc": "增量同步115网盘文件",
                "category": "",
                "data": {"action": "p115_inc_sync"},
            },
            {
                "cmd": "/p115_add_share",
                "event": EventType.PluginAction,
                "desc": "转存分享到待整理目录",
                "category": "",
                "data": {"action": "p115_add_share"},
            },
            {
                "cmd": "/p115_share_strm",
                "event": EventType.PluginAction,
                "desc": "115分享链接交互生成STRM",
                "category": "",
                "data": {"action": "p115_share_strm"},
            },
            {
                "cmd": "/ol",
                "event": EventType.PluginAction,
                "desc": "添加离线下载任务",
                "category": "",
                "data": {"action": "p115_add_offline"},
            },
            {
                "cmd": "/p115_strm",
                "event": EventType.PluginAction,
                "desc": "全量生成指定网盘目录STRM",
                "category": "",
                "data": {"action": "p115_strm"},
            },
            {
                "cmd": "/sh",
                "event": EventType.PluginAction,
                "desc": "搜索指定资源",
                "category": "",
                "data": {"action": "p115_search"},
            },
            {
                "cmd": "/hdhivechin",
                "event": EventType.PluginAction,
                "desc": "手动 HDHive 签到",
                "category": "",
                "data": {"action": "hdhive_checkin_manual"},
            },
            {
                "cmd": "/p115_checkin",
                "event": EventType.PluginAction,
                "desc": "手动 115 签到",
                "category": "",
                "data": {"action": "p115_checkin_manual"},
            },
        ]

    def get_api(self) -> List[Dict[str, Any]]:
        """
        获取 API 接口
        """
        apis = [
            {
                "path": "/redirect_url",
                "endpoint": self.api.redirect_url_get,
                "methods": ["GET"],
                "summary": "302跳转",
                "description": "115网盘302跳转",
                "allow_anonymous": True,
            },
            {
                "path": "/redirect_url",
                "endpoint": self.api.redirect_url_post,
                "methods": ["POST"],
                "summary": "302跳转",
                "description": "115网盘302跳转",
                "allow_anonymous": True,
            },
            {
                "path": "/redirect_url",
                "endpoint": self.api.redirect_url_head,
                "methods": ["HEAD"],
                "summary": "302跳转",
                "description": "115网盘302跳转",
                "allow_anonymous": True,
            },
            {
                "path": "/redirect_url/{args:path}",
                "endpoint": self.api.redirect_url_get_path,
                "methods": ["GET"],
                "summary": "302跳转",
                "description": "115网盘302跳转",
                "allow_anonymous": True,
            },
            {
                "path": "/redirect_url/{args:path}",
                "endpoint": self.api.redirect_url_post_path,
                "methods": ["POST"],
                "summary": "302跳转",
                "description": "115网盘302跳转",
                "allow_anonymous": True,
            },
            {
                "path": "/redirect_url/{args:path}",
                "endpoint": self.api.redirect_url_head_path,
                "methods": ["HEAD"],
                "summary": "302跳转",
                "description": "115网盘302跳转",
                "allow_anonymous": True,
            },
            {
                "path": "/api_strm_sync_creata",
                "endpoint": self.api.api_strm_sync_creata,
                "methods": ["POST"],
                "summary": "API 请求生成 STRM",
                "description": "API 请求生成 STRM",
            },
            {
                "path": "/api_strm_sync_create_by_path",
                "endpoint": self.api.api_strm_sync_create_by_path,
                "methods": ["POST"],
                "summary": "API 请求生成 STRM（通过一组文件夹路径）",
                "description": "API 请求生成 STRM（通过一组文件夹路径）",
            },
            {
                "path": "/api_strm_sync_remove",
                "endpoint": self.api.api_strm_sync_remove,
                "methods": ["POST"],
                "summary": "API 请求删除无效 STRM 文件",
                "description": "API 请求删除无效 STRM 文件",
            },
            {
                "path": "/add_transfer_share",
                "endpoint": self.api.add_transfer_share,
                "methods": ["GET"],
                "summary": "添加分享转存整理",
            },
            {
                "path": "/user_storage_status",
                "endpoint": self.api.get_user_storage_status,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "获取115用户基本信息和空间状态",
            },
            {
                "path": "/get_config",
                "endpoint": self.api.get_config_api,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "获取配置",
            },
            {
                "path": "/get_machine_id",
                "endpoint": self.api.get_machine_id_api,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "获取 Machine ID",
            },
            {
                "path": "/generate_emby2alist_config",
                "endpoint": self.api.generate_media_redirect_config_api,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "生成媒体重定向配置（emby2Alist / Emby 302 反向代理）",
            },
            {
                "path": "/save_config",
                "endpoint": self._save_config_api,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "保存配置",
            },
            {
                "path": "/get_status",
                "endpoint": self.api.get_status_api,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "获取状态",
            },
            {
                "path": "/full_sync",
                "endpoint": self.api.trigger_full_sync_api,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "执行全量同步",
            },
            {
                "path": "/full_sync_db",
                "endpoint": self.api.trigger_full_sync_db_api,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "执行全量同步",
            },
            {
                "path": "/strm_cleanup_pending",
                "endpoint": self.api.strm_cleanup_pending_api,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "列出待二次确认的 STRM 清理批次",
            },
            {
                "path": "/strm_cleanup_execute",
                "endpoint": self.api.strm_cleanup_execute_api,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "确认执行一批 STRM 清理",
            },
            {
                "path": "/strm_cleanup_cancel",
                "endpoint": self.api.strm_cleanup_cancel_api,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "取消一批待确认的 STRM 清理",
            },
            {
                "path": "/share_strm_cleanup_pending",
                "endpoint": self.api.share_strm_cleanup_pending_api,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "列出待确认的分享 STRM 清理批次",
            },
            {
                "path": "/share_strm_cleanup_batch_paths",
                "endpoint": self.api.share_strm_cleanup_batch_paths_api,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "分页获取待确认批次内的 STRM 路径",
            },
            {
                "path": "/share_strm_cleanup_execute",
                "endpoint": self.api.share_strm_cleanup_execute_api,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "确认执行一批分享 STRM 清理",
            },
            {
                "path": "/share_strm_cleanup_cancel",
                "endpoint": self.api.share_strm_cleanup_cancel_api,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "取消一批待确认的分享 STRM 清理",
            },
            {
                "path": "/share_strm_cleanup_scan",
                "endpoint": self.api.share_strm_cleanup_scan_api,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "立即执行分享 STRM 清理扫描",
            },
            {
                "path": "/share_strm_cleanup_last_summary",
                "endpoint": self.api.share_strm_cleanup_last_summary_api,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "上次分享 STRM 清理扫描摘要",
            },
            {
                "path": "/share_strm_missing_media_list",
                "endpoint": self.api.share_strm_missing_media_list_api,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "分页列出分享 STRM 缺失媒体",
            },
            {
                "path": "/share_strm_missing_media_clear",
                "endpoint": self.api.share_strm_missing_media_clear_api,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "清空或删除分享 STRM 缺失媒体记录",
            },
            {
                "path": "/share_sync",
                "endpoint": self.api.trigger_share_sync_api,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "执行分享同步",
            },
            {
                "path": "/clear_id_path_cache",
                "endpoint": self.api.clear_id_path_cache_api,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "清理文件路径ID缓存",
            },
            {
                "path": "/clear_increment_skip_cache",
                "endpoint": self.api.clear_increment_skip_cache_api,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "清理增量同步跳过路径缓存",
            },
            {
                "path": "/clear_302_cache",
                "endpoint": self.api.clear_302_cache_api,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "清理302跳转缓存",
            },
            {
                "path": "/browse_dir",
                "endpoint": self.api.browse_dir_api,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "浏览目录",
            },
            {
                "path": "/get_qrcode",
                "endpoint": self.api.get_qrcode_api,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "获取登录二维码",
            },
            {
                "path": "/check_qrcode",
                "endpoint": self.api.check_qrcode_api,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "检查二维码状态",
            },
            {
                "path": "/get_aliyundrive_qrcode",
                "endpoint": self.api.get_aliyundrive_qrcode_api,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "获取阿里云盘登录二维码",
            },
            {
                "path": "/check_aliyundrive_qrcode",
                "endpoint": self.api.check_aliyundrive_qrcode_api,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "检查阿里云盘二维码状态",
            },
            {
                "path": "/offline_tasks",
                "endpoint": self.api.offline_tasks_api,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "离线任务列表",
            },
            {
                "path": "/add_offline_task",
                "endpoint": self.api.add_offline_task_api,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "添加离线下载任务",
            },
            {
                "path": "/check_feature",
                "endpoint": self.api.check_feature_api,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "判断是否有权限使用此增强功能",
            },
            {
                "path": "/hdhive/oauth/start",
                "endpoint": self.api.hdhive_oauth_start_api,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "HDHive OAuth 授权开始",
            },
            {
                "path": "/hdhive/oauth/complete",
                "endpoint": self.api.hdhive_oauth_complete_api,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "HDHive OAuth 授权完成",
            },
            {
                "path": "/hdhive/oauth/status",
                "endpoint": self.api.hdhive_oauth_status_api,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "HDHive OAuth 状态",
            },
            {
                "path": "/hdhive/oauth/revoke",
                "endpoint": self.api.hdhive_oauth_revoke_api,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "HDHive OAuth 解除授权",
            },
            {
                "path": "/get_authorization_status",
                "endpoint": self.api.get_authorization_status_api,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "获取机器授权状态",
            },
            {
                "path": "/get_donate_info",
                "endpoint": self.api.get_donate_info_api,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "获取捐赠信息",
            },
            {
                "path": "/check_life_event_status",
                "endpoint": self.api.check_life_event_status_api,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "检查115生活事件线程状态并测试拉取数据",
            },
            {
                "path": "/manual_transfer",
                "endpoint": self.api.manual_transfer_api,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "手动触发网盘整理",
            },
            {
                "path": "/get_sync_del_history",
                "endpoint": self.api.get_sync_del_history,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "获取同步删除历史记录",
            },
            {
                "path": "/delete_sync_del_history",
                "endpoint": self.api.delete_sync_del_history,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "删除同步删除历史记录",
            },
            {
                "path": "/delete_all_sync_del_history",
                "endpoint": self.api.delete_all_sync_del_history,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "一键删除所有同步删除历史记录",
            },
            {
                "path": "/get_strm_sync_history",
                "endpoint": self.api.get_strm_sync_history,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "获取 STRM 同步执行历史",
            },
            {
                "path": "/delete_strm_sync_history",
                "endpoint": self.api.delete_strm_sync_history,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "删除单条 STRM 执行历史",
            },
            {
                "path": "/delete_all_strm_sync_history",
                "endpoint": self.api.delete_all_strm_sync_history,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "清空全部 STRM 执行历史",
            },
            {
                "path": "/fuse_mount",
                "endpoint": self.api.fuse_mount_api,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "挂载 FUSE 文件系统",
            },
            {
                "path": "/fuse_unmount",
                "endpoint": self.api.fuse_unmount_api,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "卸载 FUSE 文件系统",
            },
            {
                "path": "/fuse_status",
                "endpoint": self.api.fuse_status_api,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "获取 FUSE 状态",
            },
            {
                "path": "/trigger_backup",
                "endpoint": self.api.trigger_backup_api,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "手动触发 STRM 备份任务",
            },
            {
                "path": "/list_backups",
                "endpoint": self.api.list_backups_api,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "列出 STRM 备份文件",
            },
            {
                "path": "/restore_backup",
                "endpoint": self.api.restore_backup_api,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "从 STRM 备份恢复",
            },
        ]
        if getattr(self, "mcp_manager", None) is not None:
            apis.extend(
                [
                    {
                        "path": "/mcp/sse",
                        "endpoint": self.mcp_manager.handle_sse,
                        "methods": ["GET"],
                        "summary": "MCP SSE 端点",
                    },
                    {
                        "path": "/mcp/messages",
                        "endpoint": self.mcp_manager.handle_messages,
                        "methods": ["POST"],
                        "summary": "MCP 消息端点",
                    },
                ]
            )
        if servicer.webdav_core:
            apis.extend(
                [
                    {
                        "path": "/webdav",
                        "endpoint": servicer.webdav_core.propfind,
                        "methods": ["PROPFIND"],
                        "summary": "Webdav PROPFIND",
                        "description": "Webdav PROPFIND",
                        "allow_anonymous": True,
                    },
                    {
                        "path": "/webdav/{path:path}",
                        "endpoint": servicer.webdav_core.propfind,
                        "methods": ["PROPFIND"],
                        "summary": "Webdav PROPFIND",
                        "description": "Webdav PROPFIND",
                        "allow_anonymous": True,
                    },
                    {
                        "path": "/webdav",
                        "endpoint": servicer.webdav_core.get,
                        "methods": ["GET"],
                        "summary": "Webdav GET",
                        "description": "Webdav GET",
                        "allow_anonymous": True,
                    },
                    {
                        "path": "/webdav/{path:path}",
                        "endpoint": servicer.webdav_core.get,
                        "methods": ["GET"],
                        "summary": "Webdav GET",
                        "description": "Webdav GET",
                        "allow_anonymous": True,
                    },
                    {
                        "path": "/webdav",
                        "endpoint": servicer.webdav_core.options,
                        "methods": ["OPTIONS"],
                        "summary": "Webdav OPTIONS",
                        "description": "Webdav OPTIONS",
                        "allow_anonymous": True,
                    },
                    {
                        "path": "/webdav/{path:path}",
                        "endpoint": servicer.webdav_core.options,
                        "methods": ["OPTIONS"],
                        "summary": "Webdav OPTIONS",
                        "description": "Webdav OPTIONS",
                        "allow_anonymous": True,
                    },
                ]
            )
        return apis

    def get_service(self) -> List[Dict[str, str | Dict[Any, Any] | Any]] | None:
        """
        注册插件公共服务
        """
        cron_service = [
            {
                "id": "P115StrmHelper_offline_status",
                "name": "监控115网盘离线下载进度",
                "trigger": CronTrigger.from_crontab("*/2 * * * *"),
                "func": servicer.offline_status,
                "kwargs": {},
            }
        ]
        if (
            configer.monitor_life_enabled
            and configer.monitor_life_paths
            and configer.monitor_life_event_modes
        ) or (configer.pan_transfer_enabled and configer.pan_transfer_paths):
            cron_service.append(
                {
                    "id": "P115StrmHelper_monitor_life_guard",
                    "name": "115生活事件线程守护",
                    "trigger": CronTrigger.from_crontab("* * * * *"),
                    "func": servicer.check_monitor_life_guard,
                    "kwargs": {},
                }
            )
        if (
            configer.cron_full_sync_strm
            and configer.timing_full_sync_strm
            and configer.full_sync_strm_paths
        ):
            cron_service.append(
                {
                    "id": "P115StrmHelper_full_sync_strm_files",
                    "name": "定期全量同步115媒体库",
                    "trigger": CronTrigger.from_crontab(configer.cron_full_sync_strm),
                    "func": servicer.full_sync_strm_files,
                    "kwargs": {},
                }
            )
        if (
            configer.share_strm_cleanup_config.timing_share_strm_cleanup
            and configer.share_strm_cleanup_config.cron_share_strm_cleanup
        ):
            cron_service.append(
                {
                    "id": "P115StrmHelper_share_strm_cleanup",
                    "name": "定时分享STRM失效清理扫描",
                    "trigger": CronTrigger.from_crontab(
                        configer.share_strm_cleanup_config.cron_share_strm_cleanup
                    ),
                    "func": servicer.share_strm_cleanup_run,
                    "kwargs": {},
                }
            )
        if configer.cron_clear and (
            configer.clear_recyclebin_enabled or configer.clear_receive_path_enabled
        ):
            cron_service.append(
                {
                    "id": "P115StrmHelper_main_cleaner",
                    "name": "定期清理115空间",
                    "trigger": CronTrigger.from_crontab(configer.cron_clear),
                    "func": servicer.main_cleaner,
                    "kwargs": {},
                }
            )
        if (
            configer.increment_sync_strm_enabled
            and configer.increment_sync_strm_paths
            and configer.increment_sync_cron
        ):
            cron_service.append(
                {
                    "id": "P115StrmHelper_increment_sync_strm",
                    "name": "115网盘定期增量同步",
                    "trigger": CronTrigger.from_crontab(configer.increment_sync_cron),
                    "func": servicer.increment_sync_strm_files,
                    "kwargs": {},
                }
            )
        if (
            configer.enabled
            and (configer.hdhive_checkin_username or "").strip()
            and (configer.hdhive_checkin_password or "").strip()
            and (
                configer.hdhive_checkin_daily_enabled
                or configer.hdhive_checkin_gamble_enabled
            )
        ):
            cron_service.append(
                {
                    "id": "P115StrmHelper_hdhive_checkin",
                    "name": "HDHive 签到调度",
                    "trigger": CronTrigger.from_crontab("*/5 * * * *"),
                    "func": servicer.hdhive_checkin_scheduler_tick,
                    "kwargs": {},
                }
            )
        if configer.enabled and configer.p115_checkin_enabled:
            cron_service.append(
                {
                    "id": "P115StrmHelper_p115_checkin",
                    "name": "115 签到调度",
                    "trigger": CronTrigger.from_crontab("*/5 * * * *"),
                    "func": servicer.p115_checkin_scheduler_tick,
                    "kwargs": {},
                }
            )
        if configer.strm_backup_enabled and configer.strm_backup_items:
            for backup_item in configer.strm_backup_items:
                if (
                    backup_item.enabled
                    and backup_item.timing_enabled
                    and backup_item.cron
                ):
                    cron_service.append(
                        {
                            "id": f"P115StrmHelper_strm_backup_{backup_item.name}",
                            "name": f"STRM 定时备份-{backup_item.name}",
                            "trigger": CronTrigger.from_crontab(backup_item.cron),
                            "func": servicer.run_backup_task,
                            "func_kwargs": {"task_name": backup_item.name},
                        }
                    )
        if cron_service:
            return cron_service

    @staticmethod
    def get_render_mode() -> Tuple[str, Optional[str]]:
        """
        返回插件使用的前端渲染模式
        :return: 前端渲染模式，前端文件目录
        """
        return "vue", "dist/assets"

    def get_form(self) -> Tuple[Optional[List[dict]], Dict[str, Any]]:
        """
        为Vue组件模式返回初始配置数据。
        Vue模式下，第一个参数返回None，第二个参数返回初始配置数据。
        """
        return None, self.api.get_config_api()

    def get_page(self) -> Optional[List[dict]]:
        """
        Vue模式不使用Vuetify页面定义
        """
        return None

    def get_dashboard_meta(self) -> Optional[List[Dict[str, str]]]:
        """
        多仪表盘
        """
        return [
            {"key": "strm", "name": "STRM 同步执行记录"},
            {"key": "status", "name": "运行状态与账户"},
            {"key": "sync_del", "name": "同步删除历史"},
            {"key": "manual_transfer", "name": "网盘整理"},
            {"key": "full_sync_actions", "name": "全量同步"},
        ]

    def get_dashboard(
        self,
        key: str = "",
        **kwargs: Any,
    ) -> Tuple[Dict[str, Any], Dict[str, Any], Optional[List[dict]]]:
        """
        按 key 返回栅格与标题
        """
        _ = kwargs
        k = (key or "").strip()
        if k == "status":
            return (
                {"cols": 12},
                {
                    "title": "运行状态与 115 账户",
                    "subtitle": self.plugin_name,
                    "border": True,
                },
                None,
            )
        if k == "sync_del":
            return (
                {"cols": 12},
                {
                    "title": "同步删除历史",
                    "subtitle": self.plugin_name,
                    "border": True,
                },
                None,
            )
        if k == "manual_transfer":
            return (
                {"cols": 12, "sm": 6, "md": 4, "lg": 3},
                {
                    "title": "手动网盘整理",
                    "subtitle": self.plugin_name,
                    "border": True,
                },
                None,
            )
        if k == "full_sync_actions":
            return (
                {"cols": 12, "sm": 12, "md": 6, "lg": 6},
                {
                    "title": "全量同步",
                    "subtitle": self.plugin_name,
                    "border": True,
                },
                None,
            )
        return (
            {"cols": 12},
            {
                "title": "STRM 同步执行记录",
                "subtitle": self.plugin_name,
                "border": True,
            },
            None,
        )

    @staticmethod
    def get_sidebar_nav() -> List[Dict[str, Any]]:
        """
        侧栏全页导航项（联邦），由配置 sidebar_nav_keys 决定显示项与顺序
        """
        return build_sidebar_nav(list(configer.sidebar_nav_keys))

    @staticmethod
    def _get_event_userid(
        event_data: Optional[Dict[str, Any]],
    ) -> Optional[str]:
        """
        统一获取事件中的用户 ID，兼容 user 与 userid 字段
        """
        if not event_data:
            return None
        userid = event_data.get("userid") or event_data.get("user")
        if userid is None:
            return None
        return str(userid)

    @eventmanager.register(
        [
            EventType.TransferComplete,
            EventType.AudioTransferComplete,
            EventType.SubtitleTransferComplete,
        ]
    )
    def generate_strm(self, event: Event):
        """
        监控目录整理生成 STRM 文件
        """
        if (
            not configer.enabled
            or not configer.transfer_monitor_enabled
            or not configer.transfer_monitor_paths
            or not configer.moviepilot_address
        ):
            return

        item = event.event_data
        if not item:
            return
        event_type = event.event_type
        if not event_type:
            return

        strm_helper = TransferStrmHelper()
        strm_helper.do_generate(
            client=servicer.client,
            item=item,
            event_type=event_type,
            mediainfodownloader=servicer.mediainfodownloader,
        )

    @eventmanager.register(EventType.PluginAction)
    def p115_full_sync(self, event: Event):
        """
        远程全量同步
        """
        if not event:
            return
        event_data = event.event_data
        if not event_data or event_data.get("action") != "p115_full_sync":
            return
        post_message(
            channel=event.event_data.get("channel"),
            source=event.event_data.get("source"),
            title=i18n.translate("start_full_sync"),
            userid=self._get_event_userid(event_data),
        )
        servicer.full_sync_strm_files()

    @eventmanager.register(EventType.PluginAction)
    def p115_inc_sync(self, event: Event):
        """
        远程增量同步
        """
        if not event:
            return
        event_data = event.event_data
        if not event_data or event_data.get("action") != "p115_inc_sync":
            return
        post_message(
            channel=event.event_data.get("channel"),
            source=event.event_data.get("source"),
            title=i18n.translate("start_inc_sync"),
            userid=self._get_event_userid(event_data),
        )
        servicer.increment_sync_strm_files(send_msg=True)

    @eventmanager.register(EventType.PluginAction)
    def p115_strm(self, event: Event):
        """
        全量生成指定网盘目录STRM
        """
        if not event:
            return
        event_data = event.event_data
        if not event_data or event_data.get("action") != "p115_strm":
            return
        userid = self._get_event_userid(event_data)
        args = event_data.get("arg_str")
        if not args:
            logger.error(f"【全量STRM生成】缺少参数：{event_data}")
            post_message(
                channel=event.event_data.get("channel"),
                source=event.event_data.get("source"),
                title=i18n.translate("p115_strm_parameter_error"),
                userid=userid,
            )
            return
        if (
            not configer.full_sync_strm_paths
            or not configer.moviepilot_address
            or not configer.user_download_mediaext
        ):
            post_message(
                channel=event.event_data.get("channel"),
                source=event.event_data.get("source"),
                title=i18n.translate("p115_strm_full_sync_config_error"),
                userid=userid,
            )
            return

        status, paths = PathUtils.get_p115_strm_path(
            paths=configer.full_sync_strm_paths, media_path=args
        )
        if not status:
            post_message(
                channel=event.event_data.get("channel"),
                source=event.event_data.get("source"),
                title=f"{args} {i18n.translate('p115_strm_match_path_error')}",
                userid=userid,
            )
            return
        strm_helper = FullSyncStrmHelper(
            client=servicer.client,
            mediainfodownloader=servicer.mediainfodownloader,
        )
        strm_helper.strm_exec_history_kind = "full_partial"
        strm_helper.strm_exec_history_extra = {"arg_str": args}
        post_message(
            channel=event.event_data.get("channel"),
            source=event.event_data.get("source"),
            title=i18n.translate("p115_strm_start_sync", paths=args),
            userid=userid,
        )
        strm_helper.generate_strm_files(
            full_sync_strm_paths=paths,
        )
        (
            strm_count,
            mediainfo_count,
            strm_fail_count,
            mediainfo_fail_count,
            remove_unless_strm_count,
            strm_cleanup_deferred_count,
        ) = strm_helper.get_generate_total()
        text = f"""
📂 网盘路径：{args}
📄 生成STRM文件 {strm_count} 个
⬇️ 下载媒体文件 {mediainfo_count} 个
❌ 生成STRM失败 {strm_fail_count} 个
🚫 下载媒体失败 {mediainfo_fail_count} 个
"""
        if remove_unless_strm_count != 0:
            text += f"🗑️ 清理无效STRM文件 {remove_unless_strm_count} 个"
        if strm_cleanup_deferred_count != 0:
            text += f"\n⏳ 待二次确认清理无效 STRM {strm_cleanup_deferred_count} 个"
        post_message(
            channel=event.event_data.get("channel"),
            source=event.event_data.get("source"),
            userid=userid,
            title=i18n.translate("full_sync_done_title"),
            text=text,
        )

    @eventmanager.register(EventType.PluginAction)
    def p115_search(self, event: Event):
        """
        处理搜索请求
        """
        if not event:
            return
        event_data = event.event_data
        if not event_data or event_data.get("action") != "p115_search":
            return
        userid = self._get_event_userid(event_data)

        has_tg = bool(configer.tg_search_channels)
        has_hdhive = is_authorized()
        if not has_tg and not has_hdhive:
            post_message(
                channel=event.event_data.get("channel"),
                source=event.event_data.get("source"),
                title=i18n.translate("p115_search_config_error"),
                userid=userid,
            )
            return

        args = event_data.get("arg_str")
        if not args:
            logger.error(f"【搜索】缺少参数：{event_data}")
            post_message(
                channel=event.event_data.get("channel"),
                source=event.event_data.get("source"),
                title=i18n.translate("p115_search_parameter_error"),
                userid=userid,
            )
            return

        try:
            session = session_manager.get_or_create(
                event_data, plugin_id=self.__class__.__name__
            )

            search_keyword = args.strip()

            action = Action(command="search", view="search_list", value=search_keyword)

            immediate_messages = self.action_handler.process(session, action)
            # 报错，截断后续运行
            if immediate_messages:
                for msg in immediate_messages:
                    self.__send_message(session, text=msg.get("text"), title="错误")
                return

            # 设置页面
            if not action.view:
                logger.error("处理 search 命令失败: 视图为空")
                return
            session.go_to(action.view)
            self._render_and_send(session)
        except Exception as e:
            logger.error(f"处理 search 命令失败: {e}", exc_info=True)

    @eventmanager.register(EventType.PluginAction)
    def hdhive_checkin_manual(self, event: Event):
        """
        远程命令 /hdhivechin 手动 HDHive 签到
        """
        if not event:
            return
        event_data = event.event_data
        if not event_data or event_data.get("action") != "hdhive_checkin_manual":
            return
        userid = self._get_event_userid(event_data)

        ok, text = run_hdhive_checkin_once(manual=True, send_notify=False)
        post_message(
            channel=event.event_data.get("channel"),
            source=event.event_data.get("source"),
            title="HDHive 手动签到" + ("成功" if ok else "失败"),
            text="\n" + text + "\n",
            userid=userid,
        )

    @eventmanager.register(EventType.PluginAction)
    def p115_checkin_manual(self, event: Event):
        """
        远程命令 /p115_checkin 手动 115 签到
        """
        if not event:
            return
        event_data = event.event_data
        if not event_data or event_data.get("action") != "p115_checkin_manual":
            return
        userid = self._get_event_userid(event_data)

        ok, text = run_p115_checkin_once(
            client=servicer.client, manual=True, send_notify=False
        )
        post_message(
            channel=event.event_data.get("channel"),
            source=event.event_data.get("source"),
            title="115 手动签到" + ("成功" if ok else "失败"),
            text="\n" + text + "\n",
            userid=userid,
        )

    @eventmanager.register(EventType.MessageAction)
    def message_action(self, event: Event):
        """
        处理按钮点击回调
        """
        try:
            event_data = event.event_data
            callback_text = event_data.get("text", "")

            if strm_cleanup_interaction.try_handle_message_action(event_data):
                return

            # 1. 解码 Action callback_text = c:xxx|w:xxx|v|xxx
            session_id, action = decode_action(callback_text=callback_text)
            if not session_id or not action:
                # 如果解码失败或不属于本插件，则忽略
                return

            # 2. 获取会话
            session = session_manager.get(session_id)
            if not session:
                context = {
                    "channel": event_data.get("channel"),
                    "source": event_data.get("source"),
                    "userid": event_data.get("userid") or event_data.get("user"),
                    "original_message_id": event_data.get("original_message_id"),
                    "original_chat_id": event_data.get("original_chat_id"),
                }
                self.post_message(
                    **context,
                    title="⚠️ 会话已过期",
                    text="操作已超时。\n请重新发起 `/sh` 命令。",
                )
                return

            # 3. 更新会话上下文
            session.update_message_context(event_data)

            # 4. 委托给 ActionHandler 处理业务逻辑
            immediate_messages = self.action_handler.process(session, action)
            if immediate_messages:
                for msg in immediate_messages:
                    self.__send_message(session, text=msg.get("text"), title="错误")
                    return

            # 5. 渲染新视图并发送
            self._render_and_send(session)
        except Exception as e:
            logger.debug(f"出错了：{e}", exc_info=True)

    def _render_and_send(self, session: TSession):
        """
        根据 Session 的当前状态，渲染视图并发送/编辑消息。
        """
        # 1. 委托给 ViewRenderer 生成界面数据
        render_data = self.view_renderer.render(session)

        # 2. 发送或编辑消息
        self.__send_message(session, render_data=render_data)

        # 3. 处理会话结束逻辑
        if session.view.name in ["subscribe_success", "close"]:
            # 深复制会话的删除消息数据
            delete_message_data = deepcopy(session.get_delete_message_data())
            session_manager.end(session.session_id)
            # 等待一段时间让用户看到最后一条消息
            sleep(5)
            self.__delete_message(**delete_message_data)

    def __send_message(
        self, session: TSession, render_data: Optional[dict] = None, **kwargs
    ):
        """
        统一的消息发送接口。
        """
        context = asdict(session.message)
        if render_data:
            context.update(render_data)
        context.update(kwargs)
        # 将 user key改名成 userid，规避传入值只是user
        userid = context.get("user")
        if userid:
            context["userid"] = userid
            # 删除多余的 user 键
            context.pop("user", None)
        self.post_message(**context)

    def __delete_message(
        self,
        channel: MessageChannel,
        source: str,
        message_id: Union[str, int],
        chat_id: Optional[Union[str, int]] = None,
    ) -> bool:
        """
        删除会话中的原始消息。
        """
        # 兼容旧版本无删除方法
        if hasattr(self.chain, "delete_message"):
            return self.chain.delete_message(
                channel=channel, source=source, message_id=message_id, chat_id=chat_id
            )
        return False

    @staticmethod
    def _share_link_capabilities(text: str) -> Tuple[bool, bool, Optional[str]]:
        """
        判断分享消息分流：是否可走转存、是否可走 STRM（当前消息含 115 链接）

        :param text: 用户消息全文或命令参数
        :return: (can_transfer, can_strm, u115_url)；仅当 can_strm 为真时 u115_url 非空
        """
        can_transfer = bool(configer.share_recieve_paths)
        gen_cfg = configer.share_interactive_gen_strm_config
        local_path_ok = bool((gen_cfg.local_path or "").strip())
        u115 = ShareLinkResolver.extract_u115_share_url_from_text(text)
        can_strm = (
            local_path_ok
            and u115 is not None
            and ShareInteractiveGenStrmQueue.validate_prerequisites() is None
        )
        return can_transfer, can_strm, u115 if can_strm else None

    def _handle_offline_download(
        self,
        urls: Optional[List[str]],
        event_data: Dict[str, Any],
        userid: Optional[str],
    ):
        """
        处理离线下载公共流程

        :param urls: 已解析好的离线下载链接列表
        :param event_data: 事件上下文
        :param userid: 用户ID
        """
        url_list = [u for u in (urls or []) if u]

        if not url_list:
            logger.error(f"【离线下载】缺少参数：{event_data}")
            post_message(
                channel=event_data.get("channel"),
                source=event_data.get("source"),
                title=i18n.translate("p115_add_offline_no_recognized_link"),
                text=i18n.translate("p115_add_offline_no_recognized_link_detail"),
                userid=self._get_event_userid(event_data),
            )
            return

        if len(configer.offline_download_paths) <= 1:
            ok, added_count = servicer.offlinehelper.add_urls_to_transfer(url_list)
            if ok:
                post_message(
                    channel=event_data.get("channel"),
                    source=event_data.get("source"),
                    title=i18n.translate("p115_add_offline_success", count=added_count),
                    userid=userid,
                )
            else:
                post_message(
                    channel=event_data.get("channel"),
                    source=event_data.get("source"),
                    title=i18n.translate("p115_add_offline_fail"),
                    userid=userid,
                )
            return

        try:
            session = session_manager.get_or_create(
                event_data, plugin_id=self.__class__.__name__
            )

            action = Action(
                command="offline_download_path",
                view="offline_download_paths",
                value=url_list,
            )

            immediate_messages = self.action_handler.process(session, action)
            # 报错，截断后续运行
            if immediate_messages:
                for msg in immediate_messages:
                    self.__send_message(session, text=msg.get("text"), title="错误")
                return

            # 设置页面
            session.go_to("offline_download_paths")
            self._render_and_send(session)
        except Exception as e:
            logger.error(f"处理离线下载命令失败: {e}")

    @eventmanager.register(EventType.UserMessage)
    def user_add_share(self, event: Event):
        """
        用户消息中的分享链接：按配置分流转存、STRM 或双选菜单
        """
        if not configer.enabled:
            return
        text = event.event_data.get("text")
        if not text:
            return
        share_url = ShareLinkResolver.extract_share_url_from_text(text)
        if not share_url:
            return

        can_transfer, can_strm, u115 = self._share_link_capabilities(text)
        event_data = event.event_data
        channel = event_data.get("channel")
        source = event_data.get("source")
        userid = self._get_event_userid(event_data)

        if can_transfer and can_strm:
            try:
                session = session_manager.get_or_create(
                    event_data, plugin_id=self.__class__.__name__
                )
                session.business.share_recieve_url = share_url
                session.business.share_strm_u115_url = u115
                session.go_to("share_link_intent")
                self._render_and_send(session)
            except Exception as e:
                logger.error(f"处理分享链接意图菜单失败: {e}", exc_info=True)
            return

        if can_strm and not can_transfer:
            servicer.share_interactive_gen_strm_queue.enqueue_and_notify_user(
                share_url=u115,
                channel=channel,
                source=source,
                userid=userid,
            )
            return

        if can_transfer:
            if len(configer.share_recieve_paths) <= 1:
                servicer.sharetransferhelper.add_share(
                    url=share_url,
                    channel=channel,
                    source=source,
                    userid=userid,
                )
                return
            try:
                session = session_manager.get_or_create(
                    event_data, plugin_id=self.__class__.__name__
                )

                action = Action(
                    command="share_recieve_path",
                    view="share_recieve_paths",
                    value=share_url,
                )

                immediate_messages = self.action_handler.process(session, action)
                if immediate_messages:
                    for msg in immediate_messages:
                        self.__send_message(session, text=msg.get("text"), title="错误")
                    return

                session.go_to("share_recieve_paths")
                self._render_and_send(session)
            except Exception as e:
                logger.error(f"处理分享转存命令失败: {e}")
            return

        servicer.sharetransferhelper.add_share(
            url=share_url,
            channel=channel,
            source=source,
            userid=userid,
        )

    @eventmanager.register(EventType.UserMessage)
    def user_add_offline_links(self, event: Event):
        """
        用户消息中的离线链接：触发离线下载流程
        """
        if not configer.enabled:
            return
        if not configer.offline_download_paths:
            return
        if len(configer.offline_download_paths) <= 0:
            return
        event_data = event.event_data if event else {}
        text = (event_data.get("text") or "").strip()
        if not text:
            return
        offline_urls = OfflineLinkResolver.parse_offline_input(text)
        if not offline_urls:
            return
        userid = self._get_event_userid(event_data)
        self._handle_offline_download(
            urls=offline_urls,
            event_data=event_data,
            userid=userid,
        )

    @eventmanager.register(EventType.PluginAction)
    def p115_add_share(self, event: Event):
        """
        远程分享转存
        """
        args = None
        event_data = {}
        if event:
            event_data = event.event_data
            if not event_data or event_data.get("action") != "p115_add_share":
                return
            args = event_data.get("arg_str")
            if not args:
                logger.error(f"【分享转存】缺少参数：{event_data}")
                post_message(
                    channel=event.event_data.get("channel"),
                    source=event.event_data.get("source"),
                    title=i18n.translate("p115_add_share_parameter_error"),
                    userid=self._get_event_userid(event_data),
                )
                return

        share_url = (
            ShareLinkResolver.extract_share_url_from_text(args) if args else None
        )
        if not share_url:
            if args:
                logger.error(f"【分享转存】无法从参数中解析分享链接：{event_data}")
                post_message(
                    channel=event_data.get("channel"),
                    source=event_data.get("source"),
                    title=i18n.translate("p115_add_share_parameter_error"),
                    userid=self._get_event_userid(event_data),
                )
            return

        if len(configer.share_recieve_paths) <= 1:
            servicer.sharetransferhelper.add_share(
                url=share_url,
                channel=event.event_data.get("channel"),
                source=event.event_data.get("source"),
                userid=self._get_event_userid(event_data),
            )
            return

        try:
            session = session_manager.get_or_create(
                event.event_data, plugin_id=self.__class__.__name__
            )

            action = Action(
                command="share_recieve_path",
                view="share_recieve_paths",
                value=share_url,
            )

            immediate_messages = self.action_handler.process(session, action)
            # 报错，截断后续运行
            if immediate_messages:
                for msg in immediate_messages:
                    self.__send_message(session, text=msg.get("text"), title="错误")
                return

            # 设置页面
            session.go_to("share_recieve_paths")
            self._render_and_send(session)
        except Exception as e:
            logger.error(f"处理分享转存命令失败: {e}")

    @eventmanager.register(EventType.PluginAction)
    def p115_share_strm(self, event: Event):
        """
        分享交互生成 STRM（仅 115 链接，队列执行）
        """
        event_data = event.event_data if event else {}
        if not event_data or event_data.get("action") != "p115_share_strm":
            return
        args = event_data.get("arg_str")
        userid = self._get_event_userid(event_data)
        channel = event_data.get("channel")
        source = event_data.get("source")
        if not args:
            logger.error(f"【分享交互生成STRM】缺少参数：{event_data}")
            post_message(
                channel=channel,
                source=source,
                title=i18n.translate("p115_share_strm_parameter_error"),
                userid=userid,
            )
            return

        share_urls = ShareLinkResolver.extract_all_u115_share_urls_from_text(args)
        if not share_urls:
            if ShareLinkResolver.extract_share_url_from_text(args):
                post_message(
                    channel=channel,
                    source=source,
                    title=i18n.translate("p115_share_strm_not_u115_error"),
                    userid=userid,
                )
            else:
                post_message(
                    channel=channel,
                    source=source,
                    title=i18n.translate("p115_share_strm_parameter_error"),
                    userid=userid,
                )
            return

        err_key = ShareInteractiveGenStrmQueue.validate_prerequisites()
        if err_key:
            post_message(
                channel=channel,
                source=source,
                title=i18n.translate(err_key),
                userid=userid,
            )
            return

        pending = 0
        for share_url in share_urls:
            pending = servicer.share_interactive_gen_strm_queue.enqueue(
                share_url=share_url,
                channel=channel,
                source=source,
                userid=userid,
            )

        post_message(
            channel=channel,
            source=source,
            title=i18n.translate("p115_share_strm_done_title"),
            text=i18n.translate(
                "p115_share_strm_multi_queued",
                count=len(share_urls),
                pending=pending,
            ),
            userid=userid,
        )

    @eventmanager.register(EventType.PluginAction)
    def p115_add_offline(self, event: Event):
        """
        添加离线下载任务
        """
        event_data = event.event_data if event else {}
        if not event_data or event_data.get("action") != "p115_add_offline":
            return
        raw = (event_data.get("arg_str") or "").strip()
        if not raw:
            logger.error(f"【离线下载】缺少参数：{event_data}")
            post_message(
                channel=event_data.get("channel"),
                source=event_data.get("source"),
                title=i18n.translate("p115_add_offline_parameter_error"),
                userid=self._get_event_userid(event_data),
            )
            return
        url_list = OfflineLinkResolver.parse_offline_input(raw)
        if not url_list:
            logger.error(f"【离线下载】无法从参数中解析离线下载链接：{event_data}")
            post_message(
                channel=event_data.get("channel"),
                source=event_data.get("source"),
                title=i18n.translate("p115_add_offline_no_recognized_link"),
                text=i18n.translate("p115_add_offline_no_recognized_link_detail"),
                userid=self._get_event_userid(event_data),
            )
            return
        self._handle_offline_download(
            urls=url_list,
            event_data=event_data,
            userid=self._get_event_userid(event_data),
        )

    @eventmanager.register(EventType.WebhookMessage)
    def sync_del_by_webhook(self, event: Event):
        """
        通过Webhook事件同步删除媒体
        """
        if not configer.sync_del_enabled:
            return

        if not event or not event.event_data:
            return

        sync_del_webhook_queue.enqueue(
            SyncDelWebhookTask(
                event_data=deepcopy(event.event_data),
                enabled=configer.sync_del_enabled,
                notify=configer.sync_del_notify,
                del_source=configer.sync_del_source,
                p115_library_path=configer.sync_del_p115_library_path,
                p115_force_delete_files=configer.sync_del_p115_force_delete_files,
            )
        )

    @eventmanager.register(EventType.DownloadFileDeleted)
    def download_file_del_sync(self, event: Event):
        """
        下载文件删除处理事件
        """
        if not configer.sync_del_enabled:
            return

        if not event:
            return

        mediasyncdel_helper = MediaSyncDelHelper()
        mediasyncdel_helper.download_file_del_sync(event)

    @eventmanager.register(ChainEventType.TransferRenameBuild)
    def rename_dict_supplement(self, event: Event) -> None:
        """
        媒体数据补充

        响应主程序渲染前的 TransferRenameBuild 事件，通过 ffprobe / 中心化接口
        获取真实媒体信息（如 effect=SDR/HDR、视频/音频编码等），写回
        ``event_data.rename_dict``。

        与渲染后的 TransferRename 字符串改写类插件天然分层、互不冲突。
        """
        if not configer.enabled:
            return
        if not configer.rename_dict_supplement_enabled:
            return

        data = event.event_data
        if TransferRenameBuildEventData is None or not isinstance(
            data, TransferRenameBuildEventData
        ):
            return
        source_path: Optional[str] = data.source_path
        source_item: Optional[FileItem] = data.source_item
        if not source_path or not str(source_path).strip():
            logger.debug("【媒体数据补充】source_path 为空，跳过本次重命名补全")
            return
        if not source_item:
            logger.debug("【媒体数据补充】source_item 为空，跳过本次重命名补全")
            return

        if source_item.type != "file":
            logger.debug("【媒体数据补充】圆盘整理跳过本次重命名补全")
            return

        if Path(source_path).suffix.lower() not in settings.RMT_MEDIAEXT:
            logger.debug("【媒体数据补充】文件后缀不是媒体文件，跳过本次重命名补全")
            return

        def share_strm_center(url: str) -> Optional[Dict[str, Any]]:
            for i in ["P115StrmHelper", "share_code=", "receive_code=", "id="]:
                if i not in url:
                    return None
            try:
                _params = UrlUtils.parse_query_params(url)
                cache_key = (
                    f"{_params['share_code']}:{_params['receive_code']}:{_params['id']}"
                )
                if cache_key not in sharestrmcacher.file_item_dict:
                    return None
                _client = P115Center()
                _data_dict = sharestrmcacher.file_item_dict[cache_key]
                sharestrmcacher.file_item_dict.pop(cache_key)
                _resp = _client.download_emby_mediainfo_data(
                    [(_data_dict["sha1"], _data_dict["size"])]
                )
                _media_info = RenameDictUtils.emby_mediainfo_to_rename_fields(
                    _resp[_data_dict["sha1"].upper()]
                )
                if _media_info:
                    logger.info(f"【媒体数据补充】中心化获取媒体信息: {url}")
                    return _media_info
                return None
            except Exception as e:
                logger.warning(f"【媒体数据补充】{url} 中心化获取媒体信息失败: {e}")
                return None

        media_info: Dict[str, Any] = {}

        params: Dict[str, Any] = {"strm_resolve_media_info": share_strm_center}
        need_ffprobe = True
        if source_item.storage == "local":
            params["source_path"] = source_path
        elif source_item.storage in ["u115", "115网盘Plus"]:
            if source_item.fileid in pantransfercacher.file_item_dict:
                client = P115Center()
                data_dict = pantransfercacher.file_item_dict[source_item.fileid]
                try:
                    resp = client.download_emby_mediainfo_data(
                        [(data_dict["sha1"], data_dict["size"])]
                    )
                    media_info = RenameDictUtils.emby_mediainfo_to_rename_fields(
                        resp[data_dict["sha1"].upper()]
                    )
                    pantransfercacher.file_item_dict.pop(source_item.fileid)
                    if media_info:
                        logger.info(
                            f"【媒体数据补充】中心化获取媒体信息: {source_path}"
                        )
                        need_ffprobe = False
                    else:
                        logger.warning(
                            f"【媒体数据补充】{source_path} 中心化获取媒体信息为空"
                        )
                except Exception as e:
                    logger.warning(
                        f"【媒体数据补充】{source_path} 中心化获取媒体信息失败: {e}"
                    )
            params["url"] = (
                f"http://127.0.0.1:{settings.PORT}/api/v1/plugin/P115StrmHelper/redirect_url/{source_item.fileid}"
            )
        elif source_item.storage == "CloudDrive储存":
            params["url"] = (
                f"http://127.0.0.1:{settings.PORT}/api/v1/plugin/P115StrmHelper/redirect_url/{source_item.fileid}"
            )
        else:
            logger.error(f"【媒体数据补充】不支持的存储类型: {source_item.storage}")
            return
        if need_ffprobe:
            media_info, error_message = RenameDictUtils.ffprobe_get_media_info(**params)
            if not media_info:
                logger.error(f"【媒体数据补充】获取媒体信息失败: {error_message}")
                return
        overwrite_mode = configer.rename_dict_supplement_overwrite_mode
        if overwrite_mode not in ("fill_missing", "always"):
            overwrite_mode = "fill_missing"
        for key, value in media_info.items():
            if not value:
                continue
            if overwrite_mode == "fill_missing":
                cur = data.rename_dict.get(key)
                if cur is None:
                    pass
                elif isinstance(cur, str):
                    cur_stripped = cur.strip()
                    if cur_stripped and (key != "audioCodec" or re_search(r"\d+\.\d+", cur_stripped)):
                        continue
                else:
                    continue
            data.rename_dict[key] = value

    @eventmanager.register(ChainEventType.TransferIntercept)
    def intercept_if_exists_in_library(self, event: Event) -> None:
        """
        媒体库已存在时拦截整理
        """
        if not configer.enabled or not configer.transfer_intercept_exists_enabled:
            return

        data = event.event_data
        if TransferInterceptEventData is None or not isinstance(
            data, TransferInterceptEventData
        ):
            return

        if data.cancel:
            return

        mediainfo = data.mediainfo
        if not mediainfo:
            return

        try:
            exist_info = self.chain.media_exists(mediainfo=mediainfo)
        except Exception as e:
            logger.error(f"【媒体库存在拦截】查询媒体库失败: {e}", exc_info=True)
            return

        if not exist_info:
            return

        # 对于电视剧，需检查具体集是否已存在，而不是整部剧是否存在
        if getattr(mediainfo, "type", None) == MediaType.TV:
            file_meta = MetaVideo(title=data.target_path.name, isfile=True)
            season = file_meta.begin_season
            if season is not None and exist_info.seasons is not None:
                exist_episodes = set(exist_info.seasons.get(season, []))
                if file_meta.episode_list:
                    file_episodes = set(file_meta.episode_list)
                    if not file_episodes.issubset(exist_episodes):
                        logger.info(
                            f"【媒体库存在拦截】{data.fileitem.path} 集数 {file_episodes}"
                            f" 不在媒体库季 {season} 已有集 {exist_episodes} 中，跳过拦截"
                        )
                        return

        data.cancel = True
        data.source = "P115StrmHelper"
        media_title = getattr(mediainfo, "title", "") or ""
        data.reason = f"媒体库已存在：{media_title}（{exist_info.server}）"
        logger.info(f"【媒体库存在拦截】拦截整理 {data.fileitem.path}，{data.reason}")

        try:
            target_path = data.target_path
            if target_path.suffix:
                rename_format = settings.RENAME_FORMAT(getattr(mediainfo, "type", None))
                dir_to_clean = DirectoryHelper.get_media_root_path(
                    rename_format, target_path
                )
            else:
                dir_to_clean = target_path
            if not dir_to_clean:
                return
            storage_chain = StorageChain()
            dir_item = storage_chain.get_file_item(
                storage=data.target_storage,
                path=dir_to_clean,
            )
            if dir_item and dir_item.type == "dir":
                files = storage_chain.list_files(dir_item)
                if files is not None and not files:
                    storage_chain.delete_file(dir_item)
                    logger.info(f"【媒体库存在拦截】已清理空目录: {dir_to_clean}")
        except Exception as e:
            logger.debug(
                f"【媒体库存在拦截】清理空目录异常: {e}",
                exc_info=True,
            )

    @eventmanager.register(ChainEventType.TransferOverwriteCheck)
    def share_strm_overwrite_check(self, event: Event) -> None:
        """
        分享STRM覆盖大小检查
        """
        if not configer.enabled or not configer.share_strm_overwrite_check_enabled:
            return

        data = event.event_data
        if TransferOverwriteCheckEventData is None or not isinstance(
            data, TransferOverwriteCheckEventData
        ):
            return

        if data.target_path.suffix.lower() != ".strm":
            return

        try:
            url = data.target_path.read_text(encoding="utf-8").strip()
        except Exception:
            return

        if (
            "P115StrmHelper" not in url
            or "share_code=" not in url
            or "receive_code=" not in url
            or "id=" not in url
        ):
            return

        params = UrlUtils.parse_query_params(url)
        share_code = params.get("share_code")
        receive_code = params.get("receive_code")
        file_id = params.get("id")

        if not all([share_code, receive_code, file_id]):
            return

        cache_key = f"{share_code}:{receive_code}:{file_id}"

        if cache_key in sharestrmcacher.file_item_dict:
            cached = sharestrmcacher.file_item_dict[cache_key]
            data.target_size = cached.get("size")
            data.source = "P115StrmHelper"
            data.reason = "使用分享STRM缓存的真实文件大小"
            logger.info(
                f"【分享STRM覆盖检查】使用缓存大小: {data.target_size} for {data.target_path}"
            )
        else:
            media_info, error_message = RenameDictUtils.ffprobe_get_media_info(url=url)
            if media_info and media_info.get("file_size"):
                data.target_size = media_info["file_size"]
                data.source = "P115StrmHelper"
                data.reason = "使用ffprobe探测的实际文件大小"
                logger.info(
                    f"【分享STRM覆盖检查】使用ffprobe探测大小: {data.target_size} for {data.target_path}"
                )
            else:
                logger.warning(
                    f"【分享STRM覆盖检查】ffprobe探测失败: {error_message} for {url}"
                )

    @eventmanager.register(EventType.TransferFailed)
    def auto_delete_inferior_source(self, event: Event) -> None:
        """
        按文件大小整理失败时自动删除低质量源文件
        """
        if not configer.enabled or not configer.auto_delete_inferior_source_enabled:
            return

        event_data = event.event_data
        if not event_data:
            return

        transferinfo = event_data.get("transferinfo")
        if not transferinfo:
            return

        message = transferinfo.message or ""
        if "质量更好" not in message and "同名文件" not in message:
            return

        fileitem = event_data.get("fileitem")
        if not fileitem:
            return
        source_path = fileitem.path
        if not source_path:
            return

        try:
            storage_chain = StorageChain()
            if storage_chain.delete_media_file(fileitem=fileitem):
                logger.info(
                    f"【自动删除低质量源文件】已删除 {fileitem.storage} 源文件: {source_path}"
                )
            else:
                logger.error(
                    f"【自动删除低质量源文件】删除 {fileitem.storage} 源文件失败: {source_path}"
                )
                return

            # 发送通知
            if configer.notify:
                post_message(
                    mtype=NotificationType.Plugin,
                    title="【自动删除低质量源文件】源文件已删除",
                    text=f"\n因媒体库已存在更高质量文件，已自动删除源文件:\n{source_path}",
                )
        except Exception as e:
            logger.error(
                f"【自动删除低质量源文件】删除源文件失败: {source_path} - {e}",
                exc_info=True,
            )

    def stop_service(self):
        """
        退出插件
        """
        servicer.stop()
        ct_db_manager.close_database()
        U115Patcher().disable()
        P115DiskPatcher().disable()
        UploadNotifyAggregator.shutdown()

    async def _save_config_api(self, request: Request) -> Dict:
        """
        异步保存配置
        """
        try:
            data = await request.json()
            if not configer.update_config(data):
                return {"code": 1, "msg": "保存失败，请查看详细日志"}

            # 持久化存储配置
            configer.update_plugin_config()

            i18n.load_translations()

            sentry_manager.reload_config()

            # 重新初始化插件
            self.init_plugin(config=self.get_config())

            return {"code": 0, "msg": "保存成功"}
        except Exception as e:
            return {"code": 1, "msg": f"保存失败: {str(e)}"}
