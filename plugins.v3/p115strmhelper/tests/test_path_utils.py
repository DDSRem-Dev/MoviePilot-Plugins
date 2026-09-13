"""
PathUtils 测试模块

包含 sanitize_path_parts 等路径工具方法的单元测试

运行方式:
    cd plugins.v2/p115strmhelper
    PYTHONPATH=../../../MoviePilot:.. python -m unittest discover -s tests -v
"""

from pathlib import Path, PurePosixPath
from unittest import TestCase
from unittest.mock import patch

from utils.path import PathUtils


class TestSanitizePathParts(TestCase):
    """
    测试 PathUtils.sanitize_path_parts 方法

    该方法用于将相对路径各分量中的非法文件名字符替换
    - Windows: <>"|?* → 下划线，: → 全角冒号
    - 其他平台直接返回原路径
    """

    def _create_relative_path(self, *parts: str) -> Path:
        """
        辅助方法：创建纯路径对象（避免与当前运行平台相关）

        使用 PurePosixPath 来模拟相对路径，确保测试跨平台一致
        """
        return PurePosixPath(*parts)

    @patch("utils.path.os_name", "nt")
    def test_windows_single_illegal_char(self):
        """Windows：单个非法字符替换，冒号替换为全角冒号"""
        rel_path = self._create_relative_path("movie:name.mp4")
        result = PathUtils.sanitize_path_parts(rel_path)
        self.assertEqual(result.as_posix(), "movie：name.mp4")

    @patch("utils.path.os_name", "nt")
    def test_windows_multiple_illegal_chars(self):
        """Windows：多个非法字符替换"""
        rel_path = self._create_relative_path("movie<>name?test*.mp4")
        result = PathUtils.sanitize_path_parts(rel_path)
        self.assertEqual(result.as_posix(), "movie__name_test_.mp4")

    @patch("utils.path.os_name", "nt")
    def test_windows_all_illegal_chars(self):
        """Windows：所有非法字符 <>"|?* → _，: → 全角冒号"""
        rel_path = self._create_relative_path('<>:":|?*')
        result = PathUtils.sanitize_path_parts(rel_path)
        self.assertEqual(result.as_posix(), "__：_：___")

    @patch("utils.path.os_name", "nt")
    def test_windows_nested_path(self):
        """Windows：多级路径中各分量都处理，冒号替换为全角冒号"""
        rel_path = self._create_relative_path("series: 1", "episode<name>.mp4")
        result = PathUtils.sanitize_path_parts(rel_path)
        self.assertEqual(result.as_posix(), "series： 1/episode_name_.mp4")

    @patch("utils.path.os_name", "nt")
    def test_windows_no_illegal_chars(self):
        """Windows：无非法字符时原样返回"""
        rel_path = self._create_relative_path("normal", "path", "file.mp4")
        result = PathUtils.sanitize_path_parts(rel_path)
        self.assertEqual(result.as_posix(), "normal/path/file.mp4")

    @patch("utils.path.os_name", "nt")
    def test_windows_empty_path(self):
        """Windows：空路径处理"""
        rel_path = self._create_relative_path()
        result = PathUtils.sanitize_path_parts(rel_path)
        self.assertEqual(result.as_posix(), ".")

    @patch("utils.path.os_name", "nt")
    def test_windows_real_world_cases(self):
        """Windows：真实场景测试 - 常见包含非法字符的网盘文件名，冒号→全角冒号"""
        test_cases = [
            # (input, expected)
            ("Avengers: Endgame (2019).mp4", "Avengers： Endgame (2019).mp4"),
            (
                "Star Wars: Episode IV - A New Hope.mp4",
                "Star Wars： Episode IV - A New Hope.mp4",
            ),
            ("<Animation> Movie.mp4", "_Animation_ Movie.mp4"),
            ('What"s Up.mp4', "What_s Up.mp4"),
            ("File|Name.mp4", "File_Name.mp4"),
            ("Name?.mp4", "Name_.mp4"),
            ("File*Name.mp4", "File_Name.mp4"),
            # 多级路径
            (
                "TV/Series: Name/Season 1/Episode|1.mp4",
                "TV/Series： Name/Season 1/Episode_1.mp4",
            ),
        ]
        for input_path, expected in test_cases:
            with self.subTest(input=input_path):
                rel_path = self._create_relative_path(*input_path.split("/"))
                result = PathUtils.sanitize_path_parts(rel_path)
                self.assertEqual(result.as_posix(), expected)

    @patch("utils.path.os_name", "posix")
    def test_posix_returns_original(self):
        """非 Windows 平台（Linux/macOS）：直接返回原路径"""
        rel_path = self._create_relative_path("movie:name", "file<test>.mp4")
        result = PathUtils.sanitize_path_parts(rel_path)
        # 应该原样返回，不做任何替换
        self.assertEqual(result.as_posix(), "movie:name/file<test>.mp4")

    @patch("utils.path.os_name", "posix")
    def test_posix_nested_path_unchanged(self):
        """非 Windows 平台：多级路径保持不变"""
        rel_path = self._create_relative_path("series:name", "season<1>", "file*.mp4")
        result = PathUtils.sanitize_path_parts(rel_path)
        self.assertEqual(result.as_posix(), "series:name/season<1>/file*.mp4")

    @patch("utils.path.os_name", "linux")
    def test_linux_returns_original(self):
        """Linux：直接返回原路径"""
        rel_path = self._create_relative_path("movie:name.mp4")
        result = PathUtils.sanitize_path_parts(rel_path)
        self.assertEqual(result.as_posix(), "movie:name.mp4")

    @patch("utils.path.os_name", "darwin")
    def test_macos_returns_original(self):
        """macOS：直接返回原路径"""
        rel_path = self._create_relative_path("movie:name.mp4")
        result = PathUtils.sanitize_path_parts(rel_path)
        self.assertEqual(result.as_posix(), "movie:name.mp4")


class TestGetMediaFilePathsWithSuffix(TestCase):
    """
    测试 PathUtils.get_media_file_paths_with_suffix 方法
    """

    def test_iso_strm_keeps_existing_media_suffix(self):
        """ISO STRM 文件名不重复追加 ISO 后缀"""
        media_path, media_path_final = PathUtils.get_media_file_paths_with_suffix(
            "/媒体库/ISO/极限审判 (2026)/极限审判 (2026).iso.strm",
            "iso",
        )

        self.assertEqual(
            media_path,
            "/媒体库/ISO/极限审判 (2026)/极限审判 (2026).iso",
        )
        self.assertEqual(
            media_path_final,
            "/媒体库/ISO/极限审判 (2026)/极限审判 (2026).ISO",
        )

    def test_normal_strm_appends_media_suffix(self):
        """普通 STRM 文件名追加真实媒体后缀"""
        media_path, media_path_final = PathUtils.get_media_file_paths_with_suffix(
            "/媒体库/Movie/电影 (2026)/电影 (2026).strm",
            "mkv",
        )

        self.assertEqual(media_path, "/媒体库/Movie/电影 (2026)/电影 (2026).mkv")
        self.assertEqual(media_path_final, "/媒体库/Movie/电影 (2026)/电影 (2026).MKV")

    def test_windows_separator_output_is_normalized(self):
        """Windows 分隔符输入也规范化为斜杠"""
        media_path, media_path_final = PathUtils.get_media_file_paths_with_suffix(
            "\\媒体库\\ISO\\电影 (2026)\\电影 (2026).iso.strm",
            "iso",
        )

        self.assertEqual(media_path, "/媒体库/ISO/电影 (2026)/电影 (2026).iso")
        self.assertEqual(media_path_final, "/媒体库/ISO/电影 (2026)/电影 (2026).ISO")

    def test_upper_iso_strm_keeps_existing_case(self):
        """大写 ISO STRM 文件名保留已有后缀大小写"""
        media_path, media_path_final = PathUtils.get_media_file_paths_with_suffix(
            "/媒体库/ISO/电影 (2026)/电影 (2026).ISO.strm",
            "iso",
        )

        self.assertEqual(media_path, "/媒体库/ISO/电影 (2026)/电影 (2026).ISO")
        self.assertEqual(media_path_final, "/媒体库/ISO/电影 (2026)/电影 (2026).iso")


class TestPathUtilsIntegration(TestCase):
    """
    集成测试：验证 sanitize_path_parts 在实际使用场景中的行为
    """

    @patch("utils.path.os_name", "nt")
    def test_windows_strm_path_generation(self):
        """
        模拟 STRM 文件路径生成的完整流程

        从网盘路径计算本地路径时，相对路径中的非法字符应被处理
        冒号替换为全角冒号，其他字符替换为下划线
        """
        # 模拟网盘路径
        pan_media_dir = Path("/cloud/media")
        target_dir = Path("/local/media")

        # 包含非法字符的网盘文件路径
        pan_file_path = Path("/cloud/media/Movie: Name (2023)/File:Name.mp4")

        # 计算相对路径
        rel_path = pan_file_path.relative_to(pan_media_dir)
        self.assertEqual(rel_path.as_posix(), "Movie: Name (2023)/File:Name.mp4")

        # 使用 sanitize_path_parts 处理（冒号→全角冒号）
        safe_rel_path = PathUtils.sanitize_path_parts(rel_path)
        self.assertEqual(safe_rel_path.as_posix(), "Movie： Name (2023)/File：Name.mp4")

        # 组合成本地路径
        local_file_path = target_dir / safe_rel_path
        self.assertEqual(
            local_file_path.as_posix(),
            "/local/media/Movie： Name (2023)/File：Name.mp4",
        )

    @patch("utils.path.os_name", "posix")
    def test_posix_strm_path_unchanged(self):
        """
        Linux/macOS 平台：STRM 路径应保持原样（这些平台支持冒号等特殊字符）
        """
        pan_media_dir = Path("/cloud/media")
        target_dir = Path("/local/media")

        pan_file_path = Path("/cloud/media/Movie: Name (2023)/File:Name.mp4")
        rel_path = pan_file_path.relative_to(pan_media_dir)

        # 非 Windows 平台不应修改路径
        safe_rel_path = PathUtils.sanitize_path_parts(rel_path)
        self.assertEqual(safe_rel_path.as_posix(), "Movie: Name (2023)/File:Name.mp4")

        local_file_path = target_dir / safe_rel_path
        self.assertEqual(
            local_file_path.as_posix(), "/local/media/Movie: Name (2023)/File:Name.mp4"
        )


if __name__ == "__main__":
    from unittest import main

    main(verbosity=2)
