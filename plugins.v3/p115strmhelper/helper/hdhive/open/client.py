from typing import Any, Literal

from httpx import Client

from app.core.config import settings
from app.utils.http import AsyncRequestUtils

from ....utils.sentry import sentry_manager
from .constants import HDHIVE_OPEN_BASE_URL
from .errors import raise_for_response

MediaType = Literal["movie", "tv"]

VideoResolution = Literal["480P", "720P", "1080P", "2K", "4K", "8K"]
Source = Literal[
    "蓝光原盘/ISO",
    "蓝光原盘/REMUX",
    "BDRip/BluRayEncode",
    "WEB-DL/WEBRip",
    "HDTV/HDTVRip",
]
SubtitleLanguage = Literal[
    "生肉",
    "简中",
    "繁中",
    "简日",
    "繁日",
    "简英",
    "繁英",
    "简韩",
    "繁韩",
    "简日双语",
    "繁日双语",
    "简英双语",
    "繁英双语",
]
SubtitleType = Literal["外挂", "内封", "内嵌"]

_META_PATHS = frozenset({"/ping", "/quota", "/usage", "/usage/today"})


@sentry_manager.capture_all_class_exceptions
class HDHiveOpenClient:
    """
    HDHive Open API 同步客户端

    所有请求携带 ``X-API-Key``；非 meta 接口在 OAuth 模式下还需 ``Authorization: Bearer``
    """

    BASE_URL = HDHIVE_OPEN_BASE_URL

    def __init__(
        self,
        api_key: str = "",
        *,
        access_token: str | None = None,
        timeout: float = 30.0,
        client: Client | None = None,
        defer_client: bool = False,
    ) -> None:
        """
        初始化客户端

        :param api_key (str): OpenAPI 应用 Secret（仅服务端/中转使用）
        :param access_token (str): OAuth 用户 Access Token，非 meta 接口必填
        :param timeout (float): 单次请求超时秒数
        :param client (Client): 可选外部 ``Client``；传入时会合并鉴权头
        :param defer_client (bool): 为 True 时不创建 httpx 客户端（由子类覆写 ``_request``）
        """
        self._api_key = api_key
        self._access_token = access_token
        self._owns_client = False
        self._client: Client | None = client
        if defer_client:
            return
        self._owns_client = client is None
        proxy_h = (
            AsyncRequestUtils._convert_proxies_for_httpx(settings.PROXY)
            if settings.PROXY
            else None
        )
        self._client = client or Client(
            base_url=self.BASE_URL,
            headers={"X-API-Key": api_key},
            timeout=timeout,
            proxy=proxy_h,
        )
        if not self._owns_client and self._client is not None:
            self._client.headers.update({"X-API-Key": api_key})

    def __enter__(self) -> "HDHiveOpenClient":
        """
        进入上下文，返回自身

        :return HDHiveOpenClient: 当前客户端实例
        """
        return self

    def __exit__(self, *_: Any) -> None:
        """
        退出上下文时关闭自有的底层 Client
        """
        self.close()

    def close(self) -> None:
        """
        若构造时未传入外部 Client，则关闭内部持有的 httpx Client
        """
        if self._owns_client and self._client is not None:
            self._client.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        access_token: str | None = None,
    ) -> Any:
        """
        发起请求并解析 JSON，失败时抛出 ``HDHiveAPIError`` 子类

        :param method (str): HTTP 方法
        :param path (str): 相对 ``BASE_URL`` 的路径
        :param params (Dict): 查询参数
        :param json (Any): JSON 请求体
        :param access_token (str): 覆盖实例级 Bearer Token
        :return Tuple: ``(data, meta)`` 元组，与 Open API 响应结构一致
        """
        token = access_token if access_token is not None else self._access_token
        headers: dict[str, str] = {}
        if token and path not in _META_PATHS:
            headers["Authorization"] = f"Bearer {token}"
        if self._client is None:
            raise RuntimeError(
                "HDHiveOpenClient has no httpx client; override _request"
            )
        resp = self._client.request(
            method, path, params=params, json=json, headers=headers or None
        )
        raise_for_response(resp)
        body: dict[str, Any] = resp.json()
        return body.get("data"), body.get("meta")

    def ping(self) -> dict[str, Any]:
        """
        ``GET /ping``：健康检查并校验 API Key

        :return Dict: 响应 ``data`` 字段
        """
        data, _ = self._request("GET", "/ping")
        return data

    def get_quota(self) -> dict[str, Any]:
        """
        ``GET /quota``：查询 API Key 配额信息（meta scope）

        :return Dict: 响应 ``data`` 字段
        """
        data, _ = self._request("GET", "/quota")
        return data

    def get_usage(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        """
        ``GET /usage``：按日期区间查询用量（meta scope）

        :param start_date (str): 起始日期，可选
        :param end_date (str): 结束日期，可选
        :return Dict: 响应 ``data`` 字段
        """
        params: dict[str, Any] = {}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        data, _ = self._request("GET", "/usage", params=params or None)
        return data

    def get_usage_today(self) -> dict[str, Any]:
        """
        ``GET /usage/today``：当日用量统计（meta scope）

        :return Dict: 响应 ``data`` 字段
        """
        data, _ = self._request("GET", "/usage/today")
        return data

    def get_resources(
        self,
        media_type: MediaType,
        tmdb_id: str | int,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """
        ``GET /resources/:type/:tmdb_id``：按 TMDB ID 列出资源（query scope）

        :param media_type (MediaType): ``movie`` 或 ``tv``
        :param tmdb_id (str | int): TMDB 作品 ID
        :return Tuple: ``(data 列表, meta)``，``meta`` 中含 ``total`` 等分页信息
        """
        data, meta = self._request("GET", f"/resources/{media_type}/{tmdb_id}")
        return data or [], meta or {}

    def unlock_resource(self, slug: str) -> dict[str, Any]:
        """
        ``POST /resources/unlock``：消耗积分解锁资源（unlock scope）

        :param slug (str): 资源 slug
        :return Dict: 含 ``url``、``access_code``、``full_url``、``already_owned`` 等字段
        """
        data, _ = self._request("POST", "/resources/unlock", json={"slug": slug})
        return data

    def check_resource(self, url: str) -> dict[str, Any]:
        """
        ``POST /check/resource``：识别网盘类型并从链接解析提取码等（query scope）

        :param url (str): 资源链接
        :return Dict: 含 ``website``、``url``、``base_link``、``access_code`` 等字段
        """
        data, _ = self._request("POST", "/check/resource", json={"url": url})
        return data

    def get_me(self) -> dict[str, Any]:
        """
        ``GET /me``：当前授权用户基础信息（query scope）

        :return Dict: 响应 ``data`` 字段
        """
        data, _ = self._request("GET", "/me")
        return data

    def checkin(self, is_gambler: bool = False) -> dict[str, Any]:
        """
        ``POST /checkin``：每日签到（write scope）

        :param is_gambler (bool): 是否开启赌徒模式（高风险高回报）
        :return Dict: 含 ``checked_in``（bool）、``message``（str）等字段
        """
        body: dict[str, Any] = {}
        if is_gambler:
            body["is_gambler"] = True
        data, _ = self._request("POST", "/checkin", json=body or None)
        return data

    def get_vip_entitlements(self) -> dict[str, Any]:
        """
        ``GET /vip/entitlements``：Premium 用户权益摘要（vip scope）

        :return Dict: 响应 ``data`` 字段
        """
        data, _ = self._request("GET", "/vip/entitlements")
        return data

    def get_vip_weekly_free_quota(self) -> dict[str, Any]:
        """
        ``GET /vip/weekly-free-quota``：永久 VIP 每周免费解锁配额（vip scope）

        :return Dict: 响应 ``data`` 字段
        """
        data, _ = self._request("GET", "/vip/weekly-free-quota")
        return data

    def get_shares(
        self,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """
        ``GET /shares``：分页列出当前用户的分享（write scope）

        :param page (int): 页码
        :param page_size (int): 每页条数
        :return Tuple: ``(data 列表, meta)``，``meta`` 含 ``total``、``page``、``page_size``
        """
        params = {"page": page, "page_size": page_size}
        data, meta = self._request("GET", "/shares", params=params)
        return data or [], meta or {}

    def get_share(self, slug: str) -> dict[str, Any]:
        """
        ``GET /shares/:slug``：按 slug 获取分享详情（query scope）

        :param slug (str): 分享 slug
        :return Dict: 响应 ``data`` 字段
        """
        data, _ = self._request("GET", f"/shares/{slug}")
        return data

    def create_share(
        self,
        url: str,
        *,
        tmdb_id: str | int | None = None,
        media_type: MediaType | None = None,
        movie_id: int | None = None,
        tv_id: int | None = None,
        collection_id: int | None = None,
        title: str | None = None,
        access_code: str | None = None,
        share_size: str | None = None,
        video_resolution: list[VideoResolution] | None = None,
        source: list[Source] | None = None,
        subtitle_language: list[SubtitleLanguage] | None = None,
        subtitle_type: list[SubtitleType] | None = None,
        remark: str | None = None,
        unlock_points: int | None = None,
        is_anonymous: bool = False,
        hide_link: bool = True,
    ) -> dict[str, Any]:
        """
        ``POST /shares``：创建分享（write scope）
        """
        body: dict[str, Any] = {"url": url}
        if tmdb_id is not None:
            body["tmdb_id"] = str(tmdb_id)
        if media_type is not None:
            body["media_type"] = media_type
        if movie_id is not None:
            body["movie_id"] = movie_id
        if tv_id is not None:
            body["tv_id"] = tv_id
        if collection_id is not None:
            body["collection_id"] = collection_id
        if title is not None:
            body["title"] = title
        if access_code is not None:
            body["access_code"] = access_code
        if share_size is not None:
            body["share_size"] = share_size
        if video_resolution is not None:
            body["video_resolution"] = video_resolution
        if source is not None:
            body["source"] = source
        if subtitle_language is not None:
            body["subtitle_language"] = subtitle_language
        if subtitle_type is not None:
            body["subtitle_type"] = subtitle_type
        if remark is not None:
            body["remark"] = remark
        if unlock_points is not None:
            body["unlock_points"] = unlock_points
        body["is_anonymous"] = is_anonymous
        body["hide_link"] = hide_link
        data, _ = self._request("POST", "/shares", json=body)
        return data

    def update_share(
        self,
        slug: str,
        *,
        title: str | None = None,
        url: str | None = None,
        access_code: str | None = None,
        share_size: str | None = None,
        video_resolution: list[VideoResolution] | None = None,
        source: list[Source] | None = None,
        subtitle_language: list[SubtitleLanguage] | None = None,
        subtitle_type: list[SubtitleType] | None = None,
        remark: str | None = None,
        unlock_points: int | None = None,
        is_anonymous: bool | None = None,
        hide_link: bool | None = None,
        notify: bool | None = None,
    ) -> dict[str, Any]:
        """
        ``PATCH /shares/:slug``：部分更新分享（write scope）

        :raises ValueError: 未提供任何可更新字段时
        """
        body: dict[str, Any] = {}
        if title is not None:
            body["title"] = title
        if url is not None:
            body["url"] = url
        if access_code is not None:
            body["access_code"] = access_code
        if share_size is not None:
            body["share_size"] = share_size
        if video_resolution is not None:
            body["video_resolution"] = video_resolution
        if source is not None:
            body["source"] = source
        if subtitle_language is not None:
            body["subtitle_language"] = subtitle_language
        if subtitle_type is not None:
            body["subtitle_type"] = subtitle_type
        if remark is not None:
            body["remark"] = remark
        if unlock_points is not None:
            body["unlock_points"] = unlock_points
        if is_anonymous is not None:
            body["is_anonymous"] = is_anonymous
        if hide_link is not None:
            body["hide_link"] = hide_link
        if notify is not None:
            body["notify"] = notify
        if not body:
            raise ValueError("update_share requires at least one field to update")
        data, _ = self._request("PATCH", f"/shares/{slug}", json=body)
        return data

    def delete_share(self, slug: str) -> None:
        """
        ``DELETE /shares/:slug``：删除分享（write scope）

        :param slug (str): 分享 slug
        """
        self._request("DELETE", f"/shares/{slug}")
