from pathlib import Path
from typing import Optional, Union

from app.sdk.events import eventmanager
from app.sdk.media import MetaInfoPath
from app.sdk.media import MetaBase
from app.sdk.config import settings
from app.sdk.media import MediaInfo, resolve_media_identity
from app.sdk.logging import logger
from app.chain.media import MediaChain
from app.schemas.types import MediaType, EventType
from app.schemas import FileItem


def _same_media_identity(left: Optional[MediaInfo], right: Optional[MediaInfo]) -> bool:
    left_source, left_id = resolve_media_identity(left)
    right_source, right_id = resolve_media_identity(right)
    if (
        not left_source
        or not left_id
        or (left_source, left_id)
        != (
            right_source,
            right_id,
        )
    ):
        return False
    try:
        left_type = MediaType(left.type)
        right_type = MediaType(right.type)
    except (AttributeError, TypeError, ValueError):
        return False
    return left_type in (MediaType.MOVIE, MediaType.TV) and left_type == right_type


def media_scrape_metadata(
    path: Union[str, Path],
    item_name: str = "",
    mediainfo: Optional[MediaInfo] = None,
    meta: Optional[MetaBase] = None,
) -> None:
    """
    向宿主提交媒体刮削事件，由宿主异步执行刮削

    :param path (Path): 本地媒体文件路径，也接受字符串
    :param item_name (str): 日志显示的媒体名称
    :param mediainfo (MediaInfo): 已识别的媒体信息，缺省时按文件名识别
    :param meta (MetaBase): 文件元数据，缺省时由宿主解析
    """
    item_name = item_name if item_name else Path(path).name
    mediachain = MediaChain()
    logger.info(f"【媒体刮削】{item_name} 开始刮削元数据")
    if mediainfo:
        # 整理文件刮削
        if mediainfo.type == MediaType.MOVIE:
            # 电影刮削上级文件夹
            dir_path = Path(path).parent
            fileitem = FileItem(
                storage="local",
                type="dir",
                path=dir_path.as_posix(),
                name=dir_path.name,
                basename=dir_path.stem,
                modify_time=dir_path.stat().st_mtime,
            )
        else:
            # 电视剧刮削文件夹
            # 通过重命名格式判断根目录文件夹
            # 计算重命名中的文件夹层数
            rename_format_level = len(settings.TV_RENAME_FORMAT.split("/")) - 1
            if rename_format_level < 1:
                file_path = Path(path)
                fileitem = FileItem(
                    storage="local",
                    type="file",
                    path=file_path.as_posix(),
                    name=file_path.name,
                    basename=file_path.stem,
                    extension=file_path.suffix[1:].lower(),
                    size=file_path.stat().st_size,
                    modify_time=file_path.stat().st_mtime,
                )
            else:
                dir_path = Path(Path(path).parents[rename_format_level - 1])
                fileitem = FileItem(
                    storage="local",
                    type="dir",
                    path=dir_path.as_posix(),
                    name=dir_path.name,
                    basename=dir_path.stem,
                    modify_time=dir_path.stat().st_mtime,
                )
        eventmanager.send_event(
            EventType.MetadataScrape,
            {
                "meta": meta,
                "mediainfo": mediainfo,
                "fileitem": fileitem,
            },
        )
    else:
        # 对于没有 mediainfo 的媒体文件刮削
        # 获取媒体信息
        meta = MetaInfoPath(Path(path))
        mediainfo = mediachain.recognize_by_meta(meta)
        if not meta or not mediainfo:
            logger.info(f"【媒体刮削】{item_name} 获取媒体信息数据失败，跳过刮削")
            return
        # 判断刮削路径
        # 先获取上级目录 meta
        file_type = "dir"
        dir_path = Path(path).parent
        tem_mediainfo = mediachain.recognize_by_meta(MetaInfoPath(dir_path))
        # 只有上级目录信息和文件的信息一致时才继续判断上级目录
        if _same_media_identity(tem_mediainfo, mediainfo):
            if mediainfo.type == MediaType.TV:
                # 如果是电视剧，再次获取上级目录媒体信息，兼容电视剧命名，获取 mediainfo
                dir_path = dir_path.parent
                tem_mediainfo = mediachain.recognize_by_meta(MetaInfoPath(dir_path))
                if _same_media_identity(tem_mediainfo, mediainfo):
                    # 存在 mediainfo 则使用本级目录
                    finish_path = dir_path
                else:
                    # 否则使用上级目录
                    logger.warn(f"【媒体刮削】{dir_path} 无法识别文件媒体信息！")
                    finish_path = Path(path).parent
            else:
                # 电影情况，使用当前目录和元数据
                finish_path = dir_path
        else:
            # 如果上级目录没有媒体信息则使用传入的路径
            logger.warn(f"【媒体刮削】{dir_path} 无法识别文件媒体信息！")
            finish_path = Path(path)
            file_type = "file"
        fileitem = FileItem(
            storage="local",
            type=file_type,
            path=str(finish_path),
            name=finish_path.name,
            basename=finish_path.stem,
            modify_time=finish_path.stat().st_mtime,
        )
        eventmanager.send_event(
            EventType.MetadataScrape,
            {
                "meta": meta,
                "mediainfo": mediainfo,
                "fileitem": fileitem,
            },
        )

    logger.info(f"【媒体刮削】{item_name} 刮削元数据完成")
