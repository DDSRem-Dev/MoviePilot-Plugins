__all__ = [
    "HDHiveBrowserError",
    "HDHiveError",
    "HDHiveLoginError",
    "HDHivePlaywrightClient",
    "get_hdhive_browser_client",
    "is_hdhive_search_ready",
]

from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from platform import machine as _machine
from re import compile as re_compile
from re import fullmatch
from shutil import rmtree
from socket import (
    AF_INET,
    SO_REUSEADDR,
    SOCK_STREAM,
    SOL_SOCKET,
    socket,
)
from sys import platform
from time import monotonic
from typing import Any, Dict, Iterator, List, Optional, Tuple
from urllib.parse import unquote, urlparse

from orjson import dumps, loads

from app.sdk.config import settings

from ...core.config import configer
from ...utils.hdhive import (
    EXTRACT_SHARE_URL_JS,
    READ_RESOURCE_CHUNKS_JS,
    extract_hdhive_page_resources,
    extract_hdhive_resource_rows,
    is_hdhive_share_url,
)
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


USER_MENU_SELECTOR = (
    'button[aria-label="打开用户菜单"], button[aria-label="Open user menu"]'
)
CHECKIN_BUTTON_SELECTORS = {
    False: 'button:has(path[d^="M11.5 21h-5.5"])',
    True: 'button:has(path[d^="M3 3m0 2a2 2 0 0 1 2 -2h14"])',
}

INSTALL_RESULT_OBSERVER_JS = """
() => {
    window.__re0CheckinObserver?.disconnect();
    window.__re0CheckinResults = [];
    const selector = '[data-slot="toast"], [role="alert"], [role="alertdialog"]';
    const previous = new WeakMap();
    const results = new Map();
    const containers = () => [...new Set(
        [...document.querySelectorAll(selector)].map(el =>
            el.closest('[data-slot="toast"]') || el
        )
    )];
    const read = el => ({
        text: (el.innerText || '').trim(),
        status: el.classList.contains('toast--success') ? 'success' :
            el.classList.contains('toast--danger') ? 'error' : ''
    });
    for (const el of containers()) previous.set(el, JSON.stringify(read(el)));
    const collect = () => {
        for (const el of containers()) {
            const result = read(el);
            const value = JSON.stringify(result);
            if (!result.text || !el.getClientRects().length || previous.get(el) === value) continue;
            previous.set(el, value);
            results.set(el, result);
        }
        window.__re0CheckinResults = [...results.values()];
    };
    window.__re0CheckinObserver = new MutationObserver(collect);
    window.__re0CheckinObserver.observe(document.body, {
        childList: true, subtree: true, characterData: true,
        attributes: true, attributeFilter: ['class']
    });
}
"""
READ_RESULTS_JS = "() => window.__re0CheckinResults || []"
STOP_RESULT_OBSERVER_JS = "() => window.__re0CheckinObserver?.disconnect()"


def _is_navigation_error(error: Exception) -> bool:
    return any(
        message in str(error)
        for message in (
            "Execution context was destroyed",
            "Cannot find context with specified id",
        )
    )


def parse_checkin_result(text: str, status: str = "") -> Optional[Tuple[bool, str]]:
    """
    解析 RE0 签到提示，区分已签到、成功、失败与非结果文本

    :param text (str): Toast 完整文本，包含标题和描述
    :param status (str): Toast 状态，success、error 或空字符串

    :return Tuple: 明确结果的成功标记与文案，非结果文本返回 None
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    clean = " ".join(lines)
    if not clean:
        return None
    lowered = clean.lower()
    if any(
        word in lowered
        for word in (
            "已经签到",
            "已签到",
            "签到过",
            "明天再来",
            "already checked in",
            "already checked-in",
            "already signed in",
        )
    ):
        detail = " ".join(
            line for line in lines if line not in ("签到失败", "Check-in failed")
        )
        return True, f"今日已签到：{detail or clean}"
    if status == "error" or any(
        word in lowered
        for word in (
            "失败",
            "错误",
            "异常",
            "请先登录",
            "未登录",
            "error",
            "failed",
        )
    ):
        return False, clean
    if status == "success" or any(
        word in lowered
        for word in (
            "签到成功",
            "check-in successful",
            "check in successful",
        )
    ):
        return True, clean
    return None


def _click_home_dialog_button(page: Any, button: Any, debug: Any) -> None:
    try:
        button.click(timeout=3000)
    except Exception as e:
        if not any(
            text in str(e).lower()
            for text in ("stable check", "not stable", "position is still changing")
        ):
            raise
        # cloakbrowser 的稳定性检查可能持续失败，确认命中目标后使用真实鼠标事件
        point = button.evaluate(
            """el => {
                if (!el.isConnected || el.matches(':disabled') ||
                    el.getAttribute('aria-disabled') === 'true' ||
                    el.closest('[inert]')) return false;
                const rect = el.getBoundingClientRect();
                if (!rect.width || !rect.height) return false;
                const hit = document.elementFromPoint(
                    rect.x + rect.width / 2, rect.y + rect.height / 2
                );
                if (!hit || !el.contains(hit)) return false;
                return {x: rect.x + rect.width / 2, y: rect.y + rect.height / 2};
            }"""
        )
        if not point:
            raise
        page.mouse.click(point["x"], point["y"])
        debug.log("首页弹窗按钮稳定性检查失败，已确认按钮未遮挡并通过真实鼠标点击")


def _ensure_preferred_provider(dialog: Any, debug: Any) -> None:
    providers = dialog.locator('[class*="UserPreferenceDialog_providerGrid"]')
    if providers.locator('input[type="checkbox"]:checked').count():
        return
    provider = providers.locator('[data-slot="checkbox"]').filter(
        has_text=re_compile(r"(?i)^115\s*(网盘|Drive)$")
    )
    checkbox = provider.locator('input[type="checkbox"]')
    # 站点嵌套 label 的鼠标点击不能可靠切换状态，使用输入框的原生键盘交互
    checkbox.focus(timeout=3000)
    checkbox.press("Space", timeout=3000)
    provider.locator('input[type="checkbox"]:checked').wait_for(
        state="attached", timeout=3000
    )
    debug.log("未设置偏好网盘，已选择 115 网盘")


def _wait_for_preference_save(page: Any, dialog: Any, debug: Any) -> None:
    deadline = monotonic() + 15
    while monotonic() < deadline:
        for result in reversed(page.evaluate(READ_RESULTS_JS)):
            if result.get("status") == "error":
                raise RuntimeError(f"RE0 偏好设置保存失败：{result.get('text', '')}")
        if not dialog.is_visible():
            debug.log("偏好设置弹窗已关闭，继续签到")
            return
        page.wait_for_timeout(250)
    raise RuntimeError("RE0 偏好设置提交后弹窗未关闭，未收到保存成功结果")


def _dismiss_home_dialogs(page: Any, debug: Any) -> None:
    menu = page.locator(USER_MENU_SELECTOR).first
    menu.wait_for(state="visible", timeout=30000)
    dismiss = page.get_by_role(
        "button",
        name=re_compile(
            r"^(我知道了(?:\s*[（(].*?[)）])?|保存并启用推荐|Got it|Save and enable recommendations)$"
        ),
    )
    deadline = monotonic() + 45
    while True:
        visible_dialogs = page.locator('[role="dialog"]:visible')
        if not visible_dialogs.count():
            return
        if monotonic() >= deadline:
            raise RuntimeError("RE0 首页弹窗未关闭，请检查公告或首次登录设置")
        for button in dismiss.all():
            if button.is_visible() and button.is_enabled():
                name = button.inner_text().strip()
                save_preferences = name in (
                    "保存并启用推荐",
                    "Save and enable recommendations",
                )
                dialog_locator = button.locator("xpath=ancestor::*[@role='dialog'][1]")
                dialog = dialog_locator.element_handle()
                if dialog is None:
                    continue
                try:
                    if save_preferences:
                        _ensure_preferred_provider(dialog_locator, debug)
                        page.evaluate(INSTALL_RESULT_OBSERVER_JS)
                    _click_home_dialog_button(page, button, debug)
                except Exception as e:
                    if save_preferences:
                        page.evaluate(STOP_RESULT_OBSERVER_JS)
                    debug.log(f"弹窗按钮暂不可点击，继续检查其他弹窗: {e}")
                    continue
                if save_preferences:
                    debug.log("已点击保存偏好设置按钮，等待站点确认")
                    try:
                        _wait_for_preference_save(page, dialog, debug)
                    finally:
                        page.evaluate(STOP_RESULT_OBSERVER_JS)
                else:
                    debug.log("已点击首页公告确认按钮")
                break
        page.wait_for_timeout(250)


def run_checkin(page: Any, gamble: bool, debug: Any) -> Tuple[bool, str]:
    """
    在已登录的 RE0 首页通过用户菜单签到并捕获 Toast 结果

    :param page (Any): 已完成登录并加载首页的浏览器页面
    :param gamble (bool): 是否使用赌狗签到
    :param debug (Any): 签到调试记录器

    :return Tuple: 签到是否完成及结果说明
    """
    label = "赌狗签到" if gamble else "每日签到"
    _dismiss_home_dialogs(page, debug)
    page.locator(USER_MENU_SELECTOR).first.click(timeout=10000)
    button = page.locator(CHECKIN_BUTTON_SELECTORS[gamble]).first
    button.wait_for(state="visible", timeout=10000)
    page.evaluate(INSTALL_RESULT_OBSERVER_JS)
    try:
        # 站点校验 isTrusted，必须由浏览器真实点击以提交 Server Action
        button.click(timeout=10000)
        deadline = monotonic() + 60
        while monotonic() < deadline:
            for result in reversed(page.evaluate(READ_RESULTS_JS)):
                parsed = parse_checkin_result(
                    result.get("text", ""), result.get("status", "")
                )
                if parsed is not None:
                    debug.screenshot(page, "final_result", parsed[1])
                    return parsed
            page.wait_for_timeout(250)
        debug.screenshot(page, "result_timeout", "等待 RE0 签到提示超时")
        debug.save_html(page, "result_timeout")
        return False, f"{label}：等待 RE0 签到结果超时"
    finally:
        page.evaluate(STOP_RESULT_OBSERVER_JS)


class HDHiveError(Exception):
    """
    RE0 浏览器自动化异常基类
    """


class HDHiveLoginError(HDHiveError):
    """
    RE0 认证或 Cookie 相关失败
    """

    login_redirect: bool

    def __init__(self, message: str, *, login_redirect: bool = False) -> None:
        super().__init__(message)
        self.login_redirect = login_redirect


class HDHiveBrowserError(HDHiveError):
    """
    RE0 页面操作或浏览器自动化失败
    """


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
            self._log(f"RE0 {label} Debug Session")
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
                    "请稍候",
                    "请稍等",
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
        try:
            if any(
                urlparse(frame.url).hostname == "challenges.cloudflare.com"
                for frame in page.frames
            ):
                signals.append("CF-frame（含 Shadow DOM 内的验证帧）")
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
    RE0 站点浏览器自动化客户端

    运行时自动选择 cloakbrowser（新版 MoviePilot）或 Playwright Chromium（旧版 MoviePilot）
    """

    DEFAULT_BASE_URL = "https://re0.me"
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
    def _page_with_login(
        self, debug: Optional[_CheckinDebugSession] = None
    ) -> Iterator[Any]:
        """
        创建「已在同一上下文内真实登录」的浏览器页面，自动管理上下文生命周期

        :param debug (_CheckinDebugSession): 可选调试记录器，在关闭页面前保存失败现场

        :yields Any: 已登录的页面对象
        :raises HDHiveLoginError: 未配置账号密码或登录失败
        """
        if not self._username or not self._password:
            raise HDHiveLoginError(
                "未配置账号密码，无法登录（会话需绑定用户）",
                login_redirect=True,
            )
        with self._fresh_context() as context:
            page = context.new_page()
            try:
                if not self._fill_and_submit(
                    page, self._username, self._password, debug=debug
                ):
                    raise HDHiveLoginError(
                        "登录失败（未离开登录页）", login_redirect=True
                    )
                try:
                    self._build_cookie_str_from_raw(context.cookies())
                except Exception:
                    pass
                yield page
            except Exception:
                if debug:
                    debug.log_page_state(page, "浏览器流程失败")
                    debug.screenshot(page, "browser_failure")
                    debug.save_html(page, "browser_failure")
                raise

    @staticmethod
    def _click_cf_checkbox(page: Any) -> bool:
        """
        点击 Cloudflare 验证帧中未选中的复选框，兼容封闭 Shadow DOM

        :param page (Any): 浏览器页面对象

        :return bool: 是否实际点击了验证复选框
        """
        for frame in page.frames:
            if urlparse(frame.url).hostname != "challenges.cloudflare.com":
                continue
            try:
                checkbox = frame.get_by_role("checkbox").first
                if checkbox.is_visible() and not checkbox.is_checked():
                    checkbox.click(timeout=1000)
                    return True
            except Exception:
                pass

            # CF 可将复选框放在封闭 Shadow DOM 内，需由无障碍树定位真实控件
            session = None
            try:
                session = page.context.new_cdp_session(frame)
                nodes = session.send("Accessibility.getFullAXTree").get("nodes", [])
                for node in nodes:
                    if (
                        node.get("ignored")
                        or node.get("role", {}).get("value") != "checkbox"
                    ):
                        continue
                    properties = {
                        prop["name"]: prop.get("value", {}).get("value")
                        for prop in node.get("properties", [])
                    }
                    if properties.get("disabled") or properties.get("checked") in (
                        True,
                        "true",
                    ):
                        continue
                    node_id = node.get("backendDOMNodeId")
                    if not node_id:
                        continue
                    quad = session.send("DOM.getBoxModel", {"backendNodeId": node_id})[
                        "model"
                    ]["content"]
                    x = sum(quad[0::2]) / 4
                    y = sum(quad[1::2]) / 4
                    if max(quad[0::2]) <= min(quad[0::2]) or max(quad[1::2]) <= min(
                        quad[1::2]
                    ):
                        continue
                    for event_type in ("mouseMoved", "mousePressed", "mouseReleased"):
                        event = {"type": event_type, "x": x, "y": y}
                        if event_type != "mouseMoved":
                            event.update(button="left", clickCount=1)
                        session.send("Input.dispatchMouseEvent", event)
                    return True
            except Exception:
                # 验证帧可能在自动通过或重新加载时销毁，交由等待循环重试
                continue
            finally:
                if session:
                    try:
                        session.detach()
                    except Exception:
                        pass
        return False

    def _wait_for_cloudflare(
        self, page: Any, debug: Optional[_CheckinDebugSession] = None
    ) -> None:
        deadline = monotonic() + 90
        detected = False
        clicks = 0
        next_click = 0.0
        while monotonic() < deadline:
            try:
                challenge = page.evaluate(
                    """() => Boolean(
                        window._cf_chl_opt ||
                        document.querySelector('#challenge-running, #challenge-form') ||
                        /^(Just a moment|Checking your browser|请稍候|请稍等)/i.test(document.title)
                    )"""
                )
            except Exception as e:
                if not _is_navigation_error(e):
                    raise
                page.wait_for_timeout(500)
                continue
            if not challenge:
                if detected and debug:
                    debug.log("Cloudflare 验证页已通过，继续加载 RE0 页面")
                return
            if not detected:
                detected = True
                if debug:
                    debug.log(
                        "检测到 Cloudflare 访问验证，等待自动通过或点击验证复选框（最长 90 秒）"
                    )
                    debug.log_page_state(page, "Cloudflare 验证")
            now = monotonic()
            if clicks < 3 and now >= next_click:
                if self._click_cf_checkbox(page):
                    clicks += 1
                    if debug:
                        debug.log(f"已点击 Cloudflare 验证复选框（第 {clicks} 次）")
                next_click = now + 5
            page.wait_for_timeout(500)
        reason = (
            "Cloudflare 访问验证在 90 秒内未通过"
            if detected
            else "RE0 页面持续跳转或无法读取"
        )
        raise HDHiveBrowserError(
            f"{reason}，请检查代理及 challenges.cloudflare.com 的连通性，当前 URL: {page.url}"
        )

    def _goto(
        self, page: Any, url: str, debug: Optional[_CheckinDebugSession] = None
    ) -> None:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        self._wait_for_cloudflare(page, debug)

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
        返回 RE0 Cookie 持久化文件路径

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

    def _fill_login_form(
        self,
        page: Any,
        username: str,
        password: str,
        debug: Optional[_CheckinDebugSession] = None,
    ) -> None:
        fields = [
            (
                "用户名",
                page.locator(
                    ":is(input[name='username'], input[name='email'], "
                    "input[type='email'], input[autocomplete='username'], "
                    "input[placeholder*='邮箱'], input[placeholder*='email'], "
                    "input[placeholder*='用户名']):visible"
                ).first,
                username,
            ),
            (
                "密码",
                page.locator(
                    ":is(input[name='password'], input[type='password']):visible"
                ).first,
                password,
            ),
        ]
        for label, field, _ in fields:
            try:
                field.wait_for(state="visible", timeout=15000)
            except PlaywrightTimeoutError as e:
                raise HDHiveLoginError(f"等待登录{label}输入框超时") from e

        invalid = []
        for attempt in range(3):
            for label, field, value in fields:
                try:
                    if field.input_value(timeout=1000) == value:
                        continue
                    try:
                        field.fill(value, timeout=5000)
                    except Exception as e:
                        if debug:
                            debug.log(
                                f"{label}常规填写异常（{type(e).__name__}），检查实际输入值"
                            )
                    if field.input_value(timeout=1000) != value:
                        # 人性化输入可能丢失焦点，使用原生 setter 并通知 React 更新受控字段
                        field.evaluate(
                            """(el, value) => {
                                const win = el.ownerDocument.defaultView;
                                const setter = Object.getOwnPropertyDescriptor(
                                    win.HTMLInputElement.prototype, 'value'
                                ).set;
                                setter.call(el, value);
                                el.dispatchEvent(new win.Event('input', {bubbles: true}));
                                el.dispatchEvent(new win.Event('change', {bubbles: true}));
                            }""",
                            value,
                            timeout=3000,
                        )
                        if debug:
                            debug.log(
                                f"{label}输入值未保留，已使用原生输入事件重新填写"
                            )
                except Exception as e:
                    if debug:
                        debug.log(
                            f"{label}填写未完成（{type(e).__name__}），等待表单稳定后重试"
                        )

            # 等待受控表单重渲染，并同时复核两项，避免填写密码时用户名被清空
            page.wait_for_timeout(500)
            invalid = []
            for label, field, value in fields:
                try:
                    if field.input_value(timeout=1000) == value:
                        continue
                except Exception:
                    pass
                invalid.append(label)
            if not invalid:
                if debug:
                    debug.log("登录表单账号及密码已填写并校验，准备提交")
                return
            if debug:
                debug.log(
                    f"登录表单第 {attempt + 1} 次校验未通过：{'、'.join(invalid)}"
                )
        raise HDHiveLoginError(
            f"登录表单填写失败：{'、'.join(invalid)}输入值未保留，已停止提交"
        )

    def _fill_and_submit(
        self,
        page: Any,
        username: str,
        password: str,
        debug: Optional[_CheckinDebugSession] = None,
    ) -> bool:
        """
        打开登录页、填写账号密码并提交，等待离开 /login

        page API 与 playwright / cloakbrowser 均兼容

        :param page (Any): 浏览器页面对象
        :param username (str): 登录用户名或邮箱
        :param password (str): 登录密码
        :param debug (_CheckinDebugSession): 可选调试记录器
        :return bool: 若 URL 在超时内离开登录页则为 True
        :raises HDHiveLoginError: 等待跳转超时
        """
        root = HDHivePlaywrightClient.DEFAULT_BASE_URL
        self._goto(
            page,
            f"{root}{HDHivePlaywrightClient.LOGIN_PAGE}",
            debug,
        )
        self._fill_login_form(page, username, password, debug)
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

    def _checkin_via_browser(self, gamble: bool) -> Tuple[bool, str]:
        if not self._username or not self._password:
            return False, "未配置 RE0 账号密码"

        label = "赌狗签到" if gamble else "每日签到"
        debug = _CheckinDebugSession(label)
        try:
            with self._page_with_login(debug=debug) as page:
                if page.url.rstrip("/") == self.DEFAULT_BASE_URL:
                    self._wait_for_cloudflare(page, debug)
                else:
                    self._goto(page, self.DEFAULT_BASE_URL, debug)
                if urlparse(page.url).path.rstrip("/") == self.LOGIN_PAGE:
                    raise HDHiveLoginError(
                        "RE0 登录已失效，请检查账户密码", login_redirect=True
                    )
                result = run_checkin(page, gamble, debug)
        except HDHiveLoginError as e:
            result = (False, str(e))
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

    def _get_resources_via_browser(
        self,
        media_type: str,
        tmdb_id: str | int,
    ) -> List[Dict[str, Any]]:
        if media_type not in ("movie", "tv") or not str(tmdb_id).isdigit():
            raise HDHiveBrowserError("RE0 搜索需要有效的媒体类型和 TMDB ID")
        detail_url = f"{self.DEFAULT_BASE_URL}/tmdb/{media_type}/{tmdb_id}"
        captured: List[Dict[str, Any]] = []

        def _handle_response(response: Any) -> None:
            try:
                if response.status == 200 and "json" in response.headers.get(
                    "content-type", ""
                ):
                    captured.extend(extract_hdhive_resource_rows(response.json()))
            except Exception:
                pass

        try:
            with self._page_with_login() as page:
                page.on("response", _handle_response)
                try:
                    self._goto(page, detail_url)
                    deadline = monotonic() + 20
                    navigation_error: Optional[Exception] = None
                    last_chunks: Optional[List[str]] = None
                    while monotonic() < deadline:
                        if urlparse(page.url).path.rstrip("/") == self.LOGIN_PAGE:
                            raise HDHiveLoginError(
                                "RE0 登录已失效", login_redirect=True
                            )
                        try:
                            chunks = page.evaluate(READ_RESOURCE_CHUNKS_JS)
                        except Exception as e:
                            if not _is_navigation_error(e):
                                raise
                            # CF 放行或站内重定向可能晚于 DOMContentLoaded，仅重读新页面
                            navigation_error = e
                            page.wait_for_timeout(250)
                            continue
                        navigation_error = None
                        if chunks != last_chunks:
                            rows = extract_hdhive_page_resources(chunks)
                            if rows is not None:
                                return rows
                            last_chunks = chunks
                        if captured:
                            return extract_hdhive_resource_rows({"data": captured})
                        page.wait_for_timeout(250)
                    if navigation_error is not None:
                        raise HDHiveBrowserError(
                            "RE0 搜索页面持续跳转，20 秒内未能读取资源列表，请稍后重试"
                        ) from navigation_error
                    raise HDHiveBrowserError(
                        "未能读取 RE0 资源列表，请检查页面是否加载成功"
                    )
                finally:
                    page.remove_listener("response", _handle_response)
        except HDHiveError:
            raise
        except Exception as e:
            raise HDHiveBrowserError(f"资源搜索浏览器操作失败: {e}") from e

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
        通过浏览器解锁 RE0 115网盘资源，返回资源链接

        :param slug (str): 资源 slug（``get_resources`` 返回的 ``href`` 最后一段 UUID）

        :return Dict: 含 ``url``、``full_url``、``already_owned`` 的字典

        :raises HDHiveLoginError: 未登录或认证失效且无法自动重新登录
        :raises HDHiveBrowserError: 浏览器页面操作失败
        """
        if not self._username or not self._password:
            raise HDHiveLoginError("未配置账号密码，无法解锁（会话需绑定用户）")
        if not fullmatch(r"[A-Za-z0-9_-]+", slug):
            raise HDHiveBrowserError("RE0 资源 slug 无效")

        resource_url = f"{self.DEFAULT_BASE_URL}/resource/115/{slug}"
        try:
            with self._page_with_login() as page:
                self._goto(page, resource_url)
                confirm = page.get_by_role(
                    "button", name=re_compile(r"^(确认解锁|确定解锁|Confirm unlock)$")
                ).first
                submitted = False
                deadline = monotonic() + 30
                while monotonic() < deadline:
                    if urlparse(page.url).path.rstrip("/") == self.LOGIN_PAGE:
                        raise HDHiveLoginError("RE0 登录已失效", login_redirect=True)
                    if is_hdhive_share_url(page.url):
                        url = page.url
                    else:
                        try:
                            url = page.evaluate(EXTRACT_SHARE_URL_JS)
                        except Exception as e:
                            if not _is_navigation_error(e):
                                raise
                            # 解锁成功后会跨站跳转，下一轮读取跳转地址
                            page.wait_for_timeout(250)
                            continue
                    if is_hdhive_share_url(url):
                        return {
                            "url": url,
                            "full_url": url,
                            "already_owned": not submitted,
                        }
                    error = page.locator('[data-slot="toast"].toast--danger').first
                    if error.is_visible():
                        raise HDHiveBrowserError(f"RE0 解锁失败：{error.inner_text()}")
                    if not submitted and confirm.is_visible() and confirm.is_enabled():
                        confirm.click(timeout=10000)
                        submitted = True
                        deadline = monotonic() + 30
                    page.wait_for_timeout(250)
                detail = (
                    "解锁后未能获取 115 链接"
                    if submitted
                    else "未找到资源链接或「确认解锁」按钮"
                )
                raise HDHiveBrowserError(f"{detail}（URL: {page.url}）")
        except HDHiveError:
            raise
        except Exception as e:
            raise HDHiveBrowserError(f"解锁浏览器操作失败: {e}") from e


def is_hdhive_search_ready() -> bool:
    """
    判断 RE0 频道搜索是否已配置且可用

    RE0 已上线加密会话绑定，认证操作必须在同一上下文内真实登录，因此必须配置
    账户密码（仅有持久化 Cookie 已不足以维持登录）

    :return bool: 可用返回 True
    """
    if not configer.hdhive_search_enabled:
        return False
    user = (configer.hdhive_checkin_username or "").strip()
    pwd = (configer.hdhive_checkin_password or "").strip()
    return bool(user and pwd)


def get_hdhive_browser_client() -> Optional[HDHivePlaywrightClient]:
    """
    获取已配置凭据的 RE0 浏览器客户端

    按环境自动选用 cloakbrowser 或 Playwright 后端。认证操作会在各自的浏览器上下文内
    用账号密码真实登录以绑定加密会话，因此此处只需注入凭据即可；未配置账号密码时不可用。

    :return Any: 已就绪的客户端；未配置账号密码时为 None
    """
    user = (configer.hdhive_checkin_username or "").strip()
    pwd = (configer.hdhive_checkin_password or "").strip()
    if not user or not pwd:
        return None
    client = HDHivePlaywrightClient()
    client.set_credentials(user, pwd)
    client.load_saved_cookie()
    return client
