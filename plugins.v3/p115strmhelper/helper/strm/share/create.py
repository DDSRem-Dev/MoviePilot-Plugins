from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import batched
from os import remove as os_remove
from os.path import exists as path_exists, getsize as path_getsize, join as path_join
from pathlib import Path
from queue import Empty, Queue
from tempfile import gettempdir
from threading import Lock, Thread
from time import perf_counter, sleep
from typing import Any, Deque, Dict, Iterator, List, Optional, Set, Tuple

from p115client import check_response
from p115client.tool.iterdir import share_iter_files
from p115client.util import share_extract_payload

from app.core.config import settings
from app.log import logger

from ....core.cache import sharestrmcacher
from ....core.config import configer
from ....core.p115_client import create_client_with_timeout
from ....core.history import StrmExecHistoryManager
from ....core.i18n import i18n
from ....core.message import post_message
from ....core.p115 import ShareP115Client, iter_share_files_with_path
from ....core.scrape import media_scrape_metadata
from ....helper.mediainfo_download import MediaInfoDownloader
from ....helper.mediaserver import MediaServerRefresh
from ....schemas.share import ShareStrmConfig
from ....schemas.size import CompareMinSize
from ....utils.path import PathUtils
from ....utils.rename_dict import RenameDictUtils
from ....utils.sentry import sentry_manager
from ....utils.strm import StrmGenerater, StrmUrlGetter

from .audit_download_queue import share_audit_download_queue
from .oof import ShareFilesDataCollector, ShareOOPServerHelper


class ShareStrmHelper:
    """
    根据分享生成STRM
    """

    def __init__(self, mediainfodownloader: MediaInfoDownloader):
        """
        初始化 STRM 生成器

        :param mediainfodownloader (MediaInfoDownloader): 媒体信息下载器实例
        """
        self.rmt_mediaext: Set[str] = {
            f".{ext.strip()}"
            for ext in configer.user_rmt_mediaext.replace("，", ",").split(",")
        }
        self.download_mediaext: Set[str] = {
            f".{ext.strip()}"
            for ext in configer.user_download_mediaext.replace("，", ",").split(",")
        }

        raw_client = ShareP115Client(configer.cookies)
        if configer.timeout_enabled:
            default_timeout = configer.get_default_timeout()
            slow_timeout = configer.get_slow_timeout()
            self.share_client = create_client_with_timeout(
                raw_client, default_timeout, slow_timeout
            )
        else:
            self.share_client = raw_client
        self.mediainfodownloader = mediainfodownloader

        self.elapsed_time = 0
        self.strm_exec_history_kind: Optional[str] = None
        self.strm_exec_history_extra: Optional[Dict[str, Any]] = None

        self.total_count = 0
        self.strm_count = 0
        self.mediainfo_count = 0
        self._strm_generated_paths: Set[str] = set()

        self.strm_fail_count = 0
        self.strm_fail_dict: Dict[str, str] = {}
        self.mediainfo_fail_count = 0
        self.mediainfo_fail_dict: List = []

        self.download_mediainfo_list = []
        self.share_media_contexts: Dict[str, List[Dict[str, Any]]] = {}

        self.scrape_refresh_queue = Deque()
        self.mp_transfer_queue = Deque()

        self.lock = Lock()
        self.strm_count_lock = Lock()
        self.strm_fail_lock = Lock()

        self.strmurlgetter = StrmUrlGetter()

    @staticmethod
    def get_share_code(config: ShareStrmConfig) -> ShareStrmConfig:
        """
        解析分享配置，获取分享码和提取码
        """
        if config.share_link:
            data = share_extract_payload(config.share_link)
            share_code = data["share_code"]
            receive_code = data["receive_code"]
            logger.info(
                f"【分享STRM生成】解析分享链接 share_code={share_code} receive_code={receive_code}"
            )
        else:
            if not config.share_code or not config.share_receive:
                return config
            share_code = config.share_code
            receive_code = config.share_receive
        config.share_code = share_code
        config.share_receive = receive_code
        return config

    def scrape_refresh_media(self, config: ShareStrmConfig) -> None:
        """
        刮削媒体 & 刷新媒体服务器

        :param config (ShareStrmConfig): 分享 STRM 生成配置
        """
        media_server_refresh = MediaServerRefresh(
            func_name="【分享STRM生成】",
            enabled=config.media_server_refresh,
            mp_mediaserver=configer.share_strm_mp_mediaserver_paths,
            mediaservers=configer.share_strm_mediaservers,
            delay_seconds=configer.share_strm_media_server_refresh_delay,
        )

        def _refresh_media_server(file_path: Path) -> None:
            media_server_refresh.refresh_mediaserver(
                file_path=file_path.as_posix(), file_name=file_path.name
            )

        def _scrape_media_data(file_path: Path) -> None:
            logger.info(f"【分享STRM生成】{file_path.as_posix()} 开始刮削...")
            media_scrape_metadata(file_path.as_posix())

        def _scrape_and_refresh(file_path: Path) -> None:
            logger.info(f"【分享STRM生成】{file_path.as_posix()} 开始刮削...")
            _scrape_media_data(file_path)
            _refresh_media_server(file_path)

        if config.scrape_metadata and config.media_server_refresh:
            func = _scrape_and_refresh
        elif config.scrape_metadata:
            func = _scrape_media_data
        elif config.media_server_refresh:
            func = _refresh_media_server
        else:
            return

        while len(self.scrape_refresh_queue) != 0:
            path = self.scrape_refresh_queue.popleft()
            func(Path(path))

    def mp_transfer(self) -> None:
        """
        交由 MoviePilot 整理文件
        """
        while len(self.mp_transfer_queue) != 0:
            entry = self.mp_transfer_queue.popleft()
            if isinstance(entry, dict):
                path = Path(entry["path"])
                share_audit_download_queue.transfer_local_file(path, entry)
            else:
                share_audit_download_queue.transfer_local_file(Path(entry))

    def _attach_related_media_contexts(self) -> None:
        if not configer.rename_dict_supplement_enabled:
            return
        for entry in self.download_mediainfo_list:
            if not entry.get("mp_transfer_after_download"):
                continue
            relation_key = entry.get("media_relation_key")
            contexts = self.share_media_contexts.get(relation_key, [])
            unique_contexts = {
                f"{context.get('share_code')}:{context.get('file_id')}": context
                for context in contexts
            }
            if len(unique_contexts) == 1:
                entry["related_media"] = dict(next(iter(unique_contexts.values())))
            elif len(unique_contexts) > 1:
                logger.warning(
                    f"【分享STRM生成】伴随文件匹配到多个同名主视频，"
                    f"跳过媒体字段上下文: {entry.get('path')}"
                )

    def __process_single_item(
        self,
        item: Dict,
        config: ShareStrmConfig,
        detailed_data: bool,
    ) -> None:
        """
        处理单个 STRM 文件

        :param item (Dict): 网盘文件信息
        :param config (ShareStrmConfig): 分享 STRM 生成配置
        :param detailed_data (bool): 是否为详细迭代数据
        """
        file_path = item["path"]

        if not PathUtils.has_prefix(file_path, config.share_path):
            logger.debug(
                "【分享STRM生成】此文件不在用户设置分享目录下，跳过分享路径: %s",
                str(file_path).replace(config.local_path, "", 1),
            )
            return

        share_path_obj = Path(config.share_path)
        local_path_obj = Path(config.local_path)
        item_path_obj = Path(file_path)

        file_path = local_path_obj / PathUtils.sanitize_path_parts(
            item_path_obj.relative_to(share_path_obj)
        )
        file_target_dir = file_path.parent
        original_file_name = file_path.name
        file_name = StrmGenerater.get_strm_filename(file_path)
        new_file_path = file_target_dir / file_name
        new_file_path_str = str(new_file_path)

        try:
            if detailed_data and config.auto_download_mediainfo:
                if file_path.suffix.lower() in self.download_mediaext:
                    with self.lock:
                        self.download_mediainfo_list.append(
                            {
                                "type": "share",
                                "share_code": config.share_code,
                                "receive_code": config.share_receive,
                                "file_id": item["id"],
                                "path": file_path,
                                "thumb": item.get("thumb", None),
                                "sha1": item["sha1"],
                            }
                        )
                    return

            sfx_lower = file_path.suffix.lower()
            if (
                detailed_data
                and config.moviepilot_transfer
                and config.moviepilot_transfer_download_rmt_audio_sub
                and (
                    sfx_lower in settings.RMT_AUDIOEXT
                    or sfx_lower in settings.RMT_SUBEXT
                )
            ):
                file_path.parent.mkdir(parents=True, exist_ok=True)
                relation_key = None
                if configer.rename_dict_supplement_enabled:
                    relation_key = RenameDictUtils.get_media_relation_key(
                        file_path.as_posix(),
                        sfx_lower,
                        settings.RMT_SUBEXT,
                        storage="local",
                    )
                with self.lock:
                    download_item: Dict[str, Any] = {
                        "type": "share",
                        "share_code": config.share_code,
                        "receive_code": config.share_receive,
                        "file_id": item["id"],
                        "path": file_path,
                        "thumb": item.get("thumb", None),
                        "sha1": item["sha1"],
                        "mp_transfer_after_download": True,
                    }
                    if relation_key:
                        download_item["media_relation_key"] = relation_key
                    self.download_mediainfo_list.append(download_item)
                return

            if sfx_lower not in self.rmt_mediaext:
                logger.warn(
                    "【分享STRM生成】文件后缀不匹配，跳过分享路径: %s",
                    str(file_path).replace(config.local_path, "", 1),
                )
                return

            if not (
                result := StrmGenerater.should_generate_strm(
                    original_file_name,
                    mode="share",
                    filesize=CompareMinSize(
                        min_size=config.min_file_size, file_size=item["size"]
                    ),
                )
            )[1]:
                logger.warn(
                    f"【分享STRM生成】{result[0]}，跳过分享路径: {str(file_path).replace(config.local_path, '', 1)}"
                )
                return

            if not item["id"]:
                logger.error(
                    f"【分享STRM生成】{original_file_name} 不存在 id 值，无法生成 STRM 文件"
                )
                with self.strm_fail_lock:
                    self.strm_fail_dict[str(new_file_path)] = "不存在 id 值"
                    self.strm_fail_count += 1
                return

            new_file_path.parent.mkdir(parents=True, exist_ok=True)

            strm_url = self.strmurlgetter.get_share_strm_url(
                config.share_code,
                config.share_receive,
                item["id"],
                item["name"],
                item["path"],
            )

            new_file_path.write_text(strm_url, encoding="utf-8")
            with self.strm_count_lock:
                if new_file_path_str not in self._strm_generated_paths:
                    self.strm_count += 1
                    self._strm_generated_paths.add(new_file_path_str)
            logger.info("【分享STRM生成】生成 STRM 文件成功: %s", str(new_file_path))
            cache_key = f"{config.share_code}:{config.share_receive}:{item['id']}"
            cache_data = {"size": item["size"]}
            if detailed_data:
                cache_data["sha1"] = item["sha1"]
            sharestrmcacher.file_item_dict[cache_key] = cache_data

            if configer.rename_dict_supplement_enabled and config.moviepilot_transfer:
                relation_key = RenameDictUtils.get_media_relation_key(
                    file_path.as_posix(),
                    sfx_lower,
                    settings.RMT_SUBEXT,
                    storage="local",
                )
                media_context = {
                    "share_code": config.share_code,
                    "receive_code": config.share_receive,
                    "file_id": item["id"],
                    "sha1": item.get("sha1"),
                    "size": item.get("size"),
                    "strm_url": strm_url,
                }
                with self.lock:
                    self.share_media_contexts.setdefault(relation_key, []).append(
                        media_context
                    )

            if config.moviepilot_transfer:
                self.mp_transfer_queue.append(new_file_path)

            if config.media_server_refresh or config.scrape_metadata:
                self.scrape_refresh_queue.append(new_file_path)
        except Exception as e:
            sentry_manager.sentry_hub.capture_exception(e)
            logger.error(
                "【分享STRM生成】生成 STRM 文件失败: %s  %s",
                str(new_file_path),
                e,
            )
            with self.strm_fail_lock:
                self.strm_fail_count += 1
                self.strm_fail_dict[str(new_file_path)] = str(e)
            return

    def _create_online_share_iterator(
        self, config: ShareStrmConfig
    ) -> Tuple[Iterator[Dict], bool]:
        """
        根据配置创建在线分享文件迭代器

        :param config (ShareStrmConfig): 分享 STRM 生成配置

        :return Tuple: 文件迭代器与是否为详细数据
        """
        if config.iter_function == "iter_share_files_with_path":
            return (
                iter_share_files_with_path(
                    client=self.share_client,
                    share_code=config.share_code,
                    receive_code=config.share_receive,
                    cid=0,
                    speed_mode=config.speed_mode,
                    **configer.get_ios_ua_app(),
                ),
                True,
            )
        return (
            share_iter_files(
                client=self.share_client,
                share_code=config.share_code,
                receive_code=config.share_receive,
                cid=0,
            ),
            False,
        )

    def generate_strm_files_for_configs(self, configs: List[ShareStrmConfig]) -> None:
        """
        按给定分享配置列表生成 STRM

        :param configs (List): 分享 STRM 配置列表
        """
        if not configs:
            return

        for config in configs:
            comment_info = f" ({config.comment})" if config.comment else ""

            if not config.enabled:
                logger.info(f"【分享STRM生成】跳过未启用的配置{comment_info}: {config}")
                continue

            config = ShareStrmHelper.get_share_code(config)

            if not config.share_code or not config.share_receive:
                logger.error(
                    f"【分享STRM生成】缺失分享码或提取码{comment_info}: {config}"
                )
                continue

            logger.info(
                f"【分享STRM生成】开始处理分享配置{comment_info}: "
                f"share_code={config.share_code}, "
                f"share_path={config.share_path}, "
                f"local_path={config.local_path}"
            )
            start_time = perf_counter()

            batch_id = f"{config.share_code}{config.share_receive}"

            # 分享状态校验
            resp = None
            try:
                resp = self.share_client.share_snap_cookie(
                    {
                        "share_code": config.share_code,
                        "receive_code": config.share_receive,
                    }
                )
                check_response(resp)
            except Exception:
                if not resp:
                    e = "访问分享接口失败"
                else:
                    if isinstance(resp, dict):
                        e = resp.get("error", "未知错误")
                        try:
                            if resp.get("error"):
                                delete_result = ShareOOPServerHelper.delete_share_files(
                                    batch_id
                                )
                                logger.info(
                                    f"【分享STRM生成】删除无效分享数据{comment_info}: {delete_result}"
                                )
                        except Exception:
                            pass
                    else:
                        e = str(resp)
                logger.error(f"【分享STRM生成】校验分享状态出错{comment_info}: {e}")
                continue

            data_collector = None
            allow_oop_upload = False
            detailed_data = True
            temp_file = path_join(gettempdir(), f"share_data_{batch_id}.json.gz")
            download_success = ShareOOPServerHelper.download_share_files_data(
                share_code=config.share_code,
                receive_code=config.share_receive,
                temp_file=temp_file,
            )
            if download_success:
                logger.info(f"【分享STRM生成】使用下载的数据生成 STRM{comment_info}")
                data_iter = ShareOOPServerHelper.read_share_files_data_from_file(
                    temp_file
                )
            else:
                logger.info(f"【分享STRM生成】数据不存在，开始在线迭代{comment_info}")
                data_iter, detailed_data = self._create_online_share_iterator(config)
                if detailed_data:
                    data_collector = ShareFilesDataCollector(data_iter, temp_file)
                    data_iter = data_collector
                    allow_oop_upload = True
                else:
                    logger.info(
                        "【分享STRM生成】使用 share_iter_files 简略数据，"
                        f"跳过 OOP 数据收集和上传{comment_info}"
                    )

            logger.info(
                f"【分享STRM生成】数据来源: "
                f"{'OOP 详细数据' if download_success else config.iter_function}, "
                f"detailed_data={detailed_data}, allow_oop_upload={allow_oop_upload}"
            )

            has_exception = False
            try:
                with ThreadPoolExecutor(max_workers=128) as executor:
                    for batch in batched(data_iter, 1_000):
                        self.total_count += len(batch)
                        future_to_item = {
                            executor.submit(
                                self.__process_single_item,
                                item=item,
                                config=config,
                                detailed_data=detailed_data,
                            ): item
                            for item in batch
                        }

                        for future in as_completed(future_to_item):
                            item = future_to_item[future]
                            try:
                                future.result()
                            except Exception as e:
                                has_exception = True
                                sentry_manager.sentry_hub.capture_exception(e)
                                logger.error(
                                    f"【分享STRM生成】并发处理出错: {item} - {str(e)}"
                                )
            except Exception as e:
                has_exception = True
                sentry_manager.sentry_hub.capture_exception(e)
                logger.error(f"【分享STRM生成】处理分享文件时出错{comment_info}: {e}")

            end_time = perf_counter()
            self.elapsed_time += end_time - start_time

            # 数据上传服务器
            def cleanup_temp_file(file_path: str) -> None:
                """
                清理临时数据文件

                :param file_path (str): 临时文件路径
                """
                if path_exists(file_path):
                    try:
                        os_remove(file_path)
                        logger.debug(f"【分享STRM生成】已清理临时文件: {file_path}")
                    except (OSError, TypeError, ValueError):
                        pass

            if has_exception:
                logger.warn(
                    f"【分享STRM生成】处理过程中出现异常，跳过数据上传{comment_info}: share_code={config.share_code}"
                )
                cleanup_temp_file(temp_file)
            elif download_success:
                file_size_mb = path_getsize(temp_file) / 1024 / 1024
                logger.info(
                    f"【分享STRM生成】使用下载数据完成，文件大小: {file_size_mb:.2f} MB{comment_info}"
                )
                cleanup_temp_file(temp_file)
            elif allow_oop_upload and data_collector is not None:
                file_path, data_count = data_collector.get_file_info()
                if data_count > 0:
                    file_size_mb = path_getsize(file_path) / 1024 / 1024
                    logger.info(
                        f"【分享STRM生成】共收集 {data_count} 条数据，文件大小: {file_size_mb:.2f} MB"
                    )
                    upload_result = ShareOOPServerHelper.upload_share_files_data(
                        share_code=config.share_code,
                        receive_code=config.share_receive,
                        temp_file=file_path,
                    )
                    if upload_result:
                        logger.info(
                            f"【分享STRM生成】数据上传成功{comment_info}: share_code={config.share_code}"
                        )
                    else:
                        logger.warn(
                            f"【分享STRM生成】数据上传失败{comment_info}: share_code={config.share_code}"
                        )
                else:
                    logger.debug(
                        f"【分享STRM生成】未收集到数据，跳过上传{comment_info}: share_code={config.share_code}"
                    )
                    cleanup_temp_file(file_path)

            self.scrape_refresh_media(config)

        self._attach_related_media_contexts()

        (
            immediate_downloads,
            queued_count,
            terminal_failures,
        ) = share_audit_download_queue.partition_downloads(self.download_mediainfo_list)

        deferred_paths: Set[str] = set()
        if immediate_downloads:
            (
                self.mediainfo_count,
                self.mediainfo_fail_count,
                self.mediainfo_fail_dict,
            ) = self.mediainfodownloader.batch_auto_share_downloader(
                downloads_list=immediate_downloads
            )
            failed_paths = set(self.mediainfo_fail_dict)
            failed_items = [
                item
                for item in immediate_downloads
                if Path(item["path"]).as_posix() in failed_paths
            ]
            deferred_paths = set(
                share_audit_download_queue.enqueue_failed_auditing_downloads(
                    failed_items
                )
            )
            if deferred_paths:
                self.mediainfo_fail_dict = [
                    path
                    for path in self.mediainfo_fail_dict
                    if path not in deferred_paths
                ]
                self.mediainfo_fail_count = len(self.mediainfo_fail_dict)
                queued_count += len(deferred_paths)
        self.mediainfo_fail_count += len(terminal_failures)
        self.mediainfo_fail_dict.extend(terminal_failures)
        if queued_count:
            logger.info(
                f"【分享STRM生成】{queued_count} 个文件正在审核，已转入后台下载队列"
            )

        for entry in immediate_downloads:
            if not entry.get("mp_transfer_after_download"):
                continue
            path = Path(entry["path"])
            if path.as_posix() in deferred_paths:
                continue
            if path.is_file():
                self.mp_transfer_queue.append(entry)
        if self.mp_transfer_queue:
            self.mp_transfer()

    def generate_strm_files(self) -> None:
        """
        获取分享文件，生成 STRM
        """
        if not configer.share_strm_config:
            return
        self.generate_strm_files_for_configs(list(configer.share_strm_config))

    def get_generate_total(self) -> Tuple[int, int, int, int]:
        """
        输出总共生成文件个数
        """
        if self.strm_fail_dict:
            for path, error in self.strm_fail_dict.items():
                logger.warn(f"【分享STRM生成】{path} 生成错误原因: {error}")

        if self.mediainfo_fail_dict:
            for path in self.mediainfo_fail_dict:
                logger.warn(f"【分享STRM生成】{path} 下载错误")

        logger.info(
            f"【分享STRM生成】分享生成 STRM 文件完成，总共生成 {self.strm_count} 个 STRM 文件，下载 {self.mediainfo_count} 个媒体数据文件"
        )

        if self.strm_fail_count != 0 or self.mediainfo_fail_count != 0:
            logger.warn(
                f"【分享STRM生成】{self.strm_fail_count} 个 STRM 文件生成失败，{self.mediainfo_fail_count} 个媒体数据文件下载失败"
            )

        logger.debug(
            f"【分享STRM生成】时间 {self.elapsed_time:.6f} 秒，总迭代文件数量 {self.total_count}"
        )

        result = (
            self.strm_count,
            self.mediainfo_count,
            self.strm_fail_count,
            self.mediainfo_fail_count,
        )
        kind = self.strm_exec_history_kind
        if kind:
            StrmExecHistoryManager.append_run(
                kind=kind,
                success=True,
                stats={
                    "strm_count": self.strm_count,
                    "mediainfo_count": self.mediainfo_count,
                    "strm_fail_count": self.strm_fail_count,
                    "mediainfo_fail_count": self.mediainfo_fail_count,
                },
                elapsed_sec=float(self.elapsed_time),
                total_iterated=int(self.total_count),
                api_requests=0,
                extra=self.strm_exec_history_extra,
            )
            self.strm_exec_history_kind = None
            self.strm_exec_history_extra = None
        return result


class ShareInteractiveGenStrmQueue:
    """
    分享交互生成 STRM 的 FIFO 队列与后台工作线程
    """

    def __init__(self) -> None:
        self.mediainfodownloader: Optional[MediaInfoDownloader] = None
        self._task_queue: Queue = Queue()
        self._worker_thread: Optional[Thread] = None
        self._worker_lock = Lock()

    def bind_mediainfodownloader(
        self, mediainfodownloader: Optional[MediaInfoDownloader]
    ) -> None:
        """
        绑定媒体信息下载器

        :param mediainfodownloader (MediaInfoDownloader): MediaInfoDownloader 实例，可为 None
        """
        self.mediainfodownloader = mediainfodownloader

    @staticmethod
    def validate_prerequisites() -> Optional[str]:
        """
        校验分享交互生成 STRM 是否可入队

        :return str: 失败时返回 i18n 键名，成功返回 None
        """
        if not configer.enabled:
            return "p115_share_strm_plugin_disabled"
        if not configer.get_config("cookies"):
            return "p115_share_strm_config_error"
        if not configer.get_config("moviepilot_address"):
            return "p115_share_strm_config_error"
        g = configer.share_interactive_gen_strm_config
        if not (g.local_path or "").strip():
            return "p115_share_strm_config_error"
        return None

    def _ensure_worker_running(self) -> None:
        """
        确保工作线程已启动
        """
        with self._worker_lock:
            if self._worker_thread is None or not self._worker_thread.is_alive():
                self._worker_thread = Thread(
                    target=self._process_queue,
                    name="P115ShareInteractiveGenStrm",
                    daemon=True,
                )
                self._worker_thread.start()

    def _process_queue(self) -> None:
        """
        串行消费队列中的任务
        """
        while True:
            try:
                task = self._task_queue.get(timeout=60)
            except Empty:
                logger.debug("【分享交互生成STRM】队列空闲，工作线程退出")
                break
            share_url, channel, source, userid = task
            try:
                self._run_job(
                    share_url=share_url,
                    channel=channel,
                    source=source,
                    userid=userid,
                )
            except Exception as e:
                logger.error(f"【分享交互生成STRM】任务异常: {e}", exc_info=True)
                self._post_user_message(
                    channel=channel,
                    source=source,
                    userid=userid,
                    title=i18n.translate("p115_share_strm_fail_title"),
                    text=i18n.translate("p115_share_strm_fail_text", err=str(e)),
                )
            finally:
                self._task_queue.task_done()
                sleep(2)

    def _post_user_message(
        self,
        channel: Any,
        source: Optional[str],
        userid: Optional[str],
        title: str,
        text: Optional[str] = None,
    ) -> None:
        """
        向触发命令的用户发送消息
        """
        if channel is not None and userid:
            post_message(
                channel=channel,
                source=source,
                title=title,
                text=text,
                userid=userid,
            )

    def _run_job(
        self,
        share_url: str,
        channel: Any,
        source: Optional[str],
        userid: Optional[str],
    ) -> None:
        """
        执行单条分享交互生成 STRM
        """
        err_key = self.validate_prerequisites()
        if err_key:
            self._post_user_message(
                channel=channel,
                source=source,
                userid=userid,
                title=i18n.translate(err_key),
            )
            return

        if not self.mediainfodownloader:
            logger.error("【分享交互生成STRM】MediaInfoDownloader 未初始化")
            self._post_user_message(
                channel=channel,
                source=source,
                userid=userid,
                title=i18n.translate("p115_share_strm_fail_title"),
                text=i18n.translate(
                    "p115_share_strm_fail_text",
                    err="MediaInfoDownloader 未初始化",
                ),
            )
            return

        g = configer.share_interactive_gen_strm_config
        virtual = ShareStrmConfig(
            enabled=True,
            comment="分享交互生成STRM",
            share_link=share_url,
            share_path="/",
            local_path=(g.local_path or "").strip(),
            min_file_size=g.min_file_size,
            auto_download_mediainfo=g.auto_download_mediainfo,
            moviepilot_transfer=g.moviepilot_transfer,
            moviepilot_transfer_download_rmt_audio_sub=(
                g.moviepilot_transfer_download_rmt_audio_sub
            ),
            iter_function=g.iter_function,
            speed_mode=g.speed_mode,
            scrape_metadata=False,
            media_server_refresh=False,
        )

        strm_helper = ShareStrmHelper(mediainfodownloader=self.mediainfodownloader)
        strm_helper.strm_exec_history_kind = "share_interactive"
        strm_helper.strm_exec_history_extra = {"share_url": share_url}
        strm_helper.generate_strm_files_for_configs([virtual])
        strm_count, mediainfo_count, strm_fail_count, mediainfo_fail_count = (
            strm_helper.get_generate_total()
        )

        detail = (
            f"\n📄 生成STRM文件 {strm_count} 个\n"
            f"⬇️ 下载媒体文件 {mediainfo_count} 个\n"
            f"❌ 生成STRM失败 {strm_fail_count} 个\n"
            f"🚫 下载媒体失败 {mediainfo_fail_count} 个"
        )
        self._post_user_message(
            channel=channel,
            source=source,
            userid=userid,
            title=i18n.translate("p115_share_strm_done_title"),
            text=detail,
        )

    def enqueue(
        self,
        share_url: str,
        channel: Any = None,
        source: Optional[str] = None,
        userid: Optional[str] = None,
    ) -> int:
        """
        将任务入队

        :param share_url (str): 115 分享链接
        :param channel (Any): 消息渠道
        :param source (str): 消息来源
        :param userid (str): 用户 ID
        :return int: 入队后队列中等待执行的任务数量
        """
        self._task_queue.put((share_url, channel, source, userid))
        self._ensure_worker_running()
        return self._task_queue.qsize()

    def enqueue_and_notify_user(
        self,
        share_url: str,
        channel: Any = None,
        source: Optional[str] = None,
        userid: Optional[str] = None,
    ) -> int:
        """
        入队并向用户发送排队提示

        :param share_url (str): 115 分享链接
        :param channel (Any): 消息渠道
        :param source (str): 消息来源
        :param userid (str): 用户 ID
        :return int: 入队后队列中等待执行的任务数量
        """
        pending = self.enqueue(
            share_url=share_url,
            channel=channel,
            source=source,
            userid=userid,
        )
        post_message(
            channel=channel,
            source=source,
            title=i18n.translate("p115_share_strm_queued", pending=pending),
            userid=userid,
        )
        return pending
