"""
整理接管扩展名判定与事件分类测试模块

覆盖：_normalize_ext、_is_subtitle_file/_is_audio_file/_is_media_file、
is_subtitle_or_audio_file 及 discover 层关联匹配（extension 缺失回退）
"""

import importlib
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, List, Optional
from unittest import TestCase
from unittest.mock import MagicMock, patch

plugin_root = Path(__file__).resolve().parents[1]


def _make_module(name: str, **attrs: Any) -> ModuleType:
    """
    创建并注册假模块

    :param name (str): 模块名
    :param attrs (Dict): 模块属性

    :return ModuleType: 假模块
    """
    module = ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


def _make_pkg(name: str) -> ModuleType:
    """
    创建并注册假包

    :param name (str): 包名

    :return ModuleType: 假包
    """
    return _make_module(name, __path__=[])


class FakeSettings:
    """
    假 MoviePilot 设置
    """

    RMT_SUBEXT = [".srt", ".ass", ".ssa", ".sup"]
    RMT_AUDIOEXT = [".aac", ".ac3", ".m4a", ".flac"]
    RMT_MEDIAEXT = [".mp4", ".mkv", ".ts", ".iso", ".strm"]
    DEFAULT_SUB = "zh-cn"


class FakeFileItem:
    """
    假文件项
    """

    def __init__(
        self,
        path: Optional[str] = None,
        name: Optional[str] = None,
        extension: Optional[str] = None,
        type: str = "file",
    ) -> None:
        """
        初始化假文件项

        :param path (str): 路径
        :param name (str): 名称
        :param extension (str): 扩展名
        :param type (str): 类型
        """
        self.path = path
        self.name = name or (Path(path).name if path else None)
        self.extension = extension
        self.type = type


class FakeMetaInfoPath:
    """
    假元数据解析结果
    """

    def __init__(self, path: Path) -> None:
        """
        初始化假元数据

        :param path (Path): 路径
        """
        self.cn_name = None
        self.en_name = None
        self.part = None
        self.season = None
        self.episode = None


class FakeStorageChain:
    """
    假存储链
    """

    @staticmethod
    def is_bluray_folder(fileitem: Any) -> bool:
        """
        判断蓝光原盘目录

        :param fileitem (Any): 文件项

        :return bool: 是否蓝光原盘
        """
        return False


class FakeTransferTask:
    """
    假整理任务
    """

    def __init__(self, fileitem: FakeFileItem, target_path: Path) -> None:
        """
        初始化假整理任务

        :param fileitem (FakeFileItem): 文件项
        :param target_path (Path): 目标路径
        """
        self.fileitem = fileitem
        self.target_path = target_path
        self.related_files: List[Any] = []


class FakeRelatedFile:
    """
    假关联文件
    """

    def __init__(self, fileitem: Any, target_path: Path, file_type: str) -> None:
        """
        初始化假关联文件

        :param fileitem (Any): 文件项
        :param target_path (Path): 目标路径
        :param file_type (str): 文件类型
        """
        self.fileitem = fileitem
        self.target_path = target_path
        self.file_type = file_type


class FakePathUtils:
    """
    假路径工具
    """

    @staticmethod
    def get_media_path(paths: Any, file_path: Any) -> tuple:
        """
        获取媒体路径

        :param paths (Any): 监控目录配置
        :param file_path (Any): 文件路径

        :return tuple: (状态, 本地目录, 网盘目录)
        """
        return (True, "/local/媒体库", "/pan/媒体库")

    @staticmethod
    def sanitize_path_parts(path: Any) -> Any:
        """
        清洗路径段

        :param path (Any): 路径

        :return Any: 原路径
        """
        return path


def _setup_mock_env() -> None:
    """
    注册全部假依赖模块
    """
    for pkg in [
        "app",
        "app.sdk",
        "app.chain",
        "app.db",
        "app.db.oper",
        "app.schemas",
        "app.modules",
        "app.plugins",
        "p115client",
        "p115client.tool",
    ]:
        _make_pkg(pkg)

    _make_module(
        "app.sdk.logging",
        logger=SimpleNamespace(
            info=lambda *a, **k: None,
            debug=lambda *a, **k: None,
            warn=lambda *a, **k: None,
            warning=lambda *a, **k: None,
            error=lambda *a, **k: None,
        ),
    )
    _make_module("app.sdk.config", settings=FakeSettings())
    _make_module(
        "app.sdk.events",
        eventmanager=SimpleNamespace(send_event=lambda *a, **k: None),
    )
    _make_module(
        "app.sdk.media", MediaInfo=object, MetaBase=object, MetaInfoPath=FakeMetaInfoPath
    )
    _make_module("app.chain.storage", StorageChain=FakeStorageChain)
    _make_module(
        "app.chain.transfer",
        TransferChain=object,
        task_lock=SimpleNamespace(),
    )
    _make_module("app.db.oper.transferhistory", TransferHistoryOper=object)
    _make_module("app.application.directory", DirectoryHelper=object)
    _make_module(
        "app.schemas",
        FileItem=FakeFileItem,
        Message=object,
        TransferInfo=object,
        TransferTask=object,
    )
    _make_module(
        "app.schemas.types",
        EventType=SimpleNamespace(
            TransferComplete="TransferComplete",
            SubtitleTransferComplete="SubtitleTransferComplete",
            AudioTransferComplete="AudioTransferComplete",
            TransferFailed="TransferFailed",
            SubtitleTransferFailed="SubtitleTransferFailed",
            AudioTransferFailed="AudioTransferFailed",
        ),
        MediaType=object,
        MessageType=object,
        ChainEventType=object,
    )
    _make_module("app.sdk.utilities", StringUtils=object)
    _make_module("p115client", P115Client=object, check_response=lambda *a, **k: None)
    _make_module("p115client.tool.edit", update_name=object)
    _make_module("p115client.tool.attr", get_attr=object)
    _make_module("app.plugins.p115disk", __path__=[])

    _make_pkg("app.plugins.p115strmhelper")
    _make_pkg("app.plugins.p115strmhelper.core")
    _make_pkg("app.plugins.p115strmhelper.schemas")
    _make_pkg("app.plugins.p115strmhelper.db_manager")
    _make_pkg("app.plugins.p115strmhelper.helper")
    _make_pkg("app.plugins.p115strmhelper.helper.transfer")
    _make_module("app.plugins.p115strmhelper.core.config", configer=SimpleNamespace())
    _make_module(
        "app.plugins.p115strmhelper.schemas.transfer",
        TransferTask=object,
        RelatedFile=FakeRelatedFile,
    )
    _make_pkg("app.plugins.p115strmhelper.helper.strm")
    _make_module("app.plugins.p115strmhelper.core.scrape", media_scrape_metadata=object)
    _make_module("app.plugins.p115strmhelper.db_manager.oper", FileDbHelper=MagicMock)
    _make_module(
        "app.plugins.p115strmhelper.helper.mediainfo_download",
        MediaInfoDownloader=object,
    )
    _make_module(
        "app.plugins.p115strmhelper.helper.mediaserver",
        MediaServerRefresh=object,
        emby_mediainfo_queue=object,
    )
    _make_module(
        "app.plugins.p115strmhelper.utils.path",
        PathUtils=FakePathUtils,
        PathRemoveUtils=object,
    )
    _make_module(
        "app.plugins.p115strmhelper.utils.sentry",
        sentry_manager=SimpleNamespace(
            sentry_hub=SimpleNamespace(capture_exception=lambda *a, **k: None)
        ),
    )
    _make_module(
        "app.plugins.p115strmhelper.utils.strm",
        StrmUrlGetter=object,
        StrmGenerater=object,
    )


def _load_module(rel_path: str) -> Any:
    """
    按插件相对路径加载真实模块（绕过插件包 __init__，避免触发运行依赖）

    :param rel_path (str): 插件内相对路径，点号或斜杠均可，如 "helper.transfer.handler"

    :return Any: 已加载模块
    """
    module_name = f"app.plugins.p115strmhelper.{rel_path.replace('/', '.')}"
    file_rel = f"{rel_path.replace('.', '/')}.py"
    spec = importlib.util.spec_from_file_location(module_name, plugin_root / file_rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class TestExtNormalization(TestCase):
    """
    扩展名归一化测试
    """

    @classmethod
    def setUpClass(cls) -> None:
        """
        加载真实模块（先加载 handler 的依赖子模块）
        """
        _setup_mock_env()
        cls.cache_updater = _load_module("helper.transfer.cache_updater")
        cls.linked = _load_module("helper.transfer.linked_subtitle_audio")
        cls.linked_batch = _load_module("helper.transfer.handler_linked_batch")
        cls.handler = _load_module("helper.transfer.handler")

    def test_normalize_ext(self) -> None:
        """
        归一化兼容带点/不带点/大小写/空格
        """
        normalize = self.handler.TransferHandler._normalize_ext
        self.assertEqual(normalize("ass"), ".ass")
        self.assertEqual(normalize(".ass"), ".ass")
        self.assertEqual(normalize("ASS"), ".ass")
        self.assertEqual(normalize(" .Mkv "), ".mkv")
        self.assertIsNone(normalize(None))
        self.assertIsNone(normalize(""))

    def test_is_subtitle_file(self) -> None:
        """
        默认配置下字幕判定
        """
        is_sub = self.handler.TransferHandler._is_subtitle_file
        self.assertTrue(is_sub(FakeFileItem(extension="ass")))
        self.assertTrue(is_sub(FakeFileItem(extension="srt")))
        self.assertFalse(is_sub(FakeFileItem(extension="mkv")))
        self.assertFalse(is_sub(FakeFileItem(extension=None, path="/x/noext")))

    def test_is_subtitle_file_fallback_path(self) -> None:
        """
        extension 缺失时回退路径后缀（u115 存储 ico 缺失场景）
        """
        is_sub = self.handler.TransferHandler._is_subtitle_file
        self.assertTrue(
            is_sub(FakeFileItem(extension=None, path="/115/媒体库/x/xx.ass"))
        )
        self.assertFalse(
            is_sub(FakeFileItem(extension=None, path="/115/媒体库/x/xx.mkv"))
        )

    def test_is_subtitle_file_config_without_dot(self) -> None:
        """
        配置不带点时仍能判定（用户配置 srt,ass）
        """
        is_sub = self.handler.TransferHandler._is_subtitle_file
        with patch.object(FakeSettings, "RMT_SUBEXT", ["srt", "ass"]):
            self.assertTrue(is_sub(FakeFileItem(extension="ass")))
            self.assertFalse(is_sub(FakeFileItem(extension="ssa")))

    def test_is_media_file(self) -> None:
        """
        媒体文件判定
        """
        is_media = self.handler.TransferHandler._is_media_file
        self.assertTrue(is_media(FakeFileItem(extension="mkv")))
        self.assertTrue(is_media(FakeFileItem(extension="mp4")))
        self.assertFalse(is_media(FakeFileItem(extension="ass")))
        self.assertTrue(
            is_media(FakeFileItem(extension=None, path="/115/媒体库/x/xx.mkv"))
        )
        self.assertFalse(
            is_media(FakeFileItem(type="dir", extension=None, path="/115/原盘"))
        )

    def test_is_audio_file(self) -> None:
        """
        音轨文件判定
        """
        is_audio = self.handler.TransferHandler._is_audio_file
        self.assertTrue(is_audio(FakeFileItem(extension="flac")))
        self.assertFalse(is_audio(FakeFileItem(extension="ass")))
        self.assertTrue(
            is_audio(FakeFileItem(extension=None, path="/115/媒体库/x/xx.flac"))
        )

    def test_is_subtitle_or_audio_file(self) -> None:
        """
        拦截层字幕/音轨判定
        """
        check = self.linked.is_subtitle_or_audio_file
        self.assertTrue(check(FakeFileItem(extension="ass")))
        self.assertTrue(check(FakeFileItem(extension=None, path="/115/x/xx.srt")))
        self.assertTrue(check(FakeFileItem(extension="flac")))
        self.assertFalse(check(FakeFileItem(extension="mkv")))


class TestDiscoverRelatedFiles(TestCase):
    """
    关联文件发现测试
    """

    @classmethod
    def setUpClass(cls) -> None:
        """
        加载真实模块
        """
        _setup_mock_env()
        cls.linked = _load_module("helper.transfer.linked_subtitle_audio")

    def _build_task(self) -> FakeTransferTask:
        """
        构造假整理任务（主视频与字幕同名）

        :return FakeTransferTask: 假任务
        """
        main_video = FakeFileItem(
            path="/115/待整理/剑风传奇Berserk (1997)/Season 1/剑风传奇Berserk - S01E23 - 第 23 集.mkv",
            extension="mkv",
        )
        target = Path(
            "/115/媒体库/电视剧/日番/剑风传奇Berserk (1997)/Season 1/剑风传奇Berserk - S01E23 - 第 23 集.mkv"
        )
        return FakeTransferTask(fileitem=main_video, target_path=target)

    def test_match_subtitle_extension_missing(self) -> None:
        """
        extension 缺失时字幕仍能被关联
        """
        task = self._build_task()
        subtitle = FakeFileItem(
            path="/115/待整理/剑风传奇Berserk (1997)/Season 1/剑风传奇Berserk - S01E23 - 第 23 集.ass",
            extension=None,
        )
        main_metainfo = FakeMetaInfoPath(Path(task.fileitem.path))

        self.linked.match_subtitle_files(
            task, Path(task.fileitem.path), main_metainfo, [subtitle]
        )

        self.assertEqual(len(task.related_files), 1)
        related = task.related_files[0]
        self.assertEqual(related.file_type, "subtitle")
        self.assertTrue(str(related.target_path).endswith(".ass"))
        self.assertNotIn(".None", str(related.target_path))

    def test_match_audio_track_extension_missing(self) -> None:
        """
        extension 缺失时音轨仍能被关联
        """
        task = self._build_task()
        track = FakeFileItem(
            path="/115/待整理/剑风传奇Berserk (1997)/Season 1/剑风传奇Berserk - S01E23 - 第 23 集.flac",
            extension=None,
        )

        self.linked.match_audio_track_files(task, Path(task.fileitem.path), [track])

        self.assertEqual(len(task.related_files), 1)
        related = task.related_files[0]
        self.assertEqual(related.file_type, "audio_track")
        self.assertTrue(str(related.target_path).endswith(".flac"))
        self.assertNotIn(".None", str(related.target_path))

    def test_match_subtitle_non_subtitle_ignored(self) -> None:
        """
        非字幕文件不会被关联
        """
        task = self._build_task()
        nfo = FakeFileItem(
            path="/115/待整理/剑风传奇Berserk (1997)/Season 1/剑风传奇Berserk - S01E23 - 第 23 集.nfo",
            extension="nfo",
        )
        main_metainfo = FakeMetaInfoPath(Path(task.fileitem.path))

        self.linked.match_subtitle_files(
            task, Path(task.fileitem.path), main_metainfo, [nfo]
        )

        self.assertEqual(len(task.related_files), 0)
