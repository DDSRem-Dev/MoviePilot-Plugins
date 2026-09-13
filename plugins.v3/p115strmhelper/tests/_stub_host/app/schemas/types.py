"""宿主枚举与常量替身。"""

from enum import Enum


class MediaType(Enum):
    """媒体类型。"""

    MOVIE = "电影"
    TV = "电视剧"
    MUSIC = "音乐"
    UNKNOWN = "未知"


class MediaSource(str, Enum):
    """媒体数据源。"""

    TMDB = "tmdb"
    DOUBAN = "douban"
    BANGUMI = "bangumi"
    ANILIST = "anilist"
    TVDB = "tvdb"
    IMDB = "imdb"


class MessageType(Enum):
    """通知场景（V3 名；旧名 NotificationType）。"""

    Download = "资源下载"
    Organize = "整理入库"
    Subscribe = "订阅"
    SiteMessage = "站点"
    MediaServer = "媒体服务器"
    Manual = "手动处理"
    Plugin = "插件"
    Agent = "智能体"
    Other = "其它"


# 旧名别名：宿主兼容层同样保留，供仍按旧名书写的调用点使用
NotificationType = MessageType


class NotificationChannel(Enum):
    """通知渠道（V3 名；旧名 MessageChannel）。"""

    Telegram = "Telegram"
    WeChat = "微信"
    Webhook = "Webhook"
    Slave = "Slave"


MessageChannel = NotificationChannel


class EventType(Enum):
    """事件类型。"""

    PluginReload = "插件重载"
    PluginData = "插件数据"
    TransferComplete = "整理完成"


class ChainEventType(Enum):
    """链事件类型。"""

    TransferRenameBuild = "整理重命名构建"
    StorageOperSelection = "存储操作选择"
    TransferIntercept = "整理拦截"
    TransferOverwriteCheck = "整理覆盖检查"


class MediaImageType(Enum):
    """媒体图片类型。"""

    Poster = "海报"
    Backdrop = "背景图"
    Logo = "Logo"


class ContentType(Enum):
    """消息内容类型。"""

    Text = "text"
    Image = "image"


class ModuleType(Enum):
    """模块类型。"""

    Other = "其它"


class OtherModulesType(Enum):
    """其它模块子类型。"""

    Other = "其它"


class StorageAction(Enum):
    """存储操作。"""

    List = "list"
    Upload = "upload"


MUSIC_ENTITY_ALBUM = "album"
