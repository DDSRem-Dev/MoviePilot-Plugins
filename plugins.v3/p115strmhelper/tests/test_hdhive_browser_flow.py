"""
RE0 浏览器搜索与解锁方法回归测试
"""

import importlib
import sys
from json import dumps, loads
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest import TestCase
from unittest.mock import MagicMock, patch


def _load_browser() -> Any:
    root = Path(__file__).resolve().parents[1]
    prefix = "_re0_browser_test"
    modules = {}
    for name, path in (
        (prefix, root),
        (f"{prefix}.core", root / "core"),
        (f"{prefix}.helper", root / "helper"),
        (f"{prefix}.helper.hdhive", root / "helper" / "hdhive"),
        (f"{prefix}.utils", root / "utils"),
        ("app", None),
        ("app.core", None),
    ):
        module = ModuleType(name)
        module.__path__ = [str(path)] if path else []
        modules[name] = module
    for name, attributes in (
        (f"{prefix}.core.config", {"configer": MagicMock()}),
        (
            f"{prefix}.utils.sentry",
            {
                "sentry_manager": SimpleNamespace(
                    capture_all_class_exceptions=lambda cls: cls
                )
            },
        ),
        ("app.core.config", {"settings": MagicMock()}),
        ("orjson", {"loads": loads, "dumps": lambda value: dumps(value).encode()}),
    ):
        module = ModuleType(name)
        module.__dict__.update(attributes)
        modules[name] = module
    with patch.dict(sys.modules, modules):
        return importlib.import_module(f"{prefix}.helper.hdhive.browser")


class TestRE0BrowserFlow(TestCase):
    """
    使用页面替身执行插件实际方法，校验搜索和解锁分支
    """

    @classmethod
    def setUpClass(cls) -> None:
        """
        隔离 MoviePilot 依赖并加载浏览器客户端
        """
        cls.browser = _load_browser()

    def setUp(self) -> None:
        """
        创建已登录页面替身
        """
        self.client = self.browser.HDHivePlaywrightClient()
        self.client.set_credentials("test-user", "test-password")
        self.client._wait_for_cloudflare = MagicMock()
        self.page = MagicMock()
        self.page.url = "https://re0.me/resource/115/test-resource"
        self.client._page_with_login = MagicMock()
        self.client._page_with_login.return_value.__enter__.return_value = self.page

    def test_search_reads_page_resource_data(self) -> None:
        """
        不依赖卡片 href 或额外 JSON 请求即可获取资源
        """
        self.page.evaluate.return_value = [
            "1:"
            + dumps(
                {
                    "groupData": {
                        "115": [
                            {
                                "slug": "test-resource",
                                "website": "115",
                                "title": "movie",
                            }
                        ]
                    }
                }
            )
            + "\n"
        ]
        rows = self.client.get_resources("movie", 27205)
        self.assertEqual(rows[0]["href"], "/resource/115/test-resource")
        self.page.goto.assert_called_once_with(
            "https://re0.me/tmdb/movie/27205",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        self.page.get_by_role.assert_not_called()

    def test_search_does_not_report_load_failure_as_empty_results(self) -> None:
        """
        无可识别资源数据时明确失败
        """
        with patch.object(self.browser, "monotonic", side_effect=[0, 21]):
            with self.assertRaisesRegex(self.browser.HDHiveBrowserError, "未能读取"):
                self.client.get_resources("tv", 1396)

    def test_search_parses_only_changed_chunks(self) -> None:
        """
        等待分片时只解析变化的内容，完整分片到达后立即返回
        """
        pending = ['1:{"groupData":{"115":["$a"]}}\n']
        complete = pending + ['a:{"slug":"test-resource","website":"115"}\n']
        self.page.evaluate.side_effect = [pending, pending, complete]
        with patch.object(
            self.browser,
            "extract_hdhive_page_resources",
            wraps=self.browser.extract_hdhive_page_resources,
        ) as parse:
            rows = self.client.get_resources("movie", 27205)
        self.assertEqual(rows[0]["href"], "/resource/115/test-resource")
        self.assertEqual(parse.call_count, 2)

    def test_checkin_reuses_homepage_after_login(self) -> None:
        """
        登录已到首页时省去重复加载，仍检查 CF 后继续签到
        """
        self.page.url = "https://re0.me/"
        with (
            patch.object(self.browser, "_CheckinDebugSession"),
            patch.object(
                self.browser, "run_checkin", return_value=(True, "已签到")
            ) as run,
        ):
            self.assertTrue(self.client.checkin(False)[0])
        self.page.goto.assert_not_called()
        self.client._wait_for_cloudflare.assert_called_once()
        run.assert_called_once()

    def test_checkin_navigates_home_when_login_lands_elsewhere(self) -> None:
        """
        登录落在其他页面时仍导航到签到入口
        """
        with (
            patch.object(self.browser, "_CheckinDebugSession"),
            patch.object(self.browser, "run_checkin", return_value=(True, "已签到")),
        ):
            self.assertTrue(self.client.checkin(False)[0])
        self.page.goto.assert_called_once_with(
            "https://re0.me", wait_until="domcontentloaded", timeout=30000
        )

    def test_search_recovers_after_navigation_destroys_context(self) -> None:
        """
        搜索读取中发生跳转时重读新页面，不重新导航或丢失结果
        """
        chunks = [
            "1:"
            + dumps(
                {"groupData": {"115": [{"slug": "after-redirect", "website": "115"}]}}
            )
            + "\n"
        ]
        self.page.evaluate.side_effect = [
            RuntimeError(
                "Page.evaluate: Execution context was destroyed, most likely because of a navigation"
            ),
            RuntimeError("Cannot find context with specified id"),
            chunks,
        ]
        rows = self.client.get_resources("movie", 27205)
        self.assertEqual(rows[0]["href"], "/resource/115/after-redirect")
        self.assertEqual(self.page.evaluate.call_count, 3)
        self.assertEqual(self.page.wait_for_timeout.call_count, 2)
        self.page.goto.assert_called_once()
        self.page.remove_listener.assert_called_once_with(
            "response", self.page.on.call_args.args[1]
        )

    def test_search_navigation_retry_keeps_original_deadline(self) -> None:
        """
        持续跳转不能无限重试或将失败返回为空列表
        """
        self.page.evaluate.side_effect = RuntimeError("Execution context was destroyed")
        with patch.object(self.browser, "monotonic", side_effect=[0, 1, 19, 21]):
            with self.assertRaisesRegex(
                self.browser.HDHiveBrowserError, "搜索页面持续跳转"
            ):
                self.client.get_resources("movie", 27205)
        self.assertEqual(self.page.evaluate.call_count, 2)
        self.page.remove_listener.assert_called_once()

    def test_search_navigation_to_login_reports_auth_failure(self) -> None:
        """
        重试期间跳回登录页仍按认证失败处理
        """
        self.page.evaluate.side_effect = RuntimeError("Execution context was destroyed")
        self.page.wait_for_timeout.side_effect = lambda _: setattr(
            self.page, "url", "https://re0.me/login?redirect=%2Ftmdb%2Fmovie%2F27205"
        )
        with self.assertRaises(self.browser.HDHiveLoginError) as caught:
            self.client.get_resources("movie", 27205)
        self.assertTrue(caught.exception.login_redirect)
        self.page.evaluate.assert_called_once()
        self.page.remove_listener.assert_called_once()

    def test_search_does_not_retry_unrelated_evaluation_errors(self) -> None:
        """
        页面关闭或脚本错误应立即报告，不能被跳转重试掩盖
        """
        for message in (
            "Target page, context or browser has been closed",
            "ReferenceError: missingVariable is not defined",
        ):
            with self.subTest(message=message):
                self.page.reset_mock()
                self.page.evaluate.side_effect = RuntimeError(message)
                with self.assertRaises(self.browser.HDHiveBrowserError) as caught:
                    self.client.get_resources("movie", 27205)
                self.assertIn(message, str(caught.exception))
                self.page.evaluate.assert_called_once()
                self.page.wait_for_timeout.assert_not_called()
                self.page.remove_listener.assert_called_once()

    def test_unlock_existing_link_does_not_click(self) -> None:
        """
        已解锁资源直接返回完整链接，不再次解锁
        """
        url = "https://115.com/s/example?password=1122"
        self.page.evaluate.return_value = url
        self.assertEqual(
            self.client.unlock_resource("test-resource"),
            {
                "url": url,
                "full_url": url,
                "already_owned": True,
            },
        )
        self.page.get_by_role.return_value.first.click.assert_not_called()

    def test_new_unlock_captures_redirect_and_submits_once(self) -> None:
        """
        新解锁点击一次后返回跨站跳转地址及提取码
        """
        url = "https://115cdn.com/s/example?password=de44"
        self.page.evaluate.return_value = None
        self.page.locator.return_value.first.is_visible.return_value = False
        self.page.wait_for_timeout.side_effect = lambda _: setattr(
            self.page, "url", url
        )
        result = self.client.unlock_resource("test-resource")
        self.assertEqual(result, {"url": url, "full_url": url, "already_owned": False})
        button = self.page.get_by_role.return_value.first
        button.click.assert_called_once()
        pattern = self.page.get_by_role.call_args.kwargs["name"]
        self.assertIsNotNone(pattern.fullmatch("确认解锁"))
        self.assertIsNotNone(pattern.fullmatch("确定解锁"))

    def test_unlock_navigation_during_evaluation_is_retried(self) -> None:
        """
        页面执行上下文因跳转消失时读取新地址
        """
        url = "https://115cdn.com/s/example?password=de44"
        self.page.evaluate.side_effect = [
            None,
            RuntimeError("Execution context was destroyed"),
        ]
        self.page.locator.return_value.first.is_visible.return_value = False
        calls = []

        def advance(_: int) -> None:
            calls.append(1)
            if len(calls) == 2:
                self.page.url = url

        self.page.wait_for_timeout.side_effect = advance
        self.assertEqual(self.client.unlock_resource("test-resource")["full_url"], url)

    def test_unlock_failure_toast_is_reported(self) -> None:
        """
        积分不足等业务失败不能返回解锁成功
        """
        self.page.evaluate.return_value = None
        self.page.locator.return_value.first.inner_text.return_value = "积分不足"
        with self.assertRaisesRegex(self.browser.HDHiveBrowserError, "积分不足"):
            self.client.unlock_resource("test-resource")
        self.page.get_by_role.return_value.first.click.assert_not_called()

    def test_unlock_does_not_wait_on_script_errors(self) -> None:
        """
        解锁脚本出错时立即返回异常，不等待跳转超时
        """
        self.page.evaluate.side_effect = RuntimeError("ReferenceError: invalid script")
        with self.assertRaisesRegex(self.browser.HDHiveBrowserError, "invalid script"):
            self.client.unlock_resource("test-resource")
        self.page.wait_for_timeout.assert_not_called()
        self.page.get_by_role.return_value.first.click.assert_not_called()

    def test_login_redirect_is_auth_failure(self) -> None:
        """
        登录失效时返回认证错误
        """
        self.page.url = "https://re0.me/login?redirect=%2Fresource"
        with self.assertRaises(self.browser.HDHiveLoginError):
            self.client.unlock_resource("test-resource")

    def test_invalid_slug_cannot_change_target_path(self) -> None:
        """
        拒绝将查询参数或路径穿越当作资源标识
        """
        with self.assertRaisesRegex(self.browser.HDHiveBrowserError, "slug 无效"):
            self.client.unlock_resource("../other?from=test")
        self.client._page_with_login.assert_not_called()


class TestRE0Cloudflare(TestCase):
    """
    验证首次访问 CF 等待、真实控件点击与登录失败诊断
    """

    @classmethod
    def setUpClass(cls) -> None:
        """
        隔离宿主依赖加载浏览器客户端
        """
        cls.browser = _load_browser()

    def setUp(self) -> None:
        """
        创建可推进虚拟时间的页面，避免测试实际等待
        """
        self.client = self.browser.HDHivePlaywrightClient()
        self.page = MagicMock()
        self.page.url = "https://re0.me/login"
        self.page.frames = []
        self.elapsed = 0.0

        def advance(milliseconds: int) -> None:
            self.elapsed += milliseconds / 1000

        self.page.wait_for_timeout.side_effect = advance
        clock = patch.object(self.browser, "monotonic", lambda: self.elapsed)
        clock.start()
        self.addCleanup(clock.stop)

    def test_normal_page_does_not_wait_or_click(self) -> None:
        """
        普通页面立即继续，不点击其他业务复选框
        """
        self.page.evaluate.return_value = False
        self.client._wait_for_cloudflare(self.page)
        self.page.wait_for_timeout.assert_not_called()
        self.page.context.new_cdp_session.assert_not_called()

    def test_challenge_can_pass_without_checkbox(self) -> None:
        """
        自动验证完成后继续，无需强制点击
        """
        self.page.evaluate.side_effect = [True, True, False]
        self.client._wait_for_cloudflare(self.page)
        self.assertEqual(self.elapsed, 1)

    def test_challenge_script_error_does_not_wait_ninety_seconds(self) -> None:
        """
        非跳转异常应立即报告，不能误当作 CF 等待
        """
        self.page.evaluate.side_effect = RuntimeError("ReferenceError: invalid script")
        with self.assertRaisesRegex(RuntimeError, "invalid script"):
            self.client._wait_for_cloudflare(self.page)
        self.page.wait_for_timeout.assert_not_called()

    def test_login_form_is_used_only_after_challenge(self) -> None:
        """
        登录必须先通过验证再等待输入框及填写凭据
        """
        self.page.evaluate.side_effect = [True, False]
        frame = MagicMock()
        frame.url = (
            "https://challenges.cloudflare.com/cdn-cgi/challenge-platform/widget"
        )
        frame.get_by_role.return_value.first.is_checked.return_value = False
        self.page.frames = [frame]
        events = []
        frame.get_by_role.return_value.first.click.side_effect = lambda **_: (
            events.append("verify")
        )
        with patch.object(
            self.client,
            "_fill_login_form",
            side_effect=lambda *_: events.append("fill"),
        ):
            self.assertTrue(self.client._fill_and_submit(self.page, "user", "password"))
        self.assertEqual(events, ["verify", "fill"])

    def test_closed_shadow_checkbox_uses_accessibility_bounds(self) -> None:
        """
        封闭 Shadow DOM 按无障碍树的控件边界点击并释放 CDP 会话
        """
        frame = MagicMock()
        frame.url = "https://challenges.cloudflare.com/widget"
        frame.get_by_role.return_value.first.is_visible.return_value = False
        self.page.frames = [frame]
        session = self.page.context.new_cdp_session.return_value
        session.send.side_effect = [
            {
                "nodes": [
                    {
                        "role": {"value": "checkbox"},
                        "backendDOMNodeId": 12,
                        "properties": [
                            {"name": "checked", "value": {"value": "false"}}
                        ],
                    }
                ]
            },
            {"model": {"content": [20, 30, 40, 30, 40, 50, 20, 50]}},
            {},
            {},
            {},
        ]
        self.assertTrue(self.client._click_cf_checkbox(self.page))
        self.page.context.new_cdp_session.assert_called_once_with(frame)
        session.send.assert_any_call(
            "Input.dispatchMouseEvent",
            {
                "type": "mousePressed",
                "x": 30,
                "y": 40,
                "button": "left",
                "clickCount": 1,
            },
        )
        session.detach.assert_called_once()

    def test_other_frame_checkboxes_are_not_clicked(self) -> None:
        """
        严格限制挑战域名，避免点击业务页面或相似域名
        """
        frame = MagicMock()
        frame.url = "https://challenges.cloudflare.com.example.org/widget"
        self.page.frames = [frame]
        self.assertFalse(self.client._click_cf_checkbox(self.page))
        frame.get_by_role.assert_not_called()
        self.page.context.new_cdp_session.assert_not_called()

    def test_timeout_does_not_type_credentials_and_limits_clicks(self) -> None:
        """
        持续验证最多点击三次，超时不填账号密码
        """
        self.page.evaluate.return_value = True
        with patch.object(
            self.client, "_click_cf_checkbox", return_value=True
        ) as click:
            with self.assertRaisesRegex(
                self.browser.HDHiveBrowserError, "Cloudflare.*90 秒"
            ):
                self.client._fill_and_submit(self.page, "user", "password")
        self.assertEqual(click.call_count, 3)
        self.assertEqual(self.elapsed, 90)
        self.page.fill.assert_not_called()
        self.page.wait_for_selector.assert_not_called()

    def test_navigation_during_challenge_is_retried(self) -> None:
        """
        验证跳转销毁执行上下文时继续等待新页面
        """
        self.page.evaluate.side_effect = [
            True,
            RuntimeError("Execution context was destroyed"),
            False,
        ]
        self.client._wait_for_cloudflare(self.page)
        self.assertEqual(self.elapsed, 1)

    def test_login_failure_captures_debug_before_context_closes(self) -> None:
        """
        进入签到首页之前失败也保存页面状态、截图和 HTML
        """
        self.client.set_credentials("user", "password")
        context = MagicMock()
        context.new_page.return_value = self.page
        debug = MagicMock()
        events = []
        context_manager = MagicMock()
        context_manager.__enter__.return_value = context
        context_manager.__exit__.side_effect = lambda *_: (
            events.append("close") or False
        )
        debug.save_html.side_effect = lambda *_: events.append("capture")
        with (
            patch.object(self.client, "_fresh_context", return_value=context_manager),
            patch.object(
                self.client,
                "_fill_and_submit",
                side_effect=self.browser.HDHiveLoginError("timeout"),
            ),
        ):
            with self.assertRaises(self.browser.HDHiveLoginError):
                with self.client._page_with_login(debug=debug):
                    self.fail("登录失败不能进入业务流程")
        self.assertEqual(events, ["capture", "close"])
        debug.log_page_state.assert_called_once()
        debug.screenshot.assert_called_once()


class TestRE0LoginForm(TestCase):
    """
    测试登录字段丢失、填写异常及受控表单重置时的恢复行为
    """

    @classmethod
    def setUpClass(cls) -> None:
        """
        隔离宿主依赖加载登录客户端
        """
        cls.browser = _load_browser()

    def setUp(self) -> None:
        """
        建立可以真实模拟输入值变化的字段替身
        """
        self.client = self.browser.HDHivePlaywrightClient()
        self.client._goto = MagicMock()
        self.page = MagicMock()
        self.debug = MagicMock()
        self.values = {"username": "", "password": ""}
        self.fields = {}
        for key in self.values:
            field = MagicMock()
            field.input_value.side_effect = lambda key=key, **_: self.values[key]
            field.fill.side_effect = lambda value, key=key, **_: self.values.update(
                {key: value}
            )
            field.evaluate.side_effect = lambda script, value, key=key, **_: (
                self.values.update({key: value})
            )
            self.fields[key] = field
        self.page.locator.side_effect = lambda selector: SimpleNamespace(
            first=self.fields["username" if "username" in selector else "password"]
        )

    def test_normal_form_uses_native_fill_without_fallback(self) -> None:
        """
        正常填写后校验两个字段再提交
        """
        self.assertTrue(
            self.client._fill_and_submit(self.page, "user", "secret", self.debug)
        )
        self.assertEqual(self.values, {"username": "user", "password": "secret"})
        self.page.click.assert_called_once()
        for field in self.fields.values():
            field.evaluate.assert_not_called()

    def test_silent_empty_username_is_repaired_before_submit(self) -> None:
        """
        常规填写未报错但用户名仍为空时使用原生输入事件恢复
        """
        self.fields["username"].fill.side_effect = None
        self.assertTrue(
            self.client._fill_and_submit(self.page, "user", "secret", self.debug)
        )
        self.assertEqual(self.values["username"], "user")
        self.fields["username"].evaluate.assert_called_once()
        self.page.click.assert_called_once()

    def test_fill_exception_recovers_without_logging_credentials(self) -> None:
        """
        填写异常可以恢复，但日志不记录异常内可能包含的凭据
        """
        self.fields["username"].fill.side_effect = RuntimeError(
            "private-user private-password"
        )
        self.client._fill_and_submit(
            self.page, "private-user", "private-password", self.debug
        )
        self.assertEqual(self.values["username"], "private-user")
        logged = str(self.debug.log.call_args_list)
        self.assertNotIn("private-user", logged)
        self.assertNotIn("private-password", logged)

    def test_form_rerender_clearing_username_is_retried(self) -> None:
        """
        填完密码后受控表单清空用户名时重新填写并校验
        """

        def rerender(_: int) -> None:
            if self.page.wait_for_timeout.call_count == 1:
                self.values["username"] = ""

        self.page.wait_for_timeout.side_effect = rerender
        self.client._fill_and_submit(self.page, "user", "secret", self.debug)
        self.assertEqual(self.fields["username"].fill.call_count, 2)
        self.assertEqual(self.fields["password"].fill.call_count, 1)
        self.assertEqual(self.values, {"username": "user", "password": "secret"})
        self.page.click.assert_called_once()

    def test_persistent_empty_field_never_submits(self) -> None:
        """
        三次校验均失败后明确退出，不提交空账号或通过回车兜底
        """
        self.fields["username"].fill.side_effect = None
        self.fields["username"].evaluate.side_effect = None
        with self.assertRaisesRegex(
            self.browser.HDHiveLoginError, "用户名输入值未保留"
        ):
            self.client._fill_and_submit(self.page, "user", "secret", self.debug)
        self.assertEqual(self.fields["username"].fill.call_count, 3)
        self.page.click.assert_not_called()
        self.page.keyboard.press.assert_not_called()

    def test_missing_username_field_does_not_submit(self) -> None:
        """
        必须等待两个输入框可见，不能仅凭密码框存在就继续
        """
        self.fields[
            "username"
        ].wait_for.side_effect = self.browser.PlaywrightTimeoutError("timeout")
        with self.assertRaisesRegex(
            self.browser.HDHiveLoginError, "等待登录用户名输入框超时"
        ):
            self.client._fill_and_submit(self.page, "user", "secret", self.debug)
        self.fields["password"].fill.assert_not_called()
        self.page.click.assert_not_called()
