__all__ = [
    "HDHiveBrowserError",
    "HDHiveError",
    "HDHiveLoginError",
    "HDHivePlaywrightClient",
    "get_hdhive_browser_client",
    "is_hdhive_search_ready",
]

from base64 import urlsafe_b64decode
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from platform import machine as _machine
from re import search
from shutil import rmtree
from socket import (
    AF_INET,
    SO_REUSEADDR,
    SOCK_STREAM,
    SOL_SOCKET,
    socket,
)
from sys import platform
from time import sleep, time
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple, TypeVar
from urllib.parse import unquote, urlparse

from orjson import dumps, loads

from app.core.config import settings
from app.log import logger

from ...core.config import configer
from ...utils.sentry import sentry_manager

_CLOAKBROWSER_AVAILABLE = False
_PLAYWRIGHT_AVAILABLE = False

try:
    from cloakbrowser import launch_context as _cloak_launch_context

    _CLOAKBROWSER_AVAILABLE = True
except ImportError:
    pass

try:
    from playwright.sync_api import (
        Browser,
        BrowserContext,
        Playwright,
        TimeoutError as PlaywrightTimeoutError,
        sync_playwright,
    )

    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    Browser = Any  # type: ignore[assignment,misc]
    BrowserContext = Any  # type: ignore[assignment,misc]
    Playwright = Any  # type: ignore[assignment,misc]

    class PlaywrightTimeoutError(Exception):  # type: ignore[misc]
        """
        playwright 未安装时的占位异常类
        """

    sync_playwright = None  # type: ignore[assignment]

try:
    from slippers import Proxy as _SocksProxy

    _SLIPPERS_AVAILABLE = True
except ImportError:
    _SocksProxy = None  # type: ignore[assignment]
    _SLIPPERS_AVAILABLE = False


class HDHiveError(Exception):
    """
    HDHive 浏览器自动化异常基类
    """


class HDHiveLoginError(HDHiveError):
    """
    HDHive 认证或 Cookie 相关失败
    """

    login_redirect: bool

    def __init__(self, message: str, *, login_redirect: bool = False) -> None:
        super().__init__(message)
        self.login_redirect = login_redirect


class HDHiveBrowserError(HDHiveError):
    """
    HDHive 页面操作或浏览器自动化失败
    """


_T = TypeVar("_T")


class _CheckinDebugSession:
    """
    签到流程 Debug 会话：记录日志、保存截图和 HTML
    """

    _MAX_SESSIONS = 3

    def __init__(self, label: str) -> None:
        """
        初始化 Debug 会话并在插件临时目录下创建输出文件夹

        :param label (str): 签到类型标签（如「赌狗签到」「每日签到」）
        """
        self._enabled = False
        self._step = 0
        self._dir: Optional[Path] = None
        self._log_path: Optional[Path] = None
        try:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            base = configer.PLUGIN_TEMP_PATH / "hdhive"
            self._dir = base / f"debug_{ts}"
            self._dir.mkdir(parents=True, exist_ok=True)
            self._log_path = self._dir / "checkin.log"
            self._enabled = True
            self._log(f"{'=' * 60}")
            self._log(f"HDHive {label} Debug Session")
            self._log(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            self._log(f"输出目录: {self._dir}")
            self._log(
                f"后端: cloakbrowser={_CLOAKBROWSER_AVAILABLE}  playwright={_PLAYWRIGHT_AVAILABLE}"
            )
            self._log(f"平台: {platform}  机器架构: {_machine()}")
            self._log(f"{'=' * 60}")
            self._cleanup_old_sessions(base)
        except Exception:
            pass

    @staticmethod
    def _cleanup_old_sessions(base: Path) -> None:
        """
        清理超出保留数量的旧 Debug 会话目录

        :param base (Path): Debug 会话根目录
        """
        try:
            sessions = sorted(base.glob("debug_*"), key=lambda p: p.name)
            for old in sessions[
                : max(0, len(sessions) - _CheckinDebugSession._MAX_SESSIONS)
            ]:
                rmtree(old, ignore_errors=True)
        except Exception:
            pass

    def _log(self, msg: str) -> None:
        """
        将一行日志追加写入会话 log 文件

        :param msg (str): 日志内容
        """
        if not self._enabled or self._log_path is None:
            return
        try:
            ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(f"[{ts}] {msg}\n")
        except Exception:
            pass

    def log(self, msg: str) -> None:
        """
        记录一条 Debug 日志

        :param msg (str): 日志内容
        """
        self._log(msg)

    def screenshot(self, page: Any, name: str, note: str = "") -> None:
        """
        截取当前页面全页截图并写入会话目录

        :param page (Any): 浏览器页面对象
        :param name (str): 截图文件名前缀
        :param note (str): 可选说明，写入日志
        """
        if not self._enabled or self._dir is None:
            return
        self._step += 1
        step_name = f"{self._step:02d}_{name}"
        try:
            url = page.url
        except Exception:
            url = "unknown"
        try:
            title = page.title()
        except Exception:
            title = "unknown"
        self._log(f"[截图] {step_name}" + (f" — {note}" if note else ""))
        self._log(f"  URL  : {url}")
        self._log(f"  Title: {title}")
        try:
            path = self._dir / f"{step_name}.png"
            page.screenshot(path=str(path), full_page=True, timeout=10000)
            self._log(f"  保存 : {path.name}")
        except Exception as e:
            self._log(f"  截图失败: {e}")

    def save_html(self, page: Any, name: str) -> None:
        """
        保存当前页面 HTML 到会话目录

        :param page (Any): 浏览器页面对象
        :param name (str): 输出文件名前缀（不含扩展名）
        """
        if not self._enabled or self._dir is None:
            return
        try:
            html = page.content()
            path = self._dir / f"{name}.html"
            path.write_text(html, encoding="utf-8")
            self._log(f"  HTML : {path.name} ({len(html)} 字节)")
        except Exception as e:
            self._log(f"  HTML 保存失败: {e}")

    def log_page_state(self, page: Any, tag: str = "") -> None:
        """
        记录当前页面 URL、标题及 Cloudflare 相关信号

        :param page (Any): 浏览器页面对象
        :param tag (str): 可选标签，便于在日志中区分阶段
        """
        if not self._enabled:
            return
        try:
            url = page.url
            title = page.title()
            self._log(f"[页面状态{' ' + tag if tag else ''}]")
            self._log(f"  URL  : {url}")
            self._log(f"  Title: {title}")
            cf_signals = self._detect_cf_signals(page)
            if cf_signals:
                self._log(f"  CF信号: {', '.join(cf_signals)}")
            else:
                self._log("  CF信号: 无")
        except Exception as e:
            self._log(f"  页面状态读取失败: {e}")

    @staticmethod
    def _detect_cf_signals(page: Any) -> list:
        """
        检测页面上是否存在 Cloudflare 挑战相关 DOM 或文案

        :param page (Any): 浏览器页面对象

        :return List: 检测到的信号描述列表
        """
        signals = []
        try:
            title = page.title()
            if any(
                k in title
                for k in (
                    "Just a moment",
                    "Checking your browser",
                    "Attention Required",
                )
            ):
                signals.append(f"可疑标题='{title}'")
        except Exception:
            pass
        cf_selectors = {
            "CF-iframe(challenges)": "iframe[src*='challenges.cloudflare.com']",
            "CF-iframe(cf)": "iframe[src*='cloudflare.com']",
            "CF-wrapper-div": "div#cf-wrapper",
            "CF-browser-verify": "div.cf-browser-verification",
            "CF-turnstile": "div.cf-turnstile",
            "CF-challenge": "div#challenge-form",
            "CF-ray-id": "[id*='cf-']",
        }
        for label, sel in cf_selectors.items():
            try:
                el = page.query_selector(sel)
                if el:
                    signals.append(label)
            except Exception:
                pass
        cf_texts = (
            "完成验证后签到",
            "请验证您是真人",
            "当前操作需要完成验证码验证后继续",
        )
        try:
            body_text = page.evaluate("() => document.body.innerText || ''")
            for t in cf_texts:
                if t in body_text:
                    signals.append(f"CF-modal-text='{t}'")
        except Exception:
            pass
        return signals

    def finalize(self, success: bool, result: str) -> None:
        """
        写入签到流程结束摘要

        :param success (bool): 签到是否成功

        :param result (str): 结果文案或错误信息
        """
        self._log(f"{'=' * 60}")
        self._log(f"签到结束: {'成功' if success else '失败'}")
        self._log(f"结果: {result}")
        self._log(f"{'=' * 60}")


@sentry_manager.capture_all_class_exceptions
class HDHivePlaywrightClient:
    """
    HDHive 站点浏览器自动化客户端

    运行时自动选择 cloakbrowser（新版 MoviePilot）或 Playwright Chromium（旧版 MoviePilot）
    """

    DEFAULT_BASE_URL = "https://hdhive.com"
    LOGIN_PAGE = "/login"
    _CHROME_UA_SUFFIX = (
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
    )
    _COOKIE_FILENAME = "hdhive_cookies.json"

    def __init__(self, headless: bool = True) -> None:
        """
        :param headless (bool): 浏览器是否无头模式
        """
        self._headless = headless
        self._cookie_str: Optional[str] = None
        self._username: str = ""
        self._password: str = ""

    @staticmethod
    def _check_backend() -> str:
        """
        检测可用的浏览器后端，优先返回 cloakbrowser

        :return str: 'cloakbrowser' 或 'playwright'

        :raises RuntimeError: 两者均不可用时
        """
        if _CLOAKBROWSER_AVAILABLE:
            return "cloakbrowser"
        if _PLAYWRIGHT_AVAILABLE:
            return "playwright"
        raise RuntimeError(
            "浏览器登录需要 cloakbrowser 或 playwright，"
            "但当前环境中两者均未安装。"
            "新版 MoviePilot 请确认已安装 cloakbrowser；"
            "旧版 MoviePilot 请运行 playwright install 下载浏览器内核"
        )

    @staticmethod
    def _platform_product_and_hint() -> tuple[str, str]:
        """
        根据当前运行平台返回 UA product 字段和 Sec-Ch-Ua-Platform 值

        :return Tuple: (UA product 字符串, Sec-Ch-Ua-Platform 值)
        """
        m = _machine().lower()
        arm_like = "arm" in m or "aarch" in m
        if platform == "linux":
            arch = "aarch64" if arm_like else "x86_64"
            return f"X11; Linux {arch}", '"Linux"'
        elif platform == "win32":
            product = (
                "Windows NT 10.0; ARM64" if arm_like else "Windows NT 10.0; Win64; x64"
            )
            return product, '"Windows"'
        else:
            return "Macintosh; Intel Mac OS X 10_15_7", '"macOS"'

    @staticmethod
    def _build_ua() -> str:
        """
        构造与当前运行平台匹配的 Chrome User-Agent（用于 httpx 请求）

        :return str: UA 字符串
        """
        product, _ = HDHivePlaywrightClient._platform_product_and_hint()
        return f"Mozilla/5.0 ({product}) {HDHivePlaywrightClient._CHROME_UA_SUFFIX}"

    @staticmethod
    def _build_browser_ua_and_hints(chrome_major: str) -> tuple[str, Dict[str, str]]:
        """
        根据实际 Chromium 版本构建与平台一致的 UA 和 Sec-Ch-Ua 系列请求头

        :param chrome_major (str): Chromium 主版本号字符串（如 "135"）
        :return Tuple: (UA 字符串, extra_http_headers 字典)
        """
        product, platform_hint = HDHivePlaywrightClient._platform_product_and_hint()
        ua = (
            f"Mozilla/5.0 ({product}) "
            f"AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{chrome_major}.0.0.0 Safari/537.36"
        )
        hints: Dict[str, str] = {
            "Sec-Ch-Ua": (
                f'"Chromium";v="{chrome_major}", '
                f'"Not.A/Brand";v="8", '
                f'"Google Chrome";v="{chrome_major}"'
            ),
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": platform_hint,
        }
        return ua, hints

    @staticmethod
    def _stealth_init_script() -> str:
        """
        构造在每个页面启动前注入的反检测脚本（仅用于 playwright 后端）

        - 清除 navigator.webdriver
        - 伪造 plugins / languages
        - 注入 window.chrome
        - 从 navigator.userAgentData.brands 移除 HeadlessChrome
        - 同步 patch getHighEntropyValues 返回值

        :return str: JS 字符串
        """
        return """
            try { Object.defineProperty(navigator, 'webdriver', {get: () => undefined}); } catch(e) {}
            try { Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5].map(() => ({}))
            }); } catch(e) {}
            try { Object.defineProperty(navigator, 'languages', {
                get: () => ['zh-CN', 'zh', 'en-US', 'en']
            }); } catch(e) {}
            window.chrome = window.chrome || { runtime: {} };
            (function() {
                const origUAD = navigator.userAgentData;
                if (!origUAD) return;
                const isHeadless = b => /headless/i.test(b.brand);
                const cleanBrands = origUAD.brands.filter(b => !isHeadless(b));
                const fake = {
                    get brands() { return cleanBrands; },
                    get mobile() { return origUAD.mobile; },
                    get platform() { return origUAD.platform; },
                    getHighEntropyValues(hints) {
                        return origUAD.getHighEntropyValues(hints).then(v => {
                            if (v && v.brands) v.brands = v.brands.filter(b => !isHeadless(b));
                            if (v && v.fullVersionList) v.fullVersionList = v.fullVersionList.filter(b => !isHeadless(b));
                            return v;
                        });
                    },
                    toJSON() {
                        return { brands: cleanBrands, mobile: origUAD.mobile, platform: origUAD.platform };
                    }
                };
                try {
                    Object.defineProperty(Navigator.prototype, 'userAgentData', {
                        get: () => fake, configurable: true
                    });
                    return;
                } catch(e) {}
                try {
                    Object.defineProperty(navigator, 'userAgentData', {
                        get: () => fake, configurable: true
                    });
                    return;
                } catch(e) {}
                try {
                    Object.defineProperty(origUAD, 'brands', {
                        get: () => cleanBrands, configurable: true
                    });
                } catch(e) {}
            })();
            const origQuery = window.navigator.permissions && window.navigator.permissions.query;
            if (origQuery) {
                window.navigator.permissions.query = (parameters) => (
                    parameters.name === 'notifications'
                        ? Promise.resolve({ state: Notification.permission })
                        : origQuery.call(window.navigator.permissions, parameters)
                );
            }
        """

    @staticmethod
    def _install_request_header_sanitizer(
        context: BrowserContext, chrome_major: str
    ) -> None:
        """
        在 BrowserContext 上拦截所有出站请求，强制清理 sec-ch-ua 系列头（仅用于 playwright 后端）

        - sec-ch-ua / sec-ch-ua-full-version-list 中的 HeadlessChrome 项替换为 Google Chrome
        - 用作 extra_http_headers 的兜底（部分 Chromium 行为不受 extra_http_headers 覆盖）

        :param context (BrowserContext): BrowserContext
        :param chrome_major (str): Chromium 主版本号
        """
        sec_ch_ua = (
            f'"Chromium";v="{chrome_major}", '
            f'"Not.A/Brand";v="8", '
            f'"Google Chrome";v="{chrome_major}"'
        )

        def _sanitize(route, request) -> None:
            try:
                headers = dict(request.headers)
                stripped = False
                for key in list(headers.keys()):
                    lower = key.lower()
                    if lower == "sec-ch-ua":
                        headers[key] = sec_ch_ua
                        stripped = True
                    elif lower == "sec-ch-ua-full-version-list":
                        if "headless" in headers[key].lower():
                            headers.pop(key)
                            stripped = True
                if stripped:
                    route.continue_(headers=headers)
                else:
                    route.continue_()
            except Exception:
                try:
                    route.continue_()
                except Exception:
                    pass

        context.route("**/*", _sanitize)

    @staticmethod
    def _chromium_launch_args() -> list[str]:
        """
        返回 Chromium 进程启动参数（仅用于 playwright 后端）

        :return List: 传给 chromium.launch(args=...) 的参数列表
        """
        args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
        ]
        if platform == "linux":
            args.extend(
                [
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-gpu",
                    "--disable-software-rasterizer",
                ]
            )
        return args

    @staticmethod
    def _proxy_url_from_settings() -> Optional[str]:
        """
        从 settings.PROXY 得到单一代理 URL 字符串

        :return str: http(s)://... 或 socks5://... 字符串，未配置或无法解析时为 None
        """
        p = settings.PROXY
        if not p:
            return None
        if isinstance(p, str):
            return p
        if isinstance(p, dict):
            u = p.get("https") or p.get("http")
            return str(u) if u else None
        return None

    @staticmethod
    def _playwright_proxy_settings() -> Optional[Dict[str, str]]:
        """
        将 MoviePilot settings.PROXY 转为 playwright chromium.launch 的 proxy 参数字典

        不含认证的 SOCKS5 可直接传给 playwright；含认证的 SOCKS5 须经由 slippers 转发

        :return Dict: 含 server，可选 username / password 的字典；无代理时为 None
        """
        raw = HDHivePlaywrightClient._proxy_url_from_settings()
        if not raw:
            return None
        u = urlparse(raw)
        if not u.scheme or not u.hostname:
            return None
        if u.scheme in ("socks5", "socks") and (u.username or u.password):
            return None
        port = u.port
        if port is None:
            port = 443 if u.scheme == "https" else 80
        server = f"{u.scheme}://{u.hostname}:{port}"
        pw: Dict[str, str] = {"server": server}
        if u.username:
            pw["username"] = unquote(u.username)
        if u.password:
            pw["password"] = unquote(u.password)
        return pw

    @staticmethod
    @contextmanager
    def _slippers_proxy_if_needed() -> Iterator[Optional[str]]:
        """
        若全局代理使用 Playwright/Chromium 不原生支持的协议，在本机启动 slippers 转发

        需要转发的情况：

        - ``socks4``：Chromium 不支持此协议
        - 带认证的 ``socks5``：Playwright 会拒绝；cloakbrowser 通过 ``--proxy-server``
          传入时 Chromium 会静默丢弃凭据并 fallback 到直连
          （参见 CloakHQ/CloakBrowser#157）

        :yield: slippers 本地代理 URL 字符串；不需要转发时为 None
        """
        raw = HDHivePlaywrightClient._proxy_url_from_settings()
        if not raw:
            yield None
            return
        u = urlparse(raw)
        if not u.scheme or not u.hostname:
            yield None
            return
        if u.scheme in ("http", "https"):
            yield None
            return
        if u.scheme in ("socks5", "socks") and not (u.username or u.password):
            yield None
            return
        if not _SLIPPERS_AVAILABLE:
            yield None
            return
        sock = socket(AF_INET, SOCK_STREAM)
        try:
            sock.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", 0))
            local_port = sock.getsockname()[1]
        finally:
            sock.close()
        sp = _SocksProxy(raw, host="127.0.0.1", port=local_port)
        with sp:
            yield sp.url()

    @staticmethod
    def _chromium_launch_kwargs(
        headless: bool, proxy: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        组装 chromium.launch 参数（仅用于 playwright 后端）

        - 用 channel="chromium" 强制使用完整 Chromium 二进制（新 headless 模式），
          避免 chromium-headless-shell 暴露 HeadlessChrome brand

        :param headless (bool): 是否无头模式
        :param proxy (Dict): 已解析的 playwright proxy 字典；为 None 时不设置
        :return Dict: 传给 launch 的关键字参数
        """
        kwargs: Dict[str, Any] = {
            "headless": headless,
            "channel": "chromium",
            "args": HDHivePlaywrightClient._chromium_launch_args(),
        }
        if proxy:
            kwargs["proxy"] = proxy
        return kwargs

    @staticmethod
    def _make_playwright_context(
        pw: Playwright,
        headless: bool,
        proxy: Optional[Dict[str, str]] = None,
    ) -> tuple[Browser, BrowserContext]:
        """
        playwright 后端：启动 Chromium 并创建登录页用上下文（语言、时区、视口）

        :param pw (Playwright): sync_playwright() 返回的 Playwright 实例
        :param headless (bool): 是否无头模式
        :param proxy (Dict): 已解析的 playwright proxy 字典
        :return Tuple: (browser, context)
        """
        browser = pw.chromium.launch(
            **HDHivePlaywrightClient._chromium_launch_kwargs(headless, proxy),
        )
        major = browser.version.split(".")[0]
        ua, hints = HDHivePlaywrightClient._build_browser_ua_and_hints(major)
        context = browser.new_context(
            user_agent=ua,
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            viewport={"width": 1280, "height": 720},
            extra_http_headers=hints,
        )
        context.add_init_script(HDHivePlaywrightClient._stealth_init_script())
        HDHivePlaywrightClient._install_request_header_sanitizer(context, major)
        return browser, context

    @staticmethod
    def _make_cloak_context(
        headless: bool, proxy_override: Optional[str] = None
    ) -> Any:
        """
        cloakbrowser 后端：创建浏览器上下文

        cloakbrowser 内置指纹伪装，无需手动注入 stealth 脚本或拦截请求头；
        socks4、带认证的 socks5 等 Chromium 不原生支持的协议请通过
        :meth:`_slippers_proxy_if_needed` 转发后将本地 URL 以
        ``proxy_override`` 传入。

        :param headless (bool): 是否无头模式
        :param proxy_override (str): 覆盖全局代理的本地代理 URL（如 slippers 转发地址）；
                               为 None 时从 settings 读取
        :return Any: playwright BrowserContext（由 cloakbrowser 内部创建）
        """
        proxy = (
            proxy_override
            if proxy_override is not None
            else HDHivePlaywrightClient._proxy_url_from_settings()
        )
        humanize: bool = getattr(settings, "CLOAKBROWSER_HUMANIZE", True)
        human_preset: Optional[str] = getattr(
            settings, "CLOAKBROWSER_HUMAN_PRESET", None
        )
        kwargs: Dict[str, Any] = {
            "headless": headless,
            "humanize": humanize,
        }
        if proxy:
            kwargs["proxy"] = proxy
        if human_preset:
            kwargs["human_preset"] = human_preset
        return _cloak_launch_context(**kwargs)

    @contextmanager
    def _fresh_context(self) -> Iterator[Any]:
        """
        创建空白浏览器上下文，自动选择 cloakbrowser / playwright 后端并处理代理

        :yield: 浏览器上下文（playwright BrowserContext）
        """
        backend = self._check_backend()
        with self._slippers_proxy_if_needed() as slip_url:
            if backend == "cloakbrowser":
                context = self._make_cloak_context(
                    self._headless, proxy_override=slip_url
                )
                try:
                    yield context
                finally:
                    context.close()
            else:
                with sync_playwright() as p:
                    proxy = (
                        {"server": slip_url}
                        if slip_url is not None
                        else self._playwright_proxy_settings()
                    )
                    browser, context = self._make_playwright_context(
                        p, self._headless, proxy
                    )
                    try:
                        yield context
                    finally:
                        browser.close()

    @contextmanager
    def _page_with_cookies(self, cookies: Dict[str, str], domain: str) -> Iterator[Any]:
        """
        创建已注入 Cookie 的浏览器页面，自动管理上下文生命周期

        :param cookies (Dict): name → value Cookie 映射
        :param domain (str): Cookie 所属域名
        :yields Any: 已注入 Cookie 的页面对象
        """
        with self._fresh_context() as context:
            self._inject_cookies(context, cookies, domain)
            yield context.new_page()

    @staticmethod
    def _inject_cookies(context: Any, cookies: Dict[str, str], domain: str) -> None:
        """
        将 Cookie 字典批量注入浏览器上下文

        :param context (Any): 浏览器上下文
        :param cookies (Dict): name → value 映射
        :param domain (str): Cookie 所属域名
        """
        context.add_cookies(
            [
                {"name": n, "value": v, "domain": domain, "path": "/"}
                for n, v in cookies.items()
            ]
        )

    @staticmethod
    def _parse_cookie_str(cookie_str: str) -> dict[str, str]:
        """
        解析 name=value; ... 格式的 Cookie 字符串

        :param cookie_str (str): Cookie 头字符串
        :return Dict: 名称到值的映射
        """
        cookies: dict[str, str] = {}
        for item in cookie_str.split(";"):
            if "=" in item:
                name, value = item.strip().split("=", 1)
                cookies[name.strip()] = value.strip()
        return cookies

    @classmethod
    def _cookie_file_path(cls) -> Path:
        """
        返回 HDHive Cookie 持久化文件路径

        :return Path: 插件数据目录下的 Cookie JSON 文件路径
        """
        return configer.PLUGIN_CONFIG_PATH / cls._COOKIE_FILENAME

    def _build_cookie_str_from_raw(
        self, raw_cookies: List[Dict[str, Any]]
    ) -> Optional[Tuple[str, str]]:
        """
        从浏览器原始 Cookie 列表中提取 token / csrf_access_token，
        组装 cookie_str 并写入持久化文件

        :param raw_cookies (List): context.cookies() 返回的 Cookie 字典列表
        :return Tuple: (cookie_str, token)；token 不存在时为 None
        """
        token = next((c["value"] for c in raw_cookies if c["name"] == "token"), None)
        csrf = next(
            (c["value"] for c in raw_cookies if c["name"] == "csrf_access_token"),
            None,
        )
        if not token:
            return None
        parts = [f"token={token}"]
        if csrf:
            parts.append(f"csrf_access_token={csrf}")
        self._cookie_str = "; ".join(parts)
        self._save_cookie_to_file()
        return self._cookie_str, token

    def _save_cookie_to_file(self) -> None:
        """
        将当前实例 Cookie 写入持久化文件
        """
        if not self._cookie_str:
            return
        try:
            path = self._cookie_file_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "cookie_str": self._cookie_str,
                "saved_at": datetime.now().isoformat(),
            }
            path.write_bytes(dumps(payload))
        except Exception:
            pass

    @classmethod
    def _load_cookie_from_file(cls) -> Optional[str]:
        """
        从持久化文件读取 Cookie 字符串

        :return str: cookie_str；文件不存在或解析失败时为 None
        """
        try:
            path = cls._cookie_file_path()
            if not path.exists():
                return None
            payload = loads(path.read_bytes())
            return payload.get("cookie_str") or None
        except Exception:
            return None

    def load_saved_cookie(self) -> Optional[str]:
        """
        从持久化文件加载上次保存的 Cookie，写入实例并返回 cookie_str

        :return str: cookie_str；文件不存在或无有效 token 时为 None
        """
        cookie_str = self._load_cookie_from_file()
        if not cookie_str:
            return None
        cookies = self._parse_cookie_str(cookie_str)
        if not cookies.get("token"):
            return None
        self._cookie_str = cookie_str
        return cookie_str

    def clear_saved_cookie(self) -> None:
        """
        清除实例内 Cookie 及持久化文件
        """
        self._cookie_str = None
        try:
            path = self._cookie_file_path()
            if path.exists():
                path.unlink()
        except Exception:
            pass

    def set_credentials(self, username: str, password: str) -> "HDHivePlaywrightClient":
        """
        存储账号密码，供 Cookie 过期时自动重新登录

        :param username (str): 账号或邮箱
        :param password (str): 密码
        :return Any: self（支持链式调用）
        """
        self._username = username.strip()
        self._password = password.strip()
        return self

    @staticmethod
    def _parse_jwt_exp(token: str) -> Optional[int]:
        """
        从 JWT token 字符串解析 ``exp`` 字段（UNIX 时间戳）

        :return int: 过期时间戳；无法解析时为 None
        """
        try:
            parts = token.split(".")
            if len(parts) != 3:
                return None
            payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
            payload = loads(urlsafe_b64decode(payload_b64))
            exp = payload.get("exp")
            return int(exp) if exp is not None else None
        except Exception:
            return None

    def _is_token_valid(self, buffer_secs: int = 300) -> bool:
        """
        检查当前 Cookie 中的 JWT token 是否仍在有效期内

        :param buffer_secs (int): 提前多少秒视为「即将过期」（默认 5 分钟）
        :return bool: 有效返回 True；过期、无 token 或无法解析返回 False
        """
        if not self._cookie_str:
            return False
        token = self._parse_cookie_str(self._cookie_str).get("token", "")
        if not token:
            return False
        exp = self._parse_jwt_exp(token)
        if exp is None:
            return True

        return time() + buffer_secs < exp

    def _relogin(self) -> bool:
        """
        使用存储的账号密码重新进行浏览器登录，成功后更新持久化 Cookie

        :return bool: 重新登录是否成功
        """
        if not self._username or not self._password:
            return False
        try:
            self.clear_saved_cookie()
            return (
                self.login(username=self._username, password=self._password) is not None
            )
        except Exception:
            return False

    def _execute_with_auth_retry(self, run: Callable[[], _T]) -> _T:
        """
        在 token 有效前提下执行浏览器任务，必要时自动重新登录并重试一次

        :param run (Callable): 单次浏览器会话 Callable
        :return Any: run() 的返回值
        :raises HDHiveLoginError: 认证失败且无法自动重新登录
        :raises HDHiveBrowserError: 浏览器操作失败
        """
        if not self._is_token_valid():
            if not self._relogin():
                raise HDHiveLoginError("Cookie 已过期，请配置账号密码以自动重新登录")

        try:
            return run()
        except HDHiveLoginError as e:
            if not e.login_redirect:
                raise
            if not self._relogin():
                raise HDHiveLoginError(
                    "Cookie 被服务器拒绝，无法自动重新登录（请检查账号密码）",
                ) from e
            return run()

    def _fill_and_submit(
        self,
        page: Any,
        username: str,
        password: str,
    ) -> bool:
        """
        打开登录页、填写账号密码并提交，等待离开 /login

        page API 与 playwright / cloakbrowser 均兼容

        :param page (Any): 浏览器页面对象
        :param username (str): 登录用户名或邮箱
        :param password (str): 登录密码
        :return bool: 若 URL 在超时内离开登录页则为 True
        :raises HDHiveLoginError: 等待跳转超时
        """
        root = HDHivePlaywrightClient.DEFAULT_BASE_URL
        page.goto(
            f"{root}{HDHivePlaywrightClient.LOGIN_PAGE}",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        try:
            page.wait_for_selector(
                "input[name='username'], input[name='password']", timeout=15000
            )
        except PlaywrightTimeoutError:
            raise HDHiveLoginError(f"等待登录输入框超时，当前 URL: {page.url}")

        user_selectors = [
            "input[name='username']",
            "input[name='email']",
            "input[type='email']",
            "input[placeholder*='邮箱']",
            "input[placeholder*='email']",
            "input[placeholder*='用户名']",
        ]
        for sel in user_selectors:
            try:
                if page.query_selector(sel):
                    page.fill(sel, username)
                    break
            except Exception:
                continue

        pwd_selectors = [
            "input[name='password']",
            "input[type='password']",
            "input[placeholder*='密码']",
        ]
        for sel in pwd_selectors:
            try:
                if page.query_selector(sel):
                    page.fill(sel, password)
                    break
            except Exception:
                continue

        sleep(0.5)
        submit_selectors = [
            "button[type='submit']",
            "button:has-text('登录')",
            "button:has-text('Login')",
        ]
        submitted = False
        for sel in submit_selectors:
            try:
                if page.query_selector(sel):
                    page.click(sel)
                    submitted = True
                    break
            except Exception:
                continue
        if not submitted:
            page.keyboard.press("Enter")

        try:
            page.wait_for_url(lambda url: "/login" not in url, timeout=30000)
            return True
        except PlaywrightTimeoutError:
            page_hint = ""
            try:
                page_hint = page.evaluate(
                    """() => {
                        const selectors = [
                            '[role="alert"]', '.error', '.alert', '.message',
                            '[class*="error"]', '[class*="alert"]', '[class*="Error"]',
                        ];
                        for (const sel of selectors) {
                            const el = document.querySelector(sel);
                            if (el) {
                                const t = (el.innerText || '').trim();
                                if (t) return t;
                            }
                        }
                        return '';
                    }"""
                )
            except Exception:
                pass
            hint = f"，错误提示: {page_hint}" if page_hint else ""
            raise HDHiveLoginError(
                f"登录超时，当前 URL: {page.url}，页面标题: {page.title()}{hint}"
            )

    @staticmethod
    def _parse_checkin_result_text(text: str, label: str) -> Tuple[bool, str]:
        """
        根据签到结果弹窗文本判断签到是否成功，并返回干净的展示文案

        :param text (str): 签到结果弹窗文本
        :param label (str): 签到类型（赌狗签到或每日签到）

        :return Tuple: (是否成功, 展示用文案或错误信息)
        """
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        clean = " ".join(lines)

        already_keywords = ("已经签到", "签到过", "明天再来")
        fail_keywords = ("失败", "错误", "error", "failed")

        if any(k in clean for k in already_keywords):
            body_lines = [
                ln
                for ln in lines
                if not any(
                    ln == kw or ln.startswith("签到") and "失败" in ln
                    for kw in ("签到失败",)
                )
            ]
            display = " ".join(body_lines) if body_lines else clean
            return True, f"今日已签到：{display}"

        if any(k in clean.lower() for k in fail_keywords):
            return False, clean

        return True, clean

    @staticmethod
    def _find_checkin_btn_by_font_decode(
        page: Any,
        label: str,
        debug: "_CheckinDebugSession",
    ) -> Optional[Any]:
        """
        字体解码兜底：通过浏览器 canvas 逐字渲染比对，在保护字体混淆的菜单中定位目标按钮

        站点用 protected-action 自定义字体把菜单文本映射到 PUA 字符，且每次打开菜单位置随机，
        此方法用浏览器自身渲染能力对 PUA 字符和候选汉字做像素 MSE 比对，无需外部库或参考字体文件

        :param page: 浏览器页面对象
        :param label (str): 目标签到标签（「每日签到」或「赌狗签到」）
        :param debug: Debug 会话
        :return: ElementHandle（找到的按钮）；失败时为 None
        """
        try:
            font_family: Optional[str] = page.evaluate(
                """
                () => {
                    try {
                        for (const sheet of document.styleSheets) {
                            try {
                                for (const rule of sheet.cssRules) {
                                    if (rule.constructor.name !== 'CSSFontFaceRule') continue;
                                    const fam = rule.style.getPropertyValue('font-family')
                                        .replace(/['"]/g, '').trim();
                                    if (fam.startsWith('protected-action')) return fam;
                                }
                            } catch (e) {}
                        }
                    } catch (e) {}
                    return null;
                }
                """
            )
            if not font_family:
                debug.log("  字体解码兜底：未找到 protected-action 字体声明")
                return None
            debug.log(f"  字体解码兜底：保护字体={font_family!r}  目标={label!r}")

            handle = page.evaluate_handle(
                """
                async ([label, fontFamily]) => {
                    // 收集所有含保护字体 span 的菜单按钮
                    const candidates = [];
                    for (const btn of document.querySelectorAll('button[type="button"]')) {
                        const span = btn.querySelector('span[style*="protected-action"]');
                        if (!span) continue;
                        const text = span.textContent;
                        if (!text || !text.trim()) continue;
                        candidates.push({ btn, text: text.trim() });
                    }
                    if (!candidates.length) return null;

                    const SIZE = 128, FS = 80;
                    const canvas = document.createElement('canvas');
                    canvas.width = SIZE; canvas.height = SIZE;
                    const ctx = canvas.getContext('2d', { willReadFrequently: true });

                    function renderChar(char, family) {
                        ctx.fillStyle = 'white';
                        ctx.fillRect(0, 0, SIZE, SIZE);
                        ctx.font = FS + 'px "' + family + '"';
                        ctx.fillStyle = 'black';
                        ctx.textAlign = 'center';
                        ctx.textBaseline = 'middle';
                        ctx.fillText(char, SIZE / 2, SIZE / 2);
                        const d = ctx.getImageData(0, 0, SIZE, SIZE).data;
                        const g = new Float32Array(SIZE * SIZE);
                        for (let i = 0; i < g.length; i++) g[i] = d[i * 4];
                        return g;
                    }

                    function mse(a, b) {
                        let s = 0;
                        for (let i = 0; i < a.length; i++) { const d = a[i] - b[i]; s += d * d; }
                        return s / a.length;
                    }

                    // 等待保护字体就绪
                    try { await document.fonts.load(FS + 'px "' + fontFamily + '"'); } catch (e) {}

                    const labelChars = Array.from(label);
                    // 用系统字体预渲染目标文本各字符
                    const refImgs = labelChars.map(ch => renderChar(ch, 'sans-serif'));

                    let bestBtn = null, bestScore = Infinity;
                    for (const { btn, text } of candidates) {
                        const puaChars = Array.from(text);
                        if (puaChars.length !== labelChars.length) continue;
                        let total = 0;
                        for (let i = 0; i < puaChars.length; i++) {
                            total += mse(renderChar(puaChars[i], fontFamily), refImgs[i]);
                        }
                        const score = total / puaChars.length;
                        if (score < bestScore) { bestScore = score; bestBtn = btn; }
                    }
                    return bestBtn;
                }
                """,
                [label, font_family],
            )
            elem = handle.as_element() if handle else None
            if elem:
                debug.log("  字体解码兜底：成功匹配签到按钮")
                return elem
            debug.log("  字体解码兜底：无候选按钮匹配（字符数不符或菜单未出现）")
            return None
        except Exception as e:
            debug.log(f"  字体解码兜底异常: {e}")
            return None

    def _checkin_via_browser(self, gamble: bool) -> Tuple[bool, str]:
        """
        模拟签到

        :param gamble (bool): True 为赌狗签到，False 为每日签到

        :return Tuple: (是否成功, 展示用文案或错误信息)
        """
        if not self._cookie_str:
            return False, "请先 login 或传入 Cookie"

        root = self.DEFAULT_BASE_URL
        cookies = self._parse_cookie_str(self._cookie_str)
        domain = root.replace("https://", "").replace("http://", "")
        label = "赌狗签到" if gamble else "每日签到"

        debug = _CheckinDebugSession(label)
        backend = self._check_backend()
        proxy_url = self._proxy_url_from_settings()
        debug.log(f"后端: {backend}")
        debug.log(f"代理配置: {proxy_url if proxy_url else '无'}")
        debug.log(f"Cookie 数量: {len(cookies)}  键名: {list(cookies.keys())}")
        debug.log(f"headless: {self._headless}")

        def _do_checkin(page: Any) -> Tuple[bool, str]:
            debug.log(f"导航到主页: {root}")
            page.goto(root, wait_until="domcontentloaded", timeout=30000)
            debug.screenshot(page, "homepage", "主页加载完毕")
            debug.log_page_state(page, "主页")

            debug.log("检测关闭弹窗按钮（'我知道了'）")
            try:
                dismiss_loc = page.locator("button:has-text('我知道了')")
                dismiss_loc.first.wait_for(state="visible", timeout=8000)
                debug.log("发现关闭弹窗按钮，开始关闭")
                debug.screenshot(page, "dismiss_btn_visible", "关闭弹窗按钮出现")
                for attempt in range(20):
                    try:
                        dismiss_loc.first.click()
                        debug.log(f"  第 {attempt + 1} 次点击关闭弹窗")
                    except Exception as e:
                        debug.log(f"  第 {attempt + 1} 次点击关闭弹窗失败: {e}")
                    try:
                        dismiss_loc.first.wait_for(state="hidden", timeout=1500)
                        debug.log("  弹窗已关闭")
                        break
                    except PlaywrightTimeoutError:
                        sleep(1)
                debug.screenshot(page, "after_dismiss", "关闭弹窗后")
            except Exception as e:
                debug.log(f"未检测到关闭弹窗或已关闭: {e}")
                debug.screenshot(page, "no_dismiss_btn", "无关闭弹窗按钮")

            debug.log("开始查找头像按钮")
            clicked_avatar = False
            for avatar_sel, force in (
                ("button:has(div.MuiAvatar-root)", False),
                ("div.MuiAvatar-root", True),
            ):
                try:
                    debug.log(f"  尝试头像选择器: {avatar_sel}  force={force}")
                    page.wait_for_selector(avatar_sel, timeout=15000)
                    debug.log("  头像元素已找到，准备点击")
                    debug.screenshot(
                        page, "before_avatar_click", f"点击头像前 ({avatar_sel})"
                    )
                    page.click(avatar_sel, force=force)
                    clicked_avatar = True
                    debug.log("  头像点击成功")
                    debug.screenshot(
                        page, "after_avatar_click", "头像点击后（菜单应出现）"
                    )
                    break
                except PlaywrightTimeoutError:
                    debug.log(f"  头像选择器超时: {avatar_sel}")
                    debug.log_page_state(page, f"头像超时({avatar_sel})")
                    continue
                except Exception as e:
                    debug.log(f"  头像选择器异常: {avatar_sel}  错误: {e}")
                    continue

            if not clicked_avatar:
                debug.log("所有头像选择器均失败！")
                debug.screenshot(page, "avatar_all_failed", "头像查找全部失败")
                debug.save_html(page, "avatar_all_failed")
                return False, "等待头像按钮超时，可能未登录成功"

            # SVG 图标识别
            _CHECKIN_SVG_ANCHOR = {
                False: "M6.96 2c.418",  # 每日签到 — 日历+号图标
                True: "M216 64v128",  # 赌狗签到 — 方块图标
            }
            anchor = _CHECKIN_SVG_ANCHOR[gamble]
            debug.log(f"等待签到按钮出现 (SVG图标识别, 锚点={anchor!r})")
            btn_loc = page.locator(f"button:has(path[d^='{anchor}'])")
            btn_elem = None
            try:
                btn_loc.first.wait_for(state="visible", timeout=15000)
                debug.log("签到按钮已出现（SVG图标匹配）")
                debug.screenshot(page, "checkin_btn_visible", f"签到按钮可见: {label}")
            except PlaywrightTimeoutError:
                debug.log("SVG图标超时，启动字体解码兜底...")
                debug.screenshot(
                    page, "checkin_btn_svg_timeout", "SVG匹配超时，尝试字体解码"
                )
                btn_elem = HDHivePlaywrightClient._find_checkin_btn_by_font_decode(
                    page, label, debug
                )
                if btn_elem is None:
                    debug.log("字体解码兜底失败，签到流程终止")
                    debug.screenshot(page, "checkin_btn_timeout", "签到按钮等待超时")
                    debug.save_html(page, "checkin_btn_timeout")
                    return False, f"等待{label}按钮超时，用户菜单未出现"
                btn_loc = None
                debug.screenshot(
                    page, "checkin_btn_found_by_font", "字体解码找到签到按钮"
                )

            debug.log("等待签到按钮位置稳定（bounding box）")
            _prev_box: dict = {}
            for i in range(20):
                try:
                    _box = (
                        btn_loc.first.bounding_box()
                        if btn_loc
                        else btn_elem.bounding_box()
                    ) or {}
                except Exception:
                    _box = {}
                if _box and _box == _prev_box:
                    debug.log(f"  按钮位置稳定（第 {i + 1} 次检测）: {_box}")
                    break
                _prev_box = _box
                sleep(0.1)

            debug.log("安装 MutationObserver 监听签到结果弹窗")
            page.evaluate("""
                () => {
                    window.__checkinResult = null;
                    const resultPhrases = [
                        '签到成功', '签到失败', '已经签到', '明天再来',
                        '获得积分', '签到奖励', '积分+', '赌狗签到成功', '赌狗签到失败'
                    ];
                    const seen = new WeakSet();
                    const obs = new MutationObserver((mutations) => {
                        if (window.__checkinResult) return;
                        for (const mut of mutations) {
                            for (const node of mut.addedNodes) {
                                if (node.nodeType !== 1 || seen.has(node)) continue;
                                seen.add(node);
                                const candidates = [node, ...node.querySelectorAll('*')];
                                for (const el of candidates) {
                                    const t = (el.innerText || '').trim();
                                    if (!t || t.length >= 300) continue;
                                    if (resultPhrases.some(p => t.includes(p))) {
                                        window.__checkinResult = t;
                                        obs.disconnect();
                                        return;
                                    }
                                }
                            }
                        }
                    });
                    obs.observe(document.body, { childList: true, subtree: true });
                }
            """)

            debug.log("点击签到按钮")
            if btn_loc:
                btn_loc.first.click()
            else:
                btn_elem.click()
            debug.screenshot(page, "after_checkin_click", "签到按钮点击后")

            cf_container_sel = "div#cf-turnstile"
            cf_iframe_sel = "iframe[src*='challenges.cloudflare.com']"

            debug.log("第一阶段：等待 CF 挑战容器 div#cf-turnstile (15s)")
            cf_container_found = False
            try:
                page.wait_for_selector(cf_container_sel, timeout=15000)
                cf_container_found = True
                debug.log("【CF挑战】检测到 CF 容器，等待 iframe 异步加载 (15s)")
                debug.screenshot(page, "cf_container_detected", "CF容器已出现")
                debug.log_page_state(page, "CF容器")
                debug.save_html(page, "cf_container_detected")
            except PlaywrightTimeoutError:
                debug.log("未检测到 CF 容器（正常情况）")

            if cf_container_found:
                cf_retry_sel = "button:has-text('重新验证')"
                cf_iframe_found = False
                cf_retry_found = False
                debug.log("第二阶段：等待 CF iframe 或重新验证按钮 (15s)")
                deadline = 15000
                step_ms = 500
                waited = 0
                while waited < deadline:
                    try:
                        el = page.query_selector(cf_iframe_sel)
                        if el:
                            cf_iframe_found = True
                            debug.log(f"  CF iframe 出现 (waited={waited}ms)")
                            break
                    except Exception:
                        pass
                    try:
                        el = page.query_selector(cf_retry_sel)
                        if el:
                            cf_retry_found = True
                            debug.log(f"  CF 重新验证按钮出现 (waited={waited}ms)")
                            break
                    except Exception:
                        pass
                    page.wait_for_timeout(step_ms)
                    waited += step_ms

                debug.screenshot(
                    page,
                    "cf_phase2_result",
                    f"第二阶段结果 iframe={cf_iframe_found} revalidate={cf_retry_found}",
                )
                debug.log_page_state(page, "CF第二阶段")
                debug.save_html(page, "cf_phase2_result")

                if cf_iframe_found:
                    debug.log("【CF挑战】CF iframe 已加载，开始尝试点击")
                    cf_frame = page.frame_locator(cf_iframe_sel)
                    cf_click_success = False
                    for cf_sel in (
                        "input[type='checkbox']",
                        "[class*='ctp-checkbox']",
                        ".mark",
                        "label",
                    ):
                        try:
                            debug.log(f"  尝试 CF 选择器: {cf_sel}")
                            cf_frame.locator(cf_sel).click(timeout=5000)
                            debug.log(f"  CF 选择器点击成功: {cf_sel}")
                            cf_click_success = True
                            sleep(0.5)
                            debug.screenshot(
                                page, "after_cf_click", f"CF点击后 (sel={cf_sel})"
                            )
                            break
                        except Exception as e:
                            debug.log(f"  CF 选择器失败: {cf_sel}  错误: {e}")

                    if not cf_click_success:
                        debug.log("【CF挑战】所有 CF 选择器均失败，CF 可能未被解决！")
                        debug.screenshot(
                            page, "cf_click_all_failed", "CF所有选择器失败"
                        )

                    debug.log("等待 CF iframe 消失（验证通过），超时 30s")
                    try:
                        page.wait_for_selector(
                            cf_iframe_sel, state="hidden", timeout=30000
                        )
                        debug.log("CF iframe 已消失，验证通过")
                        debug.screenshot(page, "cf_resolved", "CF验证通过后")
                    except PlaywrightTimeoutError:
                        debug.log(
                            "【CF挑战】等待 CF iframe 消失超时，CF 验证可能未通过！"
                        )
                        debug.screenshot(page, "cf_not_resolved", "CF验证未通过超时")
                        debug.log_page_state(page, "CF未通过")
                        debug.save_html(page, "cf_not_resolved")

                elif cf_retry_found:
                    debug.log("【CF挑战】Turnstile 首次验证失败，点击重新验证按钮")
                    try:
                        page.click(cf_retry_sel)
                        debug.log("  重新验证按钮点击成功")
                        sleep(1)
                        debug.screenshot(page, "after_cf_retry", "CF重新验证按钮点击后")
                    except Exception as e:
                        debug.log(f"  重新验证按钮点击失败: {e}")

                    debug.log("等待 Turnstile token 写入（验证通过），超时 30s")
                    token_sel = "input[name='cf-turnstile-response']"
                    token_set = False
                    deadline2 = 30000
                    waited2 = 0
                    while waited2 < deadline2:
                        try:
                            val = page.eval_on_selector(
                                token_sel, "el => el.value", timeout=500
                            )
                            if val:
                                token_set = True
                                debug.log(
                                    f"  Turnstile token 已写入 (waited={waited2}ms) token[:20]={val[:20]}..."
                                )
                                break
                        except Exception:
                            pass
                        page.wait_for_timeout(step_ms)
                        waited2 += step_ms

                    if token_set:
                        debug.log("Turnstile 验证通过，继续等待签到结果")
                        debug.screenshot(
                            page, "cf_token_received", "Turnstile token已获取"
                        )
                    else:
                        debug.log(
                            "【CF挑战】30s 内未获得 Turnstile token，验证可能未通过"
                        )
                        debug.screenshot(page, "cf_token_timeout", "等待token超时")
                        debug.log_page_state(page, "token超时")
                        debug.save_html(page, "cf_token_timeout")

                else:
                    debug.log("【CF挑战】15s 内既无 iframe 也无重新验证按钮")
                    debug.screenshot(page, "cf_unknown_state", "CF状态未知")
                    debug.log_page_state(page, "CF未知状态")
                    debug.save_html(page, "cf_unknown_state")

                    widget_token_sel = "input[name='cf-turnstile-response']"
                    try:
                        existing_val = page.eval_on_selector(
                            widget_token_sel, "el => el.value", timeout=1000
                        )
                        if existing_val:
                            debug.log("  Token 已存在，直接进入结果轮询")
                        else:
                            debug.log(
                                "  Widget 已初始化但 token 为空，Turnstile 验证请求静默挂起，"
                                "尝试 JS reset 触发重新验证"
                            )
                            try:
                                page.click("div#cf-turnstile", force=True)
                                debug.log("  已点击 Turnstile 容器")
                                sleep(0.5)
                                debug.screenshot(
                                    page, "cf_container_nudge", "Turnstile容器点击后"
                                )
                            except Exception as e:
                                debug.log(f"  容器点击失败: {e}")

                            try:
                                reset_result = page.evaluate(
                                    """() => {
                                        if (window.turnstile) {
                                            turnstile.reset('#cf-turnstile');
                                            return 'reset called';
                                        }
                                        return 'turnstile not available';
                                    }"""
                                )
                                debug.log(f"  Turnstile JS reset: {reset_result}")
                                sleep(1)
                                debug.screenshot(
                                    page, "cf_after_js_reset", "Turnstile JS reset后"
                                )
                            except Exception as e:
                                debug.log(f"  Turnstile JS reset 失败: {e}")

                            debug.log("等待 Turnstile token 写入（验证通过），超时 30s")
                            token_set = False
                            waited3 = 0
                            while waited3 < 30000:
                                try:
                                    val = page.eval_on_selector(
                                        widget_token_sel, "el => el.value", timeout=500
                                    )
                                    if val:
                                        token_set = True
                                        debug.log(
                                            f"  Token 写入成功 (waited={waited3}ms)"
                                        )
                                        break
                                except Exception:
                                    pass
                                page.wait_for_timeout(step_ms)
                                waited3 += step_ms

                            if not token_set:
                                debug.log(
                                    "  30s 内 token 未写入，Cloudflare Turnstile 验证无法完成。"
                                    "可能原因：浏览器指纹被识别为机器人、代理未正确路由 challenges.cloudflare.com 流量。"
                                )
                                debug.screenshot(
                                    page, "cf_mode_c_timeout", "ModeC超时无token"
                                )
                                debug.save_html(page, "cf_mode_c_timeout")
                    except Exception:
                        debug.log(
                            "  Widget 未初始化（cf-turnstile 为空），Turnstile JS 未运行"
                        )

            else:
                cf_signals = _CheckinDebugSession._detect_cf_signals(page)
                if cf_signals:
                    debug.log(
                        f"【警告】未检测到 CF 容器，但页面有 CF 信号: {cf_signals}"
                    )
                    debug.screenshot(
                        page, "cf_signals_no_container", "有CF信号但无容器"
                    )
                    debug.save_html(page, "cf_signals_no_container")

            debug.log("开始轮询签到结果（最长 60s）")
            _RESULT_PHRASES = [
                "签到成功",
                "签到失败",
                "已经签到",
                "明天再来",
                "获得积分",
                "签到奖励",
                "积分+",
            ]
            _SCAN_JS = (
                "() => {"
                "  const t = document.body.innerText || '';"
                "  const phrases = " + str(_RESULT_PHRASES) + ";"
                "  const hit = phrases.find(p => t.includes(p));"
                "  if (!hit) return null;"
                "  const idx = t.indexOf(hit);"
                "  return t.slice(Math.max(0, idx - 10), idx + 80).trim();"
                "}"
            )
            deadline_ms = 60000
            interval_ms = 500
            elapsed = 0
            result_text = None
            _screenshot_interval = 5000
            _last_screenshot_at = 0
            while elapsed < deadline_ms:
                captured = page.evaluate("() => window.__checkinResult")
                if captured:
                    result_text = str(captured)
                    debug.log(
                        f"MutationObserver 捕获结果 (elapsed={elapsed}ms): {result_text!r}"
                    )
                    break
                scanned = page.evaluate(_SCAN_JS)
                if scanned:
                    result_text = str(scanned)
                    debug.log(
                        f"页面扫描捕获结果 (elapsed={elapsed}ms): {result_text!r}"
                    )
                    break

                if elapsed - _last_screenshot_at >= _screenshot_interval:
                    debug.screenshot(
                        page, f"poll_{elapsed // 1000}s", f"轮询中 {elapsed // 1000}s"
                    )
                    _last_screenshot_at = elapsed

                page.wait_for_timeout(interval_ms)
                elapsed += interval_ms

            if result_text:
                debug.log(f"原始结果文本: {result_text!r}")
                ok, msg = HDHivePlaywrightClient._parse_checkin_result_text(
                    result_text, label
                )
                debug.screenshot(
                    page, "final_result", f"签到{'成功' if ok else '失败'}: {msg}"
                )
                return ok, msg

            debug.log("轮询超时，未捕获到任何签到结果文本")
            debug.screenshot(page, "result_timeout", "等待签到结果超时")
            debug.log_page_state(page, "结果超时")
            debug.save_html(page, "result_timeout")
            return False, f"{label}：等待结果超时"

        try:
            with self._page_with_cookies(cookies, domain) as page:
                result = _do_checkin(page)
        except PlaywrightTimeoutError as e:
            result = (False, f"{label}操作超时: {e}")
        except Exception as e:
            result = (False, f"{label}浏览器签到失败: {e}")

        debug.finalize(*result)
        return result

    def checkin(self, gamble: bool) -> Tuple[bool, str]:
        """
        签到

        :param gamble (bool): True 为赌狗签到，False 为每日签到
        :return Tuple: (是否成功, 展示用文案或错误信息)
        """
        return self._checkin_via_browser(gamble)

    def _do_login(self, username: str, password: str) -> Optional[Tuple[str, str]]:
        """
        浏览器登录：自动选择 cloakbrowser 或 playwright 后端

        :param username (str): 登录用户名或邮箱
        :param password (str): 登录密码
        :return Tuple: (完整 Cookie 字符串, token)，登录失败为 None
        :raises HDHiveLoginError: 登录超时或表单交互失败
        """
        with self._fresh_context() as context:
            page = context.new_page()
            ok = self._fill_and_submit(page, username, password)
            raw_cookies = context.cookies()
        if not ok:
            return None
        return self._build_cookie_str_from_raw(raw_cookies)

    def login(
        self,
        cookie_str: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> Optional[Tuple[str, str]]:
        """
        使用 Cookie 登录：传入 cookie_str 时写入实例并返回 (Cookie 字符串, token)

        浏览器登录：不传 cookie_str 时须传入 username 与 password，
        自动选择 cloakbrowser（新版 MoviePilot）或 playwright（旧版 MoviePilot）

        :param cookie_str (str): 已持有的 token=...; csrf_access_token=... 等 Cookie 串
        :param username (str): 浏览器登录用用户名或邮箱
        :param password (str): 浏览器登录用密码
        :return Tuple: (完整 Cookie 字符串, token)，失败为 None
        :raises HDHiveLoginError: 登录参数无效或表单认证失败
        :raises HDHiveBrowserError: 浏览器登录过程失败
        """
        if cookie_str is not None:
            s = cookie_str.strip()
            if not s:
                return None
            self._cookie_str = s
            cookies = HDHivePlaywrightClient._parse_cookie_str(s)
            token = cookies.get("token")
            if not token:
                return None
            return s, token

        if not username or not password:
            raise HDHiveLoginError("未提供 cookie_str 时须传入 username 与 password")

        try:
            return self._do_login(username, password)
        except HDHiveError:
            raise
        except Exception as e:
            raise HDHiveBrowserError(f"登录失败: {e}") from e

    @staticmethod
    def _scrape_resource_cards_js() -> str:
        """
        返回从页面 DOM 提取 115网盘 资源卡片信息的 JavaScript

        :return str: 可传给 page.evaluate() 的 JS 函数字符串
        """
        return r"""
        () => {
            const sizeRe = /(\d+\.?\d*)\s*(TB|GB|MB|G(?!B)|M(?!B))\b/i;
            const dateRe = /发布于\s*([\d/\-]+)/;
            const resRe = /\b(4K|8K|2K|1080[piP]?|720[piP]?|480[piP]?)\b/;
            const pointsRe = /(\d+)\s*积分/;

            // Collect all elements (including <a> cards) containing exactly one
            // "发布于" AND a file size indicator.
            const candidates = [];
            for (const el of document.querySelectorAll('a,div,article,li,section')) {
                const t = el.innerText || '';
                if (!t.includes('发布于') || !sizeRe.test(t)) continue;
                if ((t.match(/发布于/g) || []).length !== 1) continue;
                if (t.length < 30 || t.length > 5000) continue;
                candidates.push(el);
            }

            // Keep only minimal elements: skip any element that contains
            // another candidate (the contained one is more specific).
            const minimal = candidates.filter(
                el => !candidates.some(other => other !== el && el.contains(other))
            );

            const metaTerms = new Set([
                '4K','8K','2K','免费','官组','管理员','WEB-DL','WEBRip','BDRip','REMUX','HDTV',
                '简中','繁中','简英','繁英','内封','外挂','内嵌','简日','繁日','简韩','繁韩',
                '1080P','1080p','720P','720p','480P','480p',
                '蓝光原盘','ISO'
            ]);

            return minimal.map(card => {
                const text = card.innerText || '';
                const lines = text.split('\n').map(l => l.trim()).filter(Boolean);

                const dateMatch = text.match(dateRe);
                const sizeMatch = text.match(sizeRe);
                const resMatch = text.match(resRe);
                const pointsMatch = text.match(pointsRe);
                const isFree = text.includes('免费');

                const tags = [];
                if (text.includes('官组') || text.includes('管理员')) tags.push('官组');
                if (isFree) tags.push('免费');
                if (pointsMatch) tags.push(pointsMatch[0].trim());

                // Username line: the line just before the date line
                const dateLineIdx = lines.findIndex(l => /发布于/.test(l));
                const user = dateLineIdx > 0 ? lines[dateLineIdx - 1] : (lines[0] || '');

                // Title: lines that don't look like metadata
                const titleLines = lines.filter(l => {
                    if (l.length < 3) return false;
                    if (metaTerms.has(l)) return false;
                    if (/^发布于/.test(l)) return false;
                    if (/^\d+\s*积分$/.test(l)) return false;
                    if (/^\d+\.?\d*\s*(T?B|G[Bi]?|M[Bi]?)$/i.test(l)) return false;
                    if (l === user) return false;
                    return true;
                });
                let title = titleLines
                    .map(l => l.replace(/^\d+\s*积分\s*/, '').trim())
                    .filter(Boolean)
                    .join(' ')
                    .trim();

                // Walk up to the nearest <a> ancestor to get the resource href
                let hrefEl = card;
                while (hrefEl && hrefEl.tagName !== 'A') {
                    hrefEl = hrefEl.parentElement;
                }
                const href = hrefEl ? (hrefEl.getAttribute('href') || '') : '';

                return {
                    user,
                    posted_at: dateMatch ? dateMatch[1] : '',
                    tags,
                    title,
                    resolution: resMatch ? resMatch[1] : '',
                    size: sizeMatch ? (sizeMatch[1] + ' ' + sizeMatch[2].toUpperCase()) : '',
                    is_free: isFree,
                    unlock_points: isFree ? 0 : (pointsMatch ? parseInt(pointsMatch[1]) : null),
                    href,
                };
            });
        }
        """

    def _get_resources_via_browser(
        self,
        media_type: str,
        tmdb_id: str | int,
    ) -> List[Dict[str, Any]]:
        """
        浏览器自动化实现：直接导航到媒体详情页获取 115网盘资源

        :param media_type (str): ``movie`` 或 ``tv``
        :param tmdb_id (int): TMDB 作品 ID

        :return List: 资源信息字典列表

        :raises HDHiveLoginError: 认证或 Cookie 失效且无法自动重新登录
        :raises HDHiveBrowserError: 浏览器页面操作失败
        """
        root = self.DEFAULT_BASE_URL
        domain = root.replace("https://", "").replace("http://", "")
        detail_url = f"{root}/tmdb/{media_type}/{tmdb_id}"

        def _do_fetch(page: Any) -> List[Dict[str, Any]]:
            captured: List[Dict[str, Any]] = []

            def _handle_response(response: Any) -> None:
                try:
                    if response.status != 200:
                        return
                    if "json" not in response.headers.get("content-type", ""):
                        return
                    body = response.json()
                    if not isinstance(body, dict):
                        return
                    data = body.get("data")
                    if not isinstance(data, list) or not data:
                        return
                    first = data[0]
                    if not isinstance(first, dict):
                        return
                    if any(
                        k in first
                        for k in (
                            "size",
                            "resolution",
                            "video_resolution",
                            "share_size",
                            "source",
                            "slug",
                            "unlock_points",
                        )
                    ):
                        captured.extend(data)
                except Exception:
                    pass

            page.on("response", _handle_response)
            page.goto(detail_url, wait_until="domcontentloaded", timeout=30000)

            if "/login" in page.url:
                raise HDHiveLoginError(
                    "Cookie 被重定向到登录页",
                    login_redirect=True,
                )

            try:
                dismiss = page.locator("button:has-text('我知道了')")
                dismiss.first.wait_for(state="visible", timeout=1500)
                dismiss.first.click()
                dismiss.first.wait_for(state="hidden", timeout=2000)
            except Exception:
                pass

            _tab_115_sel = (
                "button:has-text('115网盘'), [role='tab']:has-text('115网盘')"
            )
            try:
                tab = page.locator(_tab_115_sel)
                tab.first.wait_for(state="visible", timeout=10000)
                tab.first.click()
            except Exception:
                page.evaluate("""
                    () => {
                        for (const t of document.querySelectorAll('[role="tab"]')) {
                            if ((t.innerText || '').includes('115')) { t.click(); break; }
                        }
                    }
                """)
            _waited = 0
            while _waited < 5000 and not captured:
                page.wait_for_timeout(100)
                _waited += 100

            if captured:
                return captured

            try:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(500)
            except Exception:
                pass
            dom_data = page.evaluate(self._scrape_resource_cards_js())
            return dom_data or []

        def _run_session() -> List[Dict[str, Any]]:
            cookies = (
                self._parse_cookie_str(self._cookie_str) if self._cookie_str else {}
            )
            try:
                with self._page_with_cookies(cookies, domain) as page:
                    return _do_fetch(page)
            except HDHiveError:
                raise
            except Exception as e:
                raise HDHiveBrowserError(f"资源搜索浏览器操作失败: {e}") from e

        return self._execute_with_auth_retry(_run_session)

    def get_resources(
        self,
        media_type: str,
        tmdb_id: str | int,
    ) -> List[Dict[str, Any]]:
        """
        通过浏览器按媒体类型和 TMDB ID 搜索 115网盘资源，返回资源信息列表

        :param media_type (str): ``movie`` 或 ``tv``
        :param tmdb_id (int): TMDB 作品 ID

        :return List: 资源信息字典列表，每项包含 ``user``、``posted_at``、``tags``、
                 ``title``、``resolution``、``size``、``is_free``、``unlock_points`` 等字段

        :raises HDHiveLoginError: 认证或 Cookie 失效且无法自动重新登录
        :raises HDHiveBrowserError: 浏览器页面操作失败
        """
        return self._get_resources_via_browser(media_type, tmdb_id)

    def unlock_resource(self, slug: str) -> Dict[str, Any]:
        """
        通过浏览器解锁 HDHive 115网盘资源，返回资源链接

        :param slug (str): 资源 slug（``get_resources`` 返回的 ``href`` 最后一段 UUID）

        :return Dict: 含 ``url``、``full_url``、``already_owned`` 的字典

        :raises HDHiveLoginError: 未登录或认证失效且无法自动重新登录
        :raises HDHiveBrowserError: 浏览器页面操作失败
        """
        if not self._cookie_str:
            raise HDHiveLoginError("请先调用 login() 或 load_saved_cookie()")

        root = self.DEFAULT_BASE_URL
        domain = root.replace("https://", "").replace("http://", "")
        resource_url = f"{root}/resource/115/{slug}"

        _EXTRACT_URL_JS = r"""
            () => {
                // Check input fields first (shown in the unlocked state)
                for (const el of document.querySelectorAll('input')) {
                    const v = (el.value || '').trim();
                    if (/https?:\/\/(115cdn|115)\.com\/\S+/.test(v)) return v;
                }
                // Fallback: scan visible text for a 115 URL
                const m = (document.body?.innerText || '').match(
                    /https?:\/\/(115cdn|115)\.com\/\S+/
                );
                return m ? m[0].replace(/\s+$/, '') : null;
            }
        """

        def _do_unlock(page: Any) -> Dict[str, Any]:
            captured_url: Optional[str] = None

            def _handle_response(response: Any) -> None:
                nonlocal captured_url
                try:
                    if response.status != 200:
                        return
                    if "json" not in response.headers.get("content-type", ""):
                        return
                    body = response.json()
                    if not isinstance(body, dict):
                        return
                    data = body.get("data") or {}
                    if not isinstance(data, dict):
                        return
                    for key in ("full_url", "url", "link", "resource_url"):
                        val = data.get(key)
                        if val and search(r"(115cdn|115)\.com", str(val)):
                            captured_url = str(val).strip()
                            break
                except Exception:
                    pass

            page.on("response", _handle_response)

            page.goto(resource_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(1000)

            if "/login" in page.url:
                raise HDHiveLoginError(
                    "Cookie 被重定向到登录页",
                    login_redirect=True,
                )

            existing = page.evaluate(_EXTRACT_URL_JS)
            if existing:
                return {"url": existing, "full_url": existing, "already_owned": True}

            confirm_loc = page.get_by_text("确定解锁", exact=True)
            try:
                confirm_loc.first.wait_for(state="visible", timeout=8000)
                confirm_loc.first.click()
            except PlaywrightTimeoutError:
                raise HDHiveBrowserError(
                    f"未找到「确定解锁」按钮，页面可能未正确加载（URL: {page.url}）"
                )

            try:
                page.wait_for_load_state("load", timeout=15000)
            except PlaywrightTimeoutError:
                pass
            page.wait_for_timeout(1000)

            final_url = page.url
            if search(r"(115cdn|115)\.com", final_url):
                return {"url": final_url, "full_url": final_url, "already_owned": False}

            url: Optional[str] = captured_url
            if not url:
                try:
                    url = page.evaluate(_EXTRACT_URL_JS)
                except Exception:
                    pass
            if not url:
                current = page.url
                if search(r"(115cdn|115)\.com", current):
                    url = current
            if not url:
                raise HDHiveBrowserError(
                    f"解锁后未能获取 115 链接（当前 URL: {page.url}）"
                )

            return {"url": url, "full_url": url, "already_owned": False}

        def _run_session() -> Dict[str, Any]:
            cookies = (
                self._parse_cookie_str(self._cookie_str) if self._cookie_str else {}
            )
            try:
                with self._page_with_cookies(cookies, domain) as page:
                    return _do_unlock(page)
            except HDHiveError:
                raise
            except Exception as e:
                raise HDHiveBrowserError(f"解锁浏览器操作失败: {e}") from e

        return self._execute_with_auth_retry(_run_session)


def is_hdhive_search_ready() -> bool:
    """
    判断 HDHive 频道搜索是否已配置且可用

    需开启 hdhive_search_enabled，且已填写账户密码或存在持久化 Cookie

    :return bool: 可用返回 True
    """
    if not configer.hdhive_search_enabled:
        return False
    user = (configer.hdhive_checkin_username or "").strip()
    pwd = (configer.hdhive_checkin_password or "").strip()
    if user and pwd:
        return True
    return HDHivePlaywrightClient._cookie_file_path().exists()


def get_hdhive_browser_client() -> Optional[HDHivePlaywrightClient]:
    """
    获取已登录的 HDHive 浏览器客户端：优先持久化 Cookie，否则用配置账号密码登录

    按环境自动选用 cloakbrowser 或 Playwright 后端；始终注入凭据以支持 Cookie 过期后自动刷新

    :return Any: 已就绪的客户端；无法就绪时为 None
    """
    user = (configer.hdhive_checkin_username or "").strip()
    pwd = (configer.hdhive_checkin_password or "").strip()
    client = HDHivePlaywrightClient()
    if user and pwd:
        client.set_credentials(user, pwd)
    if client.load_saved_cookie():
        return client
    if not user or not pwd:
        return None
    try:
        if client.login(username=user, password=pwd):
            return client
    except HDHiveError as e:
        logger.warning("【HDHive】浏览器登录失败: %s", e)
    return None
