from pathlib import Path, PurePosixPath
from time import localtime, strftime, time
from typing import Any, Dict, List, Optional, Tuple

from app.chain.storage import StorageChain
from app.core.config import settings
from app.core.event import Event
from app.db.downloadhistory_oper import DownloadHistoryOper
from app.db.models.transferhistory import TransferHistory
from app.db.plugindata_oper import PluginDataOper
from app.db.transferhistory_oper import TransferHistoryOper
from app.helper.downloader import DownloaderHelper
from app.log import logger
from app.schemas.mediaserver import WebhookEventInfo
from app.schemas.types import MediaImageType, MediaType, NotificationType

from ...core.config import configer
from ...core.i18n import i18n
from ...core.message import post_message
from ...core.plunins import PluginChian
from ...db_manager.oper import TransferHBOper
from ...helper.mediaserver import EmbyOperate
from ...utils.path import PathRemoveUtils, PathUtils
from ...utils.sentry import sentry_manager
from ...utils.webhook import WebhookUtils


@sentry_manager.capture_all_class_exceptions
class MediaSyncDelHelper:
    """
    媒体文件同步删除

    感谢：
      - https://github.com/thsrite/MoviePilot-Plugins/tree/main/plugins.v2/mediasyncdel
        - LICENSE: https://github.com/thsrite/MoviePilot-Plugins/blob/main/LICENSE
      - https://github.com/DDSRem/MoviePilot-Plugins/tree/main/plugins.v2/samediasyncdel
    """

    def __init__(self):
        self.plugindata = PluginDataOper()
        self.downloadhis = DownloadHistoryOper()
        self.transferhis = TransferHistoryOper()
        self.transferhisb = TransferHBOper()
        self.downloader_helper = DownloaderHelper()
        self.chain = PluginChian()
        self.storagechain = StorageChain()
        self.mediaserver_operate = EmbyOperate(func_name="【同步删除】")

        downloader_services = self.downloader_helper.get_services()
        for downloader_name, downloader_info in downloader_services.items():
            if downloader_info.config.default:
                self.default_downloader = downloader_name

    def download_file_del_sync(self, event: Event):
        """
        下载文件删除事件处理
        """
        src = event.event_data.get("src")
        if not src:
            return
        download_hash = self.downloadhis.get_hash_by_fullpath(src)
        if download_hash:
            download_history = self.downloadhis.get_by_hash(download_hash)
            self.handle_torrent(
                type=download_history.type, src=src, torrent_hash=download_hash
            )
        else:
            logger.warn(f"【同步删除】未查询到文件 {src} 对应的下载记录")

    def remove_by_path(self, path: str, del_source: bool = False):
        """
        通过路径删除历史记录和源文件

        :param path (str): 删除路径
        :param del_source (bool): 删除源文件
        """
        transfer_history = self.transferhisb.get_transfer_his_by_path_title(path)

        if not transfer_history:
            logger.warn(f"【同步删除】无 {path} 有关的历史记录")
            return [], [], 0, []

        del_torrent_hashs = []
        stop_torrent_hashs = []
        error_cnt = 0
        for transferhis in transfer_history:
            dest_path = transferhis.dest

            if not dest_path:
                logger.warn(
                    f"【同步删除】转移记录 {transferhis.id} 目标路径为空，跳过删除"
                )
                continue

            if not PathUtils.has_prefix(dest_path, path):
                logger.warn(f"【同步删除】{dest_path} 不在 {path} 下，跳过删除")
                continue

            self.transferhis.delete(transferhis.id)
            logger.info(f"【同步删除】{transferhis.id} {dest_path} 历史记录已删除")

            if del_source:
                if (
                    transferhis.src
                    and Path(transferhis.src).suffix in settings.RMT_MEDIAEXT
                    and transferhis.src_storage == "local"
                    and transferhis.mode != "move"
                ):
                    if Path(transferhis.src).exists():
                        logger.info(f"【同步删除】源文件 {transferhis.src} 开始删除")
                        Path(transferhis.src).unlink(missing_ok=True)
                        logger.info(f"【同步删除】源文件 {transferhis.src} 已删除")
                        PathRemoveUtils.remove_parent_dir(
                            file_path=Path(transferhis.src),
                            mode=settings.RMT_MEDIAEXT,
                            func_type="【同步删除】",
                        )

                    if transferhis.download_hash:
                        try:
                            # 2、判断种子是否被删除完
                            delete_flag, success_flag, handle_torrent_hashs = (
                                self.handle_torrent(
                                    type=transferhis.type,
                                    src=transferhis.src,
                                    torrent_hash=transferhis.download_hash,
                                )
                            )
                            if not success_flag:
                                error_cnt += 1
                            else:
                                if delete_flag:
                                    del_torrent_hashs += handle_torrent_hashs
                                else:
                                    stop_torrent_hashs += handle_torrent_hashs
                        except Exception as e:
                            logger.error("【同步删除】删除种子失败：%s" % str(e))

        return del_torrent_hashs, stop_torrent_hashs, error_cnt, transfer_history

    def handle_torrent(self, type: str, src: str, torrent_hash: str):
        """
        判断种子是否局部删除
        局部删除则暂停种子
        全部删除则删除种子

        :param type (str): 类型
        :param src (str): 目录
        :param torrent_hash (str): 种子 hash 值
        """
        download_id = torrent_hash
        download = self.default_downloader
        history_key = f"{download}-{torrent_hash}"
        plugin_id = "TorrentTransfer"
        transfer_history = configer.get_plugin_data(
            key=history_key, plugin_id=plugin_id
        )
        logger.info(f"【同步删除】查询到 {history_key} 转种历史 {transfer_history}")

        handle_torrent_hashs = []
        try:
            # 删除本次种子记录
            self.downloadhis.delete_file_by_fullpath(fullpath=src)

            # 根据种子hash查询所有下载器文件记录
            download_files = self.downloadhis.get_files_by_hash(
                download_hash=torrent_hash
            )
            if not download_files:
                logger.error(
                    f"【同步删除】未查询到种子任务 {torrent_hash} 存在文件记录，未执行下载器文件同步或该种子已被删除"
                )
                return False, False, []

            # 查询未删除数
            no_del_cnt = 0
            for download_file in download_files:
                if (
                    download_file
                    and download_file.state
                    and int(download_file.state) == 1
                ):
                    no_del_cnt += 1

            if no_del_cnt > 0:
                logger.info(
                    f"【同步删除】查询种子任务 {torrent_hash} 存在 {no_del_cnt} 个未删除文件，执行暂停种子操作"
                )
                delete_flag = False
            else:
                logger.info(
                    f"【同步删除】查询种子任务 {torrent_hash} 文件已全部删除，执行删除种子操作"
                )
                delete_flag = True

            # 如果有转种记录，则删除转种后的下载任务
            if transfer_history and isinstance(transfer_history, dict):
                download = transfer_history["to_download"]
                download_id = transfer_history["to_download_id"]
                delete_source = transfer_history["delete_source"]

                # 删除种子
                if delete_flag:
                    # 删除转种记录
                    configer.del_plugin_data(key=history_key, plugin_id=plugin_id)

                    # 转种后未删除源种时，同步删除源种
                    if not delete_source:
                        logger.info(
                            f"【同步删除】{history_key} 转种时未删除源下载任务，开始删除源下载任务…"
                        )

                        # 删除源种子
                        logger.info(
                            f"【同步删除】删除源下载器下载任务：{self.default_downloader} - {torrent_hash}"
                        )
                        self.chain.remove_torrents(torrent_hash)
                        handle_torrent_hashs.append(torrent_hash)

                    # 删除转种后任务
                    logger.info(
                        f"【同步删除】删除转种后下载任务：{download} - {download_id}"
                    )
                    # 删除转种后下载任务
                    self.chain.remove_torrents(hashs=torrent_hash, downloader=download)
                    handle_torrent_hashs.append(download_id)
                else:
                    # 暂停种子
                    # 转种后未删除源种时，同步暂停源种
                    if not delete_source:
                        logger.info(
                            f"【同步删除】{history_key} 转种时未删除源下载任务，开始暂停源下载任务…"
                        )

                        # 暂停源种子
                        logger.info(
                            f"【同步删除】暂停源下载器下载任务：{self.default_downloader} - {torrent_hash}"
                        )
                        self.chain.stop_torrents(torrent_hash)
                        handle_torrent_hashs.append(torrent_hash)

                    logger.info(
                        f"【同步删除】暂停转种后下载任务：{download} - {download_id}"
                    )
                    # 删除转种后下载任务
                    self.chain.stop_torrents(hashs=download_id, downloader=download)
                    handle_torrent_hashs.append(download_id)
            else:
                # 未转种的情况
                if delete_flag:
                    # 删除源种子
                    logger.info(
                        f"【同步删除】删除源下载器下载任务：{download} - {download_id}"
                    )
                    self.chain.remove_torrents(download_id)
                else:
                    # 暂停源种子
                    logger.info(
                        f"【同步删除】暂停源下载器下载任务：{download} - {download_id}"
                    )
                    self.chain.stop_torrents(download_id)
                handle_torrent_hashs.append(download_id)

            # 处理辅种
            handle_torrent_hashs = self.__del_seed(
                download_id=download_id,
                delete_flag=delete_flag,
                handle_torrent_hashs=handle_torrent_hashs,
            )
            # 处理合集
            if str(type) == "电视剧":
                handle_torrent_hashs = self.__del_collection(
                    src=src,
                    delete_flag=delete_flag,
                    torrent_hash=torrent_hash,
                    download_files=download_files,
                    handle_torrent_hashs=handle_torrent_hashs,
                )
            return delete_flag, True, handle_torrent_hashs
        except Exception as e:
            logger.error(f"【同步删除】删种失败： {str(e)}")
            return False, False, []

    def __del_collection(
        self,
        src: str,
        delete_flag: bool,
        torrent_hash: str,
        download_files: list,
        handle_torrent_hashs: list,
    ):
        """
        处理做种合集

        :param src (str): 路径
        :param delete_flag (bool): 删除合集种子
        :param torrent_hash (str): 种子 hash 值
        :param download_files (list): 下载文件列表
        :param handle_torrent_hashs (list): 种子文件 hash 列表
        """
        try:
            src_download_files = self.downloadhis.get_files_by_fullpath(fullpath=src)
            if src_download_files:
                for download_file in src_download_files:
                    # src查询记录 判断download_hash是否不一致
                    if (
                        download_file
                        and download_file.download_hash
                        and str(download_file.download_hash) != str(torrent_hash)
                    ):
                        # 查询新download_hash对应files数量
                        hash_download_files = self.downloadhis.get_files_by_hash(
                            download_hash=download_file.download_hash
                        )
                        # 新download_hash对应files数量 > 删种download_hash对应files数量 = 合集种子
                        if (
                            hash_download_files
                            and len(hash_download_files) > len(download_files)
                            and hash_download_files[0].id > download_files[-1].id
                        ):
                            # 查询未删除数
                            no_del_cnt = 0
                            for hash_download_file in hash_download_files:
                                if (
                                    hash_download_file
                                    and hash_download_file.state
                                    and int(hash_download_file.state) == 1
                                ):
                                    no_del_cnt += 1
                            if no_del_cnt > 0:
                                logger.info(
                                    f"【同步删除】合集种子 {download_file.download_hash} 文件未完全删除，执行暂停种子操作"
                                )
                                delete_flag = False

                            # 删除合集种子
                            if delete_flag:
                                self.chain.remove_torrents(
                                    hashs=download_file.download_hash,
                                    downloader=download_file.downloader,
                                )
                                logger.info(
                                    f"【同步删除】删除合集种子 {download_file.downloader} {download_file.download_hash}"
                                )
                            else:
                                # 暂停合集种子
                                self.chain.stop_torrents(
                                    hashs=download_file.download_hash,
                                    downloader=download_file.downloader,
                                )
                                logger.info(
                                    f"【同步删除】暂停合集种子 {download_file.downloader} {download_file.download_hash}"
                                )
                            # 已处理种子+1
                            handle_torrent_hashs.append(download_file.download_hash)

                            # 处理合集辅种
                            handle_torrent_hashs = self.__del_seed(
                                download_id=download_file.download_hash,
                                delete_flag=delete_flag,
                                handle_torrent_hashs=handle_torrent_hashs,
                            )
        except Exception as e:
            logger.error(f"【同步删除】处理 {torrent_hash} 合集失败: {e}")

        return handle_torrent_hashs

    def __del_seed(self, download_id, delete_flag, handle_torrent_hashs):
        """
        删除辅种

        :param download_id (str): 下载 ID
        :param delete_flag (bool): 删除辅种
        :param handle_torrent_hashs (list): 种子 hash 列表
        """
        # 查询是否有辅种记录
        history_key = download_id
        plugin_id = "IYUUAutoSeed"
        seed_history = (
            configer.get_plugin_data(key=history_key, plugin_id=plugin_id) or []
        )
        logger.info(f"【同步删除】查询到 {history_key} 辅种历史 {seed_history}")

        # 有辅种记录则处理辅种
        if seed_history and isinstance(seed_history, list):
            for history in seed_history:
                downloader = history.get("downloader")
                torrents = history.get("torrents")
                if not downloader or not torrents:
                    return
                if not isinstance(torrents, list):
                    torrents = [torrents]

                # 删除辅种历史
                for torrent in torrents:
                    handle_torrent_hashs.append(torrent)
                    # 删除辅种
                    if delete_flag:
                        logger.info(f"【同步删除】删除辅种：{downloader} - {torrent}")
                        self.chain.remove_torrents(hashs=torrent, downloader=downloader)
                    # 暂停辅种
                    else:
                        self.chain.stop_torrents(hashs=torrent, downloader=downloader)
                        logger.info(f"【同步删除】辅种：{downloader} - {torrent} 暂停")

                    # 处理辅种的辅种
                    handle_torrent_hashs = self.__del_seed(
                        download_id=torrent,
                        delete_flag=delete_flag,
                        handle_torrent_hashs=handle_torrent_hashs,
                    )

            # 删除辅种历史
            if delete_flag:
                configer.del_plugin_data(key=history_key, plugin_id=plugin_id)
        return handle_torrent_hashs

    def __get_p115_media_suffix(
        self, file_path: str, p115_library_path: str
    ) -> Optional[str]:
        """
        115 网盘 遍历文件夹获取媒体文件后缀

        :param file_path (str): 文件路径
        :param p115_library_path (str): 115 网盘 媒体库路径映射
        """
        stem_suffix = Path(Path(file_path).stem).suffix
        mediaext = {ext.lstrip(".").lower() for ext in settings.RMT_MEDIAEXT or []}
        if stem_suffix and stem_suffix.lstrip(".").lower() in mediaext:
            return stem_suffix.lstrip(".")

        sub_paths = self.__get_unique_p115_path_mapping(
            media_path=file_path,
            p115_library_path=p115_library_path,
        )
        if not sub_paths:
            return None
        file_path = file_path.replace(sub_paths[0], sub_paths[2]).replace("\\", "/")
        file_dir = Path(file_path).parent
        file_basename = Path(file_path).stem
        try:
            file_dir_fileitem = self.storagechain.get_file_item(
                storage=configer.storage_module, path=Path(file_dir)
            )
            for item in self.storagechain.list_files(file_dir_fileitem):
                if item.basename == file_basename:
                    return item.extension
        except Exception as e:
            logger.error(f"【同步删除】获取115网盘媒体后缀失败: {e}")
        return None

    @staticmethod
    def __get_p115_path_matches(
        media_path: str,
        p115_library_path: str,
        path_index: int,
    ) -> List[List[str]]:
        """
        获取最长前缀匹配的 115 网盘路径映射

        :param media_path (str): 待匹配路径
        :param p115_library_path (str): 115 网盘媒体库路径映射
        :param path_index (int): 要匹配的路径列索引

        :return List: 最长前缀匹配的路径映射列表
        """
        matches = []
        for mapping in p115_library_path.splitlines():
            parts = [part.strip() for part in mapping.split("#", 2)]
            if len(parts) != 3 or not all(parts) or path_index >= len(parts):
                continue

            if path_index == 0:
                full_parts = PurePosixPath(media_path.replace("\\", "/")).parts
                prefix_parts = PurePosixPath(parts[path_index].replace("\\", "/")).parts
                is_match = full_parts[: len(prefix_parts)] == prefix_parts
            else:
                try:
                    Path(media_path).resolve(strict=False).relative_to(
                        Path(parts[path_index]).resolve(strict=False)
                    )
                    is_match = True
                except (OSError, RuntimeError, ValueError):
                    is_match = False

            if is_match:
                matches.append(parts)

        if not matches:
            return []

        if path_index == 0:
            matches_with_length = [
                (
                    parts,
                    len(PurePosixPath(parts[path_index].replace("\\", "/")).parts),
                )
                for parts in matches
            ]
        else:
            matches_with_length = [
                (
                    parts,
                    len(Path(parts[path_index]).resolve(strict=False).parts),
                )
                for parts in matches
            ]
        longest_prefix_length = max(length for _, length in matches_with_length)
        longest_matches = [
            parts
            for parts, length in matches_with_length
            if length == longest_prefix_length
        ]
        return [list(parts) for parts in dict.fromkeys(map(tuple, longest_matches))]

    def __get_unique_p115_path_mapping(
        self,
        media_path: str,
        p115_library_path: str,
        path_index: int = 0,
    ) -> Optional[List[str]]:
        """
        获取最长前缀唯一匹配的 115 网盘路径映射

        最长前缀对应多个不同映射时返回 None 以阻止删除

        :param media_path (str): 待匹配路径
        :param p115_library_path (str): 115 网盘媒体库路径映射
        :param path_index (int): 要匹配的路径列索引

        :return List: 唯一路径映射，未匹配或存在歧义时返回 None
        """
        matches = self.__get_p115_path_matches(
            media_path=media_path,
            p115_library_path=p115_library_path,
            path_index=path_index,
        )
        if len(matches) != 1:
            if matches:
                logger.warning(
                    f"【同步删除】路径 {media_path} 的最长前缀匹配到 "
                    f"{len(matches)} 条不同的 115 网盘路径映射，"
                    "已跳过删除以避免误删"
                )
            return None
        return matches[0]

    def __resolve_strm_symlink_path(
        self,
        media_path: str,
        p115_library_path: str,
    ) -> Tuple[Optional[str], bool, Optional[Path]]:
        """
        将媒体服务器 STRM 软链接解析为目标路径映射

        仅检查已配置媒体服务器路径对应的 MoviePilot 本地路径
        软链接目标未唯一匹配 MoviePilot 路径映射时返回空路径以阻止删除

        :param media_path (str): Emby 上报的媒体路径
        :param p115_library_path (str): 115 网盘媒体库路径映射

        :return Tuple: 解析后的媒体服务器路径、是否检测到软链接及本地软链接路径
        """
        if Path(media_path).suffix.lower() != ".strm":
            return media_path, False, None

        source_matches = self.__get_p115_path_matches(
            media_path=media_path,
            p115_library_path=p115_library_path,
            path_index=0,
        )
        symlink_paths = []
        for parts in source_matches:
            relative_path = PurePosixPath(media_path.replace("\\", "/")).relative_to(
                PurePosixPath(parts[0].replace("\\", "/"))
            )
            local_path = Path(parts[1]).joinpath(*relative_path.parts)
            if local_path.is_symlink():
                symlink_paths.append(local_path)

        if not symlink_paths:
            return media_path, False, None

        unique_symlink_paths = list(dict.fromkeys(symlink_paths))
        if len(unique_symlink_paths) != 1:
            logger.warning(
                f"【同步删除】路径 {media_path} 检测到多个本地 STRM 软链接，"
                "已跳过删除以避免误删"
            )
            return None, True, None

        symlink_path = unique_symlink_paths[0]
        try:
            link_target = symlink_path.resolve(strict=False)
        except (OSError, RuntimeError) as e:
            logger.warning(
                f"【同步删除】读取本地 STRM 软链接 {symlink_path} 失败，"
                f"已跳过删除以避免误删: {e}"
            )
            return None, True, symlink_path

        target_matches = self.__get_p115_path_matches(
            media_path=str(link_target),
            p115_library_path=p115_library_path,
            path_index=1,
        )
        if len(target_matches) != 1:
            logger.warning(
                f"【同步删除】检测到软链接 {symlink_path} -> {link_target}，"
                f"但目标匹配到 {len(target_matches)} 条 115 网盘路径映射，"
                "已跳过删除以避免误删"
            )
            return None, True, symlink_path

        target_parts = target_matches[0]
        relative_target = link_target.relative_to(
            Path(target_parts[1]).resolve(strict=False)
        )
        resolved_media_path = str(
            PurePosixPath(target_parts[0].replace("\\", "/")).joinpath(
                *relative_target.parts
            )
        )
        logger.info(
            f"【同步删除】路径追踪：Emby Item Path={media_path}，"
            f"本地软链接={symlink_path}，软链接目标={link_target}，"
            f"MoviePilot 映射={target_parts[1]}，115 网盘映射={target_parts[2]}"
        )
        return resolved_media_path, True, symlink_path

    def __expand_strm_directory_paths(
        self,
        media_path: str,
        p115_library_path: str,
    ) -> Tuple[List[str], bool]:
        """
        将媒体服务器目录递归展开为 STRM 文件路径

        仅展开唯一匹配且仍存在的 MoviePilot 本地目录
        本地目录已被媒体服务器删除时回退到现有目录映射

        :param media_path (str): Emby 上报的媒体路径
        :param p115_library_path (str): 115 网盘媒体库路径映射

        :return Tuple: 展开后的媒体服务器路径列表及是否识别到本地目录
        """
        source_matches = self.__get_p115_path_matches(
            media_path=media_path,
            p115_library_path=p115_library_path,
            path_index=0,
        )
        directory_matches = []
        normalized_media_path = PurePosixPath(media_path.replace("\\", "/"))
        for parts in source_matches:
            relative_path = normalized_media_path.relative_to(
                PurePosixPath(parts[0].replace("\\", "/"))
            )
            local_path = Path(parts[1]).joinpath(*relative_path.parts)
            if local_path.is_dir() and not local_path.is_symlink():
                directory_matches.append((parts, local_path))

        if not directory_matches:
            media_suffixes = {
                f".{suffix.lstrip('.').lower()}"
                for suffix in settings.RMT_MEDIAEXT or []
            }
            media_suffixes.add(".strm")
            if source_matches and Path(media_path).suffix.lower() not in media_suffixes:
                logger.info(
                    f"【同步删除】路径 {media_path} 对应本地目录已不存在，"
                    "按目录映射继续同步删除"
                )
                return [media_path], False
            return [media_path], False

        if len(directory_matches) != 1:
            logger.warning(
                f"【同步删除】路径 {media_path} 匹配到多个不同的媒体目录映射，"
                "已跳过删除以避免误删"
            )
            return [], True

        _, local_directory = directory_matches[0]
        try:
            strm_paths = sorted(
                (
                    path
                    for path in local_directory.rglob("*")
                    if path.suffix.lower() == ".strm"
                    and (path.is_file() or path.is_symlink())
                ),
                key=lambda path: str(path).casefold(),
            )
        except OSError as e:
            logger.error(
                f"【同步删除】递归读取本地媒体目录 {local_directory} 失败，"
                f"已跳过删除以避免误删: {e}",
                exc_info=True,
            )
            return [], True
        expanded_paths = [
            str(
                normalized_media_path.joinpath(
                    *strm_path.relative_to(local_directory).parts
                )
            )
            for strm_path in strm_paths
        ]
        logger.info(
            f"【同步删除】目录 {media_path} 递归识别到 "
            f"{len(expanded_paths)} 个 STRM 文件"
        )
        return expanded_paths, True

    @staticmethod
    def __get_remove_type(
        media_type: str,
        season_num: Optional[str],
        episode_num: Optional[str],
    ) -> Optional[str]:
        """
        获取删除媒体的类型

        :param media_type (str): 媒体类型
        :param season_num (str): 季数
        :param episode_num (str): 集数
        """
        # 季数
        if season_num and str(season_num).isdigit():
            season_num = str(season_num).rjust(2, "0")
        else:
            season_num = None
        # 集数
        if episode_num and str(episode_num).isdigit():
            episode_num = str(episode_num).rjust(2, "0")
        else:
            episode_num = None
        # 类型
        mtype = MediaType.MOVIE if media_type in ["Movie", "MOV"] else MediaType.TV

        # 删除电影
        if mtype == MediaType.MOVIE:
            msg = "movie"
        # 删除电视剧
        elif mtype == MediaType.TV and not season_num and not episode_num:
            msg = "tv"
        # 删除季
        elif mtype == MediaType.TV and season_num and not episode_num:
            msg = "tv_season"
        # 删除集
        elif mtype == MediaType.TV and season_num and episode_num:
            msg = "tv_episode"
        else:
            return None
        return msg

    def __get_transfer_his(
        self,
        media_type: str,
        media_name: str,
        media_path: str,
        tmdb_id: int,
        season_num: Optional[str],
        episode_num: Optional[str],
        exact_path_only: bool = False,
    ) -> Tuple[str, List[TransferHistory]]:
        """
        查询转移记录

        :param media_type (str): 媒体类型
        :param media_name (str): 媒体名称
        :param media_path (str): 媒体路径
        :param tmdb_id (int): TMDB ID
        :param season_num (str): 季数
        :param episode_num (str): 集数
        :param exact_path_only (bool): 是否仅查询目标路径完全匹配的转移记录
        """
        # 季数
        if season_num and str(season_num).isdigit():
            season_num = str(season_num).rjust(2, "0")
        else:
            season_num = None
        # 集数
        if episode_num and str(episode_num).isdigit():
            episode_num = str(episode_num).rjust(2, "0")
        else:
            episode_num = None

        # 类型
        mtype = MediaType.MOVIE if media_type in ["Movie", "MOV"] else MediaType.TV
        if exact_path_only:
            media_type_name = "电影" if mtype == MediaType.MOVIE else "剧集"
            msg = f"{media_type_name} {media_name} {tmdb_id}"
            transfer_his = self.transferhis.get_by_dest(media_path)
            transfer_history = [transfer_his] if transfer_his else []
        # 删除多版本电影
        elif mtype == MediaType.MOVIE and configer.sync_del_remove_versions:
            msg, transfer_history = "", []
            transfer_his = self.transferhis.get_by_dest(media_path)
            if transfer_his:
                msg, transfer_history = (
                    f"电影 {media_name} {tmdb_id}",
                    [transfer_his],
                )
        # 删除电影
        elif mtype == MediaType.MOVIE:
            msg = f"电影 {media_name} {tmdb_id}"
            transfer_history: List[TransferHistory] = self.transferhis.get_by(
                tmdbid=tmdb_id, mtype=mtype.value, dest=media_path
            )
        # 删除电视剧
        elif mtype == MediaType.TV and not season_num and not episode_num:
            msg = f"剧集 {media_name} {tmdb_id}"
            transfer_history: List[TransferHistory] = self.transferhis.get_by(
                tmdbid=tmdb_id, mtype=mtype.value
            )
        # 季处理为集（多版本季删除）
        elif (
            mtype == MediaType.TV
            and season_num
            and not episode_num
            and configer.sync_del_remove_versions
        ):
            msg, transfer_history = "", []
            transfer_his = self.transferhis.get_by_dest(media_path)
            if transfer_his:
                msg, transfer_history = (
                    f"剧集 {media_name} S{season_num}{transfer_his.episodes} {tmdb_id}",
                    [transfer_his],
                )
        # 删除季
        elif mtype == MediaType.TV and season_num and not episode_num:
            if not season_num or not str(season_num).isdigit():
                logger.error(f"【同步删除】{media_name} 季同步删除失败，未获取到具体季")
                return "", []
            msg = f"剧集 {media_name} S{season_num} {tmdb_id}"
            transfer_history: List[TransferHistory] = self.transferhis.get_by(
                tmdbid=tmdb_id, mtype=mtype.value, season=f"S{season_num}"
            )
        # 删除集
        elif mtype == MediaType.TV and season_num and episode_num:
            if (
                not season_num
                or not str(season_num).isdigit()
                or not episode_num
                or not str(episode_num).isdigit()
            ):
                logger.error(f"【同步删除】{media_name} 集同步删除失败，未获取到具体集")
                return "", []
            msg = f"剧集 {media_name} S{season_num}E{episode_num} {tmdb_id}"
            transfer_history: List[TransferHistory] = self.transferhis.get_by(
                tmdbid=tmdb_id,
                mtype=mtype.value,
                season=f"S{season_num}",
                episode=f"E{episode_num}",
                dest=media_path,
            )
        else:
            return "", []
        return msg, transfer_history

    def __delete_p115_files(self, storage: str, file_path: str, media_name: str):
        """
        删除 115 网盘文件

        :param storage (str): 储存类型
        :param file_path (str): 文件路径
        :param media_name (str): 媒体名称
        """
        try:
            if storage not in {"u115", "115网盘Plus", "CloudDrive储存"}:
                raise OSError("不支持的储存类型")
            # 获取文件(夹)详细信息
            fileitem = self.storagechain.get_file_item(
                storage=storage, path=Path(file_path)
            )
            if not fileitem:
                logger.warn(f"【同步删除】{media_name} 网盘媒体不存在：{file_path}")
                return
            if fileitem.type == "dir":
                # 删除整个文件夹
                self.storagechain.delete_file(fileitem)
                logger.info(f"【同步删除】{media_name} 删除网盘文件夹：{file_path}")
            else:
                # 调用 MP 模块删除媒体文件和空媒体目录
                self.storagechain.delete_media_file(fileitem=fileitem)
                logger.info(f"【同步删除】{media_name} 删除网盘媒体文件：{file_path}")
        except Exception as e:
            logger.error(f"【同步删除】{media_name} 删除网盘媒体 {file_path} 失败: {e}")

    def sync_del_by_webhook(
        self,
        event_data: WebhookEventInfo,
        enabled: bool,
        notify: bool,
        del_source: bool,
        p115_library_path: Optional[str],
        p115_force_delete_files: bool,
        delete_symlink: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """
        通过Webhook事件同步删除媒体

        :param event_data (WebhookEventInfo): 事件数据
        :param enabled (bool): 是否启用
        :param notify (bool): 是否通知
        :param del_source (bool): 是否删除源文件
        :param p115_library_path (str): 115 网盘媒体库路径映射
        :param p115_force_delete_files (bool): 115 网盘强制删除
        :param delete_symlink (bool): 是否删除本地 STRM 软链接
        """
        if not enabled:
            return None

        event_type = event_data.event

        # 神医助手深度删除标识
        if not event_type or str(event_type) != "deep.delete":
            return None

        logger.debug(f"【同步删除】收到删除事件: {event_data}")

        # 媒体类型
        media_type = event_data.item_type
        # 媒体名称
        media_name = event_data.item_name
        # 媒体路径
        media_path = event_data.item_path
        # tmdb_id
        tmdb_id = event_data.tmdb_id
        # 季数
        season_num = event_data.season_id
        # 集数
        episode_num = event_data.episode_id
        # 原始数据
        json_object = getattr(event_data, "json_object", {})

        # 对于 Emby 新版本 API 单独处理，兼容季删除
        if json_object.get("Item", {}).get("Type", None) == "Season":
            if not season_num and episode_num:
                season_num = episode_num
                episode_num = None

        remove_type = self.__get_remove_type(media_type, season_num, episode_num)
        if remove_type in ["tv_season", "movie"] and configer.sync_del_remove_versions:
            # 为了支持多版本删除，电影和季删除统一退回为集删除
            description = json_object.get("Description", "")
            item_paths = WebhookUtils.parse_item_paths_from_description(description)

            if not item_paths:
                original_path = event_data.item_path
                if original_path:
                    item_paths = [original_path]
                else:
                    logger.warn(
                        f"【同步删除】{media_name} 同步删除失败，未找到Item Path"
                    )
                    return None

            logger.info(
                f"【同步删除】{media_name} 从Description解析到 {len(item_paths)} 个Item Path: {item_paths}"
            )
        else:
            if not media_path:
                logger.warn(f"【同步删除】{media_name} 同步删除失败，未找到Item Path")
                return None
            item_paths = [media_path]

        if not p115_library_path:
            return None

        expanded_item_paths = []
        for item_path in item_paths:
            paths, directory_expanded = self.__expand_strm_directory_paths(
                media_path=item_path,
                p115_library_path=p115_library_path,
            )
            expanded_item_paths.extend((path, directory_expanded) for path in paths)

        results = []
        for media_path, directory_expanded in expanded_item_paths:
            if not media_path:
                continue

            media_suffix = None

            media_path, symlink_detected, symlink_path = (
                self.__resolve_strm_symlink_path(
                    media_path=media_path,
                    p115_library_path=p115_library_path,
                )
            )
            if symlink_detected and not media_path:
                continue

            path_mapping = self.__get_unique_p115_path_mapping(
                media_path=media_path,
                p115_library_path=p115_library_path,
            )
            if not path_mapping:
                logger.warn(
                    f"【同步删除】{media_name} 路径 {media_path} 同步删除失败，未识别到115网盘储存类型，跳过"
                )
                continue

            # 对于 115 网盘文件需要获取媒体后缀名
            if Path(media_path).suffix:
                if not directory_expanded:
                    media_suffix = json_object.get("Item", {}).get("Container", None)
                if not media_suffix:
                    media_suffix = self.__get_p115_media_suffix(
                        media_path, p115_library_path
                    )
                    if not media_suffix:
                        logger.warn(
                            f"【同步删除】{media_name} 路径 {media_path} 同步删除失败，未识别媒体后缀名，跳过"
                        )
                        continue

                if symlink_detected:
                    symlink_parts = self.__get_unique_p115_path_mapping(
                        media_path=media_path,
                        p115_library_path=p115_library_path,
                    )
                    if not symlink_parts:
                        logger.warning(
                            "【同步删除】软链接路径映射丢失，已跳过删除以避免误删"
                        )
                        continue
                    symlink_p115_path = media_path.replace(
                        symlink_parts[0], symlink_parts[2]
                    ).replace("\\", "/")
                    symlink_p115_path, _ = PathUtils.get_media_file_paths_with_suffix(
                        file_path=symlink_p115_path,
                        media_suffix=media_suffix,
                    )
                    logger.info(f"【同步删除】软链接最终删除路径：{symlink_p115_path}")
            else:
                logger.debug(
                    f"【同步删除】{media_name} 路径 {media_path} 跳过识别媒体后缀名"
                )

            # 单集或单季缺失 TMDB ID 获取
            current_tmdb_id = tmdb_id
            if (episode_num or season_num) and (
                not current_tmdb_id or not str(current_tmdb_id).isdigit()
            ):
                series_id = json_object.get("Item", {}).get("SeriesId")
                if series_id and configer.sync_del_mediaservers:
                    series_tmdb_id = self.mediaserver_operate.get_series_tmdb_id(
                        configer.sync_del_mediaservers[0], series_id
                    )
                    if series_tmdb_id:
                        current_tmdb_id = series_tmdb_id

            tmdb_id_int: Optional[int] = None
            if current_tmdb_id and str(current_tmdb_id).isdigit():
                tmdb_id_int = int(current_tmdb_id)

            if not tmdb_id_int:
                if not p115_force_delete_files:
                    logger.warn(
                        f"【同步删除】{media_name} 路径 {media_path} 同步删除失败，未获取到TMDB ID，请检查媒体库媒体是否刮削，跳过"
                    )
                    continue

            result = self.__sync_del(
                media_type=media_type,
                media_name=media_name,
                media_path=media_path,
                tmdb_id=tmdb_id_int,
                season_num=season_num,
                episode_num=episode_num,
                media_suffix=media_suffix,
                p115_library_path=p115_library_path,
                p115_force_delete_files=p115_force_delete_files,
                del_source=del_source,
                notify=notify,
                symlink_detected=symlink_detected,
                exact_path_only=directory_expanded,
            )
            if result:
                results.append(result)
                if delete_symlink and symlink_path:
                    try:
                        if symlink_path.is_symlink():
                            symlink_path.unlink()
                            logger.info(
                                f"【同步删除】本地 STRM 软链接已删除：{symlink_path}"
                            )
                    except OSError as e:
                        logger.error(
                            f"【同步删除】删除本地 STRM 软链接 {symlink_path} 失败: {e}",
                            exc_info=True,
                        )

        return results[-1] if results else None

    def __sync_del(
        self,
        media_type: str,
        media_name: str,
        media_path: str,
        tmdb_id: int,
        season_num: Optional[str],
        episode_num: Optional[str],
        media_suffix: Optional[str],
        p115_library_path: Optional[str],
        p115_force_delete_files: bool,
        del_source: bool,
        notify: bool,
        symlink_detected: bool = False,
        exact_path_only: bool = False,
    ) -> Dict[str, Any]:
        """
        执行同步删除

        :param media_type (str): 媒体类型
        :param media_name (str): 媒体名称
        :param media_path (str): 媒体路径
        :param tmdb_id (int): TMDB ID
        :param season_num (str): 季数
        :param episode_num (str): 集数
        :param media_suffix (str): 媒体后缀
        :param p115_library_path (str): 115 网盘 媒体库路径映射
        :param p115_force_delete_files (bool): 115 网盘 强制删除
        :param del_source (bool): 是否删除源文件
        :param notify (bool): 是否通知
        :param symlink_detected (bool): 是否通过本地 STRM 软链接解析路径
        :param exact_path_only (bool): 是否仅按单个目标路径删除
        """
        if not media_type:
            logger.error(
                f"【同步删除】{media_name} 同步删除失败，未获取到媒体类型，请检查媒体是否刮削"
            )
            return {}

        year = None
        del_torrent_hashs = []
        stop_torrent_hashs = []
        error_cnt = 0
        image = "https://emby.media/notificationicon.png"

        mp_media_path: Optional[Path] = None
        if p115_library_path:
            sub_paths = self.__get_unique_p115_path_mapping(
                media_path=media_path,
                p115_library_path=p115_library_path,
            )
            if sub_paths:
                mp_media_path = Path(
                    media_path.replace(sub_paths[0], sub_paths[1]).replace("\\", "/")
                )
                media_path = media_path.replace(sub_paths[0], sub_paths[2]).replace(
                    "\\", "/"
                )

        media_path, media_path_final = PathUtils.get_media_file_paths_with_suffix(
            file_path=media_path,
            media_suffix=media_suffix,
        )

        if (
            mp_media_path
            and mp_media_path.exists()
            and not symlink_detected
            and not exact_path_only
        ):
            logger.warn(
                f"【同步删除】转移路径 {media_path} 未被删除或重新生成，跳过处理"
            )
            return {}

        msg, transfer_history = self.__get_transfer_his(
            media_type=media_type,
            media_name=media_name,
            media_path=media_path,
            tmdb_id=tmdb_id,
            season_num=season_num,
            episode_num=episode_num,
            exact_path_only=exact_path_only,
        )

        if not msg:
            msg = media_name

        logger.info(f"【同步删除】正在同步删除 {msg}")

        if not transfer_history:
            # 大小写转换二次查询
            msg, transfer_history = self.__get_transfer_his(
                media_type=media_type,
                media_name=media_name,
                media_path=media_path_final,
                tmdb_id=tmdb_id,
                season_num=season_num,
                episode_num=episode_num,
                exact_path_only=exact_path_only,
            )
            if not msg:
                msg = media_name
            if not transfer_history:
                if p115_force_delete_files:
                    logger.warn(f"【同步删除】{media_name} 强制删除网盘媒体文件")
                    self.__delete_p115_files(
                        storage=configer.storage_module,
                        file_path=media_path,
                        media_name=media_name,
                    )
                else:
                    logger.warn(
                        f"【同步删除】{media_type} {media_name} 未获取到可删除数据，请检查路径映射是否配置错误，请检查tmdbid获取是否正确"
                    )
                    return {}

        if transfer_history:
            logger.info(
                f"【同步删除】获取到 {len(transfer_history)} 条转移记录，开始同步删除"
            )
            for transferhis in transfer_history:
                title = transferhis.title
                if title not in media_name:
                    logger.warn(
                        f"【同步删除】当前转移记录 {transferhis.id} {title} {transferhis.tmdbid} 与删除媒体 {media_name} 不符，防误删，暂不自动删除"
                    )
                    continue
                image = transferhis.image or image
                year = transferhis.year

                self.transferhis.delete(transferhis.id)

                self.__delete_p115_files(
                    storage=transferhis.dest_storage,
                    file_path=transferhis.dest,
                    media_name=media_name,
                )

                if del_source:
                    if (
                        transferhis.src
                        and Path(transferhis.src).suffix in settings.RMT_MEDIAEXT
                        and transferhis.src_storage == "local"
                        and transferhis.mode != "move"  # 如果是移动 -> 本地资源已经删除
                    ):
                        if Path(transferhis.src).exists():
                            logger.info(
                                f"【同步删除】源文件 {transferhis.src} 开始删除"
                            )
                            Path(transferhis.src).unlink(missing_ok=True)
                            logger.info(f"【同步删除】源文件 {transferhis.src} 已删除")
                            PathRemoveUtils.remove_parent_dir(
                                file_path=Path(transferhis.src),
                                mode=settings.RMT_MEDIAEXT,
                                func_type="【同步删除】",
                            )

                        if transferhis.download_hash:
                            try:
                                delete_flag, success_flag, handle_torrent_hashs = (
                                    self.handle_torrent(
                                        type=transferhis.type,
                                        src=transferhis.src,
                                        torrent_hash=transferhis.download_hash,
                                    )
                                )
                                if not success_flag:
                                    error_cnt += 1
                                else:
                                    if delete_flag:
                                        del_torrent_hashs += handle_torrent_hashs
                                    else:
                                        stop_torrent_hashs += handle_torrent_hashs
                            except Exception as e:
                                logger.error(f"【同步删除】删除种子失败：{str(e)}")

        logger.info(f"【同步删除】同步删除 {msg} 完成！")

        media_type_enum = (
            MediaType.MOVIE if media_type in ["Movie", "MOV"] else MediaType.TV
        )

        result = {
            "msg": msg,
            "transfer_history": transfer_history,
            "del_torrent_hashs": del_torrent_hashs,
            "stop_torrent_hashs": stop_torrent_hashs,
            "error_cnt": error_cnt,
            "image": image,
            "year": year,
            "media_type": media_type_enum,
            "tmdb_id": tmdb_id,
            "season_num": season_num,
            "episode_num": episode_num,
            "media_name": media_name,
        }

        if notify:
            backrop_image = (
                self.chain.obtain_specific_image(
                    mediaid=tmdb_id,
                    mtype=media_type_enum,
                    image_type=MediaImageType.Backdrop,
                    season=season_num,
                    episode=episode_num,
                )
                or image
            )

            torrent_cnt_msg = ""
            if del_torrent_hashs:
                torrent_cnt_msg += (
                    i18n.translate(
                        "sync_del_torrent_count", count=len(set(del_torrent_hashs))
                    )
                    + "\n"
                )
            if stop_torrent_hashs:
                stop_cnt = 0
                for stop_hash in set(stop_torrent_hashs):
                    if stop_hash not in set(del_torrent_hashs):
                        stop_cnt += 1
                if stop_cnt > 0:
                    torrent_cnt_msg += (
                        i18n.translate("sync_del_stop_count", count=stop_cnt) + "\n"
                    )
            if error_cnt:
                torrent_cnt_msg += (
                    i18n.translate("sync_del_error_count", count=error_cnt) + "\n"
                )
            post_message(
                mtype=NotificationType.Plugin,
                title=i18n.translate("media_sync_del_done_title"),
                image=backrop_image,
                text=f"{msg}\n"
                f"{i18n.translate('sync_del_record_count', count=len(transfer_history) if transfer_history else 0)}\n"
                f"{torrent_cnt_msg}"
                f"时间 {strftime('%Y-%m-%d %H:%M:%S', localtime(time()))}",
            )

        self._save_sync_del_history(result)

        return result

    def _save_sync_del_history(self, result: Dict[str, Any]):
        """
        保存同步删除历史记录

        :param result (Dict): 同步删除结果
        """
        if not result:
            logger.warning("【同步删除】历史记录保存失败：result 为空")
            return

        try:
            history = configer.get_plugin_data(key="sync_del_history") or []
            poster_image = self.chain.obtain_specific_image(
                mediaid=result.get("tmdb_id"),
                mtype=result.get("media_type"),
                image_type=MediaImageType.Poster,
            ) or result.get("image", "https://emby.media/notificationicon.png")

            history_item = {
                "type": result.get("media_type").value
                if result.get("media_type")
                else "未知",
                "title": result.get("media_name", ""),
                "year": result.get("year"),
                "path": result.get("msg", ""),
                "season": result.get("season_num")
                if result.get("season_num") and str(result.get("season_num")).isdigit()
                else None,
                "episode": result.get("episode_num")
                if result.get("episode_num")
                and str(result.get("episode_num")).isdigit()
                else None,
                "image": poster_image,
                "del_time": strftime("%Y-%m-%d %H:%M:%S", localtime(time())),
                "unique": f"{result.get('media_name', '')}:{result.get('tmdb_id', '')}:{strftime('%Y-%m-%d %H:%M:%S', localtime(time()))}",
            }
            history.append(history_item)
            configer.save_plugin_data(key="sync_del_history", value=history)
            logger.info(
                f"【同步删除】历史记录已保存：{history_item.get('title')} (TMDB ID: {result.get('tmdb_id')})"
            )
        except Exception as e:
            logger.error(f"【同步删除】保存历史记录失败: {e}", exc_info=True)
