from asyncio import Lock, gather
from contextlib import asynccontextmanager
from hashlib import sha256
from re import IGNORECASE, compile as re_compile, search as re_search, sub as re_sub
from time import monotonic
from typing import Any, List, Tuple
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
    Response as HttpxResponse,
    Timeout,
    TimeoutException,
)
from starlette.requests import ClientDisconnect
from websockets import connect

from app.log import logger

from .external_players import (
    ALL_EXTERNAL_PLAYER_KEYS,
    EXTERNAL_PLAYERS,
    EXTERNAL_PLAYER_MARKER,
    REDIRECT_PATH,
    build_external_player_script,
    decode_redirect_link,
    extract_api_key,
    inject_external_urls,
)

PLAYBACK_URL_CACHE_TTL_SECONDS = 90
PLAYBACK_USER_CACHE_TTL_SECONDS = 300
PLAYBACK_URL_CACHE_MAX_SIZE = 500
PLAYBACK_STRM_CACHE_TTL_SECONDS = 300
REDIRECT_RESOLVE_TIMEOUTS = ((3.0, 10.0), (3.0, 15.0), (5.0, 20.0))

CACHE_KEY_HEADERS = (
    "authorization",
    "cookie",
    "x-emby-token",
    "user-agent",
    "x-emby-device-id",
    "x-emby-device-name",
    "x-emby-client",
    "x-emby-client-version",
    "x-device-id",
    "x-device-name",
    "x-client",
)

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

MEDIA_ROUTES = [
    "/audio/{item_id}/{name}",
    "/emby/audio/{item_id}/{name}",
    "/videos/{item_id}/{name}",
    "/emby/videos/{item_id}/{name}",
    "/items/{item_id}/download",
    "/emby/items/{item_id}/download",
    "/items/{item_id}/file",
    "/emby/items/{item_id}/file",
    "/sync/jobitems/{item_id}/file",
    "/emby/sync/jobitems/{item_id}/file",
]

NON_MEDIA_NAMES = frozenset(
    {
        "additionalparts",
        "subtitles",
        "similar",
        "thememedia",
        "themevideos",
        "themesongs",
        "specialfeatures",
        "linkeditems",
    }
)

CROSS_ORIGIN_PATTERN = r"&&\s*\(elem\.crossOrigin\s*=\s*initialSubtitleStream\)"

PLUGIN_CROSS_ORIGIN_RE = re_compile(r"&&\(\w+\.crossOrigin=\w+\)")

CROSS_ORIGIN_VALUE_RE = re_compile(
    r'\w+\.IsRemote\s*&&\s*"DirectPlay"\s*===\s*\w+\s*\?\s*null\s*:\s*"anonymous"'
)

CROSS_ORIGIN_INTERCEPT_MARKER = "[EmbyReverseProxy] crossOrigin"

CROSS_ORIGIN_INTERCEPT_SCRIPT = (
    """<script>
(function(){
  // """
    + CROSS_ORIGIN_INTERCEPT_MARKER
    + """ 拦截器 — 302 直链播放避免 CORS
  try {
    Object.defineProperty(HTMLMediaElement.prototype,'crossOrigin',{
      get:function(){return null},
      set:function(){},
      configurable:true
    });
  } catch(e){}
  try {
    var ob=new MutationObserver(function(ms){
      ms.forEach(function(m){
        if(m.type==='attributes'&&m.attributeName==='crossorigin'){
          m.target.removeAttribute('crossorigin');
        }
        if(m.type==='childList'){
          m.addedNodes.forEach(function(n){
            if(n.nodeType===1&&(n.tagName==='VIDEO'||n.tagName==='AUDIO')){
              n.removeAttribute('crossorigin');
            }
          });
        }
      });
    });
    if(document.documentElement){
      ob.observe(document.documentElement,{attributes:true,attributeFilter:['crossorigin'],childList:true,subtree:true});
    } else {
      document.addEventListener('DOMContentLoaded',function(){
        ob.observe(document.documentElement,{attributes:true,attributeFilter:['crossorigin'],childList:true,subtree:true});
      });
    }
  } catch(e){}
})();
</script>"""
)


def create_app(
    emby_host: str,
    pin_rules: List[Tuple[str, str]] | None = None,
    external_player_url: bool = False,
    external_player_list: List[str] | None = None,
) -> FastAPI:
    """
    创建 Emby 反向代理 FastAPI 应用

    :param emby_host (str): Emby 服务器根地址
    :param pin_rules (List): 顶置路径规则列表 (路径前缀, 目标URL)；命中时先替换再 302
    :param external_player_url (bool): 是否启用外部播放器链接注入
    :param external_player_list (List): 要注入的外部播放器 key 列表；为空时使用全部

    :return FastAPI: 配置好的 FastAPI 应用实例
    """
    emby_host = emby_host.rstrip("/")
    pin_rules = pin_rules or []
    if external_player_url:
        _player_keys = (
            [k for k in external_player_list if k in EXTERNAL_PLAYERS]
            if external_player_list
            else ALL_EXTERNAL_PLAYER_KEYS
        )
    else:
        _player_keys = []

    _external_player_script = build_external_player_script(_player_keys)

    async def _read_request_body_safe(request: Request) -> bytes | None:
        """
        读取请求体；客户端已断开时返回 None，避免 ClientDisconnect 未处理导致 500

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

    def _strip_accept_encoding(headers: dict[str, str]) -> dict[str, str]:
        """
        去掉 Accept-Encoding，便于上游返回未压缩内容以便修改 body

        :param headers: 原始转发头
        :return: 不包含 accept-encoding 的头字典
        """
        return {k: v for k, v in headers.items() if k.lower() != "accept-encoding"}

    def _may_return_emby_html_shell(path: str) -> bool:
        """
        判断路径是否可能返回 Emby Web 的 HTML 壳（用于是否走缓冲并注入脚本）

        :param path: 请求路径
        :return: 若可能为 HTML 页面则 True
        """
        pl = path.lower()
        if "playbackinfo" in pl:
            return False
        if path == "/" or path == "":
            return True
        if path.startswith("/web/") or path == "/web":
            return True
        if path.endswith(".html") or path.endswith(".htm"):
            return True
        if path.startswith(("/emby/", "/items/", "/videos/", "/audio/", "/sync/")):
            return False
        last = path.rsplit("/", 1)[-1]
        if "." not in last:
            return True
        return False

    def _inject_scripts_into_html(html: str) -> str | None:
        """
        在 HTML 的 head 中注入 crossOrigin 拦截脚本和外部播放器脚本；已注入则跳过

        :param html: 页面 HTML 文本
        :return: 注入后的 HTML；无需修改时返回 None
        """
        scripts = ""
        if CROSS_ORIGIN_INTERCEPT_MARKER not in html:
            scripts += CROSS_ORIGIN_INTERCEPT_SCRIPT
        if _external_player_script and EXTERNAL_PLAYER_MARKER not in html:
            scripts += _external_player_script
        if not scripts:
            return None
        m = re_search(r"</head>", html, IGNORECASE)
        if m:
            i = m.start()
            return html[:i] + scripts + html[i:]
        m2 = re_search(r"<head[^>]*>", html, IGNORECASE)
        if m2:
            return html[: m2.end()] + scripts + html[m2.end() :]
        return None

    def _media_sources_indicate_strm(data: dict[str, Any]) -> bool:
        """
        根据 PlaybackInfo JSON 判断是否为 STRM
        Emby 解析 .strm 后 Path 变为文件内的实际地址（HTTP URL），
        因此通过 Protocol=Http + IsRemote=True 来识别

        :param data: PlaybackInfo 解析后的字典
        :return: 若任一 MediaSource 为 STRM 解析后的远程源则为 True
        """
        sources = data.get("MediaSources")
        if not isinstance(sources, list):
            return False
        for ms in sources:
            if not isinstance(ms, dict):
                continue
            if ms.get("IsRemote") is True and ms.get("Protocol") == "Http":
                return True
        return False

    def _media_sources_match_pin_rules(
        data: dict[str, Any], rules: List[Tuple[str, str]]
    ) -> bool:
        """
        判断 PlaybackInfo 中是否有 MediaSource 的 Path 经 pin_rules 替换后变为 HTTP URL

        :param data: PlaybackInfo 解析后的字典
        :param rules: 顶置路径规则列表
        :return: 若任一 MediaSource 命中规则且替换结果为 HTTP URL 则为 True
        """
        if not rules:
            return False
        sources = data.get("MediaSources")
        if not isinstance(sources, list):
            return False
        for ms in sources:
            if not isinstance(ms, dict):
                continue
            path = ms.get("Path")
            if not isinstance(path, str):
                continue
            replaced = _apply_pin_rules(path, rules)
            if replaced != path and replaced.startswith(("http://", "https://")):
                return True
        return False

    def _apply_force_direct_play_to_media_sources(
        data: dict[str, Any], item_id: str
    ) -> None:
        """
        对 PlaybackInfo 中所有 MediaSource 强制 DirectPlay，去掉转码相关字段，
        并将 DirectStreamUrl 设为相对直链（相对当前连接主机，便于走代理 302）

        :param data: PlaybackInfo 字典（就地修改）
        :param item_id: 条目 ID，用于拼 /videos 或 /audio 下的 stream 路径
        """
        sources = data.get("MediaSources")
        if not isinstance(sources, list):
            return
        for ms in sources:
            if not isinstance(ms, dict):
                continue
            ms["SupportsDirectPlay"] = True
            ms["SupportsDirectStream"] = True
            ms["SupportsTranscoding"] = False
            for key in (
                "TranscodingUrl",
                "TranscodingContainer",
                "TranscodingSubProtocol",
            ):
                ms.pop(key, None)
            ms.pop("DirectStreamUrl", None)
            sid = ms.get("Id", "")
            if not isinstance(sid, str) or not sid:
                continue
            qsid = quote(sid, safe="")
            if str(ms.get("Type", "")).lower() == "audio":
                ms["DirectStreamUrl"] = (
                    f"/audio/{item_id}/stream?Static=true&MediaSourceId={qsid}"
                )
            else:
                ms["DirectStreamUrl"] = (
                    f"/videos/{item_id}/stream?Static=true&MediaSourceId={qsid}"
                )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """
        FastAPI 生命周期管理器：创建共享 httpx 客户端及缓存，关闭时清理资源
        """
        limits = Limits(max_keepalive_connections=20, keepalive_expiry=30.0)
        app.state.http_client_follow = AsyncClient(follow_redirects=True, limits=limits)
        app.state.http_client_no_follow = AsyncClient(
            follow_redirects=False, limits=limits
        )
        app.state.playback_url_cache = {}
        app.state.playback_cache_order = []
        app.state.playback_cache_lock = Lock()
        app.state.strm_source_cache = {}
        app.state.strm_source_lock = Lock()
        app.state.playback_user_cache = {}
        app.state.playback_user_lock = Lock()
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

    @app.middleware("http")
    async def path_to_lower_middleware(request: Request, call_next):
        """
        FastAPI 中间件：将 Emby API 路径中的大写转小写，提升路由匹配兼容性
        """
        path = request.scope["path"]
        lower = path.lower()
        _api_prefixes = (
            "/emby/videos/",
            "/emby/audio/",
            "/emby/items/",
            "/emby/sync/",
            "/emby/system/",
            "/emby/users/",
            "/videos/",
            "/audio/",
            "/items/",
            "/sync/",
            "/system/",
            "/users/",
        )
        if lower.startswith(_api_prefixes):
            request.scope["path"] = lower
        return await call_next(request)

    def _build_forward_headers(request: Request) -> dict[str, str]:
        """
        构建转发请求头，排除 host 和 hop-by-hop 头

        :param request: 当前请求
        :return: 用于转发的请求头字典
        """
        return {
            k: v
            for k, v in request.headers.items()
            if k.lower() not in HOP_BY_HOP_HEADERS and k.lower() != "host"
        }

    def _real_client_ip(request: Request) -> str:
        """
        获取真实客户端 IP

        若 MoviePilot 前置有反向代理（nginx/Cloudflare 等），
        `request.client.host` 会是上游代理的 IP，导致局域网内所有用户看起来
        都来自同一 IP。优先读取 `X-Forwarded-For` / `X-Real-IP` 恢复真实 IP

        :param request: 当前请求
        :return: 客户端 IP 字符串，取不到时返回空串
        """
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",", 1)[0].strip()
        xri = request.headers.get("x-real-ip")
        if xri:
            return xri.strip()
        return request.client.host if request.client else ""

    def _playback_user_key(request: Request, item_id: str) -> tuple[str, str, str]:
        """
        构造用于关联 PlaybackInfo → Stream 的复合 key

        Stream 请求通常不携带任何 Emby 认证字段，但与其前置的 PlaybackInfo
        来自同一浏览器/设备，因此可以用 (client_ip, user_agent, item_id)
        三元组作为稳定关联键。同一设备下多用户互不影响：不同用户的
        PlaybackInfo 分属不同 item_id 的播放动作，不会相互覆盖

        :param request: 当前请求
        :param item_id: 媒体项 ID
        :return: 复合 key
        """
        ip = _real_client_ip(request)
        ua = request.headers.get("user-agent", "")
        return ip, ua, item_id

    def _header_hash(request: Request) -> str:
        """
        对缓存 key 白名单内的请求头做稳定序列化并哈希，用于区分认证/设备

        :param request: 当前请求
        :return: 十六进制摘要字符串
        """
        parts = []
        for name in sorted(CACHE_KEY_HEADERS):
            value = request.headers.get(name)
            if value is not None:
                parts.append(f"{name}:{value}")
        return sha256("\n".join(parts).encode("utf-8")).hexdigest()

    async def _handle_media(
        request: Request, item_id: str, name: str = ""
    ) -> RedirectResponse | StreamingResponse | JSONResponse | Response:
        """
        处理媒体路由：尝试 302 重定向（PlaybackInfo 或 STRM 缓存），失败则走通用反向代理

        :param request: 当前请求
        :param item_id: 媒体项 ID
        :param name: 路径中的名称（未使用，由路由匹配）
        :return: 重定向、流式响应或错误 JSON
        """
        if name.lower() in NON_MEDIA_NAMES:
            return await _reverse_proxy(request)
        api_key = extract_api_key(request)
        resp = await _try_media_response(item_id, api_key, request)
        if resp:
            return resp
        return await _reverse_proxy(request)

    async def _resolve_redirect(
        client: AsyncClient,
        url: str,
        headers: dict[str, str],
        user_id: str | None = None,
    ) -> str:
        """
        跟随重定向链，返回最终 URL

        :param client: 共享的 httpx 客户端（follow_redirects=True）
        :param url: 起始 URL
        :param headers: 请求头
        :param user_id: Emby 用户 ID，可为 None
        :return: 最终 URL；失败时返回原始 url
        """
        if user_id:
            headers = {**headers, "X-Emby-UserId": user_id}
        max_attempts = len(REDIRECT_RESOLVE_TIMEOUTS)
        for attempt, (connect_timeout, read_timeout) in enumerate(
            REDIRECT_RESOLVE_TIMEOUTS, 1
        ):
            try:
                resp = await client.head(
                    url,
                    headers=headers,
                    timeout=Timeout(read_timeout, connect=connect_timeout),
                )
                return str(resp.url)
            except TimeoutException as e:
                if attempt >= max_attempts:
                    logger.warning(
                        "解析重定向超时，使用原始 URL: %s (%s)",
                        url,
                        type(e).__name__,
                        exc_info=True,
                    )
                    return url
                logger.info(
                    "解析重定向超时，准备重试: url=%s, attempt=%s/%s, connect=%ss, read=%ss, error=%s",
                    url,
                    attempt,
                    max_attempts,
                    connect_timeout,
                    read_timeout,
                    type(e).__name__,
                )
            except Exception:
                logger.warning("解析重定向失败，使用原始 URL: %s", url, exc_info=True)
                return url
        return url

    def _apply_pin_rules(url_or_path: str, rules: List[Tuple[str, str]]) -> str:
        """
        对 PlaybackInfo 返回的 Path（URL 或路径）应用顶置规则：匹配前缀则替换为目标 URL

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
            suffix = path_component[len(path_prefix) :].lstrip("/")
            base = target_url.rstrip("/")
            new_url = base + ("/" + suffix if suffix else "")
            if original_query:
                new_url += "?" + original_query
            return new_url
        return url_or_path

    async def _try_media_response(
        item_id: str, api_key: str | None, request: Request
    ) -> RedirectResponse | None:
        """
        尝试获取媒体文件真实地址并返回 302 重定向
        优先级：已解析 URL 缓存 → PlaybackInfo 实时查询 → STRM 源缓存

        :param item_id: 媒体项 ID
        :param api_key: Emby API Key，可为 None
        :param request: 当前请求
        :return: 302 重定向响应，或 None 表示回退到反向代理
        """
        media_source_id = request.query_params.get("MediaSourceId") or ""

        user_key = _playback_user_key(request, item_id)
        user_cache = request.app.state.playback_user_cache
        user_id: str | None = None
        async with request.app.state.playback_user_lock:
            user_entry = user_cache.get(user_key)
            if user_entry:
                uid, user_expiry = user_entry
                if monotonic() < user_expiry:
                    user_id = uid
                else:
                    user_cache.pop(user_key, None)

        cache_key = (
            item_id,
            media_source_id,
            user_id or "",
            _header_hash(request),
        )
        cache = request.app.state.playback_url_cache
        order = request.app.state.playback_cache_order
        lock = request.app.state.playback_cache_lock

        cached_final_url = None
        async with lock:
            if cache_key in cache:
                final_url, expiry_ts = cache[cache_key]
                if monotonic() < expiry_ts:
                    cached_final_url = final_url
                else:
                    del cache[cache_key]
                    try:
                        order.remove(cache_key)
                    except ValueError:
                        pass
        if cached_final_url is not None:
            logger.debug("PlaybackInfo 使用缓存: item_id=%s", item_id)
            return RedirectResponse(url=cached_final_url, status_code=302)

        http_path = None

        if api_key:
            url = f"{emby_host}/Items/{item_id}/PlaybackInfo?X-Emby-Token={api_key}"
            client_follow = request.app.state.http_client_follow
            try:
                resp = await client_follow.post(url, timeout=10)
                resp.raise_for_status()
                data = resp.json()
            except Exception:
                logger.warning(
                    "PlaybackInfo 请求失败: item_id=%s", item_id, exc_info=True
                )
                data = {}
            for source in data.get("MediaSources", []):
                sid = source.get("Id", "")
                if media_source_id and sid != media_source_id:
                    continue
                path = source.get("Path", "")
                path = _apply_pin_rules(path, pin_rules)
                if path.startswith(("http://", "https://")):
                    http_path = path
                    break

        if not http_path:
            strm_cache = request.app.state.strm_source_cache
            strm_lock = request.app.state.strm_source_lock
            async with strm_lock:
                entry = strm_cache.get(item_id)
            if entry:
                sources_map, expiry_ts = entry
                if monotonic() < expiry_ts:
                    if media_source_id and media_source_id in sources_map:
                        http_path = sources_map[media_source_id]
                    elif sources_map:
                        http_path = next(iter(sources_map.values()))
                    if http_path:
                        logger.debug("使用 STRM 源缓存: item_id=%s", item_id)

        if not http_path:
            return None

        client_follow = request.app.state.http_client_follow
        fwd_headers = _build_forward_headers(request)
        final_url = await _resolve_redirect(
            client_follow, http_path, fwd_headers, user_id
        )

        async with lock:
            now = monotonic()
            expiry = now + PLAYBACK_URL_CACHE_TTL_SECONDS
            expired = [k for k in order if cache.get(k) and cache[k][1] < now]
            for k in expired:
                cache.pop(k, None)
            order[:] = [k for k in order if k not in frozenset(expired)]
            while len(cache) >= PLAYBACK_URL_CACHE_MAX_SIZE and order:
                oldest = order.pop(0)
                cache.pop(oldest, None)
            cache[cache_key] = (final_url, expiry)
            order.append(cache_key)

        logger.info("302 重定向: item_id=%s -> %s", item_id, final_url)
        return RedirectResponse(url=final_url, status_code=302)

    for route in MEDIA_ROUTES:
        app.api_route(route, methods=["GET", "HEAD"], response_model=None)(
            _handle_media
        )

    async def _ws_proxy(ws_client: WebSocket) -> None:
        """
        双向代理客户端 WebSocket 与 Emby 后端 WebSocket

        :param ws_client: 客户端 WebSocket 连接
        """
        await ws_client.accept()
        parsed = urlparse(emby_host)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        qs = str(ws_client.scope.get("query_string", b""), "utf-8")
        backend_url = f"{scheme}://{parsed.netloc}/embywebsocket"
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

    app.websocket("/embywebsocket")(_ws_proxy)
    app.websocket("/emby/embywebsocket")(_ws_proxy)

    def _current_port(request: Request) -> int:
        """
        从请求中解析当前代理端口（供客户端连回），优先 X-Forwarded-Port

        :param request: 当前请求
        :return: 端口号
        """
        forwarded = request.headers.get("x-forwarded-port")
        if forwarded:
            try:
                return int(forwarded.split(",")[0].strip())
            except (ValueError, AttributeError):
                pass
        server = request.scope.get("server")
        if server and len(server) >= 2:
            try:
                return int(server[1])
            except (ValueError, TypeError):
                pass
        return 80

    async def _system_info_handler(
        request: Request,
    ) -> JSONResponse | StreamingResponse:
        """
        代理 /emby/system/info 与 /system/info，并改写响应中的端口，使客户端连回代理而非后端

        :param request: 当前请求
        :return: 改写后的 JSON 或 502 错误
        """
        path = request.scope.get("path", "/")
        qs = str(request.url.query)
        target_url = f"{emby_host}{path}"
        if qs:
            target_url += f"?{qs}"
        headers = _build_forward_headers(request)
        client = request.app.state.http_client_follow
        try:
            resp = await client.request(
                request.method,
                target_url,
                headers=headers,
                timeout=10,
            )
        except Exception as e:
            err_msg = str(e) or type(e).__name__
            logger.warning(
                "System/Info 请求失败: %s — %s", target_url, err_msg, exc_info=True
            )
            return JSONResponse(
                status_code=502,
                content={
                    "error": "Bad Gateway",
                    "detail": f"System/Info 请求失败: {err_msg}",
                },
            )
        if resp.status_code != 200:
            logger.warning(
                "System/Info 后端返回非 200: status=%s, url=%s",
                resp.status_code,
                target_url,
            )
            return JSONResponse(
                status_code=502,
                content={
                    "error": "Bad Gateway",
                    "detail": "System/Info 请求失败",
                },
            )
        try:
            body = resp.json()
        except Exception:
            logger.warning("System/Info 响应非 JSON: %s", target_url, exc_info=True)
            return JSONResponse(
                status_code=502,
                content={
                    "error": "Bad Gateway",
                    "detail": "System/Info 请求失败",
                },
            )
        origin_port = body.get("WebSocketPortNumber")
        if origin_port is not None:
            current_port = _current_port(request)
            try:
                origin_port = int(origin_port)
            except (TypeError, ValueError):
                origin_port = None
            if origin_port is not None:
                body["WebSocketPortNumber"] = current_port
                if body.get("HttpServerPortNumber") is not None:
                    body["HttpServerPortNumber"] = current_port
                for key in ("LocalAddresses", "RemoteAddresses"):
                    if isinstance(body.get(key), list):
                        body[key] = [
                            str(s).replace(str(origin_port), str(current_port))
                            for s in body[key]
                        ]
                for key in ("LocalAddress", "WanAddress"):
                    if body.get(key) is not None:
                        body[key] = str(body[key]).replace(
                            str(origin_port), str(current_port)
                        )
        excluded = HOP_BY_HOP_HEADERS | {"content-length", "content-encoding"}
        resp_headers = {
            k: v for k, v in resp.headers.multi_items() if k.lower() not in excluded
        }
        return JSONResponse(status_code=200, content=body, headers=resp_headers)

    for _path in ("/emby/system/info", "/system/info"):
        app.api_route(
            _path,
            methods=["GET", "HEAD"],
            response_model=None,
        )(_system_info_handler)

    async def _playback_info_strm_direct_play(
        request: Request, item_id: str
    ) -> JSONResponse | Response:
        """
        代理 Items/PlaybackInfo：若 MediaSource.Path 为 .strm，则强制 DirectPlay，
        避免浏览器因编码能力走 HLS 转码，使 302 直链失效

        :param request: 当前请求
        :param item_id: 路径中的条目 ID
        :return: 改写后的 JSON 或透传响应
        """
        path = request.scope.get("path", "/")
        qs = str(request.url.query)
        target_url = f"{emby_host}{path}"
        if qs:
            target_url += f"?{qs}"

        headers = _strip_accept_encoding(_build_forward_headers(request))
        body = await _read_request_body_safe(request)
        if body is None:
            return Response(status_code=204, content=b"")
        client = request.app.state.http_client_follow

        excluded = HOP_BY_HOP_HEADERS | {"content-encoding", "content-length"}

        def _resp_headers_from_httpx(r: HttpxResponse) -> dict[str, str]:
            return {
                k: v for k, v in r.headers.multi_items() if k.lower() not in excluded
            }

        if request.method == "HEAD":
            try:
                resp = await client.request(
                    "HEAD",
                    target_url,
                    headers=headers,
                    timeout=60.0,
                )
            except Exception:
                logger.warning("PlaybackInfo HEAD 失败: %s", target_url, exc_info=True)
                return JSONResponse(
                    status_code=502,
                    content={"error": "Bad Gateway"},
                )
            return Response(
                content=b"",
                status_code=resp.status_code,
                headers=_resp_headers_from_httpx(resp),
            )

        try:
            resp = await client.request(
                request.method,
                target_url,
                headers=headers,
                content=body if body else None,
                timeout=120.0,
            )
        except Exception:
            logger.warning("PlaybackInfo 请求失败: %s", target_url, exc_info=True)
            return JSONResponse(
                status_code=502,
                content={
                    "error": "Bad Gateway",
                    "detail": f"无法连接到 Emby 服务器: {emby_host}",
                },
            )

        if resp.status_code != 200:
            return Response(
                content=resp.content,
                status_code=resp.status_code,
                headers=_resp_headers_from_httpx(resp),
            )

        try:
            data = resp.json()
        except Exception:
            logger.warning("PlaybackInfo 响应非 JSON: %s", target_url, exc_info=True)
            return Response(
                content=resp.content,
                status_code=resp.status_code,
                headers=_resp_headers_from_httpx(resp),
            )

        if not isinstance(data, dict):
            return JSONResponse(
                content=data,
                status_code=200,
                headers=_resp_headers_from_httpx(resp),
            )

        is_strm = _media_sources_indicate_strm(data)
        is_pin = _media_sources_match_pin_rules(data, pin_rules)
        if not is_strm and not is_pin:
            return JSONResponse(
                content=data,
                status_code=200,
                headers=_resp_headers_from_httpx(resp),
            )

        _apply_force_direct_play_to_media_sources(data, item_id)

        strm_sources: dict[str, str] = {}
        for ms in data.get("MediaSources", []):
            if not isinstance(ms, dict):
                continue
            ms_path = ms.get("Path", "")
            ms_path_applied = _apply_pin_rules(ms_path, pin_rules)
            if ms_path_applied.startswith(("http://", "https://")):
                strm_sources[ms.get("Id", "")] = ms_path_applied
        if strm_sources:
            strm_cache = request.app.state.strm_source_cache
            strm_lock = request.app.state.strm_source_lock
            async with strm_lock:
                strm_cache[item_id] = (
                    strm_sources,
                    monotonic() + PLAYBACK_STRM_CACHE_TTL_SECONDS,
                )

        uid = request.query_params.get("UserId")
        if uid:
            user_key = _playback_user_key(request, item_id)
            user_cache = request.app.state.playback_user_cache
            async with request.app.state.playback_user_lock:
                user_cache[user_key] = (
                    uid,
                    monotonic() + PLAYBACK_USER_CACHE_TTL_SECONDS,
                )

        reason = "STRM" if is_strm else "路径替换"
        logger.info(
            "PlaybackInfo: %s 已强制 DirectPlay item_id=%s",
            reason,
            item_id,
        )
        return JSONResponse(
            content=data,
            status_code=200,
            headers=_resp_headers_from_httpx(resp),
        )

    for _playback_path in (
        "/items/{item_id}/playbackinfo",
        "/emby/items/{item_id}/playbackinfo",
    ):
        app.api_route(
            _playback_path,
            methods=["GET", "POST", "HEAD"],
            response_model=None,
        )(_playback_info_strm_direct_play)

    async def _reverse_proxy_html_inject(request: Request) -> Response | JSONResponse:
        """
        对可能返回 HTML 的 GET 请求整包拉取，注入 crossOrigin 拦截脚本后再返回

        :param request: 当前请求（须为 GET）
        :return: 响应体或 502 JSON
        """
        path = request.scope.get("path", "/")
        qs = str(request.url.query)
        target_url = f"{emby_host}{path}"
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
                timeout=120.0,
            )
        except Exception:
            logger.warning("无法连接到 Emby: %s", target_url, exc_info=True)
            return JSONResponse(
                status_code=502,
                content={
                    "error": "Bad Gateway",
                    "detail": f"无法连接到 Emby 服务器: {emby_host}",
                },
            )

        ct = (resp.headers.get("content-type") or "").lower()
        raw = resp.content
        out = raw
        if resp.status_code == 200 and "text/html" in ct:
            try:
                html = resp.text
            except Exception:
                html = raw.decode("utf-8", errors="replace")
            injected = _inject_scripts_into_html(html)
            if injected is not None:
                out = injected.encode("utf-8")
                logger.info("已在 HTML 注入脚本: path=%s", path)

        excluded = HOP_BY_HOP_HEADERS | {"content-encoding", "content-length"}
        resp_headers = {
            k: v for k, v in resp.headers.multi_items() if k.lower() not in excluded
        }
        if out != raw and resp.status_code == 200 and "text/html" in ct:
            resp_headers["cache-control"] = "no-cache, no-store, must-revalidate"
            resp_headers["pragma"] = "no-cache"
            resp_headers["expires"] = "0"
            lk = {k.lower(): k for k in resp_headers}
            for name in ("etag", "last-modified"):
                if name in lk:
                    del resp_headers[lk[name]]

        return Response(
            content=out,
            status_code=resp.status_code,
            headers=resp_headers,
        )

    async def _reverse_proxy(
        request: Request,
    ) -> StreamingResponse | JSONResponse | Response:
        """
        将请求反向代理到 Emby 服务器并流式返回响应

        :param request: 当前请求
        :return: 流式响应或 502 JSON 错误
        """
        path = request.scope.get("path", "/")
        if request.method == "GET" and _may_return_emby_html_shell(path):
            return await _reverse_proxy_html_inject(request)

        qs = str(request.url.query)
        target_url = f"{emby_host}{path}"
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
            logger.warning("无法连接到 Emby: %s", target_url, exc_info=True)
            return JSONResponse(
                status_code=502,
                content={
                    "error": "Bad Gateway",
                    "detail": f"无法连接到 Emby 服务器: {emby_host}",
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

    def _patch_js_response_headers(
        resp: HttpxResponse, extra: dict[str, str] | None = None
    ) -> dict[str, str]:
        """
        从 httpx 响应构造转发头，并可选附加 Cache-Control 等

        :param resp: httpx Response
        :param extra: 额外头
        :return: 适合 FastAPI Response 的头字典
        """
        excluded = HOP_BY_HOP_HEADERS | {"content-encoding", "content-length"}
        h = {k: v for k, v in resp.headers.multi_items() if k.lower() not in excluded}
        if extra:
            h.update(extra)
        return h

    async def _patch_basehtmlplayer_js(request: Request) -> JSONResponse | Response:
        """
        拦截 htmlvideoplayer/basehtmlplayer.js，将 getCrossOriginValue 相关逻辑改为不设置 crossorigin

        :param request: 当前请求
        :return: 修补后的 JS 或 502
        """
        path = request.scope.get("path", "/")
        qs = str(request.url.query)
        target_url = f"{emby_host}{path}"
        if qs:
            target_url += f"?{qs}"
        headers = _strip_accept_encoding(_build_forward_headers(request))
        client = request.app.state.http_client_follow
        try:
            resp = await client.get(target_url, headers=headers, timeout=15)
        except Exception:
            logger.warning("获取 basehtmlplayer.js 失败: %s", target_url, exc_info=True)
            return JSONResponse(status_code=502, content={"error": "Bad Gateway"})

        if resp.status_code != 200:
            return Response(
                content=resp.content,
                status_code=resp.status_code,
                headers=_patch_js_response_headers(resp),
            )

        content = resp.text
        original = content
        patched = CROSS_ORIGIN_VALUE_RE.sub("null", content)
        if patched != original:
            logger.info(
                "已修补 basehtmlplayer.js: getCrossOriginValue 三元表达式 -> null"
            )
        elif "getCrossOriginValue" in original:
            logger.info(
                "basehtmlplayer.js: 精确正则未命中，尝试将 anonymous 替换为 null"
            )
            patched = original.replace('"anonymous"', "null").replace(
                "'anonymous'", "null"
            )

        extra: dict[str, str] = {
            "content-type": "application/javascript; charset=utf-8",
        }
        if patched != original:
            extra["cache-control"] = "no-cache, no-store, must-revalidate"
            extra["pragma"] = "no-cache"
            extra["expires"] = "0"
        return Response(
            content=patched.encode("utf-8"),
            status_code=resp.status_code,
            headers=_patch_js_response_headers(resp, extra=extra),
        )

    async def _patch_plugin_js(request: Request) -> JSONResponse | Response:
        """
        拦截 htmlvideoplayer/plugin.js，去除 crossOrigin 赋值，
        使浏览器播放器在 302 重定向时不触发 CORS 预检

        :param request: 当前请求
        :return: 修补后的 JS 响应或 502 错误 JSON
        """
        path = request.scope.get("path", "/")
        qs = str(request.url.query)
        target_url = f"{emby_host}{path}"
        if qs:
            target_url += f"?{qs}"
        headers = _strip_accept_encoding(_build_forward_headers(request))
        client = request.app.state.http_client_follow
        try:
            resp = await client.get(target_url, headers=headers, timeout=15)
        except Exception:
            logger.warning("获取 plugin.js 失败: %s", target_url, exc_info=True)
            return JSONResponse(status_code=502, content={"error": "Bad Gateway"})

        content = resp.text
        original = content
        patched = PLUGIN_CROSS_ORIGIN_RE.sub("", content)
        patched = re_sub(CROSS_ORIGIN_PATTERN, "", patched)
        if patched != original:
            logger.info("已修补 plugin.js: 移除 crossOrigin 赋值")

        extra: dict[str, str] = {
            "content-type": "application/javascript; charset=utf-8",
        }
        if patched != original:
            extra["cache-control"] = "no-cache, no-store, must-revalidate"
            extra["pragma"] = "no-cache"
            extra["expires"] = "0"
        return Response(
            content=patched.encode("utf-8"),
            status_code=resp.status_code,
            headers=_patch_js_response_headers(resp, extra=extra),
        )

    for _js_path in (
        "/emby/web/modules/htmlvideoplayer/basehtmlplayer.js",
        "/web/modules/htmlvideoplayer/basehtmlplayer.js",
    ):
        app.api_route(_js_path, methods=["GET", "HEAD"], response_model=None)(
            _patch_basehtmlplayer_js
        )

    for _js_path in (
        "/emby/web/modules/htmlvideoplayer/plugin.js",
        "/web/modules/htmlvideoplayer/plugin.js",
    ):
        app.api_route(_js_path, methods=["GET", "HEAD"], response_model=None)(
            _patch_plugin_js
        )

    if _player_keys:

        async def _items_external_player_handler(
            request: Request, user_id: str, item_id: str
        ) -> JSONResponse | StreamingResponse | Response:
            """
            代理 /Users/{user_id}/Items/{item_id}，为含有 MediaSources 的响应注入 ExternalUrls

            :param request: 当前请求
            :param user_id: 用户 ID
            :param item_id: 媒体项 ID
            :return: 注入后的 JSON 或透传响应
            """
            path = request.scope.get("path", "/")
            qs = str(request.url.query)
            target_url = f"{emby_host}{path}"
            if qs:
                target_url += f"?{qs}"

            headers = _strip_accept_encoding(_build_forward_headers(request))
            client = request.app.state.http_client_follow

            try:
                resp = await client.request(
                    request.method,
                    target_url,
                    headers=headers,
                    timeout=30.0,
                )
            except Exception:
                logger.warning("Items 请求失败: %s", target_url, exc_info=True)
                return JSONResponse(
                    status_code=502,
                    content={"error": "Bad Gateway"},
                )

            if resp.status_code != 200:
                excluded = HOP_BY_HOP_HEADERS | {"content-encoding", "content-length"}
                return Response(
                    content=resp.content,
                    status_code=resp.status_code,
                    headers={
                        k: v
                        for k, v in resp.headers.multi_items()
                        if k.lower() not in excluded
                    },
                )

            try:
                data = resp.json()
            except Exception:
                excluded = HOP_BY_HOP_HEADERS | {"content-encoding", "content-length"}
                return Response(
                    content=resp.content,
                    status_code=resp.status_code,
                    headers={
                        k: v
                        for k, v in resp.headers.multi_items()
                        if k.lower() not in excluded
                    },
                )

            if isinstance(data, dict):
                api_key = extract_api_key(request) or ""
                if inject_external_urls(
                    data=data,
                    request=request,
                    emby_host=emby_host,
                    item_id=item_id,
                    api_key=api_key,
                    player_keys=_player_keys,
                ):
                    logger.debug(
                        "已注入 ExternalUrls: user_id=%s, item_id=%s",
                        user_id,
                        item_id,
                    )

            excluded = HOP_BY_HOP_HEADERS | {"content-encoding", "content-length"}
            resp_headers = {
                k: v for k, v in resp.headers.multi_items() if k.lower() not in excluded
            }
            return JSONResponse(content=data, status_code=200, headers=resp_headers)

        for _items_path in (
            "/users/{user_id}/items/{item_id}",
            "/emby/users/{user_id}/items/{item_id}",
        ):
            app.api_route(
                _items_path,
                methods=["GET"],
                response_model=None,
            )(_items_external_player_handler)

    if _player_keys:

        @app.get(REDIRECT_PATH, response_model=None)
        async def redirect_to_external(link: str | None = None) -> RedirectResponse:
            """
            解码外部播放器链接并 302 跳转

            :param link (str): base64 编码后的原始播放器链接

            :return RedirectResponse: 302 重定向响应
            """
            if not link:
                return RedirectResponse(url="/", status_code=302)
            try:
                decoded = decode_redirect_link(link)
            except Exception:
                logger.warning("无效的 redirect2external link 参数")
                return RedirectResponse(url="/", status_code=302)
            return RedirectResponse(url=decoded, status_code=302)

    @app.api_route(
        "/{path:path}",
        methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
        response_model=None,
    )
    async def catch_all(
        request: Request,
    ) -> StreamingResponse | JSONResponse | Response:
        """
        兜底路由：将未匹配请求反向代理到 Emby

        :param request (Request): 当前请求

        :return Response: 流式响应或 502 JSON 错误
        """
        return await _reverse_proxy(request)

    return app
