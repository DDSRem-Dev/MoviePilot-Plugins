"""
RE0 签到结果与浏览器流程回归测试
"""

from unittest import TestCase
from unittest.mock import MagicMock, patch

from test_hdhive_browser_flow import _load_browser


checkin = _load_browser()


class TestRE0CheckinResult(TestCase):
    """
    测试新站签到提示解析
    """

    def test_already_checked_in_overrides_error_toast(self) -> None:
        """
        已签到提示即使使用失败标题和红色 Toast 也视为完成
        """
        self.assertEqual(
            checkin.parse_checkin_result(
                "签到失败\n你已经签到过了，明天再来吧", "error"
            ),
            (True, "今日已签到：你已经签到过了，明天再来吧"),
        )

    def test_success_and_gambler_loss(self) -> None:
        """
        普通签到及赌狗扣分均可表示签到完成
        """
        for text in ("签到成功，获得 8 积分", "运气不佳，本次扣除 5 积分"):
            with self.subTest(text=text):
                self.assertEqual(
                    checkin.parse_checkin_result(text, "success"), (True, text)
                )

    def test_errors_are_not_reported_as_success(self) -> None:
        """
        验证与登录错误不得被当成签到完成
        """
        for text, status in (
            ("操作失败\n请稍后重试", "error"),
            ("请先登录", ""),
            ("签到失败\n验证错误", ""),
            ("请求过于频繁", "error"),
        ):
            with self.subTest(text=text):
                self.assertEqual(
                    checkin.parse_checkin_result(text, status),
                    (False, " ".join(text.splitlines())),
                )

    def test_pending_and_unrelated_text_is_not_a_result(self) -> None:
        """
        积分说明、加载提示和菜单文字不能触发完成状态
        """
        for text in (
            "",
            "每日签到",
            "签到奖励",
            "获得积分",
            "正在处理",
            "积分+",
            "验证通过",
        ):
            with self.subTest(text=text):
                self.assertIsNone(checkin.parse_checkin_result(text))

    def test_plain_success_and_english_already_checked_in(self) -> None:
        """
        无状态样式时仍可识别明确文案
        """
        self.assertEqual(checkin.parse_checkin_result("签到成功"), (True, "签到成功"))
        self.assertTrue(
            checkin.parse_checkin_result("Already checked in today", "error")[0]
        )


class TestRE0CheckinFlow(TestCase):
    """
    测试菜单选择、结果等待和监听清理
    """

    def test_selects_requested_mode_and_waits_for_result(self) -> None:
        """
        两种模式使用各自按钮，只在捕获明确提示后返回
        """
        for gamble in (False, True):
            with self.subTest(gamble=gamble):
                page = MagicMock()
                page.evaluate.side_effect = [
                    None,
                    [],
                    [{"text": "正在处理"}],
                    [
                        {
                            "text": "签到失败\n你已经签到过了，明天再来吧",
                            "status": "error",
                        },
                    ],
                    None,
                ]
                with patch.object(checkin, "_dismiss_home_dialogs"):
                    ok, detail = checkin.run_checkin(page, gamble, MagicMock())
                self.assertTrue(ok)
                self.assertIn("今日已签到", detail)
                page.locator.assert_any_call(checkin.CHECKIN_BUTTON_SELECTORS[gamble])
                self.assertEqual(page.wait_for_timeout.call_count, 2)
                self.assertEqual(
                    page.evaluate.call_args.args[0], checkin.STOP_RESULT_OBSERVER_JS
                )

    def test_timeout_is_failure_without_repeated_submission(self) -> None:
        """
        无结果时返回超时，不在同一会话内重复点击签到
        """
        page = MagicMock()
        with (
            patch.object(checkin, "_dismiss_home_dialogs"),
            patch.object(checkin, "monotonic", side_effect=[0, 61]),
        ):
            ok, detail = checkin.run_checkin(page, False, MagicMock())
        self.assertFalse(ok)
        self.assertIn("超时", detail)
        self.assertEqual(page.locator.return_value.first.click.call_count, 2)
        self.assertEqual(
            page.evaluate.call_args.args[0], checkin.STOP_RESULT_OBSERVER_JS
        )

    def test_click_failure_disconnects_observer(self) -> None:
        """
        点击失败时也释放结果监听
        """
        page = MagicMock()
        page.locator.return_value.first.click.side_effect = [
            None,
            RuntimeError("click failed"),
        ]
        with patch.object(checkin, "_dismiss_home_dialogs"):
            with self.assertRaisesRegex(RuntimeError, "click failed"):
                checkin.run_checkin(page, False, MagicMock())
        self.assertEqual(
            page.evaluate.call_args.args[0], checkin.STOP_RESULT_OBSERVER_JS
        )

    def test_dismisses_onboarding_after_announcement(self) -> None:
        """
        等待公告倒计时后确认公告并保存首次登录设置
        """
        page = MagicMock()
        page.locator.return_value.count.side_effect = [2, 2, 1, 0]
        announcement, onboarding = MagicMock(), MagicMock()
        announcement.inner_text.return_value = "我知道了"
        onboarding.inner_text.return_value = "保存并启用推荐"
        onboarding.locator.return_value.element_handle.return_value.is_visible.return_value = False
        announcement.is_enabled.side_effect = [False, True]
        page.get_by_role.return_value.all.side_effect = [
            [announcement],
            [announcement],
            [onboarding],
        ]
        checkin._dismiss_home_dialogs(page, MagicMock())
        announcement.click.assert_called_once()
        onboarding.click.assert_called_once()
        onboarding.locator.return_value.element_handle.return_value.is_visible.assert_called_once()
        self.assertEqual(
            page.evaluate.call_args.args[0], checkin.STOP_RESULT_OBSERVER_JS
        )
        pattern = page.get_by_role.call_args.kwargs["name"]
        self.assertIsNotNone(pattern.fullmatch("保存并启用推荐"))
        self.assertIsNone(pattern.fullmatch("稍后设置"))

    def test_unknown_dialog_reports_failure(self) -> None:
        """
        无法关闭的弹窗不能被静默忽略
        """
        page = MagicMock()
        with patch.object(checkin, "monotonic", side_effect=[0, 46]):
            with self.assertRaisesRegex(RuntimeError, "首页弹窗未关闭"):
                checkin._dismiss_home_dialogs(page, MagicMock())

    def test_dismisses_top_dialog_when_onboarding_is_covered(self) -> None:
        """
        设置弹窗被公告遮挡时先关闭公告，再关闭设置弹窗
        """
        page = MagicMock()
        page.locator.return_value.count.side_effect = [2, 1, 0]
        onboarding, announcement = MagicMock(), MagicMock()
        onboarding.click.side_effect = [RuntimeError("covered by announcement"), None]
        page.get_by_role.return_value.all.side_effect = [
            [onboarding, announcement],
            [onboarding],
        ]
        checkin._dismiss_home_dialogs(page, MagicMock())
        announcement.click.assert_called_once()
        self.assertEqual(onboarding.click.call_count, 2)

    def test_stability_failure_falls_back_for_uncovered_dialog_button(self) -> None:
        """
        cloakbrowser 稳定性检查失败后仅点击无遮挡按钮
        """
        button = MagicMock()
        button.click.side_effect = RuntimeError(
            "failed stable check: element position is still changing"
        )
        button.evaluate.return_value = {"x": 100, "y": 200}
        page = MagicMock()
        checkin._click_home_dialog_button(page, button, MagicMock())
        button.evaluate.assert_called_once()
        page.mouse.click.assert_called_once_with(100, 200)

    def test_stability_fallback_does_not_click_covered_button(self) -> None:
        """
        仍被公告遮挡时拒绝坐标回退点击
        """
        button = MagicMock()
        button.click.side_effect = RuntimeError("failed stable check")
        button.evaluate.return_value = False
        page = MagicMock()
        with self.assertRaisesRegex(RuntimeError, "stable check"):
            checkin._click_home_dialog_button(page, button, MagicMock())
        page.mouse.click.assert_not_called()

    def test_unrelated_click_errors_do_not_use_coordinate_fallback(self) -> None:
        """
        页面销毁或普通点击失败不能触发稳定性回退
        """
        button = MagicMock()
        button.click.side_effect = RuntimeError("page closed")
        with self.assertRaisesRegex(RuntimeError, "page closed"):
            checkin._click_home_dialog_button(MagicMock(), button, MagicMock())
        button.evaluate.assert_not_called()

    def test_preference_save_timeout_is_not_repeated_or_skipped(self) -> None:
        """
        保存未关闭弹窗时明确失败，不重复提交或改点稍后设置
        """
        page = MagicMock()
        page.locator.return_value.count.return_value = 1
        button = MagicMock()
        button.inner_text.return_value = "保存并启用推荐"
        page.get_by_role.return_value.all.return_value = [button]
        with patch.object(checkin, "monotonic", side_effect=[0, 0, 0, 16]):
            with self.assertRaisesRegex(RuntimeError, "偏好设置提交后弹窗未关闭"):
                checkin._dismiss_home_dialogs(page, MagicMock())
        button.click.assert_called_once()
        self.assertEqual(
            page.evaluate.call_args.args[0], checkin.STOP_RESULT_OBSERVER_JS
        )

    def test_empty_provider_selection_uses_keyboard_and_verifies_checked(self) -> None:
        """
        网盘偏好为空时通过原生键盘勾选 115，并确认选中状态
        """
        dialog = MagicMock()
        providers = dialog.locator.return_value
        providers.locator.return_value.count.return_value = 0
        provider = providers.locator.return_value.filter.return_value
        checkin._ensure_preferred_provider(dialog, MagicMock())
        provider.locator.return_value.focus.assert_called_once_with(timeout=3000)
        provider.locator.return_value.press.assert_called_once_with(
            "Space", timeout=3000
        )
        provider.locator.assert_any_call('input[type="checkbox"]:checked')
        provider.locator.return_value.wait_for.assert_called_once_with(
            state="attached", timeout=3000
        )

    def test_existing_provider_preferences_are_preserved(self) -> None:
        """
        已选择任意网盘时保持原有偏好，不自动添加或取消选项
        """
        dialog = MagicMock()
        providers = dialog.locator.return_value
        providers.locator.return_value.count.return_value = 2
        checkin._ensure_preferred_provider(dialog, MagicMock())
        providers.locator.return_value.filter.assert_not_called()

    def test_provider_selection_failure_is_not_assumed_success(self) -> None:
        """
        键盘操作后没有选中网盘时明确失败
        """
        dialog = MagicMock()
        providers = dialog.locator.return_value
        providers.locator.return_value.count.return_value = 0
        provider = providers.locator.return_value.filter.return_value
        provider.locator.return_value.wait_for.side_effect = (
            checkin.PlaywrightTimeoutError("unchecked")
        )
        with self.assertRaises(checkin.PlaywrightTimeoutError):
            checkin._ensure_preferred_provider(dialog, MagicMock())

    def test_save_validation_toast_is_reported_and_observer_stopped(self) -> None:
        """
        捕获稍纵即逝的校验提示，不将业务错误误报为弹窗超时
        """
        page = MagicMock()
        page.locator.return_value.count.return_value = 1
        button = MagicMock()
        button.inner_text.return_value = "保存并启用推荐"
        page.get_by_role.return_value.all.return_value = [button]
        page.evaluate.side_effect = [
            None,
            [{"text": "请至少选择一个偏好网盘", "status": "error"}],
            None,
        ]
        with self.assertRaisesRegex(
            RuntimeError, "偏好设置保存失败：请至少选择一个偏好网盘"
        ):
            checkin._dismiss_home_dialogs(page, MagicMock())
        button.click.assert_called_once()
        self.assertEqual(
            page.evaluate.call_args.args[0], checkin.STOP_RESULT_OBSERVER_JS
        )
