from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Union, Set, Optional

from p115client import P115Client
from p115client.tool.attr import get_attr

from app.chain.storage import StorageChain
from app.sdk.config import settings
from app.sdk.media import MediaInfo
from app.sdk.media import MetaInfoPath
from app.application.directory import DirectoryHelper
from app.sdk.logging import logger
from app.schemas import TransferInfo, FileItem
from app.schemas.types import EventType, ChainEventType, MediaType

from ....core.config import configer
from ....core.scrape import media_scrape_metadata
from ....db_manager.oper import FileDbHelper
from ....helper.mediainfo_download import MediaInfoDownloader
from ....helper.mediaserver import MediaServerRefresh, emby_mediainfo_queue
from ....utils.path import PathUtils
from ....utils.sentry import sentry_manager
from ....utils.strm import StrmUrlGetter
from .postprocess import TransferPostprocessor, event_key, file_identity
from .plan import TransferPlanBuilder, local_path


class TransferStrmHelper:
    """
    持久处理整理完成事件的 STRM、字幕和音轨后处理
    """

    @staticmethod
    def _get_overwrite_mode(storage_name: str, pan_dir_path: str) -> Optional[str]:
        """
        从 MP 媒体库目录配置中读取当前整理任务对应的覆盖模式

        通过比对 library_storage 与 library_path 前缀来定位匹配的目录配置，
        存在多级目录配置时取最长前缀匹配，避免父级配置覆盖子目录配置

        :param storage_name (str): 目标存储名称（如 u115、115网盘Plus）
        :param pan_dir_path (str): 网盘目标目录路径
        :return str: 覆盖模式字符串（always/size/never/latest），匹配失败时返回 None
        """
        try:
            pan_dir_norm = pan_dir_path.rstrip("/") + "/"
            best: Optional[tuple] = None
            for d in DirectoryHelper().get_dirs():
                if d.library_storage == storage_name and d.library_path:
                    lib_norm = d.library_path.rstrip("/") + "/"
                    if pan_dir_norm.startswith(lib_norm):
                        if best is None or len(lib_norm) > len(best[0]):
                            best = (lib_norm, d.overwrite_mode)
            return best[1] if best else None
        except Exception as e:
            logger.debug("【监控整理STRM生成】读取覆盖模式失败: %s", e)
            sentry_manager.sentry_hub.capture_exception(e)
        return None

    def do_generate(
        self,
        client: P115Client,
        item: Dict,
        event_type: Union[EventType, ChainEventType],
        mediainfodownloader: MediaInfoDownloader,
    ) -> None:
        """
        先固定执行计划，再以文件归属和云端现状约束事件重放

        :param client (P115Client): 当前实例的网盘客户端
        :param item (Dict): 宿主整理完成事件
        :param event_type (Union): 主媒体、字幕或音轨完成事件类型
        :param mediainfodownloader (MediaInfoDownloader): 当前实例的下载器

        :raises RuntimeError: 身份无法确认、文件操作或持久检查点失败
        """
        transfer = item.get("transferinfo")
        if isinstance(transfer, dict):
            transfer = TransferInfo(**transfer)
            item = dict(item, transferinfo=transfer)
        if (
            transfer is None
            or transfer.target_item is None
            or transfer.target_diritem is None
        ):
            logger.debug(
                "【监控整理STRM生成】整理结果缺少目标文件或目录信息，跳过 STRM 生成"
            )
            return
        target = transfer.target_item
        processor = TransferPostprocessor()
        key = event_key(item, event_type)
        existing = processor.store.load(key)
        if existing:
            processor.run(
                key,
                existing["plan"]["roots"],
                lambda: existing["plan"],
                lambda plan, staged: self._prepare_file(
                    plan, staged, mediainfodownloader
                ),
                lambda name, plan: self._effect(name, plan, client),
            )
            return
        allowed_storages: Set[str] = {"u115", "115网盘Plus"}
        if configer.transfer_monitor_clouddrive2_enabled:
            allowed_storages.add("CloudDrive储存")
        if target.storage not in allowed_storages:
            return
        matched, local, cloud = PathUtils.get_media_path(
            configer.get_config("transfer_monitor_paths"), transfer.target_diritem.path
        )
        if not matched:
            logger.debug("【监控整理STRM生成】%s 路径匹配不符合，跳过整理", target.name)
            return
        logger.debug("【监控整理STRM生成】匹配到网盘文件夹路径: %s", str(cloud))
        suffix = Path(target.name).suffix.lower().lstrip(".")
        media_exts = [str(ext).lower().lstrip(".") for ext in settings.RMT_MEDIAEXT]
        download_exts = {
            str(ext).lower().lstrip(".")
            for ext in settings.RMT_SUBEXT + settings.RMT_AUDIOEXT
        }
        download = event_type in {
            EventType.AudioTransferComplete,
            EventType.SubtitleTransferComplete,
        }
        if not download and StorageChain().is_bluray_folder(target):
            logger.warning(
                "【监控整理STRM生成】%s 为蓝光原盘，不支持生成 STRM 文件: %s",
                target.name,
                target.path,
            )
            return
        if (
            not download
            and event_type == EventType.TransferComplete
            and suffix
            and suffix not in media_exts
        ):
            if suffix not in download_exts:
                logger.warning(
                    "【监控整理STRM生成】%s 非媒体文件（.%s），跳过 STRM 生成",
                    target.name,
                    suffix,
                )
                return
            logger.warning(
                "【监控整理STRM生成】%s 为字幕/音频文件，自动走下载流程", target.name
            )
            download = True
        pickcode = target.pickcode
        if not pickcode and target.storage == "CloudDrive储存":
            try:
                pickcode = client.to_pickcode(int(target.fileid))
            except Exception as error:
                logger.error(
                    "【监控整理STRM生成】CloudDrive2 储存 %s 无法转换获取 PickCode 值: %s",
                    target.name,
                    error,
                    exc_info=True,
                )
                return
        if not pickcode:
            action = "下载该文件" if download else "生成 STRM 文件"
            logger.error(
                "【监控整理STRM生成】%s 不存在 pickcode 值，无法%s", target.name, action
            )
            return
        if not download and (len(pickcode) != 17 or not pickcode.isalnum()):
            logger.error(
                "【监控整理STRM生成】错误的 pickcode 值 %s，无法生成 STRM 文件",
                target.name,
            )
            return
        roots = sorted(
            {
                str(Path(line.split("#", 2)[0]).resolve())
                for line in configer.transfer_monitor_paths.splitlines()
                if "#" in line
            }
        )

        def build() -> Dict[str, Any]:
            builder = TransferPlanBuilder(processor.store, roots)
            identity = file_identity(target)
            try:
                output = local_path(local, cloud, target.path, not download)
                operation = builder.operation(output, "write", identity, [])
            except Exception as error:
                logger.error(
                    "【监控整理STRM生成】规划本地文件失败: %s, %s",
                    target.path,
                    error,
                    exc_info=True,
                )
                raise
            options = {
                name: deepcopy(configer.get_config(name))
                for name in (
                    "transfer_monitor_scrape_metadata_enabled",
                    "transfer_monitor_scrape_metadata_exclude_paths",
                    "transfer_monitor_media_server_refresh_enabled",
                    "transfer_mp_mediaserver_paths",
                    "transfer_monitor_mediaservers",
                    "transfer_monitor_media_server_refresh_delay",
                    "transfer_monitor_emby_mediainfo_enabled",
                    "native_emby_mediainfo_enabled",
                )
            }
            effects = {}
            if target.storage != "CloudDrive储存":
                effects["index"] = False
            if not download:
                try:
                    builder.build_cleanup(
                        transfer,
                        output,
                        self._get_overwrite_mode(
                            target.storage, transfer.target_diritem.path
                        )
                        == "latest",
                    )
                except Exception as error:
                    logger.error(
                        "【监控整理STRM生成】扫描旧版本 STRM 或重新整理清理文件失败: %s",
                        error,
                        exc_info=True,
                    )
                    raise
                if options["transfer_monitor_scrape_metadata_enabled"]:
                    if options[
                        "transfer_monitor_scrape_metadata_exclude_paths"
                    ] and PathUtils.get_scrape_metadata_exclude_path(
                        options["transfer_monitor_scrape_metadata_exclude_paths"],
                        str(output),
                    ):
                        logger.debug(
                            "【监控整理STRM生成】匹配到刮削排除目录，不进行刮削: %s",
                            str(output),
                        )
                    else:
                        effects["scrape"] = False
                if options["transfer_monitor_media_server_refresh_enabled"]:
                    effects["refresh"] = False
                if options["transfer_monitor_emby_mediainfo_enabled"]:
                    effects["mediainfo"] = False
            media = item.get("mediainfo")
            meta = item.get("meta")
            return {
                "identity": identity,
                "roots": roots,
                "kind": "download" if download else "strm",
                "pickcode": pickcode,
                "name": target.name,
                "target": target.model_dump(mode="json"),
                "url": None
                if download
                else StrmUrlGetter().get_strm_url(pickcode, target.name, target.path),
                "operations": [operation, *builder.operations.values()],
                "directories": builder.directories,
                "effects": effects,
                "options": options,
                "media": media.to_dict() if media else None,
                "meta": meta.to_dict() if meta else None,
            }

        processor.run(
            key,
            roots,
            build,
            lambda plan, staged: self._prepare_file(plan, staged, mediainfodownloader),
            lambda name, plan: self._effect(name, plan, client),
        )

    @staticmethod
    def _prepare_file(
        plan: Dict[str, Any], staged: Path, downloader: MediaInfoDownloader
    ) -> None:
        """
        将固定的 STRM 内容或完整字幕音轨下载到暂存文件
        """
        if plan["kind"] == "strm":
            staged.write_text(plan["url"], encoding="utf-8")
            return
        url = downloader.get_download_url(pickcode=plan["pickcode"])
        if not url:
            logger.error(
                "【监控整理STRM生成】%s 下载链接获取失败，无法下载该文件", plan["name"]
            )
            raise RuntimeError(f"{plan['name']} 下载链接获取失败")
        if not downloader.save_mediainfo_file(
            file_path=staged, file_name=plan["name"], download_url=url
        ):
            raise RuntimeError(f"{plan['name']} 媒体信息文件保存失败")

    @staticmethod
    def _effect(name: str, plan: Dict[str, Any], client: P115Client) -> None:
        """
        按固定配置提交索引、刮削、刷新及媒体信息任务
        """
        path = plan["operations"][0]["path"]
        options = plan["options"]
        media = None
        if plan["media"]:
            media = MediaInfo()
            media.from_dict(deepcopy(plan["media"]))
        meta = None
        if plan["meta"]:
            meta = MetaInfoPath(Path(plan["name"]), force_video=True)
            for key, value in plan["meta"].items():
                if key == "type" and value:
                    meta.type = MediaType(value)
                elif key not in {"season_episode", "edition", "name", "episode_list"}:
                    setattr(meta, key, value)
        if name == "index":
            target = FileItem(**plan["target"])
            if not target.fileid:
                target.fileid = str(client.to_id(plan["pickcode"]))
            helper = FileDbHelper()
            helper.upsert_batch(helper.process_fileitem(target))
        elif name == "scrape":
            media_scrape_metadata(
                path=path, item_name=plan["name"], mediainfo=media, meta=meta
            )
        elif name == "refresh":
            if not MediaServerRefresh(
                func_name="【监控整理STRM生成】",
                enabled=True,
                mp_mediaserver=options["transfer_mp_mediaserver_paths"],
                mediaservers=options["transfer_monitor_mediaservers"],
                delay_seconds=options["transfer_monitor_media_server_refresh_delay"],
            ).refresh_mediaserver(
                file_name=plan["name"], file_path=path, mediainfo=media
            ):
                raise RuntimeError("整理后处理媒体服务器刷新失败，等待重试")
        elif name == "mediainfo":
            attributes = {}
            if not options["native_emby_mediainfo_enabled"]:
                data = get_attr(
                    client=client,
                    id=plan["pickcode"],
                    skim=True,
                    **configer.get_ios_ua_app(app=False),
                )
                attributes = {"sha1": data["sha1"], "size": data["size"]}
            if not emby_mediainfo_queue.enqueue(
                func_name="【监控整理STRM生成】",
                path=Path(path),
                mp_mediaserver=options["transfer_mp_mediaserver_paths"],
                mediaservers=options["transfer_monitor_mediaservers"],
                **attributes,
            ):
                raise RuntimeError("整理后处理媒体信息任务入队失败")
