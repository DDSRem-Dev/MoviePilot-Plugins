import math
from datetime import datetime
from typing import Dict, Any, Tuple, Optional, List

from app.schemas.message import ChannelCapabilityManager

from ..helper.search import HDHiveSearch, MediaSearcher, TgSearcher
from ..core.i18n import i18n
from .framework.callbacks import Action
from .framework.registry import view_registry
from .framework.views import BaseViewRenderer
from .session import Session
from ..utils.string import StringUtils
from ..core.config import configer

view_registry.clear()


class ViewRenderer(BaseViewRenderer):
    """
    视图渲染器
    """

    @staticmethod
    def __now_date() -> str:
        """
        返回当前时间的字符串表示
        """
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def __get_paged_items_and_start_index(session: Session, page_size: int, data):
        """
        通用 - 获取当前页码的数据项

        """
        session.view.total_pages = math.ceil(len(data) / page_size)

        if session.view.page >= session.view.total_pages > 0:
            session.view.page = session.view.total_pages - 1

        start_index = session.view.page * page_size
        paged_items = data[start_index : start_index + page_size]
        return paged_items, start_index

    @staticmethod
    def __get_page_size(session: Session) -> Tuple[int, int]:
        """
        通用 - 获取当前页面的大小，决定每页显示多少个下按钮
        """
        max_buttons_per_row = ChannelCapabilityManager.get_max_buttons_per_row(
            session.message.channel
        )
        max_total_button_rows = ChannelCapabilityManager.get_max_button_rows(
            session.message.channel
        )

        # 决定本页要显示的下载器按钮行数
        if max_total_button_rows >= 4:
            button_rows = 2
        else:
            button_rows = 1

        page_size = button_rows * max_buttons_per_row
        return page_size, max_buttons_per_row

    def get_page_switch_buttons(self, session: Session) -> List[Dict[str, Any]]:
        """
        构建分页切换按钮
        """
        page_nav = []
        if session.view.page > 0:
            page_nav.append(
                self._build_button(session, "◀️ 上一页", Action(command="page_prev"))
            )
        if session.view.page < session.view.total_pages - 1:
            page_nav.append(
                self._build_button(session, "▶️ 下一页", Action(command="page_next"))
            )
        return page_nav

    def get_navigation_buttons(
        self,
        session: Session,
        go_back: Optional[str] = None,
        refresh: bool = False,
        close: bool = False,
    ) -> list:
        """
        获取导航按钮，包含返回、刷新和关闭按钮
        """
        nav_buttons = []
        if go_back:
            nav_buttons.append(self._build_common_go_back_button(session, view=go_back))
        if refresh:
            nav_buttons.append(self._build_common_refresh_button(session))
        if close:
            nav_buttons.append(self._build_common_close_button(session))
        return nav_buttons

    def get_search_data(self, session: Session):
        """
        获取搜索数据
        """
        keyword = (session.business.search_keyword or "").strip()
        if not keyword:
            session.business.search_info = {
                "data": [],
                "datatime": self.__now_date(),
                "fetch_error": False,
            }
            return
        try:
            count = 100
            data = MediaSearcher.search_like_api(keyword, count=count)
            session.business.search_info = {
                "data": data,
                "datatime": self.__now_date(),
                "fetch_error": False,
            }
        except Exception:
            session.business.search_info = {
                "data": [],
                "datatime": self.__now_date(),
                "fetch_error": True,
            }

    def get_resource_data(self, session: Session):
        """
        获取资源数据
        """
        resource_dict = session.business.resource_key_list[
            int(session.business.resource_key)
        ]

        data: List[Dict[str, Any]] = []
        if configer.tg_search_channels:
            searcher = TgSearcher()
            data.extend(
                searcher.search(
                    key=resource_dict.get("name"),
                    channels=configer.tg_search_channels,
                )
            )
        if configer.hdhive_search_enabled:
            data.extend(HDHiveSearch.fetch_resources(resource_dict))

        # 记录到session，待渲染使用
        session.business.resource_info = {"data": data, "datatime": self.__now_date()}

    @view_registry.view(name="share_recieve_paths", code="srps")
    def render_share_recieve_paths(self, session: Session) -> Dict:
        """
        渲染分享目录选择器
        """
        title, buttons, text_lines = (
            "分享转存目录列表",
            [],
            ["请选择您要转存的目录：\n"],
        )

        # 获取频道能力，是否渲染按钮
        supports_buttons = ChannelCapabilityManager.supports_buttons(
            session.message.channel
        )
        # 最大行数，每行最大按钮数
        page_size, max_buttons_per_row = self.__get_page_size(session=session)
        # 当前页的数据，当前页的索引起点
        paged_items, start_index = self.__get_paged_items_and_start_index(
            session=session, page_size=page_size, data=configer.share_recieve_paths
        )

        button_row = []

        for i, path in enumerate(paged_items):
            original_index = configer.share_recieve_paths.index(path)

            text_lines.append(
                f"{StringUtils.to_emoji_number(start_index + i + 1)}. {path}"
            )

            # 支持按钮时，生成按钮
            if supports_buttons:
                button_row.append(
                    self._build_button(
                        session,
                        text=StringUtils.to_emoji_number(start_index + i + 1),
                        action=Action(command="share_recieve", value=original_index),
                    )
                )

                # 如果当前行已满，添加到按钮列表
                if len(button_row) == max_buttons_per_row:
                    buttons.append(button_row)
                    button_row = []

        if button_row:
            buttons.append(button_row)

        text_lines.append(
            f"\n页码: {session.view.page + 1} / {session.view.total_pages}"
        )
        text_lines.append(f"\n数据刷新时间：{self.__now_date()}")

        # 添加分页行
        if page_nav := self.get_page_switch_buttons(session):
            buttons.append(page_nav)

        text = "\n".join(text_lines)
        # 添加刷新与关闭行
        buttons.append(self.get_navigation_buttons(session, refresh=True, close=True))

        return {"title": title, "text": text, "buttons": buttons}

    @view_registry.view(name="share_link_intent", code="sli")
    def render_share_link_intent(self, session: Session) -> Dict:
        """
        渲染分享链接意图选择（转存 / 分享交互生成 STRM）
        """
        title = i18n.translate("p115_share_link_intent_title")
        link_preview = (session.business.share_recieve_url or "").strip()
        text_lines = [
            "",
            i18n.translate("p115_share_link_intent_text"),
            "",
            link_preview,
        ]
        buttons: List = []
        supports_buttons = ChannelCapabilityManager.supports_buttons(
            session.message.channel
        )
        if supports_buttons:
            buttons.append(
                [
                    self._build_button(
                        session,
                        text=i18n.translate("p115_share_link_intent_btn_transfer"),
                        action=Action(command="share_intent_transfer"),
                    ),
                    self._build_button(
                        session,
                        text=i18n.translate("p115_share_link_intent_btn_strm"),
                        action=Action(command="share_intent_strm"),
                    ),
                ]
            )
        else:
            text_lines.append("")
            text_lines.append(i18n.translate("p115_share_link_intent_no_buttons_hint"))
        buttons.append(self.get_navigation_buttons(session, close=True))
        text = "\n".join(text_lines)
        return {"title": title, "text": text, "buttons": buttons}

    @view_registry.view(name="offline_download_paths", code="odps")
    def render_offline_download_paths(self, session: Session) -> Dict:
        """
        渲染离线下载目录选择器
        """
        title, buttons, text_lines = (
            "离线下载目录列表",
            [],
            ["请选择您要下载到的目录：\n"],
        )

        # 获取频道能力，是否渲染按钮
        supports_buttons = ChannelCapabilityManager.supports_buttons(
            session.message.channel
        )
        # 最大行数，每行最大按钮数
        page_size, max_buttons_per_row = self.__get_page_size(session=session)
        # 当前页的数据，当前页的索引起点
        paged_items, start_index = self.__get_paged_items_and_start_index(
            session=session, page_size=page_size, data=configer.offline_download_paths
        )

        button_row = []

        for i, path in enumerate(paged_items):
            original_index = configer.offline_download_paths.index(path)

            text_lines.append(
                f"{StringUtils.to_emoji_number(start_index + i + 1)}. {path}"
            )

            # 支持按钮时，生成按钮
            if supports_buttons:
                button_row.append(
                    self._build_button(
                        session,
                        text=StringUtils.to_emoji_number(start_index + i + 1),
                        action=Action(command="offline_download", value=original_index),
                    )
                )

                # 如果当前行已满，添加到按钮列表
                if len(button_row) == max_buttons_per_row:
                    buttons.append(button_row)
                    button_row = []

        if button_row:
            buttons.append(button_row)

        text_lines.append(
            f"\n页码: {session.view.page + 1} / {session.view.total_pages}"
        )
        text_lines.append(f"\n数据刷新时间：{self.__now_date()}")

        # 添加分页行
        if page_nav := self.get_page_switch_buttons(session):
            buttons.append(page_nav)

        text = "\n".join(text_lines)
        # 添加刷新与关闭行
        buttons.append(self.get_navigation_buttons(session, refresh=True, close=True))

        return {"title": title, "text": text, "buttons": buttons}

    @view_registry.view(name="search_list", code="shl")
    def render_search_list(self, session: Session) -> Dict:
        """
        渲染搜索
        """
        title, buttons, text_lines = "搜索列表", [], ["请选择要搜索的影视条目：\n"]

        if not session.business.search_info or session.view.refresh:
            self.get_search_data(session=session)
            session.view.refresh = False

        search_info = session.business.search_info or {}
        if search_info.get("fetch_error"):
            text = i18n.translate("p115_media_search_failed")
            buttons.append(
                self.get_navigation_buttons(session, refresh=True, close=True)
            )
            return {"title": title, "text": text, "buttons": buttons}

        if not search_info:
            text = i18n.translate("p115_media_search_empty")
            buttons.append(
                self.get_navigation_buttons(session, refresh=True, close=True)
            )
            return {"title": title, "text": text, "buttons": buttons}

        search_data = search_info.get("data", [])
        if not search_data:
            text = i18n.translate("p115_media_search_empty")
            buttons.append(
                self.get_navigation_buttons(session, refresh=True, close=True)
            )
            return {"title": title, "text": text, "buttons": buttons}

        supports_buttons = ChannelCapabilityManager.supports_buttons(
            session.message.channel
        )
        page_size, max_buttons_per_row = self.__get_page_size(session=session)
        paged_items, start_index = self.__get_paged_items_and_start_index(
            session=session, page_size=page_size, data=search_data
        )

        button_row = []
        session.business.resource_key_list = []
        for i, item in enumerate(paged_items):
            if not isinstance(item, dict):
                continue
            media_type = item.get("type")
            line = StringUtils.format_sh_search_media_line(start_index + i + 1, item)
            text_lines.append(line)

            if supports_buttons:
                button_row.append(
                    self._build_button(
                        session,
                        text=StringUtils.to_emoji_number(start_index + i + 1),
                        action=Action(
                            command="resource",
                            view="resource_list",
                            value=i,
                        ),
                    )
                )

                session.business.resource_key_list.append(
                    {
                        "type": media_type,
                        "tmdb_id": item.get("tmdb_id"),
                        "name": (item.get("title") or "").strip(),
                    }
                )

                if len(button_row) == max_buttons_per_row:
                    buttons.append(button_row)
                    button_row = []

        if button_row:
            buttons.append(button_row)

        text_lines.append(
            f"\n页码: {session.view.page + 1} / {session.view.total_pages}"
        )
        text_lines.append(
            f"\n数据刷新时间：{session.business.search_info.get('datatime', self.__now_date())}"
        )

        if page_nav := self.get_page_switch_buttons(session):
            buttons.append(page_nav)

        text = "\n".join(text_lines)
        buttons.append(self.get_navigation_buttons(session, refresh=True, close=True))

        return {"title": title, "text": text, "buttons": buttons}

    @view_registry.view(name="resource_list", code="rsl")
    def render_resource_list(self, session: Session) -> Dict:
        """
        渲染资源
        """
        title, buttons, text_lines = "资源列表", [], ["请选择转存的资源：\n"]

        if not session.business.resource_info or session.view.refresh:
            self.get_resource_data(session=session)
            session.view.refresh = False

        if not (resource_info := session.business.resource_info):
            text = "当前没有搜索结果。"
            buttons.append(
                self.get_navigation_buttons(session, refresh=True, close=True)
            )
            return {
                "title": title,
                "text": text,
                "buttons": buttons,
                "disable_web_page_preview": True,
            }

        else:
            resource_data = resource_info.get("data", [])
            # 获取频道能力，是否渲染按钮
            supports_buttons = ChannelCapabilityManager.supports_buttons(
                session.message.channel
            )
            # 最大行数，每行最大按钮数
            page_size, max_buttons_per_row = self.__get_page_size(session=session)
            # 当前页的数据，当前页的索引起点
            paged_items, start_index = self.__get_paged_items_and_start_index(
                session=session, page_size=page_size, data=resource_data
            )

            button_row = []
            for i, data in enumerate(paged_items):
                original_index = resource_data.index(data)
                num_prefix = f"{StringUtils.to_emoji_number(start_index + i + 1)}. "
                if data.get("source") == HDHiveSearch.SOURCE:
                    text_lines.append(HDHiveSearch.format_list_block(data, num_prefix))
                else:
                    label = data.get("taskname", "未知名称")
                    ch_name = (data.get("channel_name") or "").strip()
                    display = f"【{ch_name}】{label}" if ch_name else label
                    share_url = (data.get("shareurl") or "").strip()
                    if share_url:
                        display = f"{display} [🔗 链接]({share_url})"
                    text_lines.append(f"{num_prefix}{display}")

                # 支持按钮时，生成按钮
                if supports_buttons:
                    button_row.append(
                        self._build_button(
                            session,
                            text=StringUtils.to_emoji_number(start_index + i + 1),
                            action=Action(command="subscribe", value=original_index),
                        )
                    )

                    # 如果当前行已满，添加到按钮列表
                    if len(button_row) == max_buttons_per_row:
                        buttons.append(button_row)
                        button_row = []

            if button_row:
                buttons.append(button_row)

            text_lines.append(
                f"\n页码: {session.view.page + 1} / {session.view.total_pages}"
            )
            text_lines.append(
                f"\n数据刷新时间：{session.business.resource_info.get('datatime', self.__now_date())}"
            )

            # 添加分页行
            if page_nav := self.get_page_switch_buttons(session):
                buttons.append(page_nav)

        text = "\n".join(text_lines)
        buttons.append(
            self.get_navigation_buttons(
                session, go_back="search_list", refresh=True, close=True
            )
        )

        return {
            "title": title,
            "text": text,
            "buttons": buttons,
            "disable_web_page_preview": True,
        }

    @view_registry.view(name="subscribe_success", code="ss")
    def render_subscribe_success(self, _: Session) -> Dict:
        """
        渲染转存成功视图
        """
        title = "✅ 转存成功"
        text = "您的转存请求已成功处理。"
        buttons = []
        return {"title": title, "text": text, "buttons": buttons}

    @view_registry.view(name="subscribe_fail", code="sf")
    def render_subscribe_fail(self, session: Session) -> Dict:
        """
        渲染转存失败视图
        """
        title = "❌ 转存失败"
        text = "您的转存请求处理失败，请稍后重试。"
        buttons = [
            self.get_navigation_buttons(session, go_back="resource_list", close=True)
        ]
        return {"title": title, "text": text, "buttons": buttons}

    @view_registry.view(name="close", code="cl")
    def render_close(self, session: Session) -> Dict:
        """
        渲染转存失败视图
        """
        title = "❌ 关闭页面"
        text = ""
        buttons = []
        return {"title": title, "text": text, "buttons": buttons}
