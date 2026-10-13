import re
from pathlib import Path
from typing import List, Optional

from app.sdk.config import settings
from app.sdk.media import MetaBase
from app.sdk.media import MetaInfoPath
from app.sdk.logging import logger
from app.schemas import FileItem

from ...schemas.transfer import RelatedFile, TransferTask


def _normalize_ext(ext: Optional[str]) -> Optional[str]:
    """
    归一化扩展名（兼容配置中带点/不带点、大小写差异）

    :param ext (str): 原始扩展名

    :return str: 归一化后的带点小写扩展名，如 ".ass"
    """
    if not ext:
        return None
    return f".{str(ext).strip().lower().lstrip('.')}"


def _file_ext(fileitem: FileItem) -> Optional[str]:
    """
    获取文件项归一化扩展名（缺失时回退到路径后缀）

    :param fileitem (FileItem): 文件项

    :return str: 归一化后的带点小写扩展名，缺失时返回 None
    """
    ext = _normalize_ext(fileitem.extension)
    if not ext and fileitem.path:
        ext = _normalize_ext(Path(fileitem.path).suffix)
    return ext


def is_subtitle_or_audio_file(fileitem: FileItem) -> bool:
    """
    判断是否为字幕或独立音轨文件（与 MoviePilot RMT 后缀一致）

    :param fileitem (FileItem): 文件项
    :return: 是否为字幕或音轨
    """
    try:
        ext = _file_ext(fileitem)
        if not ext:
            return False
        return ext in {
            _normalize_ext(ext_item)
            for ext_item in settings.RMT_SUBEXT + settings.RMT_AUDIOEXT
        }
    except Exception as e:
        logger.debug(f"【整理接管】判断字幕/音频文件失败: {e}")
        return False


def match_subtitle_files(
    task: TransferTask,
    main_video_path: Path,
    main_video_metainfo: MetaBase,
    files: List[FileItem],
) -> None:
    """
    匹配字幕文件并追加到 task.related_files
    """
    _zhcn_sub_re = (
        r"([.\[(\s](((zh[-_])?(cn|ch[si]|sg|sc))|zho?"
        r"|chinese|(cn|ch[si]|sg|zho?)[-_&]?(cn|ch[si]|sg|zho?|eng|jap|ja|jpn)"
        r"|eng[-_&]?(cn|ch[si]|sg|zho?)|(jap|ja|jpn)[-_&]?(cn|ch[si]|sg|zho?)"
        r"|简[体中]?)[.\])\s])"
        r"|([\u4e00-\u9fa5]{0,3}[中双][\u4e00-\u9fa5]{0,2}[字文语][\u4e00-\u9fa5]{0,3})"
        r"|简体|简中|JPSC|sc_jp"
        r"|(?<![a-z0-9])gb(?![a-z0-9])"
    )
    _zhtw_sub_re = (
        r"([.\[(\s](((zh[-_])?(hk|tw|cht|tc))"
        r"|cht[-_&]?(cht|eng|jap|ja|jpn)"
        r"|eng[-_&]?cht|(jap|ja|jpn)[-_&]?cht"
        r"|繁[体中]?)[.\])\s])"
        r"|繁体中[文字]|中[文字]繁体|繁体|JPTC|tc_jp"
        r"|(?<![a-z0-9])big5(?![a-z0-9])"
    )
    _ja_sub_re = (
        r"([.\[(\s](ja-jp|jap|ja|jpn"
        r"|(jap|ja|jpn)[-_&]?eng|eng[-_&]?(jap|ja|jpn))[.\])\s])"
        r"|日本語|日語"
    )
    _eng_sub_re = r"[.\[(\s]eng[.\])\s]"

    _sub_exts = {_normalize_ext(ext_item) for ext_item in settings.RMT_SUBEXT}

    subtitle_files = [
        f
        for f in files
        if f.path != task.fileitem.path
        and f.type == "file"
        and (ext := _file_ext(f))
        and ext in _sub_exts
    ]

    if not subtitle_files:
        logger.debug(f"【整理接管】{main_video_path.parent} 目录下没有找到字幕文件")
        return

    logger.debug(f"【整理接管】字幕文件清单：{[f.name for f in subtitle_files]}")

    for sub_item in subtitle_files:
        sub_file_name = re.sub(
            _zhtw_sub_re,
            ".",
            re.sub(_zhcn_sub_re, ".", sub_item.name, flags=re.I),
            flags=re.I,
        )
        sub_file_name = re.sub(_eng_sub_re, ".", sub_file_name, flags=re.I)
        sub_metainfo = MetaInfoPath(Path(sub_item.path))

        if (
            main_video_path.stem == Path(sub_file_name).stem
            or (
                sub_metainfo.cn_name
                and sub_metainfo.cn_name == main_video_metainfo.cn_name
            )
            or (
                sub_metainfo.en_name
                and sub_metainfo.en_name == main_video_metainfo.en_name
            )
        ):
            if (
                main_video_metainfo.part
                and main_video_metainfo.part != sub_metainfo.part
            ):
                continue
            if (
                main_video_metainfo.season
                and main_video_metainfo.season != sub_metainfo.season
            ):
                continue
            if (
                main_video_metainfo.episode
                and main_video_metainfo.episode != sub_metainfo.episode
            ):
                continue

            new_file_type = ""
            if re.search(_zhcn_sub_re, sub_item.name, re.I):
                new_file_type = ".chi.zh-cn"
            elif re.search(_zhtw_sub_re, sub_item.name, re.I):
                new_file_type = ".zh-tw"
            elif re.search(_ja_sub_re, sub_item.name, re.I):
                new_file_type = ".ja"
            elif re.search(_eng_sub_re, sub_item.name, re.I):
                new_file_type = ".eng"

            file_ext = _file_ext(sub_item) or ""
            new_sub_tag_dict = {
                ".eng": ".英文",
                ".chi.zh-cn": ".简体中文",
                ".zh-tw": ".繁体中文",
            }
            new_sub_tag_list = [
                (
                    (
                        ".default" + new_file_type
                        if (
                            (
                                settings.DEFAULT_SUB == "zh-cn"
                                and new_file_type == ".chi.zh-cn"
                            )
                            or (
                                settings.DEFAULT_SUB == "zh-tw"
                                and new_file_type == ".zh-tw"
                            )
                            or (settings.DEFAULT_SUB == "ja" and new_file_type == ".ja")
                            or (
                                settings.DEFAULT_SUB == "eng"
                                and new_file_type == ".eng"
                            )
                        )
                        else new_file_type
                    )
                    if t == 0
                    else f"{new_file_type}{new_sub_tag_dict.get(new_file_type, '')}({t})"
                )
                for t in range(6)
            ]

            for new_sub_tag in new_sub_tag_list:
                target_path = task.target_path.with_name(
                    task.target_path.stem + new_sub_tag + file_ext
                )

                related_file = RelatedFile(
                    fileitem=sub_item,
                    target_path=target_path,
                    file_type="subtitle",
                )
                task.related_files.append(related_file)

                logger.debug(
                    f"【整理接管】发现字幕文件: {sub_item.name} -> {target_path.name}"
                )
                break


def match_audio_track_files(
    task: TransferTask,
    main_video_path: Path,
    files: List[FileItem],
) -> None:
    """
    匹配音轨文件并追加到 task.related_files
    """
    _audio_exts = {_normalize_ext(ext_item) for ext_item in settings.RMT_AUDIOEXT}

    audio_track_files = [
        file
        for file in files
        if file.path != task.fileitem.path
        and Path(file.name).stem == main_video_path.stem
        and file.type == "file"
        and (ext := _file_ext(file))
        and ext in _audio_exts
    ]

    if not audio_track_files:
        logger.debug(
            f"【整理接管】{main_video_path.parent} 目录下没有找到匹配的音轨文件"
        )
        return

    logger.debug(f"【整理接管】音轨文件清单：{[f.name for f in audio_track_files]}")

    for track_file in audio_track_files:
        track_ext = _file_ext(track_file) or ""
        target_path = task.target_path.with_name(task.target_path.stem + track_ext)

        related_file = RelatedFile(
            fileitem=track_file,
            target_path=target_path,
            file_type="audio_track",
        )
        task.related_files.append(related_file)

        logger.debug(
            f"【整理接管】发现音轨文件: {track_file.name} -> {target_path.name}"
        )
