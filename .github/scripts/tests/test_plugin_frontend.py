import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from get_plugin_meta import build_plugin_metadata
from plugin_frontend import build_frontend, get_frontend_path, list_frontends


class TestPluginFrontend(TestCase):
    """
    验证发布版本映射及构建产物隔离
    """

    def setUp(self) -> None:
        """
        为两个版本创建内容不同的独立前后端目录
        """
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for version in ("v2", "v3"):
            frontend = self.root / f"frontend.{version}/example"
            frontend.mkdir(parents=True)
            (frontend / "package.json").write_text(
                json.dumps({"name": f"example-{version}"})
            )
            (frontend / "package-lock.json").write_text("{}")
            backend = self.root / f"plugins.{version}/example"
            (backend / "dist/assets").mkdir(parents=True)
            (backend / "__init__.py").touch()
            (backend / "dist/assets/old.js").write_text(f"old-{version}")

    def _npm(self, args, *, cwd, check):
        if args[1:] == ["run", "build"]:
            assets = cwd / "dist/assets"
            assets.mkdir(parents=True)
            (assets / "remoteEntry.js").write_text(cwd.parent.name)

    def test_release_metadata_selects_exact_major_version(self) -> None:
        """
        手动与自动发布共用的元数据严格指向同版本前端
        """
        for source, frontend in (
            ("plugins", "frontend"),
            ("plugins.v2", "frontend.v2"),
            ("plugins.v3", "frontend.v3"),
        ):
            with self.subTest(source=source):
                metadata = build_plugin_metadata("Example", "3.0.0", source, {})
                self.assertEqual(metadata["frontend_path"], f"{frontend}/example")
                self.assertEqual(metadata["backend_worker_path"], source)

    def test_discovery_keeps_separate_projects(self) -> None:
        """
        构建矩阵为每个版本单独创建任务
        """
        matrix = list_frontends(self.root)
        self.assertEqual(len(matrix), 2)
        self.assertEqual(
            {item["frontend_path"] for item in matrix},
            {"frontend.v2/example", "frontend.v3/example"},
        )

    def test_build_copies_only_matching_artifacts(self) -> None:
        """
        两版依次构建时各自安装依赖、清除旧产物并保留另一版输出
        """
        with (
            patch("plugin_frontend.shutil.which", return_value="npm"),
            patch("plugin_frontend.subprocess.run", side_effect=self._npm) as run,
        ):
            for version in ("v2", "v3"):
                destination = build_frontend(self.root, f"plugins.{version}", "example")
                self.assertEqual(
                    destination, self.root / f"plugins.{version}/example/dist"
                )
                self.assertEqual(
                    (destination / "assets/remoteEntry.js").read_text(),
                    f"frontend.{version}",
                )
                self.assertFalse((destination / "assets/old.js").exists())
            for version in ("v2", "v3"):
                self.assertEqual(
                    (
                        self.root
                        / f"plugins.{version}/example/dist/assets/remoteEntry.js"
                    ).read_text(),
                    f"frontend.{version}",
                )
            self.assertEqual(
                [call.kwargs["cwd"].parent.name for call in run.call_args_list],
                ["frontend.v2", "frontend.v2", "frontend.v3", "frontend.v3"],
            )

    def test_missing_version_does_not_fall_back(self) -> None:
        """
        缺少 V3 前端时直接报错，不能借用 V2 的同名项目
        """
        (self.root / "frontend.v3/example/package.json").unlink()
        with patch("plugin_frontend.subprocess.run") as run:
            with self.assertRaises(FileNotFoundError):
                build_frontend(self.root, "plugins.v3", "example")
        run.assert_not_called()

    def test_failed_build_preserves_installed_backend_assets(self) -> None:
        """
        构建失败时不破坏当前插件已安装的前端
        """
        with (
            patch("plugin_frontend.shutil.which", return_value="npm"),
            patch(
                "plugin_frontend.subprocess.run",
                side_effect=subprocess.CalledProcessError(1, "npm"),
            ),
        ):
            with self.assertRaises(subprocess.CalledProcessError):
                build_frontend(self.root, "plugins.v3", "example")
        self.assertEqual(
            (self.root / "plugins.v3/example/dist/assets/old.js").read_text(), "old-v3"
        )

    def test_missing_entry_cannot_package_stale_build(self) -> None:
        """
        构建未输出联邦入口时不能把上次构建误当作成功产物
        """
        stale = self.root / "frontend.v3/example/dist/assets"
        stale.mkdir(parents=True)
        (stale / "remoteEntry.js").write_text("stale")
        with (
            patch("plugin_frontend.shutil.which", return_value="npm"),
            patch("plugin_frontend.subprocess.run"),
        ):
            with self.assertRaisesRegex(RuntimeError, "remoteEntry"):
                build_frontend(self.root, "plugins.v3", "example", install=False)
        self.assertTrue((self.root / "plugins.v3/example/dist/assets/old.js").exists())

    def test_invalid_directory_is_rejected(self) -> None:
        """
        路径参数只能选择合法的版本与插件目录
        """
        for source, plugin in (("plugins.v4", "example"), ("plugins.v3", "../example")):
            with self.assertRaises(ValueError):
                get_frontend_path(source, plugin)
