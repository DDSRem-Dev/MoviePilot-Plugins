from asyncio import Lock, create_task, gather, get_event_loop, to_thread, wait_for
from contextlib import asynccontextmanager
from re import compile as re_compile
from time import monotonic
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote, urlparse

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from httpx import (
    AsyncClient,
    Limits,
)
from starlette.requests import ClientDisconnect
from websockets import connect

from app.sdk.logging import logger

# 直链解析结果缓存 TTL（秒）：缓存的是 STRM 内部地址/规则替换结果（稳定中间地址），可长缓存
REDIRECT_URL_CACHE_TTL_SECONDS = 900
# Part 路径缓存 TTL（秒）：来自元数据 API 的 Part.key -> file 映射
PART_INFO_CACHE_TTL_SECONDS = 3600
# 直链缓存最大条目数
REDIRECT_URL_CACHE_MAX_SIZE = 500
# Part 路径缓存最大条目数
PART_INFO_CACHE_MAX_SIZE = 2000
# 详情页预热：响应中 Part 数不超过该值时才触发 STRM 预热（避免整库列表触发风暴）
PREWARM_MAX_PARTS = 5
# 热路径（起播关键路径）上游请求超时（秒）：收敛以避免拖慢起播
HOT_PATH_TIMEOUT_SECONDS = 5.0

# 非关键路径前缀：上游连接失败时静默降级为 DEBUG 日志（客户端高频轮询，失败无碍）
SILENT_FAIL_PATH_PREFIXES = (
    "/photo/:/transcode",
    "/hubs",
    "/statistics",
    "/updater",
    "/media/providers",
    "/:/prefs",
)

# 播前补全：同一 ratingKey 补全冷却时间（秒），避免反复播放同一条目重复写
# 播前补全：同步等待补全完成的最长时间（秒），超时后放行播放、补全转后台继续
PREPLAY_WAIT_BUDGET_SECONDS = 3.0
# playQueues 请求 uri 参数中的条目 ratingKey 提取
_PLAYQUEUE_KEY_RE = re_compile(r"(?:library%2Fmetadata%2F|library/metadata/)(\d+)")

# Plex Token 的可能来源
PLEX_TOKEN_QUERY_KEY = "X-Plex-Token"
PLEX_TOKEN_HEADER_KEY = "x-plex-token"

# 逐跳头，转发时剔除
HOP_BY_HOP_HEADERS = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
    }
)

# 需要拦截并缓存 Part 信息的元数据 API 路径前缀
METADATA_PATH_PREFIXES = (
    "/library/metadata/",
    "/library/sections/",
    "/hubs",
    "/playQueues",
    "/status/sessions",
)


def create_app(
    plex_host: str,
    plex_token: str = "",
    pin_rules: List[Tuple[str, str]] | None = None,
    force_direct_play: bool = True,
    preplay_cooldown_seconds: int = 600,
    on_pre_play: Optional[Callable[[str], Any]] = None,
) -> FastAPI:
    """
    创建 Plex 302 反向代理 FastAPI 应用

    :param plex_host (str): Plex 服务器根地址，如 http://192.168.1.100:32400
    :param plex_token (str): 备用 X-Plex-Token；请求自带 token 时优先使用请求中的
    :param pin_rules (List): 顶置路径规则列表 (路径前缀, 目标URL)；命中时先替换再 302
    :param force_direct_play (bool): 是否在 decision 请求中强制 DirectPlay，避免转码使 302 失效
    :param on_pre_play (Callable): 播前补全回调，参数为 ratingKey，同步阻塞执行；
        在 playQueues 创建（含继续观看直接起播）时先补全该条目媒体流信息再放行

    :return FastAPI: 配置好的 FastAPI 应用实例
    """
    plex_host = plex_host.rstrip("/")
    pin_rules = pin_rules or []

    def _extract_token(request: Request) -> str:
        """
        从请求中提取 X-Plex-Token，优先级：查询参数 → 请求头 → 插件配置兜底

        :param request: 当前请求
        :return: token 字符串，可能为空串
        """
        token = request.query_params.get(PLEX_TOKEN_QUERY_KEY)
        if token:
            return token
        token = request.headers.get(PLEX_TOKEN_HEADER_KEY)
        if token:
            return token
        return plex_token or ""

    def _build_forward_headers(request: Request) -> Dict[str, str]:
        """
        构建转发请求头，排除 host 和逐跳头

        :param request: 当前请求
        :return: 用于转发的请求头字典
        """
        return {
            k: v
            for k, v in request.headers.items()
            if k.lower() not in HOP_BY_HOP_HEADERS and k.lower() != "host"
        }

    def _strip_accept_encoding(headers: Dict[str, str]) -> Dict[str, str]:
        """
        去掉 Accept-Encoding，便于上游返回未压缩内容以便修改 body

        :param headers: 原始转发头
        :return: 不包含 accept-encoding 的头字典
        """
        return {k: v for k, v in headers.items() if k.lower() != "accept-encoding"}

    def _apply_pin_rules(url_or_path: str, rules: List[Tuple[str, str]]) -> str:
        """
        对文件路径（本地路径或 URL）应用顶置规则：匹配前缀则替换为目标 URL

        :param url_or_path: 完整 URL 或路径字符串
        :param rules: 顶置规则列表 (路径前缀, 目标URL)
        :return: 替换后的 URL，未命中则返回原串
        """
        if not url_or_path or not rules:
            return url_or_path
        path_component: str
        original_query: str = ""
        if url_or_path.startswith(("http://", "https://")):
            parsed = urlparse(url_or_path)
            path_component = parsed.path or "/"
            original_query = parsed.query or ""
        else:
            path_component = (
                url_or_path if url_or_path.startswith("/") else "/" + url_or_path
            )
        for path_prefix, target_url in rules:
            if path_component != path_prefix and not path_component.startswith(
                path_prefix + "/"
            ):
                continue
            suffix = path_component[len(path_prefix):].lstrip("/")
            base = target_url.rstrip("/")
            new_url = base + ("/" + quote(suffix, safe="/") if suffix else "")
            if original_query:
                new_url += "?" + original_query
            return new_url
        return url_or_path

    def _is_http_media_path(path: str) -> bool:
        """
        判断文件路径是否为可 302 的远程地址（STRM 内容或规则替换结果）

        :param path: 文件路径或 URL
        :return: 是 HTTP/HTTPS 地址时为 True
        """
        return isinstance(path, str) and path.startswith(("http://", "https://"))

    async def _read_request_body_safe(request: Request) -> bytes | None:
        """
        读取请求体；客户端已断开时返回 None，避免 ClientDisconnect 导致 500

        :param request: 当前请求
        :return: 请求体字节串，或 None 表示客户端已断开
        """
        try:
            return await request.body()
        except ClientDisconnect:
            logger.debug(
                "客户端已断开: %s %s",
                request.method,
                request.scope.get("path", ""),
            )
            return None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """
        FastAPI 生命周期管理器：创建共享 httpx 客户端及缓存，关闭时清理资源
        """
        limits = Limits(max_keepalive_connections=50, keepalive_expiry=60.0)
        app.state.http_client_follow = AsyncClient(follow_redirects=True, limits=limits)
        app.state.http_client_no_follow = AsyncClient(
            follow_redirects=False, limits=limits
        )
        # part_key(如 /library/parts/1/2/file) -> (file_path, expiry)
        app.state.part_info_cache = {}
        app.state.part_rating_cache = {}
        # part_path -> (strm_content_url, expiry)
        app.state.strm_content_cache = {}
        app.state.part_info_lock = Lock()
        # (part_key, header_hash) -> (final_url, expiry)
        app.state.redirect_url_cache = {}
        app.state.redirect_cache_order = []
        app.state.redirect_cache_lock = Lock()
        # 单飞合并：part_path -> Future[str]，并发相同请求共享一次解析
        app.state.inflight_redirects = {}
        app.state.inflight_lock = Lock()
        yield
        await app.state.http_client_follow.aclose()
        await app.state.http_client_no_follow.aclose()

    app = FastAPI(lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ---------- Part 路径缓存 ----------

    async def _cache_part_info(
        request: Request, part_key: str, file_path: str, rating_key: str = ""
    ) -> None:
        """
        缓存 Part.key -> 文件路径映射，供后续播放请求直接使用

        :param request: 当前请求
        :param part_key: Part 的 key，如 /library/parts/123/456/file
        :param file_path: 媒体文件的真实路径
        """
        if not part_key or not file_path:
            return
        cache = request.app.state.part_info_cache
        async with request.app.state.part_info_lock:
            if len(cache) >= PART_INFO_CACHE_MAX_SIZE:
                now = monotonic()
                expired = [k for k, v in cache.items() if v[1] < now]
                for k in expired:
                    cache.pop(k, None)
                while len(cache) >= PART_INFO_CACHE_MAX_SIZE:
                    cache.pop(next(iter(cache)), None)
            # part_key 可能带查询参数，只取 path 部分
            key = part_key.split("?", 1)[0]
            cache[key] = (file_path, monotonic() + PART_INFO_CACHE_TTL_SECONDS)
            if rating_key:
                request.app.state.part_rating_cache[key] = (
                    str(rating_key), monotonic() + PART_INFO_CACHE_TTL_SECONDS
                )

    async def _get_cached_part_path(request: Request, part_key: str) -> str:
        """
        查询 Part 路径缓存

        :param request: 当前请求
        :param part_key: Part 的 key（请求路径）
        :return: 命中的文件路径，未命中返回空串
        """
        cache = request.app.state.part_info_cache
        async with request.app.state.part_info_lock:
            entry = cache.get(part_key)
            if not entry:
                return ""
            file_path, expiry = entry
            if monotonic() >= expiry:
                cache.pop(part_key, None)
                return ""
            return file_path

    async def _get_cached_part_rating_key(request: Request, part_key: str) -> str:
        """读取 Part 对应的条目 ratingKey，供直接文件起播时补全兜底。"""
        cache = request.app.state.part_rating_cache
        async with request.app.state.part_info_lock:
            entry = cache.get(part_key)
            if not entry:
                return ""
            rating_key, expiry = entry
            if monotonic() >= expiry:
                cache.pop(part_key, None)
                return ""
            return str(rating_key)

    def _extract_parts_from_json(data: Any) -> List[Tuple[str, str, str]]:
        """
        从 Plex JSON 响应的 MediaContainer 中抽取所有 Part 的 (key, file) 对

        :param data: Plex API JSON 响应
        :return: (part_key, file_path) 列表
        """
        result: List[Tuple[str, str, str]] = []
        if not isinstance(data, dict):
            return result
        container = data.get("MediaContainer")
        if not isinstance(container, dict):
            return result
        metadata_arr: List[dict] = []
        hubs = container.get("Hub")
        if isinstance(hubs, list):
            for hub in hubs:
                if isinstance(hub, dict) and isinstance(hub.get("Metadata"), list):
                    metadata_arr.extend(
                        m for m in hub["Metadata"] if isinstance(m, dict)
                    )
        if isinstance(container.get("Metadata"), list):
            metadata_arr.extend(
                m for m in container["Metadata"] if isinstance(m, dict)
            )
        for metadata in metadata_arr:
            rating_key = str(metadata.get("ratingKey") or "")
            media_list = metadata.get("Media")
            if not isinstance(media_list, list):
                continue
            for media in media_list:
                if not isinstance(media, dict):
                    continue
                parts = media.get("Part")
                if not isinstance(parts, list):
                    continue
                for part in parts:
                    if not isinstance(part, dict):
                        continue
                    key = part.get("key")
                    file_path = part.get("file")
                    if isinstance(key, str) and isinstance(file_path, str):
                        result.append((key, file_path, rating_key))
        return result

    def _extract_parts_from_xml(text: str) -> List[Tuple[str, str, str]]:
        """
        从 Plex XML 响应中抽取所有 Part 的 (key, file) 对

        :param text: XML 文本
        :return: (part_key, file_path) 列表
        """
        from xml.etree import ElementTree

        result: List[Tuple[str, str, str]] = []
        try:
            root = ElementTree.fromstring(text)
        except ElementTree.ParseError:
            return result
        for metadata in root.iter():
            rating_key = metadata.get("ratingKey") or ""
            if not rating_key:
                continue
            for part in metadata.iter("Part"):
                key = part.get("key")
                file_path = part.get("file")
                if key and file_path:
                    result.append((key, file_path, str(rating_key)))
        return result

    async def _harvest_parts_from_response(
        request: Request, content_type: str, body: bytes
    ) -> int:
        """
        从元数据类响应中解析并缓存所有 Part 信息

        :param request: 当前请求
        :param content_type: 响应 Content-Type
        :param body: 响应体字节串
        :return: 缓存的 Part 数量
        """
        pairs: List[Tuple[str, str, str]] = []
        try:
            if "application/json" in content_type:
                from json import loads

                pairs = _extract_parts_from_json(loads(body))
            elif "xml" in content_type:
                pairs = _extract_parts_from_xml(body.decode("utf-8", errors="replace"))
        except Exception:
            logger.debug("解析元数据响应失败，跳过 Part 缓存", exc_info=True)
            return 0
        for key, file_path, rating_key in pairs:
            await _cache_part_info(request, key, file_path, rating_key)
        # 单集详情页（Part 数少）时后台预热 STRM 解析，正式播放可直接命中缓存
        if 0 < len(pairs) <= PREWARM_MAX_PARTS:
            for key, file_path, _rating_key in pairs:
                if file_path.lower().endswith(".strm"):
                    create_task(
                        _prewarm_strm(request, key.split("?", 1)[0])
                    )
        return len(pairs)

    async def _prewarm_strm(request: Request, part_path: str) -> None:
        """
        后台预热：提前解析 STRM 内容并写入缓存，失败静默

        :param request: 触发预热的元数据请求（借用其 token 与共享客户端）
        :param part_path: Part 的 key 路径
        """
        try:
            url = await _resolve_strm_content(request, part_path)
            if url:
                logger.debug("STRM 预热完成: %s", part_path)
        except Exception:
            logger.debug("STRM 预热失败: %s", part_path, exc_info=True)

    # ---------- Plex API 查询 ----------

    async def _fetch_plex_file_path(request: Request, part_path: str) -> str:
        """
        通过 Plex API 查询播放路径对应媒体文件的真实路径

        先查 Part 缓存；未命中时回退调用 /library/parts 对应的 metadata 无法直接反查，
        改为向 Plex 发起带 Accept: application/json 的条目查询

        :param request: 当前请求
        :param part_path: 播放请求路径，如 /library/parts/123/456/file
        :return: 文件真实路径，失败返回空串
        """
        cached = await _get_cached_part_path(request, part_path)
        if cached:
            logger.debug("Part 路径缓存命中: %s", part_path)
            return cached
        token = _extract_token(request)
        if not token:
            logger.warning("无 X-Plex-Token，无法查询 Plex API: %s", part_path)
            return ""
        # /library/parts/{part_id}/{ts}/file 无法直接反查条目，
        # 使用 HEAD download 请求获取重定向或文件名后再搜索的方式成本高，
        # 这里通过 Plex 的 parts 端点尝试直接查询
        client = request.app.state.http_client_follow
        # 从路径中提取 part_id
        segments = [s for s in part_path.split("/") if s]
        part_id = ""
        if len(segments) >= 3 and segments[0] == "library" and segments[1] == "parts":
            part_id = segments[2]
        if not part_id:
            return ""
        url = f"{plex_host}/library/parts/{part_id}?X-Plex-Token={quote(token, safe='')}"
        try:
            resp = await client.get(
                url,
                headers={"Accept": "application/json"},
                timeout=HOT_PATH_TIMEOUT_SECONDS,
            )
            if resp.status_code == 200:
                pairs = _extract_parts_from_json(resp.json())
                for key, file_path, rating_key in pairs:
                    await _cache_part_info(request, key, file_path, rating_key)
                    if key.split("?", 1)[0] == part_path:
                        return file_path
                if pairs:
                    return pairs[0][1]
        except Exception:
            logger.debug("Plex parts API 查询失败: %s", url, exc_info=True)
        return ""

    async def _resolve_strm_content(request: Request, part_path: str) -> str:
        """
        通过 Plex download 接口 HEAD 请求解析 STRM 文件内容指向的远程地址

        Plex 对 .strm 的 download 请求会返回 30x Location 指向文件内实际地址；
        解析结果按 part_path 缓存，跨客户端复用

        :param request: 当前请求
        :param part_path: 播放请求路径
        :return: STRM 指向的远程 URL，失败返回空串
        """
        strm_cache = request.app.state.strm_content_cache
        entry = strm_cache.get(part_path)
        if entry:
            content, expiry = entry
            if monotonic() < expiry:
                logger.debug("STRM 内容缓存命中: %s", part_path)
                return content
            strm_cache.pop(part_path, None)
        token = _extract_token(request)
        if not token:
            return ""
        url = f"{plex_host}{part_path}?download=1&X-Plex-Token={quote(token, safe='')}"
        client = request.app.state.http_client_no_follow
        try:
            resp = await client.head(url, timeout=HOT_PATH_TIMEOUT_SECONDS)
            if 300 < resp.status_code < 309:
                location = resp.headers.get("location", "")
                if location and not location.startswith(plex_host):
                    if len(strm_cache) >= PART_INFO_CACHE_MAX_SIZE:
                        now = monotonic()
                        for k in [
                            k for k, v in strm_cache.items() if v[1] < now
                        ]:
                            strm_cache.pop(k, None)
                        while len(strm_cache) >= PART_INFO_CACHE_MAX_SIZE:
                            strm_cache.pop(next(iter(strm_cache)), None)
                    strm_cache[part_path] = (
                        location,
                        monotonic() + PART_INFO_CACHE_TTL_SECONDS,
                    )
                    return location
        except Exception:
            logger.debug("STRM 内容解析失败: %s", part_path, exc_info=True)
        return ""

    # ---------- 302 重定向核心 ----------

    async def _try_redirect(request: Request) -> RedirectResponse | None:
        """
        尝试对播放/下载请求返回 302 直链重定向

        优先级：直链缓存 → 单飞合并解析（Part 文件路径 → 顶置规则/STRM）

        并发相同 part 的请求（客户端起播常见的重试/多连接）通过单飞合并，
        只触发一次上游解析，其余请求等待同一结果，避免起播被重复解析拖慢。

        :param request: 当前请求
        :return: 302 重定向响应，或 None 表示回退到反向代理
        """
        part_path = request.scope.get("path", "")

        # 缓存的是稳定中间地址（与客户端无关），仅按路径缓存以提高跨客户端命中率
        cache_key = part_path
        cache = request.app.state.redirect_url_cache
        order = request.app.state.redirect_cache_order
        lock = request.app.state.redirect_cache_lock

        async with lock:
            entry = cache.get(cache_key)
            if entry:
                final_url, expiry = entry
                if monotonic() < expiry:
                    logger.debug("直链缓存命中: %s", part_path)
                    return RedirectResponse(url=final_url, status_code=302)
                cache.pop(cache_key, None)
                try:
                    order.remove(cache_key)
                except ValueError:
                    pass

        # 单飞合并：相同 part_path 的并发解析只执行一次
        inflight = request.app.state.inflight_redirects
        inflight_lock = request.app.state.inflight_lock
        owner = False
        async with inflight_lock:
            fut = inflight.get(part_path)
            if fut is None:
                fut = get_event_loop().create_future()
                inflight[part_path] = fut
                owner = True

        if not owner:
            logger.debug("等待单飞解析: %s", part_path)
            http_url = await fut
        else:
            try:
                http_url = await _resolve_redirect_url(request, part_path)
            except Exception:
                logger.debug("解析直链异常: %s", part_path, exc_info=True)
                http_url = ""
            finally:
                async with inflight_lock:
                    inflight.pop(part_path, None)
                if not fut.done():
                    fut.set_result(http_url)

        if not http_url:
            return None

        # 直接 302 到中间地址（STRM 内部 redirect_url 或规则替换结果），
        # 由客户端自行跟随后续跳转，避免服务端预解析引入延迟
        final_url = http_url

        async with lock:
            now = monotonic()
            expired = [k for k in order if cache.get(k) and cache[k][1] < now]
            for k in expired:
                cache.pop(k, None)
            order[:] = [k for k in order if k not in frozenset(expired)]
            while len(cache) >= REDIRECT_URL_CACHE_MAX_SIZE and order:
                cache.pop(order.pop(0), None)
            cache[cache_key] = (final_url, now + REDIRECT_URL_CACHE_TTL_SECONDS)
            order.append(cache_key)

        logger.info("302 重定向: %s -> %s", part_path, final_url)
        return RedirectResponse(url=final_url, status_code=302)

    async def _resolve_redirect_url(request: Request, part_path: str) -> str:
        """
        解析播放请求对应的可 302 远程地址（不含缓存/单飞逻辑）

        :param request: 当前请求
        :param part_path: 播放请求路径
        :return: 可 302 的 HTTP(S) 地址，无法解析返回空串
        """
        file_path = await _fetch_plex_file_path(request, part_path)
        http_url = ""
        if file_path:
            replaced = _apply_pin_rules(file_path, pin_rules)
            if _is_http_media_path(replaced):
                http_url = replaced
            elif file_path.lower().endswith(".strm"):
                strm_url = await _resolve_strm_content(request, part_path)
                if strm_url:
                    strm_replaced = _apply_pin_rules(strm_url, pin_rules)
                    http_url = (
                        strm_replaced
                        if _is_http_media_path(strm_replaced)
                        else strm_url
                    )
        else:
            # 无法拿到文件路径时，仍尝试 STRM 解析（Plex 会自己 30x）
            strm_url = await _resolve_strm_content(request, part_path)
            if strm_url:
                strm_replaced = _apply_pin_rules(strm_url, pin_rules)
                if _is_http_media_path(strm_replaced):
                    http_url = strm_replaced
        return http_url

    async def _handle_stream(request: Request, part_id: str, file_id: str = ""):
        """
        处理播放/下载流路由：尝试 302，失败则走通用反向代理

        :param request: 当前请求
        :param part_id: Part ID
        :param file_id: 文件时间戳段（由路由匹配）
        :return: 重定向或反代响应
        """
        logger.info("播放请求: %s", request.scope.get("path", ""))
        part_path = request.scope.get("path", "")
        rating_key = await _get_cached_part_rating_key(request, part_path)
        if not rating_key:
            await _fetch_plex_file_path(request, part_path)
            rating_key = await _get_cached_part_rating_key(request, part_path)
        if rating_key:
            await _maybe_pre_play_complete(rating_key)
        resp = await _try_redirect(request)
        if resp:
            return resp
        logger.info("302 未命中，回退反代: %s", request.scope.get("path", ""))
        return await _reverse_proxy(request)

    for _route in (
        "/library/parts/{part_id}/{file_id}/file",
        "/library/parts/{part_id}/file",
    ):
        app.api_route(_route, methods=["GET", "HEAD"], response_model=None)(
            _handle_stream
        )

    # ---------- 转码决策：强制 DirectPlay ----------

    async def _handle_transcode_decision(request: Request):
        """
        代理 /video/:/transcode/universal/decision：
        当媒体文件为远程直链（STRM/规则命中）时强制 DirectPlay，
        避免 Plex 走转码使 302 直链失效

        :param request: 当前请求
        :return: 透传或改参后的响应
        """
        if not force_direct_play:
            return await _reverse_proxy(request)
        logger.info("转码决策请求: %s", str(request.url.query)[:200])
        # 改写查询参数强制直接播放
        query = dict(request.query_params)
        query["directPlay"] = "1"
        query["directStream"] = "1"
        path = request.scope.get("path", "/")
        qs = "&".join(f"{quote(k, safe='')}={quote(str(v), safe='')}" for k, v in query.items())
        target_url = f"{plex_host}{path}?{qs}"
        headers = _build_forward_headers(request)
        client = request.app.state.http_client_no_follow
        try:
            resp = await client.request(
                request.method, target_url, headers=headers, timeout=30.0
            )
        except Exception:
            logger.warning("转码决策请求失败: %s", target_url, exc_info=True)
            return await _reverse_proxy(request)
        excluded = HOP_BY_HOP_HEADERS | {"content-encoding", "content-length"}
        resp_headers = {
            k: v for k, v in resp.headers.multi_items() if k.lower() not in excluded
        }
        # 顺带缓存决策响应中的 Part 信息
        ct = (resp.headers.get("content-type") or "").lower()
        if resp.status_code == 200:
            count = await _harvest_parts_from_response(request, ct, resp.content)
            if count:
                logger.debug("转码决策响应缓存 Part: %s 条", count)
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            headers=resp_headers,
        )

    app.api_route(
        "/video/:/transcode/universal/decision",
        methods=["GET", "HEAD"],
        response_model=None,
    )(_handle_transcode_decision)

    # 转码播放起始请求也尝试 302（对应 plex2Alist 的 VideoTranscodePlay）
    async def _handle_transcode_start(request: Request):
        """
        处理 /video/:/transcode/universal/start：
        客户端明确要求转码(directPlay=0)时透传，否则尝试按 path 参数解析并 302

        :param request: 当前请求
        :return: 重定向或反代响应
        """
        if request.query_params.get("directPlay") == "0" and not force_direct_play:
            return await _reverse_proxy(request)
        logger.info(
            "转码起始请求: %s path=%s",
            request.scope.get("path", ""),
            request.query_params.get("path", ""),
        )
        # start 请求带 path=/library/metadata/{id} 参数，查询条目拿文件路径
        meta_path = request.query_params.get("path", "")
        token = _extract_token(request)
        if meta_path and token:
            client = request.app.state.http_client_follow
            url = f"{plex_host}{meta_path}?X-Plex-Token={quote(token, safe='')}"
            try:
                resp = await client.get(
                    url, headers={"Accept": "application/json"}, timeout=10
                )
                if resp.status_code == 200:
                    pairs = _extract_parts_from_json(resp.json())
                    media_index = int(request.query_params.get("mediaIndex") or 0)
                    part_index = int(request.query_params.get("partIndex") or 0)
                    idx = media_index + part_index
                    pair = (
                        pairs[idx]
                        if 0 <= idx < len(pairs)
                        else (pairs[0] if pairs else None)
                    )
                    if pair:
                        part_key, file_path, rating_key = pair
                        await _cache_part_info(request, part_key, file_path, rating_key)
                        http_url = ""
                        replaced = _apply_pin_rules(file_path, pin_rules)
                        if _is_http_media_path(replaced):
                            http_url = replaced
                        elif file_path.lower().endswith(".strm"):
                            # STRM：通过 download 接口解析内部地址
                            strm_url = await _resolve_strm_content(
                                request, part_key.split("?", 1)[0]
                            )
                            if strm_url:
                                strm_replaced = _apply_pin_rules(strm_url, pin_rules)
                                http_url = (
                                    strm_replaced
                                    if _is_http_media_path(strm_replaced)
                                    else strm_url
                                )
                        if http_url:
                            logger.info(
                                "302 重定向(转码起始): %s -> %s", meta_path, http_url
                            )
                            return RedirectResponse(url=http_url, status_code=302)
            except Exception:
                logger.debug("转码起始解析失败: %s", meta_path, exc_info=True)
        logger.info("转码起始未命中 302，回退反代: %s", meta_path)
        return await _reverse_proxy(request)

    for _start_route in (
        "/video/:/transcode/universal/start",
        "/video/:/transcode/universal/start.mpd",
        "/video/:/transcode/universal/start.m3u8",
    ):
        app.api_route(
            _start_route,
            methods=["GET", "HEAD"],
            response_model=None,
        )(_handle_transcode_start)

    # ---------- 播前补全（继续观看点击即播场景） ----------

    # ratingKey -> 上次播前补全的单调时间戳
    _preplay_recent: Dict[str, float] = {}
    _preplay_lock = Lock()

    async def _maybe_pre_play_complete(rating_key: str) -> None:
        """
        播前补全：在放行播放请求前，同步等待补全该条目媒体流信息。

        带冷却窗口去重；等待预算内没完成就放行播放，补全在后台线程继续，
        绝不为写库阻塞起播超过 PREPLAY_WAIT_BUDGET_SECONDS。

        :param rating_key: 即将播放条目的 ratingKey
        """
        if on_pre_play is None or not rating_key:
            return
        now = monotonic()
        async with _preplay_lock:
            last = _preplay_recent.get(rating_key)
            if last is not None and now - last < preplay_cooldown_seconds:
                return
            _preplay_recent[rating_key] = now
            # 顺带清理过期记录
            expired = [
                k for k, ts in _preplay_recent.items()
                if now - ts > preplay_cooldown_seconds
            ]
            for k in expired:
                if k != rating_key:
                    _preplay_recent.pop(k, None)
        try:
            await wait_for(
                to_thread(on_pre_play, rating_key),
                timeout=PREPLAY_WAIT_BUDGET_SECONDS,
            )
            logger.info("播前补全完成: ratingKey=%s", rating_key)
        except TimeoutError:
            # to_thread 里的补全线程会继续跑完（写库仍生效），只是不再阻塞起播
            logger.info(
                "播前补全超过 %ss 预算，先放行播放（补全后台继续）: ratingKey=%s",
                PREPLAY_WAIT_BUDGET_SECONDS, rating_key,
            )
        except Exception as exc:
            logger.debug("播前补全异常 ratingKey=%s: %s", rating_key, exc)

    def _extract_rating_key_from_playqueue(request: Request) -> str:
        """
        从 playQueues 创建请求中提取目标条目 ratingKey。

        「继续观看」点击即播时，客户端会 POST /playQueues，
        uri 参数形如 server://xxx/com.plexapp.plugins.library/library/metadata/123。

        :param request: 当前请求
        :return: ratingKey，取不到返回空串
        """
        try:
            uri = request.query_params.get("uri") or ""
            key = request.query_params.get("key") or ""
            m = _PLAYQUEUE_KEY_RE.search(key) or _PLAYQUEUE_KEY_RE.search(uri)
            return m.group(1) if m else ""
        except Exception:
            return ""

    async def _playqueue_proxy(request: Request):
        """
        代理 playQueues 创建：先尝试播前补全目标条目媒体流信息，再转发。

        覆盖「继续观看」点击即播（不经过详情页）的场景；补全带预算超时，
        不会明显拖慢起播。

        :param request: 当前请求
        :return: 上游响应
        """
        if request.method == "POST":
            rating_key = _extract_rating_key_from_playqueue(request)
            if rating_key:
                await _maybe_pre_play_complete(rating_key)
        return await _metadata_proxy(request)

    # ---------- 元数据 API：缓存 Part 信息 ----------

    async def _metadata_proxy(request: Request):
        """
        代理元数据类 API，整包拉取响应并抽取缓存 Part.key -> file 映射

        :param request: 当前请求
        :return: 上游响应（原样透传）
        """
        path = request.scope.get("path", "/")
        qs = str(request.url.query)
        target_url = f"{plex_host}{path}"
        if qs:
            target_url += f"?{qs}"
        headers = _strip_accept_encoding(_build_forward_headers(request))
        body = await _read_request_body_safe(request)
        if body is None:
            return Response(status_code=204, content=b"")
        client = request.app.state.http_client_no_follow
        try:
            resp = await client.request(
                request.method,
                target_url,
                headers=headers,
                content=body if body else None,
                timeout=60.0,
            )
        except Exception:
            logger.warning("元数据请求失败: %s", target_url, exc_info=True)
            return JSONResponse(
                status_code=502,
                content={
                    "error": "Bad Gateway",
                    "detail": f"无法连接到 Plex 服务器: {plex_host}",
                },
            )
        ct = (resp.headers.get("content-type") or "").lower()
        if resp.status_code == 200 and request.method == "GET":
            count = await _harvest_parts_from_response(request, ct, resp.content)
            if count:
                logger.debug("元数据响应缓存 Part: path=%s, %s 条", path, count)
        excluded = HOP_BY_HOP_HEADERS | {"content-encoding", "content-length"}
        resp_headers = {
            k: v for k, v in resp.headers.multi_items() if k.lower() not in excluded
        }
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            headers=resp_headers,
        )

    for _meta_route in (
        "/library/metadata/{item_id}",
        "/library/metadata/{item_id}/children",
        "/library/sections/{section_id}/all",
        "/playQueues/{queue_id}",
        "/status/sessions",
    ):
        app.api_route(_meta_route, methods=["GET", "POST"], response_model=None)(
            _metadata_proxy
        )

    # playQueues 创建单独走播前补全代理（继续观看点击即播场景）
    app.api_route("/playQueues", methods=["GET", "POST"], response_model=None)(
        _playqueue_proxy
    )

    # ---------- WebSocket 代理 ----------

    async def _ws_proxy(ws_client: WebSocket) -> None:
        """
        双向代理客户端 WebSocket 与 Plex 后端 WebSocket

        :param ws_client: 客户端 WebSocket 连接
        """
        await ws_client.accept()
        parsed = urlparse(plex_host)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        path = ws_client.scope.get("path", "/:/websockets/notifications")
        qs = str(ws_client.scope.get("query_string", b""), "utf-8")
        backend_url = f"{scheme}://{parsed.netloc}{path}"
        if qs:
            backend_url += f"?{qs}"
        try:
            async with connect(backend_url) as ws_backend:

                async def client_to_backend() -> None:
                    """
                    WebSocket 客户端→后端：转发客户端文本消息到后端
                    """
                    try:
                        while True:
                            data = await ws_client.receive_text()
                            await ws_backend.send(data)
                    except WebSocketDisconnect:
                        pass

                async def backend_to_client() -> None:
                    """
                    WebSocket 后端→客户端：转发后端消息到客户端
                    """
                    try:
                        async for msg in ws_backend:
                            if isinstance(msg, str):
                                await ws_client.send_text(msg)
                            else:
                                await ws_client.send_bytes(msg)
                    except Exception as e:
                        logger.debug("WebSocket 后端->客户端 结束: %s", e)

                await gather(client_to_backend(), backend_to_client())
        except Exception:
            logger.warning("WebSocket 代理异常", exc_info=True)
        finally:
            try:
                await ws_client.close()
            except Exception as e:
                logger.debug("关闭客户端 WebSocket 时异常: %s", e)

    app.websocket("/:/websockets/notifications")(_ws_proxy)
    app.websocket("/:/eventsource/notifications")(_ws_proxy)

    # ---------- 通用反向代理与兜底 ----------

    async def _reverse_proxy(request: Request):
        """
        将请求反向代理到 Plex 服务器并流式返回响应

        :param request: 当前请求
        :return: 流式响应或 502 JSON 错误
        """
        path = request.scope.get("path", "/")
        qs = str(request.url.query)
        target_url = f"{plex_host}{path}"
        if qs:
            target_url += f"?{qs}"
        headers = _build_forward_headers(request)
        body = await _read_request_body_safe(request)
        if body is None:
            return Response(status_code=204, content=b"")
        client = request.app.state.http_client_no_follow
        try:
            req = client.build_request(
                method=request.method,
                url=target_url,
                headers=headers,
                content=body if body else None,
            )
            resp = await client.send(req, stream=True)
        except Exception:
            # 高频非关键路径（图片转码/推荐位等）失败降为 DEBUG，避免日志刷屏
            if path.startswith(SILENT_FAIL_PATH_PREFIXES):
                logger.debug("Plex 非关键路径请求失败: %s", path)
            else:
                logger.warning("无法连接到 Plex: %s", target_url)
            return JSONResponse(
                status_code=502,
                content={
                    "error": "Bad Gateway",
                    "detail": f"无法连接到 Plex 服务器: {plex_host}",
                },
            )
        excluded = HOP_BY_HOP_HEADERS | {"content-encoding"}
        if resp.headers.get("content-encoding"):
            excluded = excluded | {"content-length"}
        resp_headers = {
            k: v for k, v in resp.headers.multi_items() if k.lower() not in excluded
        }

        async def stream():
            """
            流式读取 httpx 响应并逐块输出，完成后关闭响应
            """
            try:
                async for chunk in resp.aiter_bytes(chunk_size=65536):
                    yield chunk
            finally:
                await resp.aclose()

        return StreamingResponse(
            stream(),
            status_code=resp.status_code,
            headers=resp_headers,
        )

    # ---------- 播放状态嗅探（方案A：timeline 停止触发补全） ----------

    @app.api_route(
        "/{path:path}",
        methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
        response_model=None,
    )
    async def catch_all(request: Request):
        """
        兜底路由：将未匹配请求反向代理到 Plex

        :param request (Request): 当前请求
        :return Response: 流式响应或 502 JSON 错误
        """
        return await _reverse_proxy(request)

    return app
