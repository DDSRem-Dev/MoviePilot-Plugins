from random import randint, choice

from p115client import P115Client, check_response

from app.core.cache import cached


class UserAgentUtils:
    """
    User-Agent 生成工具
    """

    @staticmethod
    @cached(region="p115strmhelper_util_real_app_ver", ttl=60 * 60, skip_none=True)
    def get_real_app_ver() -> str:
        """
        获取 115 iOS 端真实版本号

        :return str: 形如 "38.0.2" 的版本号
        """
        try:
            resp = P115Client.app_version_list2()
            check_response(resp)
            return resp["data"]["iOS-iPhone"]["version_code"]
        except Exception:
            return "38.0.2"

    @staticmethod
    @cached(
        region="p115strmhelper_util_user_agent_u115_ios", ttl=60 * 60, skip_none=True
    )
    def generate_u115_ios() -> str:
        """
        生成 115 iOS User-Agent 字符串

        :return str: 完整的 User-Agent 字符串
        """
        try:
            resp = P115Client.app_version_list2()
            check_response(resp)
            udown_version = resp["data"]["iOS-iPhone"]["version_code"]
            wangpan_version = resp["data"]["115wangpan_iOS"]["version_code"]
        except Exception:
            udown_version = "38.0.2"
            wangpan_version = "36.2.20"
        ios_versions = [
            "15_0",
            "15_1",
            "15_2",
            "15_3",
            "15_4",
            "15_5",
            "15_6",
            "15_7",
            "15_8",
            "16_0",
            "16_1",
            "16_2",
            "16_3",
            "16_4",
            "16_5",
            "16_6",
            "16_7",
            "17_0",
            "17_1",
            "17_2",
            "17_3",
            "17_4",
            "17_5",
            "18_0",
            "18_1",
        ]
        build_num = randint(15, 21)
        build_letter = choice("ABCDE")
        build_tail = randint(100, 999)
        build = f"{build_num}{build_letter}{build_tail}"
        webkit = "605.1.15"
        os_ver = choice(ios_versions)
        client = choice(
            [
                f"115wangpan_ios/{wangpan_version}",
                f"UDown/{udown_version}",
            ]
        )
        return (
            f"Mozilla/5.0 (iPhone; CPU iPhone OS {os_ver} like Mac OS X) "
            f"AppleWebKit/{webkit} (KHTML, like Gecko) Mobile/{build} {client}"
        )
