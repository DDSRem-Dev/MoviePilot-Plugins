from typing import List, Dict

import httpx

from app.log import logger
from app.core.config import settings

from .framework.registry import command_registry, view_registry
from .framework.callbacks import Action
from .framework.handler import BaseActionHandler
from .session import Session
from ..core.config import configer
from ..core.message import post_message
from ..core.i18n import i18n
from ..helper.hdhive.browser import (
    HDHiveError,
    HDHiveLoginError,
    get_hdhive_browser_client,
)
from ..helper.search import HDHiveSearch
from ..helper.strm import ShareInteractiveGenStrmQueue
from ..service import servicer

command_registry.clear()


class ActionHandler(BaseActionHandler):
    """
    动作处理器
    处理用户的动作请求，并执行相应的业务逻辑
    """

    @command_registry.command(name="go_to", code="gt")
    def handle_go_to(self, session: Session, action: Action):
        """
        处理跳转到指定视图的操作
        """
        if action.view:
            if view_registry.get_by_name(action.view):
                session.go_to(action.view)
                if action.view == "search":
                    # 如果跳转到 start 视图，重置业务逻辑
                    session.business = session.business.__class__()
            else:
                raise ValueError(f"未知视图 '{action.view}'，跳转失败。")

    @command_registry.command(name="go_back", code="gb")
    def handle_go_back(self, session: Session, action: Action):
        """
        处理返回操作
        """
        if action.view:
            if view_registry.get_by_name(action.view):
                session.go_back(action.view)
                if action.view == "search":
                    # 如果返回到 start 视图，重置业务逻辑
                    session.business = session.business.__class__()
            else:
                logger.warning(f"未知视图 '{action.view}'，尝试返回失败。")
                raise ValueError(f"未知视图 '{action.view}'，返回失败。")

    @command_registry.command(name="page_next", code="pn")
    def handle_page_next(self, session: Session, _: Action):
        """
        处理下一页操作
        """
        session.page_next()

    @command_registry.command(name="page_prev", code="pp")
    def handle_page_prev(self, session: Session, _: Action):
        """
        处理上一页操作
        """
        session.page_prev()

    @command_registry.command(name="close", code="cl")
    def handle_closed(self, session: Session, _: Action):
        """
        处理关闭操作
        """
        session.view.name = "close"

    @command_registry.command(name="refresh", code="rf")
    def handle_refresh(self, session: Session, _: Action):
        """
        处理刷新操作
        """
        session.refresh_view()

    @command_registry.command(name="share_recieve_path", code="srp")
    def handle_share_recieve_path(self, session: Session, action: Action):
        """
        处理分享目录选择操作
        """
        session.business.share_recieve_path = None
        session.business.share_recieve_url = action.value

    @command_registry.command(name="share_intent_transfer", code="sit")
    def handle_share_intent_transfer(self, session: Session, action: Action):
        """
        分享链接意图：走分享转存
        """
        url = session.business.share_recieve_url
        if not url:
            return [
                {
                    "type": "error_message",
                    "text": i18n.translate("p115_share_link_intent_missing_url"),
                }
            ]
        paths = configer.share_recieve_paths or []
        try:
            if len(paths) <= 1:
                pan_path = paths[0] if paths else None
                servicer.sharetransferhelper.add_share(
                    url=url,
                    channel=session.message.channel,
                    source=session.message.source,
                    userid=session.message.userid,
                    pan_path=pan_path,
                )
                session.view.name = "close"
            else:
                session.business.share_recieve_path = None
                session.business.share_recieve_url = url
                session.go_to("share_recieve_paths")
        except Exception as e:
            logger.error(
                f"处理 share_intent_transfer 失败: url={url}, error={e}",
                exc_info=True,
            )
            session.go_to("start")
            return [
                {
                    "type": "error_message",
                    "text": i18n.translate("p115_share_link_intent_transfer_error"),
                }
            ]
        return None

    @command_registry.command(name="share_intent_strm", code="sis")
    def handle_share_intent_strm(self, session: Session, action: Action):
        """
        分享链接意图：走分享交互生成 STRM
        """
        u115 = session.business.share_strm_u115_url
        if not u115:
            return [
                {
                    "type": "error_message",
                    "text": i18n.translate("p115_share_link_intent_strm_unavailable"),
                }
            ]
        err_key = ShareInteractiveGenStrmQueue.validate_prerequisites()
        if err_key:
            return [
                {
                    "type": "error_message",
                    "text": i18n.translate(err_key),
                }
            ]
        try:
            servicer.share_interactive_gen_strm_queue.enqueue_and_notify_user(
                share_url=u115,
                channel=session.message.channel,
                source=session.message.source,
                userid=session.message.userid,
            )
            session.view.name = "close"
        except Exception as e:
            logger.error(
                f"处理 share_intent_strm 失败: url={u115}, error={e}",
                exc_info=True,
            )
            session.go_to("start")
            return [
                {
                    "type": "error_message",
                    "text": i18n.translate("p115_share_link_intent_strm_error"),
                }
            ]
        return None

    @command_registry.command(name="share_recieve", code="dsr")
    def handle_share_recieve(self, session: Session, action: Action):
        """
        处理分享转存操作
        """
        try:
            if action.value is None:
                raise ValueError("value 不能为空。")
            # 索引号
            item_index = int(action.value)
            if 0 <= item_index < len(configer.share_recieve_paths):
                path = configer.share_recieve_paths[item_index]
                servicer.sharetransferhelper.add_share(
                    url=session.business.share_recieve_url,
                    channel=session.message.channel,
                    source=session.message.source,
                    userid=session.message.userid,
                    pan_path=path,
                )
                session.view.name = "close"
            else:
                raise IndexError("索引超出范围。")
        except (ValueError, IndexError, TypeError) as e:
            logger.error(
                f"处理 share_recieve 失败: value={action.value}, error={e}",
                exc_info=True,
            )
            session.go_to("start")
            return [
                {"type": "error_message", "text": "处理分享转存时发生错误，请重试。"}
            ]
        return None

    @command_registry.command(name="offline_download_path", code="odp")
    def handle_offline_download_path(self, session: Session, action: Action):
        """
        处理离线下载目录选择操作
        """
        session.business.offline_download_path = None
        session.business.offline_download_urls = action.value

    @command_registry.command(name="offline_download", code="dod")
    def handle_offline_download(self, session: Session, action: Action):
        """
        处理离线下载操作
        """
        try:
            if action.value is None:
                raise ValueError("value 不能为空。")
            # 索引号
            item_index = int(action.value)
            if 0 <= item_index < len(configer.offline_download_paths):
                path = configer.offline_download_paths[item_index]
                session.view.name = "close"
                # 选择目录为整理目录则进行网盘整理，否则只添加离线下载任务
                url_list = session.business.offline_download_urls
                if (
                    path in configer.pan_transfer_paths
                    and configer.pan_transfer_enabled
                ):
                    ok, added_count = servicer.offlinehelper.add_urls_to_transfer(
                        url_list
                    )
                else:
                    ok, added_count = servicer.offlinehelper.add_urls_to_path(
                        url_list, path
                    )
                if ok:
                    post_message(
                        channel=session.message.channel,
                        source=session.message.source,
                        title=i18n.translate(
                            "p115_add_offline_success", count=added_count
                        ),
                        userid=session.message.userid,
                    )
                else:
                    post_message(
                        channel=session.message.channel,
                        source=session.message.source,
                        title=i18n.translate("p115_add_offline_fail"),
                        userid=session.message.userid,
                    )
            else:
                raise IndexError("索引超出范围。")
        except (ValueError, IndexError, TypeError) as e:
            logger.error(
                f"处理 offline_download 失败: value={action.value}, error={e}",
                exc_info=True,
            )
            session.go_to("start")
            return [
                {"type": "error_message", "text": "处理离线下载时发生错误，请重试。"}
            ]
        return None

    @command_registry.command(name="search", code="sr")
    def handle_search(self, session: Session, action: Action):
        """
        处理搜索操作
        """
        if action.value is None:
            raise ValueError("搜索关键词不能为空。")
        search_keyword = action.value.strip()
        session.business.search_keyword = search_keyword

    @command_registry.command(name="resource", code="rs")
    def handle_resource(self, session: Session, action: Action):
        """
        处理资源操作
        """
        if action.value is None:
            raise ValueError("搜索关键词不能为空。")
        resource_key = action.value
        session.business.resource_key = resource_key
        session.view.refresh = True
        session.go_to("resource_list")

    @command_registry.command(name="subscribe", code="sb")
    def handle_select_subscribe(
        self, session: Session, action: Action
    ) -> List[Dict] | None:
        """
        处理选中资源的操作
        """
        try:
            if action.value is None:
                raise ValueError("value 不能为空。")
            # 索引号
            item_index = int(action.value)
            # 全部搜索数据
            search_data = session.business.resource_info.get("data", [])

            if not search_data:
                raise ValueError("当前没有可用的资源。")
            if 0 <= item_index < len(search_data):
                data = search_data[item_index]
                share_url = ""
                if data.get("source") == HDHiveSearch.SOURCE or data.get("hdhive_slug"):
                    slug = data.get("hdhive_slug")
                    if not slug:
                        raise ValueError("HDHive 资源 slug 无效")
                    try:
                        pw_client = get_hdhive_browser_client()
                        if pw_client is None:
                            raise HDHiveLoginError("未配置 HDHive 账号密码")
                        unlocked = pw_client.unlock_resource(str(slug))
                        logger.info("HDHive 浏览器解锁成功: %s", unlocked)
                        share_url = (unlocked.get("full_url") or "").strip()
                    except HDHiveError as e:
                        logger.error(
                            "HDHive 解锁失败: slug=%s, error=%s",
                            slug,
                            e,
                            exc_info=True,
                        )
                        session.go_to("subscribe_fail")
                        return None
                else:
                    share_url = (data.get("shareurl") or "").strip()
                if not share_url:
                    raise ValueError("没有可用的分享链接")
                base = configer.get_config("moviepilot_address").rstrip("/")
                resp = httpx.get(
                    f"{base}/api/v1/plugin/P115StrmHelper/add_transfer_share",
                    params={
                        "apikey": settings.API_TOKEN,
                        "share_url": share_url,
                    },
                    timeout=httpx.Timeout(
                        connect=30.0,
                        read=900.0,
                        write=30.0,
                        pool=30.0,
                    ),
                )
                if resp.json().get("code") == 0:
                    session.go_to("subscribe_success")
                else:
                    logger.error(f"subscribe 请求失败: {resp.json()}")
                    session.go_to("subscribe_fail")
            else:
                raise IndexError("索引超出范围。")
        except (ValueError, IndexError, TypeError) as e:
            logger.error(
                f"处理 subscribe 失败: value={action.value}, error={e}", exc_info=True
            )
            session.go_to("start")
            return [{"type": "error_message", "text": "选择资源时发生错误，请重试。"}]
        return None
