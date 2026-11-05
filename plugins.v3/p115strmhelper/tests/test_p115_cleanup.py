"""
p115_cleanup 测试：用内存版 115 存储实现 StorageChain 接口，驱动真实清理实现
"""

import importlib.util
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from unittest import TestCase

_SRC = Path(__file__).resolve().parent.parent / "helper/mediasyncdel/p115_cleanup.py"
_spec = importlib.util.spec_from_file_location("p115_cleanup_under_test", _SRC)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

VIDEO = [".mkv", ".mp4", ".iso", ".strm"]
SUB = [".ass", ".srt", ".ssa", ".sub"]
AUDIO = [".mka", ".flac"]
ROOT = "/115/媒体库"


class FakeChain:
    """内存 115：目录 dict，文件 set；可注入失败"""

    def __init__(self, files=(), dirs=()):
        self.files = set(files)
        self.dirs = {ROOT, "/115"}
        for d in dirs:
            self.dirs.add(d)
        for f in self.files:
            self._add_parents(f)
        self.fail_list = set()
        self.fail_delete = set()
        self.list_none = set()
        self.deleted = []

    def _add_parents(self, p):
        for par in PurePosixPath(p).parents:
            if str(par) != "/":
                self.dirs.add(str(par))

    def _item(self, p):
        if p in self.files:
            return SimpleNamespace(
                storage="u115", type="file", path=p, name=PurePosixPath(p).name, fileid=p
            )
        if p in self.dirs:
            return SimpleNamespace(
                storage="u115", type="dir", path=p + "/", name=PurePosixPath(p).name, fileid=p
            )
        return None

    def get_file_item_strict(self, storage, path):
        return self._item(str(path))

    def list_files(self, item, recursion=False):
        d = item.path.rstrip("/")
        if d in self.list_none:
            return None
        if d in self.fail_list:
            raise FileNotFoundError(d)
        out = []
        for f in sorted(self.files):
            if str(PurePosixPath(f).parent) == d:
                out.append(self._item(f))
        for x in sorted(self.dirs):
            if x != d and str(PurePosixPath(x).parent) == d:
                out.append(self._item(x))
        return out

    def delete_file(self, item):
        p = item.path.rstrip("/")
        if p in self.fail_delete:
            return False
        self.deleted.append(p)
        if p in self.files:
            self.files.discard(p)
            return True
        if p in self.dirs:
            # 真实 115 会递归删除非空目录：这里照做，使“误删非空目录”可被测试发现
            self.dirs = {d for d in self.dirs if d != p and not d.startswith(p + "/")}
            self.files = {f for f in self.files if not f.startswith(p + "/")}
            return True
        return False


def cleaner(chain):
    return mod.P115Cleaner(chain, VIDEO, SUB, AUDIO)


M = f"{ROOT}/电影/Movie (2020)"
S = f"{ROOT}/剧集/Show (2020)/Season 1"


class SubtitleBoundary(TestCase):
    def test_boundary(self):
        f = lambda n, s: mod.subtitle_belongs_to(n, s, {"ass", "srt"})
        self.assertTrue(f("A.S01E01.ass", "A.S01E01"))
        self.assertTrue(f("A.S01E01.zh-CN.ass", "A.S01E01"))
        self.assertTrue(f("A.S01E01.zh-TW.forced.srt", "A.S01E01"))
        self.assertFalse(f("A.S01E010.zh-CN.ass", "A.S01E01"))
        self.assertFalse(f("A.S01E01x.ass", "A.S01E01"))
        self.assertFalse(f("A.S01E01.zh.nfo", "A.S01E01"))
        self.assertFalse(f("A.S01E01.a.b.c.d.ass", "A.S01E01"))


class DeleteGroup(TestCase):
    def test_movie_all_removed_dir_removed_stop_at_root(self):
        c = FakeChain([f"{M}/Movie.mkv", f"{M}/Movie.zh-CN.ass", f"{M}/Movie.zh-TW.forced.srt"])
        r = cleaner(c).delete_video_group("u115", f"{M}/Movie.mkv", ROOT)
        self.assertTrue(r.ok, r)
        self.assertEqual(c.files, set())
        self.assertIn(M, r.dirs_deleted)
        self.assertIn(ROOT, c.dirs)  # 根保留
        self.assertNotIn(ROOT, r.dirs_deleted)

    def test_climbs_only_empty_dirs_to_root(self):
        c = FakeChain([f"{M}/Movie.mkv"])
        r = cleaner(c).delete_video_group("u115", f"{M}/Movie.mkv", ROOT)
        self.assertEqual(r.dirs_deleted, [M, f"{ROOT}/电影"])
        self.assertIn(ROOT, c.dirs)

    def test_nfo_and_images_purged_when_no_video_left(self):
        c = FakeChain([f"{M}/Movie.mkv", f"{M}/Movie.nfo", f"{M}/poster.jpg", f"{M}/Movie.en.srt"])
        r = cleaner(c).delete_video_group("u115", f"{M}/Movie.mkv", ROOT)
        self.assertTrue(r.ok, r)
        self.assertEqual(c.files, set())
        self.assertEqual(sorted(r.leftovers_deleted), [f"{M}/Movie.nfo", f"{M}/poster.jpg"])
        self.assertIn(M, r.dirs_deleted)
        self.assertIn(ROOT, c.dirs)

    def test_any_leftover_file_purged_when_no_video_left(self):
        c = FakeChain([
            f"{M}/Movie.mkv", f"{M}/Movie.nfo", f"{M}/notes.txt", f"{M}/theme.mp3",
            f"{M}/noext", f"{M}/Other.zh.ass", f"{M}/x/y/z.bin",
        ])
        r = cleaner(c).delete_video_group("u115", f"{M}/Movie.mkv", ROOT)
        self.assertTrue(r.ok, r)
        self.assertEqual(c.files, set())
        self.assertNotIn(M, c.dirs)
        self.assertEqual(len(r.leftovers_deleted), 6)
        self.assertIn(ROOT, c.dirs)

    def test_strm_blocks_purge(self):
        c = FakeChain([f"{M}/Movie.mkv", f"{M}/Movie.nfo", f"{M}/Movie - alt.strm"])
        r = cleaner(c).delete_video_group("u115", f"{M}/Movie.mkv", ROOT)
        self.assertTrue(r.ok)
        self.assertEqual(c.files, {f"{M}/Movie.nfo", f"{M}/Movie - alt.strm"})

    def test_other_video_keeps_sidecars(self):
        c = FakeChain([f"{M}/Movie.mkv", f"{M}/Movie - 4K.mkv", f"{M}/Movie.nfo", f"{M}/poster.jpg"])
        r = cleaner(c).delete_video_group("u115", f"{M}/Movie.mkv", ROOT)
        self.assertTrue(r.ok)
        self.assertEqual(c.files, {f"{M}/Movie - 4K.mkv", f"{M}/Movie.nfo", f"{M}/poster.jpg"})

    def test_video_in_subdir_keeps_sidecars(self):
        c = FakeChain([f"{M}/Movie.mkv", f"{M}/Movie.nfo", f"{M}/Extras/bts.mkv"])
        r = cleaner(c).delete_video_group("u115", f"{M}/Movie.mkv", ROOT)
        self.assertTrue(r.ok)
        self.assertEqual(c.files, {f"{M}/Movie.nfo", f"{M}/Extras/bts.mkv"})

    def test_purge_can_be_disabled(self):
        c = FakeChain([f"{M}/Movie.mkv", f"{M}/Movie.nfo"])
        cl = mod.P115Cleaner(c, VIDEO, SUB, AUDIO, purge_leftovers=False)
        r = cl.delete_video_group("u115", f"{M}/Movie.mkv", ROOT)
        self.assertTrue(r.ok)
        self.assertEqual(c.files, {f"{M}/Movie.nfo"})

    def test_late_video_not_deleted(self):
        c = FakeChain([f"{M}/Movie.mkv", f"{M}/Movie.nfo"])
        orig = c.delete_file

        def racing(item):
            ok = orig(item)
            if item.path.endswith("Movie.mkv"):
                c.files.add(f"{M}/late.mkv")
            return ok

        c.delete_file = racing
        r = cleaner(c).delete_video_group("u115", f"{M}/Movie.mkv", ROOT)
        self.assertIn(f"{M}/late.mkv", c.files)
        self.assertIn(M, c.dirs)

    def test_subdir_with_video_keeps_everything(self):
        c = FakeChain([f"{M}/Movie.mkv", f"{M}/Extras/readme.txt", f"{M}/Extras/bts.mp4"])
        r = cleaner(c).delete_video_group("u115", f"{M}/Movie.mkv", ROOT)
        self.assertTrue(r.ok)
        self.assertEqual(c.files, {f"{M}/Extras/readme.txt", f"{M}/Extras/bts.mp4"})

    def test_empty_subdir_shell_removed(self):
        c = FakeChain([f"{M}/Movie.mkv", f"{M}/poster.jpg"], dirs=[f"{M}/Extras"])
        r = cleaner(c).delete_video_group("u115", f"{M}/Movie.mkv", ROOT)
        self.assertTrue(r.ok, r)
        self.assertNotIn(M, c.dirs)

    def test_e01_vs_e010_and_other_episodes_kept(self):
        d = S
        c = FakeChain([
            f"{d}/Show.S01E01.mkv", f"{d}/Show.S01E01.zh-CN.ass",
            f"{d}/Show.S01E010.mkv", f"{d}/Show.S01E010.zh-CN.ass",
            f"{d}/Show.S01E02.mkv", f"{d}/Show.S01E02.ass",
        ])
        r = cleaner(c).delete_video_group("u115", f"{d}/Show.S01E01.mkv", ROOT)
        self.assertTrue(r.ok)
        self.assertEqual(r.subtitles_deleted, ["Show.S01E01.zh-CN.ass"])
        self.assertEqual(len(c.files), 4)
        self.assertIn(d, c.dirs)

    def test_shared_subtitle_kept_when_other_video_claims(self):
        # 同主名不同容器：字幕被另一视频共用
        c = FakeChain([f"{M}/Movie.mkv", f"{M}/Movie.mp4", f"{M}/Movie.zh-CN.ass"])
        r = cleaner(c).delete_video_group("u115", f"{M}/Movie.mkv", ROOT)
        self.assertTrue(r.ok)
        self.assertEqual(r.subtitles_kept, ["Movie.zh-CN.ass"])
        self.assertEqual(c.files, {f"{M}/Movie.mp4", f"{M}/Movie.zh-CN.ass"})
        # 再删第二个版本，字幕随之清理
        r2 = cleaner(c).delete_video_group("u115", f"{M}/Movie.mp4", ROOT)
        self.assertEqual(r2.subtitles_deleted, ["Movie.zh-CN.ass"])
        self.assertNotIn(M, c.dirs)

    def test_version_suffix_subtitle_claimed_by_longer_stem_video(self):
        c = FakeChain([f"{M}/Movie.mkv", f"{M}/Movie - 4K.mkv", f"{M}/Movie - 4K.zh.ass", f"{M}/Movie.zh.ass"])
        r = cleaner(c).delete_video_group("u115", f"{M}/Movie.mkv", ROOT)
        self.assertEqual(r.subtitles_deleted, ["Movie.zh.ass"])
        self.assertIn(f"{M}/Movie - 4K.zh.ass", c.files)

    def test_list_failure_means_no_write(self):
        c = FakeChain([f"{M}/Movie.mkv", f"{M}/Movie.ass"])
        c.fail_list.add(M)
        r = cleaner(c).delete_video_group("u115", f"{M}/Movie.mkv", ROOT)
        self.assertFalse(r.ok)
        self.assertEqual(c.deleted, [])
        c.fail_list.clear()
        c.list_none.add(M)
        r = cleaner(c).delete_video_group("u115", f"{M}/Movie.mkv", ROOT)
        self.assertFalse(r.ok)
        self.assertEqual(c.deleted, [])

    def test_video_delete_failure_touches_nothing_else(self):
        c = FakeChain([f"{M}/Movie.mkv", f"{M}/Movie.ass"])
        c.fail_delete.add(f"{M}/Movie.mkv")
        r = cleaner(c).delete_video_group("u115", f"{M}/Movie.mkv", ROOT)
        self.assertFalse(r.ok)
        self.assertEqual(c.deleted, [])

    def test_subtitle_delete_failure_reported_and_dir_kept(self):
        c = FakeChain([f"{M}/Movie.mkv", f"{M}/Movie.ass"])
        c.fail_delete.add(f"{M}/Movie.ass")
        r = cleaner(c).delete_video_group("u115", f"{M}/Movie.mkv", ROOT)
        self.assertFalse(r.ok)
        self.assertIn(M, c.dirs)
        self.assertIn(f"{M}/Movie.ass", c.files)

    def test_idempotent_second_run(self):
        c = FakeChain([f"{M}/Movie.mkv", f"{M}/Movie.nfo"])
        cl = cleaner(c)
        self.assertTrue(cl.delete_video_group("u115", f"{M}/Movie.mkv", ROOT).ok)
        r = cl.delete_video_group("u115", f"{M}/Movie.mkv", ROOT)
        self.assertTrue(r.ok)
        self.assertTrue(r.video_already_absent)
        self.assertEqual(c.files, set())

    def test_idempotent_when_dir_also_gone(self):
        c = FakeChain([f"{M}/Movie.mkv"])
        cl = cleaner(c)
        cl.delete_video_group("u115", f"{M}/Movie.mkv", ROOT)
        r = cl.delete_video_group("u115", f"{M}/Movie.mkv", ROOT)
        self.assertTrue(r.ok)

    def test_refuses_non_video_and_dir_targets(self):
        c = FakeChain([f"{M}/Movie.ass", f"{M}/Movie.mkv"])
        self.assertFalse(cleaner(c).delete_video_group("u115", f"{M}/Movie.ass", ROOT).ok)
        self.assertFalse(cleaner(c).delete_video_group("u115", M, ROOT).ok)
        self.assertEqual(c.deleted, [])

    def test_target_outside_root_deletes_files_but_no_dirs(self):
        o = "/其它/Movie (2020)"
        c = FakeChain([f"{o}/Movie.mkv", f"{o}/Movie.ass"])
        r = cleaner(c).delete_video_group("u115", f"{o}/Movie.mkv", ROOT)
        self.assertTrue(r.ok)
        self.assertIn(o, c.dirs)
        self.assertEqual(r.dirs_deleted, [])

    def test_no_root_means_no_dir_cleanup(self):
        c = FakeChain([f"{M}/Movie.mkv"])
        r = cleaner(c).delete_video_group("u115", f"{M}/Movie.mkv", None)
        self.assertTrue(r.ok)
        self.assertIn(M, c.dirs)

    def test_missing_strict_api_fails_closed(self):
        c = FakeChain([f"{M}/Movie.mkv"])
        c.get_file_item_strict = None
        r = cleaner(c).delete_video_group("u115", f"{M}/Movie.mkv", ROOT)
        self.assertFalse(r.ok)
        self.assertEqual(c.deleted, [])


class SelectSuffix(TestCase):
    def _items(self, names):
        return [SimpleNamespace(type="file", name=n) for n in names]

    def test_subtitle_first_does_not_win(self):
        items = self._items(["X.ass", "X.mkv", "X.nfo"])
        self.assertEqual(mod.select_video_suffix(items, "X", VIDEO, SUB, AUDIO), "mkv")
        self.assertEqual(
            mod.select_video_suffix(list(reversed(items)), "X", VIDEO, SUB, AUDIO), "mkv"
        )

    def test_no_video_none(self):
        self.assertIsNone(mod.select_video_suffix(self._items(["X.ass"]), "X", VIDEO, SUB, AUDIO))
        self.assertIsNone(mod.select_video_suffix(self._items(["Y.mkv"]), "X", VIDEO, SUB, AUDIO))

    def test_ambiguous_none(self):
        self.assertIsNone(
            mod.select_video_suffix(self._items(["X.mkv", "X.mp4"]), "X", VIDEO, SUB, AUDIO)
        )

    def test_list_failure_none(self):
        self.assertIsNone(mod.select_video_suffix(None, "X", VIDEO, SUB, AUDIO))


class Hardening(TestCase):
    def test_absent_target_with_other_container_same_stem_refused(self):
        # Container 报文给错后缀：不得把“mkv 不存在”当成已删除，而真实 mp4 与字幕留着
        c = FakeChain([f"{M}/Movie.mp4", f"{M}/Movie.zh.ass"])
        r = cleaner(c).delete_video_group("u115", f"{M}/Movie.mkv", ROOT)
        self.assertFalse(r.ok)
        self.assertEqual(c.deleted, [])

    def test_absent_target_orphan_subtitles_cleaned(self):
        c = FakeChain([f"{M}/Movie.zh.ass", f"{M}/Movie.nfo"])
        r = cleaner(c).delete_video_group("u115", f"{M}/Movie.mkv", ROOT)
        self.assertTrue(r.ok)
        self.assertEqual(c.files, set())

    def test_dir_cleanup_only_for_verified_storages(self):
        c = FakeChain([f"{M}/Movie.mkv", f"{M}/Movie.ass"])
        r = cleaner(c).delete_video_group("115网盘Plus", f"{M}/Movie.mkv", ROOT)
        self.assertTrue(r.ok)
        self.assertEqual(c.files, set())
        self.assertIn(M, c.dirs)  # 未验证存储：不清目录
        self.assertEqual(r.dirs_deleted, [])

    def test_prefix_stem_other_episode_not_deleted(self):
        c = FakeChain([f"{S}/A.S01E01.mkv", f"{S}/A.S01E01.ass", f"{S}/A.S01E011.mkv", f"{S}/A.S01E011.ass"])
        r = cleaner(c).delete_video_group("u115", f"{S}/A.S01E01.mkv", ROOT)
        self.assertTrue(r.ok)
        self.assertEqual(c.files, {f"{S}/A.S01E011.mkv", f"{S}/A.S01E011.ass"})

    def test_last_second_nonempty_recheck(self):
        # 复核列表为空，但删目录前新文件出现：不删目录
        c = FakeChain([f"{M}/Movie.mkv"])
        cl = cleaner(c)
        orig = c.list_files
        calls = {"n": 0}

        def lf(item, recursion=False):
            res = orig(item, recursion)
            if item.path.rstrip("/") == M:
                calls["n"] += 1
                if calls["n"] == 3:  # plan, 删后复核 之后的“删前复核”
                    c.files.add(f"{M}/late.nfo")
                    return orig(item, recursion)
            return res

        c.list_files = lf
        r = cl.delete_video_group("u115", f"{M}/Movie.mkv", ROOT)
        self.assertIn(M, c.dirs)
        self.assertIn(f"{M}/late.nfo", c.files)
        self.assertEqual(r.dirs_deleted, [])

    def test_dir_target_message(self):
        c = FakeChain([f"{M}/Movie.mkv"])
        p = cleaner(c).plan("u115", M + ".mkv", ROOT)  # 不存在的目录样路径
        self.assertTrue(p.ok or p.reason)


class ContainerSuffix(TestCase):
    def test_valid(self):
        f = lambda c: mod.valid_container_suffix(c, VIDEO, SUB, AUDIO)
        self.assertEqual(f("mkv"), "mkv")
        self.assertEqual(f(".MP4"), "MP4")
        self.assertIsNone(f("mov,mp4,m4a,3gp,3g2,mj2"))
        self.assertIsNone(f("matroska"))
        self.assertIsNone(f("ass"))
        self.assertIsNone(f(""))
        self.assertIsNone(f(None))


SHOW = f"{ROOT}/剧集/Show (2020)"


def dgroup(c, path, allow=True, root=ROOT):
    return cleaner(c).delete_group("u115", path, root, allow)


class DirMode(TestCase):
    def tv(self):
        return FakeChain([
            f"{SHOW}/Season 1/S01E01.mkv", f"{SHOW}/Season 1/S01E01.zh-CN.ass",
            f"{SHOW}/Season 1/S01E02.mkv",
            f"{SHOW}/Season 2/S02E01.mkv", f"{SHOW}/Season 2/S02E01.zh-TW.forced.ass",
            f"{SHOW}/Season 2/Extras/bonus.mkv",
        ])

    def test_season_deletes_only_that_season_and_vacuums(self):
        c = self.tv()
        r = dgroup(c, f"{SHOW}/Season 2")
        self.assertTrue(r.ok, r)
        self.assertEqual(len(r.files_deleted), 3)
        self.assertNotIn(f"{SHOW}/Season 2", c.dirs)
        self.assertNotIn(f"{SHOW}/Season 2/Extras", c.dirs)
        self.assertIn(f"{SHOW}/Season 1/S01E01.mkv", c.files)
        self.assertIn(SHOW, c.dirs)

    def test_series_deletes_everything_and_climbs_to_root(self):
        c = self.tv()
        r = dgroup(c, SHOW)
        self.assertTrue(r.ok, r)
        self.assertEqual(c.files, set())
        self.assertNotIn(SHOW, c.dirs)
        self.assertNotIn(f"{ROOT}/剧集", c.dirs)
        self.assertIn(ROOT, c.dirs)

    def test_season_with_poster_purged_other_season_kept(self):
        c = self.tv()
        c.files.add(f"{SHOW}/Season 2/season02-poster.jpg")
        c.files.add(f"{SHOW}/tvshow.nfo")
        r = dgroup(c, f"{SHOW}/Season 2")
        self.assertTrue(r.ok, r)
        self.assertNotIn(f"{SHOW}/Season 2", c.dirs)
        self.assertIn(f"{SHOW}/Season 1/S01E01.mkv", c.files)
        self.assertIn(f"{SHOW}/tvshow.nfo", c.files)  # 剧集仍有视频，保留
        self.assertIn(SHOW, c.dirs)

    def test_series_any_leftover_purged(self):
        c = self.tv()
        c.files.add(f"{SHOW}/tvshow.nfo")
        c.files.add(f"{SHOW}/Season 1/notes.txt")
        c._add_parents(f"{SHOW}/Season 1/notes.txt")
        r = dgroup(c, SHOW)
        self.assertTrue(r.ok, r)
        self.assertEqual(c.files, set())
        self.assertNotIn(SHOW, c.dirs)

    def test_unknown_video_ext_in_other_season_keeps_show(self):
        c = self.tv()
        c.files.add(f"{SHOW}/Season 2/season02-poster.jpg")
        c.files.add(f"{SHOW}/tvshow.nfo")
        r = dgroup(c, f"{SHOW}/Season 2")
        self.assertTrue(r.ok, r)
        self.assertIn(f"{SHOW}/tvshow.nfo", c.files)

    def test_dir_not_allowed_for_movies_or_episodes(self):
        c = self.tv()
        r = dgroup(c, f"{SHOW}/Season 2", allow=False)
        self.assertFalse(r.ok)
        self.assertEqual(c.deleted, [])

    def test_list_failure_in_subdir_means_no_write(self):
        c = self.tv()
        c.fail_list.add(f"{SHOW}/Season 2/Extras")
        r = dgroup(c, SHOW)
        self.assertFalse(r.ok)
        self.assertEqual(c.deleted, [])

    def test_missing_dir_is_idempotent_ok(self):
        c = FakeChain([f"{M}/x.mkv"])
        r = dgroup(c, f"{ROOT}/剧集/Gone (2020)")
        self.assertTrue(r.ok)
        self.assertTrue(r.video_already_absent)
        self.assertEqual(c.deleted, [])

    def test_target_is_file_rejected_in_dir_mode(self):
        c = FakeChain([f"{SHOW}/Season 1/notes"])
        r = dgroup(c, f"{SHOW}/Season 1/notes")
        self.assertFalse(r.ok)
        self.assertEqual(c.deleted, [])

    def test_video_cap(self):
        files = [f"{SHOW}/Season 1/e{i}.mkv" for i in range(mod.MAX_DIR_VIDEOS + 1)]
        c = FakeChain(files)
        r = dgroup(c, SHOW)
        self.assertFalse(r.ok)
        self.assertEqual(c.deleted, [])

    def test_unverified_storage_refused(self):
        c = self.tv()
        r = cleaner(c).delete_group("115网盘Plus", SHOW, ROOT, True)
        self.assertFalse(r.ok)
        self.assertEqual(c.deleted, [])

    def test_video_path_still_uses_file_mode(self):
        c = self.tv()
        r = dgroup(c, f"{SHOW}/Season 1/S01E01.mkv")
        self.assertTrue(r.ok)
        self.assertEqual(r.mode, "file")
        self.assertIn(f"{SHOW}/Season 1/S01E02.mkv", c.files)

    def test_twice_is_idempotent(self):
        c = self.tv()
        self.assertTrue(dgroup(c, f"{SHOW}/Season 2").ok)
        self.assertTrue(dgroup(c, f"{SHOW}/Season 2").ok)


class Review(TestCase):
    def test_canonical_paths(self):
        f = mod.path_is_canonical
        self.assertTrue(f("/a/b/c"))
        for bad in ("a/b", "/a/../b", "/a/./b", "/a//b", "/a\\b", "/a/b/.."):
            self.assertFalse(f(bad), bad)

    def test_dotdot_rejected_everywhere(self):
        c = FakeChain([f"{M}/Movie.mkv"])
        for p in (ROOT + "/TV/..", ROOT + "/../outside/Show", "relative/Show"):
            self.assertFalse(dgroup(c, p).ok, p)
        self.assertFalse(cleaner(c).delete_group("u115", f"{M}/../Movie (2020)/Movie.mkv", ROOT).ok)
        self.assertEqual(c.deleted, [])

    def test_new_media_after_plan_is_reported(self):
        c = FakeChain([f"{SHOW}/Season 1/S01E01.mkv"])
        cl = cleaner(c)
        plan = cl.plan_dir("u115", f"{SHOW}/Season 1", ROOT)
        c.files.add(f"{SHOW}/Season 1/S01E02.mkv")
        c._add_parents(f"{SHOW}/Season 1/S01E02.mkv")
        r = cl.execute_dir("u115", plan)
        self.assertFalse(r.ok)
        self.assertIn(f"{SHOW}/Season 1/S01E02.mkv", c.files)
        self.assertIn(f"{SHOW}/Season 1", c.dirs)

    def test_dir_event_allowed(self):
        f = mod.dir_event_allowed
        self.assertTrue(f("Season", True))
        self.assertTrue(f("Series", True))
        cases = (
            ("Movie", True), ("Episode", True), ("Season", False),
            ("Season", None), ("Series", "true"), (None, True), ("", True),
        )
        for t, fol in cases:
            self.assertFalse(f(t, fol), (t, fol))

    def test_looks_like_media_file(self):
        f = lambda p: mod.looks_like_media_file(p, VIDEO)
        self.assertTrue(f("/a/Show - S01E01.strm"))
        self.assertTrue(f("/a/x.MKV"))
        self.assertFalse(f("/a/Mr. Robot (2015)"))
        self.assertFalse(f("/a/Season 1"))
        self.assertFalse(f("/a/Show Vol.1"))


class PurgeHardening(TestCase):
    def test_video_appears_between_two_scans_aborts_purge(self):
        c = FakeChain([f"{M}/Movie.mkv", f"{M}/Movie.nfo", f"{M}/poster.jpg"])
        orig = c.list_files
        n = {"k": 0}

        def lf(item, recursion=False):
            res = orig(item, recursion)
            if item.path.rstrip("/") == M:
                n["k"] += 1
                if n["k"] == 3:  # plan, 删后复核, 第一次扫描之后 -> 第二次扫描前加入
                    c.files.add(f"{M}/late.MKV")
            return res

        c.list_files = lf
        r = cleaner(c).delete_video_group("u115", f"{M}/Movie.mkv", ROOT)
        self.assertIn(f"{M}/late.MKV", c.files)
        self.assertIn(f"{M}/Movie.nfo", c.files)
        self.assertEqual(r.leftovers_deleted, [])

    def test_purge_scan_failure_deep_means_no_leftover_write(self):
        c = FakeChain([f"{M}/Movie.mkv", f"{M}/a.nfo", f"{M}/x/y/z.nfo"])
        c.fail_list.add(f"{M}/x/y")
        r = cleaner(c).delete_video_group("u115", f"{M}/Movie.mkv", ROOT)
        self.assertEqual(r.leftovers_deleted, [])
        self.assertIn(f"{M}/a.nfo", c.files)
        self.assertIn(f"{M}/x/y/z.nfo", c.files)

    def test_uppercase_and_nested_strm_block(self):
        for blocker in (f"{M}/Alt.STRM", f"{M}/sub/deep/Alt.strm"):
            c = FakeChain([f"{M}/Movie.mkv", f"{M}/a.nfo", blocker])
            cleaner(c).delete_video_group("u115", f"{M}/Movie.mkv", ROOT)
            self.assertIn(f"{M}/a.nfo", c.files, blocker)

    def test_sub_audio_not_blocking_but_deleted(self):
        # .sup/.mka/.mp3 不属于视频：无视频时随残留清理
        c = FakeChain([f"{M}/Movie.mkv", f"{M}/Other.sup", f"{M}/Other.mka", f"{M}/theme.MP3"])
        cl = mod.P115Cleaner(c, VIDEO + [".mp3"], SUB + [".sup"], AUDIO + [".mp3"])
        r = cl.delete_video_group("u115", f"{M}/Movie.mkv", ROOT)
        self.assertTrue(r.ok, r)
        self.assertEqual(c.files, set())

    def test_root_trailing_slash_and_outside_root(self):
        c = FakeChain([f"{M}/Movie.mkv", f"{M}/a.nfo"])
        r = cleaner(c).delete_video_group("u115", f"{M}/Movie.mkv", ROOT + "/")
        self.assertTrue(r.ok)
        self.assertEqual(c.files, set())
        o = "/其它/Movie (2020)"
        c2 = FakeChain([f"{o}/Movie.mkv", f"{o}/a.nfo"])
        r2 = cleaner(c2).delete_video_group("u115", f"{o}/Movie.mkv", ROOT)
        self.assertTrue(r2.ok)
        self.assertEqual(c2.files, {f"{o}/a.nfo"})

    def test_execute_dir_subdir_late_video_not_purged(self):
        c = FakeChain([f"{SHOW}/Season 1/a.mkv", f"{SHOW}/Season 1/p.jpg", f"{SHOW}/Season 2/b.mkv"])
        r = dgroup(c, f"{SHOW}/Season 1")
        self.assertTrue(r.ok, r)
        self.assertIn(f"{SHOW}/Season 2/b.mkv", c.files)
        self.assertNotIn(f"{SHOW}/Season 1", c.dirs)


class VideoLibraryOnly(TestCase):
    def test_allowed_types(self):
        for t in ("Movie", "Episode", "Season", "Series", "Video", "MusicVideo"):
            self.assertTrue(mod.is_video_library_item(t), t)

    def test_rejected_types(self):
        rejected = (
            "Audio", "MusicAlbum", "MusicArtist", "Photo", "PhotoAlbum", "Book",
            "AudioBook", "BoxSet", "Folder", "CollectionFolder", "Playlist",
            "", None, "movie",
        )
        for t in rejected:
            self.assertFalse(mod.is_video_library_item(t), t)

    def test_audio_file_never_a_deletion_target(self):
        # 即使事件被放行，音频文件也不是视频目标
        c = FakeChain([f"{M}/track.mp3", f"{M}/track.flac"])
        for name in ("track.mp3", "track.flac"):
            r = cleaner(c).delete_video_group("u115", f"{M}/{name}", ROOT)
            self.assertFalse(r.ok)
        self.assertEqual(c.deleted, [])


class OneCallDirDelete(TestCase):
    """目录整体删除只发起一次递归删除，且必须复核"""

    def test_root_dir_itself_is_never_deleted(self):
        c = FakeChain([f"{ROOT}/剧集/Show/Season 1/a.mkv"])
        r = dgroup(c, ROOT)
        self.assertFalse(r.ok)
        self.assertEqual(c.deleted, [])
        self.assertIn(ROOT, c.dirs)

    def test_outside_root_refused(self):
        c = FakeChain([f"{M}/Movie.mkv"])
        self.assertFalse(dgroup(c, "/其它/Show").ok)
        self.assertEqual(c.deleted, [])
        self.assertFalse(dgroup(c, SHOW, root=None).ok)

    def test_single_api_call_for_whole_series(self):
        files = [f"{SHOW}/Season {s}/e{i}.mkv" for s in (1, 2, 3) for i in range(40)]
        files += [f"{SHOW}/Season {s}/e{i}.nfo" for s in (1, 2, 3) for i in range(40)]
        c = FakeChain(files)
        r = dgroup(c, SHOW)
        self.assertTrue(r.ok, r)
        self.assertEqual(c.deleted[0], SHOW)  # 目录整体一次删除
        self.assertEqual(len([x for x in c.deleted if x.startswith(SHOW)]), 1)
        self.assertEqual(len(r.files_deleted), 240)
        self.assertEqual(c.files, set())

    def test_large_series_over_old_cap_allowed(self):
        files = [f"{SHOW}/Season 1/e{i}.mkv" for i in range(722)]
        c = FakeChain(files)
        r = dgroup(c, SHOW)
        self.assertTrue(r.ok, r)
        self.assertNotIn(SHOW, c.dirs)

    def test_dir_delete_failure_reported_nothing_removed(self):
        c = self.make()
        c.fail_delete.add(SHOW)
        r = dgroup(c, SHOW)
        self.assertFalse(r.ok)
        self.assertEqual(len(c.files), 3)
        self.assertEqual(r.dirs_deleted, [])

    def test_dir_fake_success_detected(self):
        c = self.make()
        c.delete_file = lambda item: True  # 假成功
        r = dgroup(c, SHOW)
        self.assertFalse(r.ok)
        self.assertTrue(any("仍存在" in e for e in r.errors))
        self.assertEqual(r.dirs_deleted, [])
        self.assertEqual(r.leftovers_deleted, [])

    def test_video_added_between_plan_and_execute_blocks(self):
        c = self.make()
        cl = cleaner(c)
        plan = cl.plan_dir("u115", SHOW, ROOT)
        c.files.add(f"{SHOW}/Season 1/new.mkv")
        c._add_parents(f"{SHOW}/Season 1/new.mkv")
        r = cl.execute_dir("u115", plan)
        self.assertFalse(r.ok)
        self.assertEqual(c.deleted, [])
        self.assertIn(f"{SHOW}/Season 1/new.mkv", c.files)

    def test_non_video_added_between_plan_and_execute_still_deleted(self):
        c = self.make()
        cl = cleaner(c)
        plan = cl.plan_dir("u115", SHOW, ROOT)
        c.files.add(f"{SHOW}/Season 1/new.nfo")
        r = cl.execute_dir("u115", plan)
        self.assertTrue(r.ok, r)
        self.assertEqual(c.files, set())

    def test_library_root_survives_when_last_title_removed(self):
        c = FakeChain([f"{ROOT}/Only (2020)/Season 1/a.mkv", f"{ROOT}/Only (2020)/tvshow.nfo"])
        r = dgroup(c, f"{ROOT}/Only (2020)")
        self.assertTrue(r.ok, r)
        self.assertIn(ROOT, c.dirs)
        self.assertEqual(r.dir_stop_reason, "到达媒体库根")

    def test_flat_library_title_directly_under_root(self):
        c = FakeChain([f"{ROOT}/Title (2020)/e1.mkv", f"{ROOT}/Title (2020)/poster.jpg", f"{ROOT}/Other/e1.mkv"])
        r = cleaner(c).delete_video_group("u115", f"{ROOT}/Title (2020)/e1.mkv", ROOT)
        self.assertTrue(r.ok, r)
        self.assertNotIn(f"{ROOT}/Title (2020)", c.dirs)
        self.assertIn(f"{ROOT}/Other/e1.mkv", c.files)

    def test_special_character_names(self):
        t = f"{ROOT}/Tom & Jerry's #1 (2020) {{tmdb-1}} [1080p]"
        c = FakeChain([f"{t}/Season 1/a b#c.mkv", f"{t}/Season 1/a b#c.zh-CN.ass", f"{t}/tvshow.nfo"])
        r = dgroup(c, t)
        self.assertTrue(r.ok, r)
        self.assertEqual(c.files, set())

    def test_failed_listing_during_climb_does_not_delete(self):
        c = FakeChain([f"{M}/Movie.mkv", f"{M}/a.nfo"])
        c.fail_list.add(M)
        r = cleaner(c).delete_video_group("u115", f"{M}/Movie.mkv", ROOT)
        self.assertFalse(r.ok)
        self.assertIn(M, c.dirs)

    def make(self):
        return FakeChain([
            f"{SHOW}/Season 1/a.mkv", f"{SHOW}/Season 1/a.zh-CN.ass", f"{SHOW}/tvshow.nfo",
        ])


class Review2(TestCase):
    def test_strm_always_counts_as_video(self):
        c = FakeChain([f"{M}/Movie.mkv", f"{M}/a.nfo", f"{M}/Alt.strm"])
        cl = mod.P115Cleaner(c, [".mkv"], SUB, AUDIO)  # 配置里没有 strm
        r = cl.delete_video_group("u115", f"{M}/Movie.mkv", ROOT)
        self.assertTrue(r.ok)
        self.assertEqual(c.files, {f"{M}/a.nfo", f"{M}/Alt.strm"})

    def test_parent_listing_failure_after_target_removed(self):
        c = FakeChain([f"{SHOW}/Season 1/a.mkv"])
        c.fail_list.add(f"{ROOT}/剧集")
        r = dgroup(c, SHOW)
        # 目标已复核删除；上溯因父目录列表失败而停止，不会删除任何其他目录
        self.assertNotIn(SHOW, c.dirs)
        self.assertIn(f"{ROOT}/剧集", c.dirs)
        self.assertIn("上级目录查询失败", r.dir_stop_reason)

    def test_video_and_entry_caps(self):
        files = [f"{SHOW}/Season 1/e{i}.mkv" for i in range(mod.MAX_DIR_VIDEOS)]
        c = FakeChain(files)
        self.assertTrue(dgroup(c, SHOW).ok)
        c2 = FakeChain(files + [f"{SHOW}/Season 1/extra.mkv"])
        self.assertFalse(dgroup(c2, SHOW).ok)
        self.assertEqual(c2.deleted, [])

    def test_missing_fileid_refused(self):
        c = FakeChain([f"{SHOW}/Season 1/a.mkv"])
        orig = c._item

        def noid(p):
            it = orig(p)
            if it is not None and p == SHOW:
                it.fileid = None
            return it

        c._item = noid
        r = dgroup(c, SHOW)
        self.assertFalse(r.ok)
        self.assertEqual(c.deleted, [])


class BigCollectionEarlyExit(TestCase):
    def test_climb_does_not_walk_whole_collection(self):
        coll = f"{ROOT}/合集/演员"
        files = [f"{coll}/W{i:04d}/W{i:04d}.mkv" for i in range(300)]
        files.append(f"{coll}/Target/Target.mkv")
        c = FakeChain(files)
        calls = {"n": 0}
        orig = c.list_files

        def counting(item, recursion=False):
            calls["n"] += 1
            return orig(item, recursion)

        c.list_files = counting
        r = cleaner(c).delete_video_group("u115", f"{coll}/Target/Target.mkv", ROOT)
        self.assertTrue(r.ok, r)
        self.assertNotIn(f"{coll}/Target", c.dirs)
        self.assertIn(coll, c.dirs)
        self.assertLess(calls["n"], 30)
        self.assertEqual(len([f for f in c.files if "/W" in f]), 300)
