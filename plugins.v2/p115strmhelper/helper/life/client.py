from filecmp import cmp as files_equal
from shutil import move as shutil_move, rmtree
from collections import defaultdict
from threading import Timer, Event, Thread
from time import sleep, strftime, localtime, time
from typing import Any, Dict, List, Optional, Set, Tuple
from pathlib import Path
from itertools import batched

from ...core.config import configer
from ...core.message import post_message
from ...core.scrape import media_scrape_metadata
from ...core.cache import idpathcacher, pantransfercacher
from ...core.i18n import i18n
from ...core.p115 import get_pid_by_path
from ...utils.path import PathUtils, PathRemoveUtils
from ...utils.storage_item import (
    resolve_directory_via_parent_list,
    resolve_file_via_parent_list,
)
from ...utils.sentry import sentry_manager
from ...utils.strm import StrmUrlGetter, StrmGenerater
from ...utils.automaton import AutomatonUtils
from ...utils.mediainfo_download import MediainfoDownloadMiddleware
from ...utils.http import check_iter_path_data
from ...utils.exception import FileItemKeyMiss
from ...db_manager.oper import FileDbHelper, LifeEventDbHelper
from ...helper.mediainfo_download import MediaInfoDownloader
from ...helper.mediasyncdel import MediaSyncDelHelper
from ...helper.mediaserver import MediaServerRefresh, emby_mediainfo_queue

from urllib.error import HTTPError

from p115client import P115Client, check_response
from p115client.exception import P115AuthenticationError, P115OSError
from p115client.tool.attr import get_path, normalize_attr
from p115client.tool.fs_files import iter_fs_files
from p115client.tool.iterdir import iter_files_with_path
from p115client.tool.life import (
    life_show,
    iter_life_behavior_once,
    BEHAVIOR_TYPE_TO_NAME,
)

from app.schemas import NotificationType, FileItem
from app.log import logger
from app.core.config import settings
from app.chain.storage import StorageChain
from app.chain.transfer import TransferChain


@sentry_manager.capture_all_class_exceptions
class MonitorLife:
    """
    监控115生活事件

    {
        1: "upload_image_file",  上传图片 生成 STRM;写入数据库
        2: "upload_file",        上传文件/目录 生成 STRM;写入数据库
        3: "star_image",         标星图片 无操作
        4: "star_file",          标星文件/目录 无操作
        5: "move_image_file",    移动图片 生成 STRM;写入数据库
        6: "move_file",          移动文件/目录 生成 STRM;写入数据库
        7: "browse_image",       浏览图片 无操作
        8: "browse_video",       浏览视频 无操作
        9: "browse_audio",       浏览音频 无操作
        10: "browse_document",   浏览文档 无操作
        14: "receive_files",     接收文件 生成 STRM;写入数据库
        17: "new_folder",        创建新目录 写入数据库
        18: "copy_folder",       复制文件夹 生成 STRM;写入数据库
        19: "folder_label",      标签文件夹 无操作
        20: "folder_rename",     重命名文件夹 重命名本地文件夹;更新数据库
        22: "delete_file",       删除文件/文件夹 删除 STRM;移除数据库
        23: "copy_file",         复制文件 生成 STRM;写入数据库
        24: "rename_file",       重命名文件 重命名本地文件/生成新STRM;更新数据库
    }
    """

    WAIT_TIME_OUT: int = 15
    SLEEP_TIME: int = 10
    WEB_FALLBACK_DURATION: int = 24 * 60 * 60

    def __init__(
        self,
        client: P115Client,
        mediainfodownloader: MediaInfoDownloader,
        stop_event: Optional[Event] = None,
    ):
        """
        初始化生活事件监听器

        :param client (P115Client): P115Client 实例
        :param mediainfodownloader (MediaInfoDownloader): 媒体信息下载器实例
        :param stop_event (Event): 可选的停止事件，用于控制监听循环
        """
        self._client = client
        self.mediainfodownloader = mediainfodownloader
        self.stop_event = stop_event

        self._monitor_life_notification_timer = None
        self._monitor_life_notification_queue = defaultdict(
            lambda: {"strm_count": 0, "mediainfo_count": 0}
        )

        self.rmt_mediaext: List = []
        self.rmt_mediaext_set: Set = set()
        self.download_mediaext_set: Set = set()

        self.mdaw = AutomatonUtils.build_automaton(
            configer.mediainfo_download_whitelist
        )
        self.mdab = AutomatonUtils.build_automaton(
            configer.mediainfo_download_blacklist
        )

        self.mediaserver_helper = MediaServerRefresh(
            func_name="【监控生活事件】",
            enabled=configer.monitor_life_media_server_refresh_enabled,
            mp_mediaserver=configer.monitor_life_mp_mediaserver_paths,
            mediaservers=configer.monitor_life_mediaservers,
            delay_seconds=configer.monitor_life_media_server_refresh_delay,
        )

        self.storagechain = StorageChain()

    def _schedule_notification(self):
        """
        安排通知发送，如果一分钟内没有新事件则发送
        """
        if self._monitor_life_notification_timer:
            self._monitor_life_notification_timer.cancel()

        self._monitor_life_notification_timer = Timer(60.0, self._send_notification)
        self._monitor_life_notification_timer.start()

    def _send_notification(self):
        """
        发送合并后的通知
        """
        if "life" not in self._monitor_life_notification_queue:
            return

        counts = self._monitor_life_notification_queue["life"]
        if counts["strm_count"] == 0 and counts["mediainfo_count"] == 0:
            return

        text_parts = []
        if counts["strm_count"] > 0:
            text_parts.append(f"📄 生成STRM文件 {counts['strm_count']} 个")
        if counts["mediainfo_count"] > 0:
            text_parts.append(f"⬇️ 下载媒体文件 {counts['mediainfo_count']} 个")

        if text_parts and configer.get_config("notify"):
            post_message(
                mtype=NotificationType.Plugin,
                title=i18n.translate("life_sync_done_title"),
                text="\n" + "\n".join(text_parts),
            )

        # 重置计数器
        self._monitor_life_notification_queue["life"] = {
            "strm_count": 0,
            "mediainfo_count": 0,
        }

    def _get_path_by_cid(self, cid: int) -> Optional[Path]:
        """
        通过 cid 获取路径
        先从缓存获取，再从数据库获取，最后通过API获取
        """
        if int(cid) == 0:
            return Path("/")
        _databasehelper = FileDbHelper()
        dir_path = idpathcacher.get_dir_by_id(cid)
        if not dir_path:
            data = _databasehelper.get_by_id(id=cid)
            if data:
                dir_path = data.get("path", "")
                if dir_path:
                    logger.debug(f"获取 {cid} 路径（数据库）: {dir_path}")
                    idpathcacher.add_cache(id=cid, directory=str(dir_path))
                    return Path(dir_path)
            dir_path = get_path(
                client=self._client,
                attr=cid,
                root_id=None,
                refresh=True,
                **configer.get_ios_ua_app(app=False),
            )
            if not dir_path:
                logger.error(f"获取 {cid} 路径失败")
                return None
            if not isinstance(dir_path, (str, Path)):
                logger.error(f"获取 {cid} 路径失败，路径类型异常: {type(dir_path)}")
                return None
            if isinstance(dir_path, Path):
                dir_path = dir_path.as_posix()
            if dir_path.startswith("根目录"):
                dir_path = dir_path[3:]
            idpathcacher.add_cache(id=cid, directory=str(dir_path))
            logger.debug(f"获取 {cid} 路径（API）: {dir_path}")
            return Path(dir_path)
        logger.debug(f"获取 {cid} 路径（缓存）: {dir_path}")
        return Path(dir_path)

    def _media_transfer_folder_cd2(
        self,
        org_file_path: str,
        rmt_mediaext: List,
        transferchain: TransferChain,
    ) -> None:
        """
        在 CloudDrive2 挂载路径上递归 list_files，将媒体文件加入整理队列

        :param org_file_path (str): 115 侧目录路径（posix）
        :param rmt_mediaext (List): 待整理媒体扩展名列表（含前导点）
        :param transferchain (TransferChain): 整理链实例
        """
        cd2_root = Path(
            configer.pan_transfer_clouddrive2_config.prefix
        ) / org_file_path.lstrip("/")
        root = resolve_directory_via_parent_list(
            self.storagechain,
            "CloudDrive储存",
            cd2_root,
            log_label="【网盘整理】",
        )
        if not root:
            return

        if str(root.fileid) not in pantransfercacher.delete_pan_transfer_list:
            pantransfercacher.delete_pan_transfer_list.append(str(root.fileid))

        def walk_cd2_dir(dir_item: FileItem) -> None:
            """
            递归遍历 CloudDrive2 目录，将媒体文件加入整理队列

            :param dir_item (FileItem): CloudDrive2 目录 FileItem
            """
            try:
                entries = self.storagechain.list_files(dir_item)
            except Exception as e:
                logger.error(
                    "【网盘整理】list_files 失败: %s %s",
                    dir_item.path,
                    e,
                    exc_info=True,
                )
                return
            if not entries:
                return
            for entry in entries:
                parent_s = str(entry.parent_fileid)
                if parent_s not in pantransfercacher.delete_pan_transfer_list:
                    pantransfercacher.delete_pan_transfer_list.append(parent_s)
                if entry.type == "dir":
                    walk_cd2_dir(entry)
                    continue
                entry_path = entry.path
                if not entry_path:
                    logger.warning("【网盘整理】路径为空，跳过: %s", entry)
                    continue
                p = Path(str(entry_path))
                sfx = p.suffix.lower()
                if sfx in rmt_mediaext:
                    fid_s = str(entry.fileid)
                    if fid_s not in pantransfercacher.creata_pan_transfer_list:
                        pantransfercacher.creata_pan_transfer_list.append(fid_s)
                    fileitem = FileItem(
                        storage="CloudDrive储存",
                        fileid=fid_s,
                        parent_fileid=str(entry.parent_fileid),
                        path=p.as_posix(),
                        type="file",
                        name=entry.name,
                        basename=entry.basename,
                        extension=(entry.extension or p.suffix[1:] or "").lower(),
                        size=entry.size if entry.size is not None else 0,
                        pickcode=None,
                        modify_time=int(entry.modify_time or 0),
                    )
                    transferchain.do_transfer(fileitem=fileitem)
                    logger.info("【网盘整理】%s 加入整理列队", p)
                elif sfx in settings.RMT_AUDIOEXT or sfx in settings.RMT_SUBEXT:
                    fid_s = str(entry.fileid)
                    if fid_s not in pantransfercacher.creata_pan_transfer_list:
                        pantransfercacher.creata_pan_transfer_list.append(fid_s)
                    fileitem = FileItem(
                        storage="CloudDrive储存",
                        fileid=fid_s,
                        parent_fileid=str(entry.parent_fileid),
                        path=p.as_posix(),
                        type="file",
                        name=entry.name,
                        basename=entry.basename,
                        extension=(entry.extension or p.suffix[1:] or "").lower(),
                        size=entry.size if entry.size is not None else 0,
                        pickcode=None,
                        modify_time=int(entry.modify_time or 0),
                    )
                    transferchain.do_transfer(fileitem=fileitem)
                    logger.info("【网盘整理】%s 加入整理列队", p)

        walk_cd2_dir(root)

    def media_transfer(self, event: Dict[str, Any], file_path: Path, rmt_mediaext):
        """
        运行媒体文件整理

        :param event (Dict): 事件
        :param file_path (Path): 文件路径
        :param rmt_mediaext (List): 媒体文件后缀名
        """
        org_file_path = file_path.as_posix()
        _databasehelper = FileDbHelper()
        transferchain = TransferChain()
        file_category = event["file_category"]
        file_id = event["file_id"]
        if file_category == 0:
            logger.info(f"【网盘整理】开始处理 {file_path} 文件夹中...")
            _databasehelper.remove_by_id_batch(int(event["file_id"]), False)
            # 文件夹情况，遍历文件夹，获取整理文件
            if configer.pan_transfer_clouddrive2_config.enabled:
                sleep(2)
                self._media_transfer_folder_cd2(
                    org_file_path,
                    rmt_mediaext,
                    transferchain,
                )
            else:
                # 缓存顶层文件夹ID
                if (
                    str(event["file_id"])
                    not in pantransfercacher.delete_pan_transfer_list
                ):
                    pantransfercacher.delete_pan_transfer_list.append(
                        str(event["file_id"])
                    )
                for item in iter_files_with_path(
                    self._client,
                    cid=int(file_id),
                    with_ancestors=True,
                    cooldown=2,
                    **configer.get_ios_ua_app(),
                ):
                    try:
                        check_iter_path_data(item)
                    except FileItemKeyMiss as e:
                        logger.warning(f"【网盘整理】数据拉取异常: {e}")
                        continue
                    item_path = item.get("path")
                    if not item_path:
                        logger.warning("【网盘整理】数据路径为空，跳过: %s", item)
                        continue
                    file_path = Path(str(item_path))
                    if not PathUtils.has_prefix(file_path, org_file_path):
                        continue
                    # 缓存文件夹ID
                    if (
                        str(item["parent_id"])
                        not in pantransfercacher.delete_pan_transfer_list
                    ):
                        pantransfercacher.delete_pan_transfer_list.append(
                            str(item["parent_id"])
                        )
                    if file_path.suffix.lower() in rmt_mediaext:
                        # 缓存文件ID
                        if (
                            str(item["id"])
                            not in pantransfercacher.creata_pan_transfer_list
                        ):
                            pantransfercacher.creata_pan_transfer_list.append(
                                str(item["id"])
                            )
                        # 缓存文件信息用于ffprobe命名补充
                        if (
                            str(item["id"])
                            not in pantransfercacher.file_item_dict.keys()
                        ):
                            pantransfercacher.file_item_dict[str(item["id"])] = {
                                "sha1": item["sha1"],
                                "size": item["size"],
                            }
                        fileitem = FileItem(
                            storage=configer.storage_module,
                            fileid=str(item["id"]),
                            parent_fileid=str(item["parent_id"]),
                            path=file_path.as_posix(),
                            type="file",
                            name=file_path.name,
                            basename=file_path.stem,
                            extension=file_path.suffix[1:].lower(),
                            size=item["size"],
                            pickcode=item["pickcode"],
                            modify_time=item["ctime"],
                        )
                        transferchain.do_transfer(fileitem=fileitem)
                        logger.info(f"【网盘整理】{file_path} 加入整理列队")
                    if (
                        file_path.suffix.lower() in settings.RMT_AUDIOEXT
                        or file_path.suffix.lower() in settings.RMT_SUBEXT
                    ):
                        # 如果是MP可处理的音轨或字幕文件，则缓存文件ID
                        if (
                            str(item["id"])
                            not in pantransfercacher.creata_pan_transfer_list
                        ):
                            pantransfercacher.creata_pan_transfer_list.append(
                                str(item["id"])
                            )
                        fileitem = FileItem(
                            storage=configer.storage_module,
                            fileid=str(item["id"]),
                            parent_fileid=str(item["parent_id"]),
                            path=file_path.as_posix(),
                            type="file",
                            name=file_path.name,
                            basename=file_path.stem,
                            extension=file_path.suffix[1:].lower(),
                            size=item["size"],
                            pickcode=item["pickcode"],
                            modify_time=item["ctime"],
                        )
                        transferchain.do_transfer(fileitem=fileitem)
                        logger.info(f"【网盘整理】{file_path} 加入整理列队")
        else:
            # 文件情况，直接整理
            if file_path.suffix.lower() in rmt_mediaext:
                _databasehelper.remove_by_id("file", event["file_id"])
                # 缓存文件ID
                if (
                    str(event["file_id"])
                    not in pantransfercacher.creata_pan_transfer_list
                ):
                    pantransfercacher.creata_pan_transfer_list.append(
                        str(event["file_id"])
                    )
                # 缓存文件信息用于ffprobe命名补充
                if str(event["file_id"]) not in pantransfercacher.file_item_dict.keys():
                    pantransfercacher.file_item_dict[str(event["file_id"])] = {
                        "sha1": event["sha1"],
                        "size": event["file_size"],
                    }
                if configer.pan_transfer_clouddrive2_config.enabled:
                    sleep(2)
                    cd2_path = Path(
                        configer.pan_transfer_clouddrive2_config.prefix
                    ) / file_path.as_posix().lstrip("/")
                    fileitem = resolve_file_via_parent_list(
                        self.storagechain,
                        "CloudDrive储存",
                        cd2_path,
                        log_label="【网盘整理】",
                    )
                    if not fileitem:
                        return
                else:
                    fileitem = FileItem(
                        storage=configer.storage_module,
                        fileid=str(file_id),
                        parent_fileid=str(event["parent_id"]),
                        path=file_path.as_posix(),
                        type="file",
                        name=file_path.name,
                        basename=file_path.stem,
                        extension=file_path.suffix[1:].lower(),
                        size=event["file_size"],
                        pickcode=event["pick_code"],
                        modify_time=event["update_time"],
                    )
                transferchain.do_transfer(fileitem=fileitem)
                logger.info(f"【网盘整理】{file_path} 加入整理列队")
            elif file_path.suffix.lower() in (
                settings.RMT_AUDIOEXT + settings.RMT_SUBEXT
            ):
                _databasehelper.remove_by_id("file", event["file_id"])
                # 缓存文件ID
                if (
                    str(event["file_id"])
                    not in pantransfercacher.creata_pan_transfer_list
                ):
                    pantransfercacher.creata_pan_transfer_list.append(
                        str(event["file_id"])
                    )
                if configer.pan_transfer_clouddrive2_config.enabled:
                    sleep(2)
                    cd2_path = Path(
                        configer.pan_transfer_clouddrive2_config.prefix
                    ) / file_path.as_posix().lstrip("/")
                    fileitem = resolve_file_via_parent_list(
                        self.storagechain,
                        "CloudDrive储存",
                        cd2_path,
                        log_label="【网盘整理】",
                    )
                    if not fileitem:
                        return
                else:
                    fileitem = FileItem(
                        storage=configer.storage_module,
                        fileid=str(file_id),
                        parent_fileid=str(event["parent_id"]),
                        path=file_path.as_posix(),
                        type="file",
                        name=file_path.name,
                        basename=file_path.stem,
                        extension=file_path.suffix[1:].lower(),
                        size=event["file_size"],
                        pickcode=event["pick_code"],
                        modify_time=event["update_time"],
                    )
                transferchain.do_transfer(fileitem=fileitem)
                logger.info(f"【网盘整理】{file_path} 加入整理列队")

    def _create(self, event: Dict[str, Any], file_path: Path):
        """
        创建 STRM 文件

        :param event (Dict): 事件
        :param file_path (Path): 路径
        """
        _databasehelper = FileDbHelper()

        _get_url = StrmUrlGetter()

        org_file_path = file_path.as_posix()
        pickcode = event["pick_code"]
        file_category = event["file_category"]
        file_id = event["file_id"]
        status, target_dir, pan_media_dir = PathUtils.get_media_path(
            configer.get_config("monitor_life_paths"), file_path
        )
        if not status or target_dir is None or pan_media_dir is None:
            return
        logger.debug("【监控生活事件】匹配到网盘文件夹路径: %s", str(pan_media_dir))

        if file_category == 0:
            # 文件夹情况，遍历文件夹
            mediainfo_count = 0
            strm_count = 0
            _databasehelper.upsert_batch(
                _databasehelper.process_life_dir_item(
                    event=event, file_path=file_path.as_posix()
                )
            )
            for batch in batched(
                iter_files_with_path(
                    self._client,
                    cid=int(file_id),
                    with_ancestors=True,
                    cooldown=2,
                    **configer.get_ios_ua_app(),
                ),
                7_000,
            ):
                processed = []
                for item in batch:
                    try:
                        check_iter_path_data(item)
                    except FileItemKeyMiss as e:
                        logger.warning(f"【监控生活事件】数据拉取异常: {e}")
                        continue
                    _process_item = _databasehelper.process_item(item)
                    if _process_item not in processed:
                        processed.extend(_process_item)
                    if item["is_dir"]:
                        continue
                    if "creata" in configer.monitor_life_event_modes:
                        file_path = item["path"]
                        if not PathUtils.has_prefix(file_path, org_file_path):
                            continue
                        file_path = Path(target_dir) / PathUtils.sanitize_path_parts(
                            Path(file_path).relative_to(pan_media_dir)
                        )
                        file_target_dir = file_path.parent
                        original_file_name = file_path.name
                        file_name = StrmGenerater.get_strm_filename(file_path)
                        new_file_path = file_target_dir / file_name

                        if configer.get_config(
                            "monitor_life_auto_download_mediainfo_enabled"
                        ):
                            if file_path.suffix.lower() in self.download_mediaext_set:
                                if not (
                                    result
                                    := MediainfoDownloadMiddleware.should_download(
                                        filename=original_file_name,
                                        blacklist_automaton=self.mdab,
                                        whitelist_automaton=self.mdaw,
                                    )
                                )[1]:
                                    logger.warning(
                                        "【监控生活事件】%s，跳过网盘路径: %s",
                                        result[0],
                                        item["path"],
                                    )
                                    continue

                                pickcode = item["pickcode"]
                                if not pickcode:
                                    logger.error(
                                        f"【监控生活事件】{original_file_name} 不存在 pickcode 值，无法下载该文件"
                                    )
                                    continue
                                download_url = (
                                    self.mediainfodownloader.get_download_url(
                                        pickcode=pickcode
                                    )
                                )

                                if not download_url:
                                    logger.error(
                                        f"【监控生活事件】{original_file_name} 下载链接获取失败，无法下载该文件"
                                    )
                                    continue

                                self.mediainfodownloader.save_mediainfo_file(
                                    file_path=Path(file_path),
                                    file_name=original_file_name,
                                    download_url=download_url,
                                )
                                mediainfo_count += 1
                                continue

                        if file_path.suffix.lower() not in self.rmt_mediaext_set:
                            logger.warn(
                                "【监控生活事件】跳过网盘路径: %s",
                                item["path"],
                            )
                            continue

                        if not (
                            result := StrmGenerater.should_generate_strm(
                                original_file_name, "life", item.get("size", None)
                            )
                        )[1]:
                            logger.warn(
                                f"【监控生活事件】{result[0]}，跳过网盘路径: {item['path']}"
                            )
                            continue

                        pickcode = item["pickcode"]
                        if not pickcode:
                            pickcode = item["pick_code"]

                        new_file_path.parent.mkdir(parents=True, exist_ok=True)

                        if not pickcode:
                            logger.error(
                                f"【监控生活事件】{original_file_name} 不存在 pickcode 值，无法生成 STRM 文件"
                            )
                            continue
                        if not (len(pickcode) == 17 and str(pickcode).isalnum()):
                            logger.error(
                                f"【监控生活事件】错误的 pickcode 值 {pickcode}，无法生成 STRM 文件"
                            )
                            continue

                        strm_url = _get_url.get_strm_url(
                            pickcode, original_file_name, item["path"]
                        )

                        with open(new_file_path, "w", encoding="utf-8") as file:
                            file.write(strm_url)
                        logger.info(
                            "【监控生活事件】生成 STRM 文件成功: %s",
                            str(new_file_path),
                        )
                        strm_count += 1
                        scrape_metadata = True
                        if configer.get_config("monitor_life_scrape_metadata_enabled"):
                            if configer.get_config(
                                "monitor_life_scrape_metadata_exclude_paths"
                            ):
                                if PathUtils.get_scrape_metadata_exclude_path(
                                    configer.get_config(
                                        "monitor_life_scrape_metadata_exclude_paths"
                                    ),
                                    str(new_file_path),
                                ):
                                    logger.debug(
                                        f"【监控生活事件】匹配到刮削排除目录，不进行刮削: {new_file_path}"
                                    )
                                    scrape_metadata = False
                            if scrape_metadata:
                                media_scrape_metadata(path=new_file_path)
                        # 刷新媒体服务器
                        self.mediaserver_helper.refresh_mediaserver(
                            file_path=str(new_file_path),
                            file_name=str(original_file_name),
                        )
                        if configer.monitor_life_emby_mediainfo_enabled and (
                            configer.native_emby_mediainfo_enabled or item.get("sha1")
                        ):
                            life_enqueue_kw = dict(
                                func_name="【监控生活事件】",
                                path=Path(new_file_path),
                                mp_mediaserver=configer.monitor_life_mp_mediaserver_paths,
                                mediaservers=configer.monitor_life_mediaservers,
                            )
                            if not configer.native_emby_mediainfo_enabled:
                                life_enqueue_kw["sha1"] = item["sha1"]
                                life_enqueue_kw["size"] = item["size"]
                            emby_mediainfo_queue.enqueue(**life_enqueue_kw)
                _databasehelper.upsert_batch(processed)
            if configer.get_config("notify"):
                if strm_count > 0 or mediainfo_count > 0:
                    self._monitor_life_notification_queue["life"]["strm_count"] += (
                        strm_count
                    )
                    self._monitor_life_notification_queue["life"][
                        "mediainfo_count"
                    ] += mediainfo_count
                    self._schedule_notification()
        else:
            file_path_string = file_path.as_posix()
            _databasehelper.upsert_batch(
                _databasehelper.process_life_file_item(
                    event=event, file_path=file_path_string
                )
            )
            if "creata" in configer.monitor_life_event_modes:
                # 文件情况，直接生成
                file_path = Path(target_dir) / PathUtils.sanitize_path_parts(
                    Path(file_path).relative_to(pan_media_dir)
                )
                file_target_dir = file_path.parent
                original_file_name = file_path.name
                file_name = StrmGenerater.get_strm_filename(file_path)
                new_file_path = file_target_dir / file_name

                if configer.get_config("monitor_life_auto_download_mediainfo_enabled"):
                    if file_path.suffix.lower() in self.download_mediaext_set:
                        if not (
                            result := MediainfoDownloadMiddleware.should_download(
                                filename=original_file_name,
                                blacklist_automaton=self.mdab,
                                whitelist_automaton=self.mdaw,
                            )
                        )[1]:
                            logger.warning(
                                "【监控生活事件】%s，跳过网盘路径: %s",
                                result[0],
                                str(file_path).replace(str(target_dir), "", 1),
                            )
                            return

                        if not pickcode:
                            logger.error(
                                f"【监控生活事件】{original_file_name} 不存在 pickcode 值，无法下载该文件"
                            )
                            return
                        download_url = self.mediainfodownloader.get_download_url(
                            pickcode=pickcode
                        )

                        if not download_url:
                            logger.error(
                                f"【监控生活事件】{original_file_name} 下载链接获取失败，无法下载该文件"
                            )
                            return

                        self.mediainfodownloader.save_mediainfo_file(
                            file_path=Path(file_path),
                            file_name=original_file_name,
                            download_url=download_url,
                        )
                        if configer.get_config("notify"):
                            self._monitor_life_notification_queue["life"][
                                "mediainfo_count"
                            ] += 1
                            self._schedule_notification()
                        return

                if file_path.suffix.lower() not in self.rmt_mediaext_set:
                    logger.warn(
                        "【监控生活事件】跳过网盘路径: %s",
                        str(file_path).replace(str(target_dir), "", 1),
                    )
                    return

                if not (
                    result := StrmGenerater.should_generate_strm(
                        original_file_name, "life", event.get("file_size", None)
                    )
                )[1]:
                    logger.warn(
                        f"【监控生活事件】{result[0]}，跳过网盘路径: {str(file_path).replace(str(target_dir), '', 1)}"
                    )
                    return

                new_file_path.parent.mkdir(parents=True, exist_ok=True)

                if not pickcode:
                    logger.error(
                        f"【监控生活事件】{original_file_name} 不存在 pickcode 值，无法生成 STRM 文件"
                    )
                    return
                if not (len(pickcode) == 17 and str(pickcode).isalnum()):
                    logger.error(
                        f"【监控生活事件】错误的 pickcode 值 {pickcode}，无法生成 STRM 文件"
                    )
                    return

                strm_url = _get_url.get_strm_url(
                    pickcode, original_file_name, file_path=file_path_string
                )

                with open(new_file_path, "w", encoding="utf-8") as file:
                    file.write(strm_url)
                logger.info(
                    "【监控生活事件】生成 STRM 文件成功: %s", str(new_file_path)
                )
                if configer.get_config("notify"):
                    self._monitor_life_notification_queue["life"]["strm_count"] += 1
                    self._schedule_notification()
                scrape_metadata = True
                if configer.get_config("monitor_life_scrape_metadata_enabled"):
                    if configer.get_config(
                        "monitor_life_scrape_metadata_exclude_paths"
                    ):
                        if PathUtils.get_scrape_metadata_exclude_path(
                            configer.get_config(
                                "monitor_life_scrape_metadata_exclude_paths"
                            ),
                            str(new_file_path),
                        ):
                            logger.debug(
                                f"【监控生活事件】匹配到刮削排除目录，不进行刮削: {new_file_path}"
                            )
                            scrape_metadata = False
                    if scrape_metadata:
                        media_scrape_metadata(path=new_file_path)
                # 刷新媒体服务器
                self.mediaserver_helper.refresh_mediaserver(
                    file_path=new_file_path.as_posix(),
                    file_name=str(original_file_name),
                )
                if configer.monitor_life_emby_mediainfo_enabled and (
                    configer.native_emby_mediainfo_enabled or event.get("sha1")
                ):
                    life_enqueue_kw = dict(
                        func_name="【监控生活事件】",
                        path=Path(new_file_path),
                        mp_mediaserver=configer.monitor_life_mp_mediaserver_paths,
                        mediaservers=configer.monitor_life_mediaservers,
                    )
                    if not configer.native_emby_mediainfo_enabled:
                        life_enqueue_kw["sha1"] = event["sha1"]
                        life_enqueue_kw["size"] = event["file_size"]
                    emby_mediainfo_queue.enqueue(**life_enqueue_kw)

    def move(self, event: Dict[str, Any]):
        """
        移动操作

        :param event (Dict): 事件
        """
        _databasehelper = FileDbHelper()

        # 获取旧路径
        old_file_path = None
        file_item = _databasehelper.get_by_id(int(event["file_id"]))
        if file_item:
            old_file_path = file_item.get("path", "")

        # 获取新路径
        new_parent_path = self._get_path_by_cid(int(event["parent_id"]))
        if new_parent_path is None:
            logger.warning(f"【监控生活事件】无法获取父目录路径，跳过移动处理: {event}")
            return
        new_file_path = (Path(new_parent_path) / event["file_name"]).as_posix()
        # 未识别目录跳过处理
        if configer.pan_transfer_unrecognized_path and PathUtils.has_prefix(
            new_file_path, configer.pan_transfer_unrecognized_path
        ):
            logger.debug(
                f"【监控生活事件】{new_file_path} 为未识别目录下的路径，跳过移动处理"
            )
            return

        # 判断旧路径是否在媒体目录
        old_is_media = False
        if old_file_path:
            old_is_media, _, _ = PathUtils.get_media_path(
                configer.monitor_life_paths, old_file_path
            )

        # 判断新路径是否在媒体目录
        new_is_media, _, _ = PathUtils.get_media_path(
            configer.monitor_life_paths, new_file_path
        )

        # 其它目录/待整理目录/媒体目录 -> 待整理目录
        if configer.pan_transfer_enabled and configer.pan_transfer_paths:
            if PathUtils.get_run_transfer_path(
                paths=configer.pan_transfer_paths,
                transfer_path=new_file_path,
            ):
                # 旧路径在媒体目录时，判断是否删除本地 STRM 文件
                if (
                    old_is_media
                    and configer.monitor_life_enabled
                    and configer.monitor_life_paths
                ):
                    logger.info(
                        "【监控生活事件】媒体目录迁入待整理目录，先执行媒体侧清理（remove_local=%s）后进行网盘整理: %s",
                        configer.monitor_life_move_media_to_transfer_remove_local_strm,
                        new_file_path,
                    )
                    self.remove(
                        event=event,
                        remove_local=configer.monitor_life_move_media_to_transfer_remove_local_strm,
                    )
                elif configer.monitor_life_enabled and configer.monitor_life_paths:
                    logger.info(
                        "【监控生活事件】非媒体目录迁入待整理目录，直接执行网盘整理: %s",
                        new_file_path,
                    )
                sleep(3)
                self.media_transfer(
                    event=event,
                    file_path=Path(new_file_path),
                    rmt_mediaext=self.rmt_mediaext,
                )
                return

        if not configer.monitor_life_enabled or not configer.monitor_life_paths:
            return

        if not old_file_path or not old_is_media:
            if new_is_media:
                # 其它目录/待整理目录 -> 媒体目录
                logger.info(
                    "【监控生活事件】移动前路径未命中数据库，新路径命中媒体目录，按其它目录迁入媒体目录处理: %s",
                    new_file_path,
                )
                self._create_with_transfer_cache_guard(
                    event=event, file_path=Path(new_file_path)
                )
            else:
                # 其它目录/待整理目录 -> 其它目录
                logger.info(
                    "【监控生活事件】移动前路径无媒体目录记录且新路径不在媒体目录，跳过处理: %s",
                    new_file_path,
                )
            return

        if new_is_media:
            # 媒体目录 -> 媒体目录
            create_new_strm = configer.monitor_life_move_media_create_new_strm
            move_mode = configer.monitor_life_move_media_mode
            logger.info(
                "【监控生活事件】媒体目录内移动，模式=%s，保留旧STRM=%s，生成新STRM=%s，目标路径: %s",
                move_mode,
                configer.monitor_life_move_media_keep_old_strm,
                create_new_strm,
                new_file_path,
            )
            if move_mode == "local_move":
                self._move_local_media_assets(
                    event=event,
                    old_file_path=old_file_path,
                    new_file_path=new_file_path,
                )
                self._sync_move_event_db_records(
                    event=event,
                    new_file_path=new_file_path,
                )
                return
            if not configer.monitor_life_move_media_keep_old_strm:
                self.remove(event=event, remove_local=True)
            if create_new_strm:
                self._create_with_transfer_cache_guard(
                    event=event, file_path=Path(new_file_path)
                )
            return

        # 媒体目录 -> 其它目录
        logger.info(
            "【监控生活事件】媒体目录迁出到其它目录，remove_local=%s，目标路径: %s",
            configer.monitor_life_move_out_media_remove_local_strm,
            new_file_path,
        )
        self.remove(
            event=event,
            remove_local=configer.monitor_life_move_out_media_remove_local_strm,
        )

    def rename(self, event: Dict[str, Any]):
        """
        重命名事件处理

        :param event (Dict): 事件对象
        """
        if not configer.monitor_life_enabled or not configer.monitor_life_paths:
            return

        if "rename" not in configer.monitor_life_event_modes:
            return

        _databasehelper = FileDbHelper()

        # 获取旧路径
        old_pan_path = None
        file_item = _databasehelper.get_by_id(int(event["file_id"]))
        if file_item:
            old_pan_path = file_item.get("path", "")

        try:
            new_pan_path = str(
                get_path(
                    client=self._client,
                    attr=event["file_id"],
                    root_id=None,
                    refresh=True,
                    **configer.get_ios_ua_app(app=False),
                )
            )
        except Exception as e:
            logger.warning(
                f"【监控生活事件】无法获取新事件路径，跳过移动处理: {event} {e}"
            )
            return

        # 未识别目录跳过处理
        if configer.pan_transfer_unrecognized_path and PathUtils.has_prefix(
            new_pan_path, configer.pan_transfer_unrecognized_path
        ):
            logger.debug(
                f"【监控生活事件】{new_pan_path} 为未识别目录下的路径，跳过重命名处理"
            )
            return

        old_path = None
        if old_pan_path:
            old_is_media, old_target_dir, old_pan_media_dir = PathUtils.get_media_path(
                configer.monitor_life_paths, old_pan_path
            )
            if (
                old_is_media
                and old_target_dir is not None
                and old_pan_media_dir is not None
            ):
                old_path = Path(old_target_dir) / PathUtils.sanitize_path_parts(
                    Path(old_pan_path).relative_to(old_pan_media_dir)
                )

        new_is_media, new_target_dir, new_pan_media_dir = PathUtils.get_media_path(
            configer.monitor_life_paths, new_pan_path
        )
        if not new_is_media or new_target_dir is None or new_pan_media_dir is None:
            logger.debug(
                f"【监控生活事件】{new_pan_path} 非媒体库路径，跳过重命名处理: {event}"
            )
            return
        new_path = Path(new_target_dir) / PathUtils.sanitize_path_parts(
            Path(new_pan_path).relative_to(new_pan_media_dir)
        )

        if int(event["type"]) == 20:
            # 文件夹重命名
            if not old_path:
                logger.warning(
                    f"【监控生活事件】无法获取旧文件夹名称，跳过重命名处理: {event}"
                )
                return

            if Path(old_path).parent != Path(new_path).parent:
                logger.warning(
                    f"【监控生活事件】旧文件夹路径与新文件夹路径不一致，跳过重命名处理: {event}",
                )
                return

            if not Path(old_path).is_dir():
                logger.warning(
                    f"【监控生活事件】{old_path} 本地文件夹不存在，跳过重命名处理: {event}",
                )
                return

            if old_pan_path and new_pan_path:
                _databasehelper.update_path_prefix_batch(
                    old_pan_path, new_pan_path, False
                )
                logger.info(
                    "【监控生活事件】目录重命名数据库路径批量同步完成: %s -> %s",
                    old_pan_path,
                    new_pan_path,
                )

            if Path(new_path).exists():
                logger.warning(
                    "【监控生活事件】重命名目标已存在，跳过: %s",
                    new_path,
                )
                return

            try:
                shutil_move(old_path, new_path)
                logger.info(
                    "【监控生活事件】本地文件夹重命名完成: %s -> %s",
                    old_path,
                    new_path,
                )
            except Exception as e:
                logger.error(
                    "【监控生活事件】本地文件夹重命名失败: %s",
                    e,
                    exc_info=True,
                )
                return
        else:
            # 文件重命名
            new_strm_path = new_path.parent / StrmGenerater.get_strm_filename(new_path)
            new_strm_exists = new_strm_path.is_file()

            if not old_path:
                if not new_strm_exists:
                    logger.info(
                        "【监控生活事件】无法获取旧路径且新文件不存在，生成 STRM 文件: %s",
                        event,
                    )
                    self._create(event=event, file_path=Path(new_pan_path))
                else:
                    logger.info(
                        "【监控生活事件】无法获取旧文件路径且新文件存在，跳过重命名处理: %s",
                        event,
                    )
                return

            old_strm_path = old_path.parent / StrmGenerater.get_strm_filename(old_path)
            old_strm_exists = old_strm_path.is_file()

            if not old_strm_exists:
                if not new_strm_exists:
                    logger.info(
                        "【监控生活事件】本地无旧文件且新路径不存在，生成 STRM 文件: %s",
                        event,
                    )
                    self._create(event=event, file_path=Path(new_pan_path))
                else:
                    logger.info(
                        "【监控生活事件】本地无旧文件但目标已存在，跳过重命名: %s",
                        event,
                    )
                return

            if Path(old_path).parent != Path(new_path).parent:
                logger.warning(
                    f"【监控生活事件】旧文件路径与新文件路径不一致，跳过重命名处理: {event}",
                )
                return

            if old_pan_path and new_pan_path:
                _databasehelper.update_path_prefix_batch(
                    old_pan_path, new_pan_path, True
                )
                logger.info(
                    "【监控生活事件】文件重命名数据库路径同步完成: %s -> %s",
                    old_pan_path,
                    new_pan_path,
                )
            elif new_pan_path:
                if _databasehelper.update_path_by_id(
                    int(event["file_id"]), new_pan_path
                ):
                    logger.info(
                        "【监控生活事件】文件重命名数据库按 id 更新路径: %s -> %s",
                        event["file_id"],
                        new_pan_path,
                    )

            same_strm_path = old_strm_path.resolve() == new_strm_path.resolve()

            if new_strm_exists and not new_strm_path.samefile(old_strm_path):
                ok, _ = self._sync_strm_text_with_event(
                    new_strm_path,
                    event["pick_code"],
                    new_path.name,
                    new_pan_path,
                    scene="重命名",
                    create_if_missing=False,
                )
                if not ok:
                    return
                related_entries_dup: List[Path] = []
                if configer.monitor_life_rename_auto_related_files:
                    for sibling in old_strm_path.parent.glob(f"{old_path.stem}*"):
                        if sibling.suffix.lower() == ".strm" or not sibling.is_file():
                            continue
                        related_entries_dup.append(sibling)
                try:
                    old_strm_path.unlink(missing_ok=True)
                    logger.info(
                        "【监控生活事件】已移除重复的旧 STRM: %s",
                        old_strm_path,
                    )
                except Exception as e:
                    logger.error(
                        "【监控生活事件】合并重复 STRM 失败: %s",
                        e,
                        exc_info=True,
                    )
                    return
                if related_entries_dup:
                    old_stem = old_path.stem
                    new_stem = new_path.stem
                    for sibling in related_entries_dup:
                        if not sibling.name.startswith(old_stem):
                            continue
                        dest_name = new_stem + sibling.name[len(old_stem) :]
                        dest = sibling.parent / dest_name
                        if dest.exists():
                            logger.info(
                                "【监控生活事件】关联文件重命名跳过，目标已存在: %s",
                                dest,
                            )
                            continue
                        sibling.rename(dest)
                        logger.info(
                            "【监控生活事件】关联文件重命名完成: %s -> %s",
                            sibling,
                            dest,
                        )
                return

            related_entries: List[Path] = []
            if configer.monitor_life_rename_auto_related_files and not same_strm_path:
                for sibling in old_strm_path.parent.glob(f"{old_path.stem}*"):
                    if sibling.suffix.lower() == ".strm" or not sibling.is_file():
                        continue
                    related_entries.append(sibling)

            try:
                if not same_strm_path:
                    old_strm_path.rename(new_strm_path)
                    logger.info(
                        "【监控生活事件】本地 STRM 重命名完成: %s -> %s",
                        old_strm_path,
                        new_strm_path,
                    )
                else:
                    logger.debug(
                        "【监控生活事件】STRM 路径未变，跳过文件重命名，校验内容: %s",
                        new_strm_path,
                    )
                self._sync_strm_text_with_event(
                    new_strm_path,
                    event["pick_code"],
                    new_path.name,
                    new_pan_path,
                    scene="重命名",
                    create_if_missing=False,
                )

                if related_entries:
                    old_stem = old_path.stem
                    new_stem = new_path.stem
                    for sibling in related_entries:
                        if not sibling.name.startswith(old_stem):
                            continue
                        dest_name = new_stem + sibling.name[len(old_stem) :]
                        dest = sibling.parent / dest_name
                        if dest.exists():
                            logger.info(
                                "【监控生活事件】关联文件重命名跳过，目标已存在: %s",
                                dest,
                            )
                            continue
                        sibling.rename(dest)
                        logger.info(
                            "【监控生活事件】关联文件重命名完成: %s -> %s",
                            sibling,
                            dest,
                        )
            except Exception as e:
                logger.error(
                    "【监控生活事件】本地文件重命名失败: %s",
                    e,
                    exc_info=True,
                )
                return

    def remove(self, event: Dict[str, Any], remove_local: bool = True):
        """
        删除 STRM 文件

        :param event (Dict): 事件对象
        :param remove_local (bool): 是否删除本地 STRM 文件
        """

        # def __get_file_path(
        #     file_name: str, file_size: str, file_id: str, file_category: int
        # ):
        #     """
        #     通过 还原文件/文件夹 再删除 获取文件路径
        #     """
        #     for item in self._client.recyclebin_list()["data"]:
        #         if (
        #             file_category == 0
        #             and str(item["file_name"]) == file_name
        #             and str(item["type"]) == "2"
        #         ) or (
        #             file_category != 0
        #             and str(item["file_name"]) == file_name
        #             and str(item["file_size"]) == file_size
        #         ):
        #             resp = self._client.recyclebin_revert(item["id"])
        #             if resp["state"]:
        #                 time.sleep(1)
        #                 path = get_path_to_cid(self._client, cid=int(item["cid"]))
        #                 time.sleep(1)
        #                 self._client.fs_delete(file_id)
        #                 return str(Path(path) / item["file_name"])
        #             else:
        #                 return None
        #     return None

        _databasehelper = FileDbHelper()

        file_path = None
        file_category = event["file_category"]
        file_item = _databasehelper.get_by_id(int(event["file_id"]))
        if file_item:
            file_path = file_item.get("path", "")
        if not file_path:
            logger.debug(
                f"【监控生活事件】{event['file_name']} 无法通过数据库获取路径，防止误删不处理"
            )
            return
        logger.debug(f"【监控生活事件】通过数据库获取路径：{file_path}")

        pan_file_path = file_path
        # 优先匹配待整理目录，如果删除的目录为待整理目录则不进行操作
        if configer.get_config("pan_transfer_enabled") and configer.get_config(
            "pan_transfer_paths"
        ):
            if PathUtils.get_run_transfer_path(
                paths=configer.get_config("pan_transfer_paths"),
                transfer_path=file_path,
            ):
                logger.debug(
                    f"【监控生活事件】{file_path} 为待整理目录下的路径，不做处理"
                )
                return

        # 未识别目录跳过处理
        if configer.pan_transfer_unrecognized_path and PathUtils.has_prefix(
            file_path, configer.pan_transfer_unrecognized_path
        ):
            logger.debug(f"【监控生活事件】{file_path} 为未识别目录下的路径，不做处理")
            return

        # 匹配是否是媒体文件夹目录
        status, target_dir, pan_media_dir = PathUtils.get_media_path(
            configer.get_config("monitor_life_paths"), file_path
        )
        if not status or target_dir is None or pan_media_dir is None:
            return
        logger.debug("【监控生活事件】匹配到网盘文件夹路径: %s", str(pan_media_dir))

        # 清理数据库此路径记录
        _databasehelper.remove_by_path(
            path_type="folder" if file_category == 0 else "file",
            path=str(pan_file_path),
        )
        if not remove_local:
            _databasehelper.remove_by_path_batch(
                path=str(pan_file_path), only_file=False
            )
            logger.info(
                f"【监控生活事件】{pan_file_path} 已从数据库移除，按配置保留本地文件"
            )
            return

        # 检查文件是否还存在
        storagechain = StorageChain()
        fileitem = storagechain.get_file_item(
            storage=configer.storage_module, path=Path(file_path)
        )
        if fileitem:
            logger.warn(
                f"【监控生活事件】网盘 {file_path} 目录存在，跳过本地删除: {fileitem}"
            )
            # 这里如果路径存在则更新数据库信息
            _databasehelper.upsert_batch(
                _databasehelper.process_fileitem(fileitem=fileitem)
            )
            return

        file_path = Path(target_dir) / PathUtils.sanitize_path_parts(
            Path(file_path).relative_to(pan_media_dir)
        )
        if file_path.suffix.lower() in self.rmt_mediaext_set:
            file_target_dir = file_path.parent
            file_name = StrmGenerater.get_strm_filename(file_path)
            file_path = file_target_dir / file_name
        logger.info(
            f"【监控生活事件】删除本地{'文件夹' if file_category == 0 else '文件'}: {file_path}"
        )
        try:
            if not Path(file_path).exists():
                logger.warn(f"【监控生活事件】本地 {file_path} 不存在，跳过删除")
                return
            if file_category == 0:
                # 删除目录
                rmtree(Path(file_path))
            else:
                # 删除文件
                Path(file_path).unlink(missing_ok=True)
                # 判断父目录是否需要删除
                PathRemoveUtils.remove_parent_dir(
                    file_path=Path(file_path),
                    mode=["strm"],
                    func_type="【监控生活事件】",
                )
            # 清理数据库所有路径
            _databasehelper.remove_by_path_batch(
                path=str(pan_file_path), only_file=False
            )
            logger.info(f"【监控生活事件】{file_path} 已删除")
            # 同步删除历史记录
            if configer.monitor_life_remove_mp_history:
                mediasyncdel = MediaSyncDelHelper()
                (
                    del_torrent_hashs,
                    stop_torrent_hashs,
                    error_cnt,
                    transfer_history,
                ) = mediasyncdel.remove_by_path(
                    path=pan_file_path,
                    del_source=configer.monitor_life_remove_mp_source,
                )
                if configer.get_config("notify") and transfer_history:
                    torrent_cnt_msg = ""
                    if del_torrent_hashs:
                        torrent_cnt_msg += (
                            i18n.translate(
                                "sync_del_torrent_count",
                                count=len(set(del_torrent_hashs)),
                            )
                            + "\n"
                        )
                    if stop_torrent_hashs:
                        stop_cnt = 0
                        # 排除已删除
                        for stop_hash in set(stop_torrent_hashs):
                            if stop_hash not in set(del_torrent_hashs):
                                stop_cnt += 1
                        if stop_cnt > 0:
                            torrent_cnt_msg += (
                                i18n.translate("sync_del_stop_count", count=stop_cnt)
                                + "\n"
                            )
                    if error_cnt:
                        torrent_cnt_msg += (
                            i18n.translate("sync_del_error_count", count=error_cnt)
                            + "\n"
                        )
                    del_type_text = (
                        i18n.translate("life_del_folder", path=pan_file_path)
                        if file_category == 0
                        else i18n.translate("life_del_file", path=pan_file_path)
                    )
                    _history_count = len(transfer_history) if transfer_history else 0
                    post_message(
                        mtype=NotificationType.Plugin,
                        title=i18n.translate("life_sync_media_del_title"),
                        text=f"\n{del_type_text}\n"
                        f"{i18n.translate('sync_del_record_count', count=_history_count)}\n"
                        f"{torrent_cnt_msg}"
                        f"时间 {strftime('%Y-%m-%d %H:%M:%S', localtime(time()))}\n",
                    )
        except Exception as e:
            logger.error(f"【监控生活事件】{file_path} 删除失败: {e}")

    def create(self, event: Dict[str, Any]):
        """
        处理新出现的路径

        :param event (Dict): 事件
        """
        # 1.获取绝对文件路径
        file_name = event["file_name"]
        dir_path = self._get_path_by_cid(int(event["parent_id"]))
        if dir_path is None:
            logger.warning(f"【监控生活事件】无法获取父目录路径，跳过处理: {event}")
            return
        file_path = Path(dir_path) / file_name
        # 未识别目录跳过处理
        if configer.pan_transfer_unrecognized_path and PathUtils.has_prefix(
            file_path.as_posix(), configer.pan_transfer_unrecognized_path
        ):
            logger.debug(
                f"【监控生活事件】{file_path} 为未识别目录下的路径，跳过新增处理"
            )
            return
        # 匹配逻辑 整理路径目录 > 生成STRM文件路径目录
        # 2.匹配是否为整理路径目录
        if configer.pan_transfer_enabled and configer.pan_transfer_paths:
            if PathUtils.get_run_transfer_path(
                paths=configer.pan_transfer_paths,
                transfer_path=file_path,
            ):
                self.media_transfer(
                    event=event,
                    file_path=Path(file_path),
                    rmt_mediaext=self.rmt_mediaext,
                )
                return
        # 3.匹配是否为生成STRM文件路径目录
        if configer.monitor_life_enabled and configer.monitor_life_paths:
            self._create_with_transfer_cache_guard(event=event, file_path=file_path)

    def _create_with_transfer_cache_guard(self, event: Dict[str, Any], file_path: Path):
        """
        命中整理缓存时按事件模式门控，再调用 STRM 生成

        :param event (Dict): 事件
        :param file_path (Path): 文件路径
        """
        if str(event["file_id"]) in pantransfercacher.creata_pan_transfer_list:
            pantransfercacher.creata_pan_transfer_list.remove(str(event["file_id"]))
            if "transfer" in configer.monitor_life_event_modes:
                self._create(event=event, file_path=file_path)
            return
        self._create(event=event, file_path=file_path)

    def _sync_strm_text_with_event(
        self,
        strm_path: Path,
        pickcode: str,
        local_file_name: str,
        pan_file_path: str,
        *,
        scene: str,
        create_if_missing: bool = True,
    ) -> Tuple[bool, bool]:
        """
        将 STRM 文本与事件期望 URL 对齐

        :param strm_path (Path): 本地 STRM 路径
        :param pickcode (str): 事件 pickcode
        :param local_file_name (str): 本地媒体文件名
        :param pan_file_path (str): 网盘路径
        :param scene (str): 日志场景前缀，例如「重命名」「模式 local_move」
        :param create_if_missing (bool): 为 True 时若文件不存在则创建；重命名流程应传 False，与旧逻辑一致（仅对已存在文件读-比较-写）
        :return Tuple: (ok, wrote) ok 为 False 表示读写失败；wrote 为 True 表示新建或覆盖写入
        """
        getter = StrmUrlGetter()
        expected = getter.get_strm_url(
            pickcode,
            local_file_name,
            file_path=pan_file_path,
        )
        if not strm_path.exists():
            if not create_if_missing:
                logger.error(
                    "【监控生活事件】%s STRM 内容同步失败: 文件不存在 %s",
                    scene,
                    strm_path,
                )
                return False, False
            try:
                strm_path.parent.mkdir(parents=True, exist_ok=True)
                with open(strm_path, "w", encoding="utf-8") as f:
                    f.write(expected)
                logger.info(
                    "【监控生活事件】%s STRM 已按事件创建: %s",
                    scene,
                    strm_path,
                )
                return True, True
            except Exception as e:
                logger.error(
                    "【监控生活事件】%s STRM 创建失败: %s",
                    scene,
                    e,
                    exc_info=True,
                )
                return False, False
        try:
            current = strm_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.error(
                "【监控生活事件】%s 读取 STRM 失败: %s",
                scene,
                e,
                exc_info=True,
            )
            return False, False
        if current.strip() == expected.strip():
            logger.debug(
                "【监控生活事件】%s STRM 内容与事件一致，无需更新: %s",
                scene,
                strm_path,
            )
            return True, False
        try:
            with open(strm_path, "w", encoding="utf-8") as f:
                f.write(expected)
            logger.info(
                "【监控生活事件】%s STRM 内容已按事件更新: %s",
                scene,
                strm_path,
            )
            return True, True
        except Exception as e:
            logger.error(
                "【监控生活事件】%s STRM 内容写入失败: %s",
                scene,
                e,
                exc_info=True,
            )
            return False, False

    def _move_local_media_assets(
        self, event: Dict[str, Any], old_file_path: str, new_file_path: str
    ) -> None:
        """
        媒体目录内移动时，纯本地迁移 STRM 与关联文件

        :param event (Dict): 事件
        :param old_file_path (str): 旧网盘路径
        :param new_file_path (str): 新网盘路径
        """
        old_status, old_target_dir, old_pan_media_dir = PathUtils.get_media_path(
            configer.monitor_life_paths, old_file_path
        )
        new_status, new_target_dir, new_pan_media_dir = PathUtils.get_media_path(
            configer.monitor_life_paths, new_file_path
        )
        if (
            not old_status
            or not new_status
            or old_target_dir is None
            or old_pan_media_dir is None
            or new_target_dir is None
            or new_pan_media_dir is None
        ):
            logger.info(
                "【监控生活事件】模式 local_move 本地迁移跳过，路径未匹配媒体目录 old=%s new=%s",
                old_file_path,
                new_file_path,
            )
            return

        old_local_path = Path(old_target_dir) / PathUtils.sanitize_path_parts(
            Path(old_file_path).relative_to(old_pan_media_dir)
        )
        new_local_path = Path(new_target_dir) / PathUtils.sanitize_path_parts(
            Path(new_file_path).relative_to(new_pan_media_dir)
        )

        if int(event["file_category"]) == 0:
            if not old_local_path.exists():
                logger.info(
                    "【监控生活事件】模式 local_move 目录迁移跳过，旧目录不存在: %s",
                    old_local_path,
                )
                return
            if new_local_path.exists():
                logger.info(
                    "【监控生活事件】模式 local_move 目录迁移跳过，目标目录已存在: %s",
                    new_local_path,
                )
                return
            new_local_path.parent.mkdir(parents=True, exist_ok=True)
            shutil_move(str(old_local_path), str(new_local_path))
            logger.info(
                "【监控生活事件】模式 local_move 目录迁移完成: %s -> %s",
                old_local_path,
                new_local_path,
            )
            return

        old_strm_path = old_local_path.parent / StrmGenerater.get_strm_filename(
            old_local_path
        )
        new_strm_path = new_local_path.parent / StrmGenerater.get_strm_filename(
            new_local_path
        )
        moved_any = False
        pickcode = event["pick_code"]

        old_strm_exists = old_strm_path.is_file()
        new_strm_exists = new_strm_path.is_file()

        if old_strm_exists and not new_strm_exists:
            new_strm_path.parent.mkdir(parents=True, exist_ok=True)
            shutil_move(str(old_strm_path), str(new_strm_path))
            moved_any = True
            logger.info(
                "【监控生活事件】模式 local_move 文件迁移 STRM 完成: %s -> %s",
                old_strm_path,
                new_strm_path,
            )
            self._sync_strm_text_with_event(
                new_strm_path,
                pickcode,
                new_local_path.name,
                new_file_path,
                scene="模式 local_move",
            )
        elif old_strm_exists and new_strm_exists:
            if new_strm_path.samefile(old_strm_path):
                self._sync_strm_text_with_event(
                    new_strm_path,
                    pickcode,
                    new_local_path.name,
                    new_file_path,
                    scene="模式 local_move",
                )
            else:
                ok, _ = self._sync_strm_text_with_event(
                    new_strm_path,
                    pickcode,
                    new_local_path.name,
                    new_file_path,
                    scene="模式 local_move",
                )
                if ok:
                    try:
                        old_strm_path.unlink(missing_ok=True)
                        moved_any = True
                        logger.info(
                            "【监控生活事件】模式 local_move 已移除重复的旧 STRM: %s",
                            old_strm_path,
                        )
                    except Exception as e:
                        logger.error(
                            "【监控生活事件】模式 local_move 移除旧 STRM 失败: %s",
                            e,
                            exc_info=True,
                        )
        elif not old_strm_exists and new_strm_exists:
            self._sync_strm_text_with_event(
                new_strm_path,
                pickcode,
                new_local_path.name,
                new_file_path,
                scene="模式 local_move",
            )
        else:
            logger.info(
                "【监控生活事件】模式 local_move 文件迁移 STRM 跳过，源与目标均不存在: old=%s new=%s",
                old_strm_path,
                new_strm_path,
            )

        if configer.monitor_life_move_media_local_move_related_files:
            for sibling in old_strm_path.parent.glob(f"{old_local_path.stem}*"):
                if sibling.suffix.lower() == ".strm" or not sibling.is_file():
                    continue
                target_sibling = new_strm_path.parent / sibling.name
                if target_sibling.exists():
                    if files_equal(sibling, target_sibling, shallow=False):
                        try:
                            sibling.unlink()
                            moved_any = True
                            logger.info(
                                "【监控生活事件】模式 local_move 关联文件目标已存在且内容一致，已删除源: %s",
                                sibling,
                            )
                        except Exception as e:
                            logger.error(
                                "【监控生活事件】模式 local_move 删除重复关联文件源失败: %s",
                                e,
                                exc_info=True,
                            )
                    else:
                        logger.warning(
                            "【监控生活事件】模式 local_move 关联文件目标已存在且内容不一致，跳过覆盖: %s",
                            target_sibling,
                        )
                    continue
                new_strm_path.parent.mkdir(parents=True, exist_ok=True)
                shutil_move(str(sibling), str(target_sibling))
                moved_any = True
                logger.info(
                    "【监控生活事件】模式 local_move 关联文件迁移完成: %s -> %s",
                    sibling,
                    target_sibling,
                )

        if moved_any:
            PathRemoveUtils.remove_parent_dir(
                file_path=old_strm_path,
                mode="mixed",
                func_type="【监控生活事件】",
            )

    def _sync_move_event_db_records(
        self, event: Dict[str, Any], new_file_path: str
    ) -> None:
        """
        同步移动事件后的数据库路径记录

        :param event (Dict): 事件
        :param new_file_path (str): 新网盘路径
        """
        _databasehelper = FileDbHelper()
        file_id = int(event["file_id"])
        file_category = int(event["file_category"])

        if file_category == 0:
            old_item = _databasehelper.get_by_id(file_id)
            old_prefix = str(old_item.get("path", "")) if old_item else None
            if old_prefix:
                _databasehelper.update_path_prefix_batch(
                    old_prefix, new_file_path, False
                )
                logger.info(
                    "【监控生活事件】local_move 目录移动后数据库路径批量同步完成: %s -> %s",
                    old_prefix,
                    new_file_path,
                )
            else:
                logger.info(
                    "【监控生活事件】local_move 目录移动后数据库同步跳过，旧路径不存在: %s",
                    file_id,
                )
            return

        # 文件移动：按新路径覆盖该文件记录
        _databasehelper.upsert_batch(
            _databasehelper.process_life_file_item(event=event, file_path=new_file_path)
        )
        logger.info(
            "【监控生活事件】local_move 文件移动后数据库记录已同步: %s", new_file_path
        )

    def _wait_for_transfer_complete(self):
        """
        等待 MoviePilot 整理任务完成
        """
        wait_start_time = None
        last_info_time = None

        while True:
            if not TransferChain().get_queue_tasks():
                break

            if wait_start_time is None:
                wait_start_time = time()
                last_info_time = wait_start_time

            wait_duration = time() - wait_start_time
            wait_duration_minutes = int(wait_duration // 60)

            if wait_duration >= 15 * 60:
                time_since_last_info = time() - last_info_time
                if time_since_last_info >= 60:
                    logger.info(
                        f"【监控生活事件】MoviePilot 整理运行中，已等待 {wait_duration_minutes} 分钟，"
                        "等待整理完成后继续监控生活事件..."
                    )
                    last_info_time = time()
            else:
                logger.debug(
                    "【监控生活事件】MoviePilot 整理运行中，等待整理完成后继续监控生活事件..."
                )

            if self.stop_event and self.stop_event.wait(timeout=20):
                return True

        return False

    @staticmethod
    def _is_405_error(e: Exception) -> bool:
        """
        判断异常是否由 HTTP 405 导致

        :param e (Exception): 异常对象

        :return bool: 是否为 405 错误
        """
        if isinstance(e, HTTPError):
            return e.code == 405
        if isinstance(e, P115OSError):
            message = str(e)
            return "405" in message or "Method Not Allowed" in message
        return False

    def _get_life_event_app(self) -> str:
        """
        获取当前应使用的生活事件拉取 app

        若处于 web fallback 窗口期内则返回 web，否则返回 ios
        """
        state = configer.get_plugin_data("monitor_life_app_fallback") or {}
        fallback_until = state.get("web_fallback_until")
        if fallback_until and time() < fallback_until:
            return "web"
        if fallback_until:
            state.pop("web_fallback_until", None)
            configer.save_plugin_data("monitor_life_app_fallback", state)
        return "ios"

    def _reset_ios_405_count(self) -> None:
        """
        ios 拉取成功时清空 405 计数
        """
        state = configer.get_plugin_data("monitor_life_app_fallback") or {}
        if state.get("ios_405_count"):
            state["ios_405_count"] = 0
            configer.save_plugin_data("monitor_life_app_fallback", state)

    def _clear_web_fallback(self) -> None:
        """
        清理 web fallback 状态
        """
        state = configer.get_plugin_data("monitor_life_app_fallback") or {}
        if state.pop("web_fallback_until", None):
            configer.save_plugin_data("monitor_life_app_fallback", state)

    def _record_ios_405(self) -> None:
        """
        记录一次 ios 405 且 web 成功，连续 3 次后 24h 内默认使用 web
        """
        state = configer.get_plugin_data("monitor_life_app_fallback") or {}
        count = state.get("ios_405_count", 0) + 1
        if count >= 3:
            configer.save_plugin_data(
                "monitor_life_app_fallback",
                {
                    "ios_405_count": 0,
                    "web_fallback_until": int(time()) + self.WEB_FALLBACK_DURATION,
                },
            )
            logger.warning(
                "【监控生活事件】proapi 连续 3 次 405 且 webapi 正常，24h 内切换为 webapi 拉取"
            )
        else:
            state["ios_405_count"] = count
            configer.save_plugin_data("monitor_life_app_fallback", state)

    def _pull_life_events(self, from_time: float, from_id: int, app: str) -> List:
        """
        单次拉取生活事件

        :param from_time (float): 起始时间
        :param from_id (int): 起始 ID
        :param app (str): app 类型

        :return List: 事件列表
        """
        events_batch: List = []
        for attempt in range(3, -1, -1):
            try:
                # 每次尝试先清空旧的值
                events_batch: List = []

                request_kwargs = configer.get_ios_ua_app(app=False)
                request_kwargs["app"] = app

                events_iterator = iter_life_behavior_once(
                    client=self._client,
                    from_time=from_time,
                    from_id=from_id,
                    cooldown=2,
                    **request_kwargs,
                )

                try:
                    first_event = next(events_iterator)
                except P115AuthenticationError:
                    logger.error("【监控生活事件】登入失效，请重新扫码登入")
                    break
                except StopIteration:
                    # 迭代器为空，没有数据，属于正常情况
                    break

                if "update_time" not in first_event or "id" not in first_event:
                    break

                events_batch = [first_event]
                events_batch.extend(list(events_iterator))
                break
            except Exception as e:
                if self._is_405_error(e) and app == "ios":
                    raise
                if attempt <= 0:
                    logger.error(f"【监控生活事件】拉取数据失败：{e}")
                    raise
                logger.warn(
                    f"【监控生活事件】拉取数据失败，剩余重试次数 {attempt} 次：{e}"
                )
                if self.stop_event and self.stop_event.wait(timeout=2):
                    return []

        return events_batch

    def once_pull(self, from_time, from_id):
        """
        单次拉取

        :param from_time (int): 起始时间
        :param from_id (int): 起始 ID

        :return Tuple: (from_time, from_id)
        """
        if self._wait_for_transfer_complete():
            return from_time, from_id

        app = self._get_life_event_app()
        method = "webapi" if app == "web" else "proapi"
        logger.debug("【监控生活事件】当前使用接口: %s", method)

        try:
            events_batch: List = self._pull_life_events(
                from_time=from_time, from_id=from_id, app=app
            )
            if app == "ios":
                self._reset_ios_405_count()
        except (HTTPError, P115OSError) as e:
            if app == "web":
                if not self._is_405_error(e):
                    raise
                logger.warning(
                    "【监控生活事件】webapi 拉取返回 405，尝试 proapi: %s",
                    e,
                )
                self._clear_web_fallback()
                events_batch: List = self._pull_life_events(
                    from_time=from_time, from_id=from_id, app="ios"
                )
                self._reset_ios_405_count()
            elif not self._is_405_error(e):
                raise
            else:
                logger.warning(
                    "【监控生活事件】proapi 拉取返回 405，尝试切换到 webapi 重试"
                )
                try:
                    events_batch: List = self._pull_life_events(
                        from_time=from_time, from_id=from_id, app="web"
                    )
                except (HTTPError, P115OSError):
                    raise

                self._record_ios_405()

        if not events_batch:
            if self.stop_event and self.stop_event.wait(timeout=self.WAIT_TIME_OUT):
                return from_time, from_id
            elif not self.stop_event:
                sleep(self.SLEEP_TIME)
            return from_time, from_id

        db_helper = LifeEventDbHelper()
        db_helper.upsert_batch_by_list(events_batch)

        return_from_time: int = from_time
        return_from_id: int = from_id
        for event in reversed(events_batch):
            self.rmt_mediaext = [
                f".{ext.strip()}"
                for ext in configer.get_config("user_rmt_mediaext")
                .replace("，", ",")
                .split(",")
            ]
            self.rmt_mediaext_set = set(self.rmt_mediaext)
            self.download_mediaext_set = {
                f".{ext.strip()}"
                for ext in configer.get_config("user_download_mediaext")
                .replace("，", ",")
                .split(",")
            }

            logger.debug(
                f"【监控生活事件】{BEHAVIOR_TYPE_TO_NAME.get(event['type'], '未知类型')}: {event}"
            )

            return_from_id = int(event["id"])
            return_from_time = int(event["update_time"])

            if int(event["type"]) not in {1, 2, 5, 6, 14, 17, 18, 20, 22, 23, 24}:
                continue

            if (
                int(event["type"]) == 1
                or int(event["type"]) == 2
                or int(event["type"]) == 14
                or int(event["type"]) == 18
                or int(event["type"]) == 23
            ):
                # 新路径事件处理
                self.create(event=event)

            if int(event["type"]) == 5 or int(event["type"]) == 6:
                # 移动事件处理
                self.move(event=event)

            if int(event["type"]) == 20 or int(event["type"]) == 24:
                # 重命名事件处理
                self.rename(event=event)

            if int(event["type"]) == 22:
                # 删除文件/文件夹事件处理
                if str(event["file_id"]) in pantransfercacher.delete_pan_transfer_list:
                    # 检查是否命中删除文件夹缓存，命中则无需处理
                    pantransfercacher.delete_pan_transfer_list.remove(
                        str(event["file_id"])
                    )
                else:
                    if (
                        configer.monitor_life_enabled
                        and configer.monitor_life_paths
                        and "remove" in configer.monitor_life_event_modes
                    ):
                        self.remove(event=event)

            if int(event["type"]) == 17:
                # 对于创建文件夹事件直接写入数据库
                _databasehelper = FileDbHelper()
                file_name = event["file_name"]
                dir_path = self._get_path_by_cid(int(event["parent_id"]))
                if dir_path is None:
                    logger.warning(
                        f"【监控生活事件】无法获取父目录路径，跳过写入数据库: {event}"
                    )
                    continue
                file_path = Path(dir_path) / file_name
                # 待整理目录跳过处理
                if configer.pan_transfer_enabled and configer.pan_transfer_paths:
                    if PathUtils.get_run_transfer_path(
                        paths=configer.pan_transfer_paths,
                        transfer_path=file_path.as_posix(),
                    ):
                        continue
                # 未识别目录跳过处理
                if configer.pan_transfer_unrecognized_path:
                    if PathUtils.has_prefix(
                        file_path.as_posix(), configer.pan_transfer_unrecognized_path
                    ):
                        continue
                _databasehelper.upsert_batch(
                    _databasehelper.process_life_dir_item(
                        event=event, file_path=file_path
                    )
                )

        if self.stop_event and self.stop_event.wait(timeout=self.WAIT_TIME_OUT):
            return return_from_time, return_from_id
        elif not self.stop_event:
            sleep(self.SLEEP_TIME)

        return return_from_time, return_from_id

    def once_transfer(self, path: str) -> None:
        """
        手动运行网盘整理

        :param path (str): 网盘路径
        """
        if not path or not isinstance(path, str):
            logger.error(f"【监控生活事件】无效的路径参数: {path}")
            return

        logger.info(f"【监控生活事件】开始手动运行网盘整理，路径: {path}")

        total_files = 0
        total_dirs = 0
        success_count = 0
        failed_count = 0
        skipped_count = 0
        failed_items = []

        try:
            self.rmt_mediaext = [
                f".{ext.strip()}"
                for ext in configer.user_rmt_mediaext.replace("，", ",").split(",")
            ]

            try:
                parent_id = get_pid_by_path(self._client, path, True, True, True)
                logger.info(
                    f"【监控生活事件】网盘媒体目录 ID 获取成功: {path} -> {parent_id}"
                )
            except Exception as e:
                logger.error(f"【监控生活事件】网盘媒体目录 ID 获取失败: {path} {e}")
                return

            logger.info(f"【监控生活事件】开始遍历目录: {path}")
            try:
                for batch_count, data in enumerate(
                    iter_fs_files(
                        self._client,
                        parent_id,
                        cooldown=2,
                        **configer.get_ios_ua_app(app=False),
                    ),
                    1,
                ):
                    if not data:
                        logger.debug(
                            f"【监控生活事件】第 {batch_count} 批数据为空，跳过"
                        )
                        continue
                    items = data.get("data", [])
                    if not items:
                        logger.debug(
                            f"【监控生活事件】第 {batch_count} 批数据中无文件项，跳过"
                        )
                        continue
                    logger.debug(
                        f"【监控生活事件】处理第 {batch_count} 批数据，包含 {len(items)} 个项目"
                    )
                    for item_index, item in enumerate(items, 1):
                        item_type = "未知"
                        item_name = "未知"
                        try:
                            item = normalize_attr(item)
                            item_name = item.get("name") or ""
                            item_id = item.get("id")
                            item_type = "文件夹" if item.get("is_dir") else "文件"

                            if item.get("is_dir"):
                                total_dirs += 1
                            else:
                                total_files += 1

                            file_path = Path(path) / str(item_name)

                            event = {
                                "file_category": 0 if item.get("is_dir") else 1,
                                "file_id": item.get("id"),
                                "parent_id": item.get("parent_id"),
                                "file_size": item.get("size", 0),
                                "pick_code": item.get("pickcode", ""),
                                "update_time": item.get("ctime", 0),
                                "file_name": item_name,
                                "sha1": item["sha1"],
                            }

                            logger.debug(
                                f"【监控生活事件】处理 {item_type} [{batch_count}-{item_index}]: "
                                f"{item_name} (ID: {item_id})"
                            )
                            self.media_transfer(
                                event=event,
                                file_path=file_path,
                                rmt_mediaext=self.rmt_mediaext,
                            )
                            success_count += 1
                        except Exception as e:
                            failed_count += 1
                            error_msg = f"{item_type} {item_name} 处理异常: {type(e).__name__}: {e}"
                            failed_items.append(error_msg)
                            logger.error(f"【监控生活事件】{error_msg}")
                            continue
                    processed = success_count + failed_count + skipped_count
                    logger.info(
                        f"【监控生活事件】已处理 {processed} 个项目 "
                        f"(成功: {success_count}, 失败: {failed_count}, 跳过: {skipped_count})"
                    )
            except StopIteration:
                pass
            except Exception as e:
                logger.error(
                    f"【监控生活事件】遍历文件时发生错误: 错误类型: {type(e).__name__}, 错误: {e}"
                )
        except Exception as e:
            logger.error(
                f"【监控生活事件】网盘整理过程中发生未预期的错误: "
                f"错误类型: {type(e).__name__}, 错误: {e}",
            )
        finally:
            total_processed = total_files + total_dirs
            logger.info(
                f"【监控生活事件】手动网盘整理完成 - 路径: {path}\n"
                f"  总计: {total_processed} 个项目 (文件: {total_files}, 文件夹: {total_dirs})\n"
                f"  成功: {success_count} 个\n"
                f"  失败: {failed_count} 个\n"
                f"  跳过: {skipped_count} 个"
            )
            if failed_items:
                logger.warning(
                    f"【监控生活事件】失败项目详情 ({len(failed_items)} 个):\n"
                    + "\n".join(f"  - {item}" for item in failed_items[:10])
                    + (
                        f"\n  ... 还有 {len(failed_items) - 10} 个失败项目"
                        if len(failed_items) > 10
                        else ""
                    )
                )

    def check_status(self):
        """
        检查生活事件开启状态
        """
        try:
            resp = life_show(
                self._client, timeout=5, **configer.get_ios_ua_app(app=False)
            )
            check_response(resp)
            return True
        except Exception as e:
            logger.error(f"【监控生活事件】生活事件开启失败: {e}")
            return False

    def start_manual_transfer(self, path: str) -> bool:
        """
        启动后台手动整理任务

        :param path (str): 网盘路径
        :return bool: 是否成功启动任务
        """
        if not path or not isinstance(path, str) or not path.strip():
            logger.error(f"【监控生活事件】无效的路径参数: {path}")
            return False

        path = path.strip()

        def run_transfer():
            """
            在后台线程中执行手动网盘整理任务
            """
            try:
                logger.info(f"【监控生活事件】开始执行手动整理任务: {path}")
                self.once_transfer(path)
                logger.info(f"【监控生活事件】手动整理任务完成: {path}")
            except Exception as e:
                logger.error(f"【监控生活事件】手动整理任务执行失败: {path}, 错误: {e}")

        transfer_thread = Thread(target=run_transfer, daemon=True)
        transfer_thread.start()
        logger.info(f"【监控生活事件】已启动手动整理任务线程: {path}")
        return True
