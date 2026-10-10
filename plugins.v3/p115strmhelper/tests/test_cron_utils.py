"""
CronUtils 测试模块

包含 cron 表达式验证和修复工具方法的单元测试
"""

from unittest import TestCase

from utils.cron import CronUtils


class TestValidateCronExpression(TestCase):
    """测试 CronUtils.validate_cron_expression 方法"""

    def test_valid_standard_expressions(self):
        """测试有效标准 cron 表达式"""
        valid_cases = [
            "0 */6 * * *",  # 每 6 小时
            "0 0 * * *",  # 每天零点
            "*/5 * * * *",  # 每 5 分钟
            "0 2 * * 1",  # 每周一 2 点
            "0 0 1 * *",  # 每月 1 号
        ]
        for expr in valid_cases:
            with self.subTest(expr=expr):
                is_valid, error = CronUtils.validate_cron_expression(expr)
                self.assertTrue(is_valid, f"'{expr}' 应有效，但返回: {error}")
                self.assertEqual(error, "")

    def test_invalid_expressions(self):
        """测试无效 cron 表达式"""
        invalid_cases = [
            "invalid",  # 完全无效
            "1 2 3",  # 字段不足
            "0 0 * *",  # 字段不足
            "60 * * * *",  # 分钟越界
            "0 25 * * *",  # 小时越界
        ]
        for expr in invalid_cases:
            with self.subTest(expr=expr):
                is_valid, error = CronUtils.validate_cron_expression(expr)
                self.assertFalse(is_valid, f"'{expr}' 应无效")
                self.assertNotEqual(error, "")

    def test_empty_input(self):
        """测试空输入"""
        is_valid, error = CronUtils.validate_cron_expression("")
        self.assertFalse(is_valid)
        self.assertEqual(error, "")

        is_valid, error = CronUtils.validate_cron_expression("   ")
        self.assertFalse(is_valid)
        self.assertEqual(error, "")

    def test_none_input(self):
        """测试 None 输入"""
        is_valid, error = CronUtils.validate_cron_expression(None)
        self.assertFalse(is_valid)


class TestFixCronExpression(TestCase):
    """测试 CronUtils.fix_cron_expression 方法"""

    def test_no_fix_needed(self):
        """测试无需修复的表达式"""
        expr = "0 */6 * * *"
        self.assertEqual(CronUtils.fix_cron_expression(expr), expr)

    def test_minute_out_of_range(self):
        """测试分钟越界修复"""
        # 分钟 > 59
        self.assertEqual(CronUtils.fix_cron_expression("60 * * * *"), "59 * * * *")
        # 分钟 < 0（会被解析为字段值错误，保持原样）

    def test_hour_out_of_range(self):
        """测试小时越界修复"""
        self.assertEqual(CronUtils.fix_cron_expression("0 25 * * *"), "0 23 * * *")
        self.assertEqual(CronUtils.fix_cron_expression("0 30 * * *"), "0 23 * * *")

    def test_day_out_of_range(self):
        """测试日期越界修复"""
        self.assertEqual(CronUtils.fix_cron_expression("0 0 32 * *"), "0 0 31 * *")
        self.assertEqual(CronUtils.fix_cron_expression("0 0 0 * *"), "0 0 1 * *")

    def test_month_out_of_range(self):
        """测试月份越界修复"""
        self.assertEqual(CronUtils.fix_cron_expression("0 0 1 13 *"), "0 0 1 12 *")
        self.assertEqual(CronUtils.fix_cron_expression("0 0 1 0 *"), "0 0 1 1 *")

    def test_weekday_out_of_range(self):
        """测试星期越界修复"""
        self.assertEqual(CronUtils.fix_cron_expression("0 0 * * 8"), "0 0 * * 7")

    def test_range_fix(self):
        """测试范围表达式修复"""
        # 反转的范围
        result = CronUtils.fix_cron_expression("0 20-10 * * *")
        self.assertEqual(result, "0 10-20 * * *")
        # 越界范围
        self.assertEqual(CronUtils.fix_cron_expression("0 0-30 * * *"), "0 0-23 * * *")

    def test_step_fix(self):
        """测试步长表达式修复"""
        # 步长过大
        self.assertEqual(CronUtils.fix_cron_expression("*/100 * * * *"), "*/59 * * * *")
        # 步长为 0 或负数
        self.assertEqual(CronUtils.fix_cron_expression("*/0 * * * *"), "*/1 * * * *")

    def test_list_fix(self):
        """测试列表表达式修复"""
        self.assertEqual(CronUtils.fix_cron_expression("0,70 * * * *"), "0,59 * * * *")
        # 测试分钟列表中有多个值越界
        self.assertEqual(
            CronUtils.fix_cron_expression("0,70,80 * * * *"), "0,59,59 * * * *"
        )

    def test_complex_expression(self):
        """测试复杂表达式修复"""
        # 混合范围、步长和列表
        expr = "0,70 0-30/5 32 13 8"
        result = CronUtils.fix_cron_expression(expr)
        parts = result.split()
        self.assertEqual(parts[0], "0,59")  # 分钟
        self.assertEqual(parts[2], "31")  # 日期
        self.assertEqual(parts[3], "12")  # 月份
        self.assertEqual(parts[4], "7")  # 星期

    def test_wildcard_preserved(self):
        """测试通配符保持"""
        self.assertEqual(CronUtils.fix_cron_expression("* * * * *"), "* * * * *")


class TestGetDefaultCron(TestCase):
    """测试 CronUtils.get_default_cron 方法"""

    def test_default_value(self):
        """测试默认值"""
        default = CronUtils.get_default_cron()
        self.assertEqual(default, "0 */6 * * *")
        # 验证是有效的
        is_valid, _ = CronUtils.validate_cron_expression(default)
        self.assertTrue(is_valid)


class TestIsValidCron(TestCase):
    """测试 CronUtils.is_valid_cron 方法"""

    def test_valid_returns_true(self):
        """测试有效表达式返回 True"""
        self.assertTrue(CronUtils.is_valid_cron("0 */6 * * *"))
        self.assertTrue(CronUtils.is_valid_cron("*/5 * * * *"))

    def test_invalid_returns_false(self):
        """测试无效表达式返回 False"""
        self.assertFalse(CronUtils.is_valid_cron("invalid"))
        self.assertFalse(CronUtils.is_valid_cron(""))
        self.assertFalse(CronUtils.is_valid_cron(None))


class TestFixCronField(TestCase):
    """测试 CronUtils._fix_cron_field 内部方法"""

    def test_single_value(self):
        """测试单个值修复"""
        self.assertEqual(CronUtils._fix_cron_field("70", 0, 59), "59")
        # 负数无法转换为整数，保持原样
        self.assertEqual(CronUtils._fix_cron_field("-5", 0, 59), "-5")

    def test_range_value(self):
        """测试范围修复"""
        # 正常范围
        self.assertEqual(CronUtils._fix_cron_field("10-20", 0, 59), "10-20")
        # 反转范围
        self.assertEqual(CronUtils._fix_cron_field("20-10", 0, 59), "10-20")
        # 越界范围
        self.assertEqual(CronUtils._fix_cron_field("50-70", 0, 59), "50-59")

    def test_step_value(self):
        """测试步长修复"""
        # 正常步长
        self.assertEqual(CronUtils._fix_cron_field("*/5", 0, 59), "*/5")
        # 步长过大
        self.assertEqual(CronUtils._fix_cron_field("*/100", 0, 59), "*/59")
        # 范围 + 步长
        self.assertEqual(CronUtils._fix_cron_field("0-10/3", 0, 59), "0-10/3")

    def test_list_value(self):
        """测试列表修复"""
        self.assertEqual(CronUtils._fix_cron_field("0,30,70", 0, 59), "0,30,59")

    def test_wildcard(self):
        """测试通配符"""
        self.assertEqual(CronUtils._fix_cron_field("*", 0, 59), "*")


if __name__ == "__main__":
    from unittest import main

    main(verbosity=2)
