import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import guard  # noqa: E402

BRANCH = "cleanup/2026-09-16"


def run_git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def git_output(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def append_line(path, line):
    with path.open("a") as handle:
        handle.write(line + "\n")


def files_under(path):
    return sorted(item for item in path.rglob("*") if item.is_file())


def force_remove(func, path, _exc_info):
    os.chmod(path, stat.S_IWRITE)
    func(path)


class GuardTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        run_git(self.repo, "init", "-b", "main")
        run_git(self.repo, "config", "user.name", "Test")
        run_git(self.repo, "config", "user.email", "test@example.com")
        (self.repo / ".gitignore").write_text(".env\nnode_modules/\n")
        (self.repo / "main.py").write_text("print('hi')\n")
        (self.repo / "start.bat").write_text("python main.py\n")
        (self.repo / "lib").mkdir()
        (self.repo / "lib" / "util.py").write_text("X = 1\n")
        run_git(self.repo, "add", ".gitignore", "main.py", "start.bat", "lib/util.py")
        run_git(self.repo, "commit", "-m", "init")
        (self.repo / ".env").write_text("SECRET=abc\n")
        (self.repo / "node_modules").mkdir()
        (self.repo / "node_modules" / "pkg.js").write_text("x\n")
        run_git(self.repo, "switch", "-c", BRANCH)
        self.state = guard.state_dir_for(self.repo, BRANCH)
        self.snapshot_result = guard.cmd_snapshot(self.repo, self.state, "main")

    def tearDown(self):
        shutil.rmtree(self.tmp, onerror=force_remove)

    def commit_all(self, message):
        run_git(self.repo, "commit", "-am", message)

    def verify(self):
        return guard.cmd_verify(self.repo, self.state)

    def resnapshot(self):
        shutil.rmtree(self.state, onerror=force_remove)
        result = guard.cmd_snapshot(self.repo, self.state, "main")
        self.assertTrue(result["ok"], result)


class SnapshotTests(GuardTestCase):
    def test_records_invariants(self):
        self.assertTrue(self.snapshot_result["ok"], self.snapshot_result)
        snapshot = guard.load_snapshot(self.state)
        self.assertEqual(snapshot["base_branch"], "main")
        self.assertEqual(snapshot["cleanup_branch"], BRANCH)
        self.assertIn(".env", snapshot["local_files"])
        self.assertNotIn("node_modules/pkg.js", snapshot["local_files"])
        self.assertEqual(snapshot["contracts"], ["main.py", "start.bat"])
        self.assertTrue((self.state / "backup" / ".env").exists())

    def test_state_dir_lives_inside_git_dir(self):
        expected = (self.repo / ".git" / "tidy-project" / "cleanup-2026-09-16").resolve()
        self.assertEqual(self.state, expected)

    def test_refuses_to_overwrite_existing_snapshot(self):
        self.assertFalse(guard.cmd_snapshot(self.repo, self.state, "main")["ok"])

    def test_refuses_on_base_branch(self):
        run_git(self.repo, "switch", "main")
        result = guard.cmd_snapshot(self.repo, self.tmp / "other-state", "main")
        self.assertFalse(result["ok"])


class VerifyTests(GuardTestCase):
    def test_passes_on_untouched_repo(self):
        self.assertEqual(self.verify(), {"ok": True, "violations": []})

    def test_allows_commits_on_cleanup_branch(self):
        (self.repo / "lib" / "util.py").write_text("X = 2\n")
        self.commit_all("change")
        self.assertTrue(self.verify()["ok"])

    def test_flags_moved_base_branch(self):
        run_git(self.repo, "switch", "main")
        (self.repo / "lib" / "util.py").write_text("X = 3\n")
        self.commit_all("oops")
        run_git(self.repo, "switch", BRANCH)
        result = self.verify()
        self.assertFalse(result["ok"])
        self.assertTrue(any("base branch main moved" in v for v in result["violations"]))

    def test_flags_wrong_current_branch(self):
        run_git(self.repo, "switch", "main")
        self.assertTrue(any("current branch" in v for v in self.verify()["violations"]))

    def test_flags_dirty_tree(self):
        (self.repo / "stray.txt").write_text("x\n")
        self.assertTrue(any("working tree not clean" in v for v in self.verify()["violations"]))

    def test_flags_changed_local_file_and_restore_fixes_it(self):
        (self.repo / ".env").write_text("SECRET=changed-by-agent\n")
        self.assertIn("local file changed: .env", self.verify()["violations"])
        restored = guard.cmd_restore(self.repo, self.state)
        self.assertEqual(restored["restored"], [".env"])
        self.assertEqual((self.repo / ".env").read_text(), "SECRET=abc\n")
        self.assertEqual(self.verify(), {"ok": True, "violations": []})

    def test_flags_deleted_local_file_and_restore_fixes_it(self):
        (self.repo / ".env").unlink()
        self.assertIn("local file missing: .env", self.verify()["violations"])
        guard.cmd_restore(self.repo, self.state)
        self.assertTrue(self.verify()["ok"])

    def test_ignores_regenerable_dirs(self):
        (self.repo / "node_modules" / "pkg.js").write_text("changed content\n")
        self.assertTrue(self.verify()["ok"])

    def test_flags_missing_contract(self):
        run_git(self.repo, "rm", "-q", "start.bat")
        run_git(self.repo, "commit", "-m", "remove launcher")
        self.assertIn("contract file missing: start.bat", self.verify()["violations"])

    def test_added_contract_is_enforced(self):
        guard.cmd_add_contract(self.state, "lib\\util.py")
        run_git(self.repo, "rm", "-q", "lib/util.py")
        run_git(self.repo, "commit", "-m", "remove util")
        self.assertIn("contract file missing: lib/util.py", self.verify()["violations"])

    def test_flags_remote_ref_change(self):
        head = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        run_git(self.repo, "update-ref", "refs/remotes/origin/" + BRANCH, head)
        self.assertTrue(any("remote-tracking refs changed" in v for v in self.verify()["violations"]))


class RollbackTests(GuardTestCase):
    def rollback(self, start):
        return guard.cmd_rollback(self.repo, self.state, start)

    def test_undoes_tracked_changes_and_new_commits(self):
        start = git_output(self.repo, "rev-parse", "HEAD")
        (self.repo / "lib" / "new.py").write_text("Y = 1\n")
        run_git(self.repo, "add", "lib/new.py")
        run_git(self.repo, "commit", "-m", "add new")
        (self.repo / "lib" / "util.py").write_text("X = 2\n")
        result = self.rollback(start)
        self.assertTrue(result["ok"], result)
        self.assertEqual(git_output(self.repo, "rev-parse", "HEAD"), start)
        self.assertFalse((self.repo / "lib" / "new.py").exists())
        self.assertEqual((self.repo / "lib" / "util.py").read_text(), "X = 1\n")
        self.assertEqual(git_output(self.repo, "status", "--porcelain"), "")

    def test_quarantines_stray_untracked_files_instead_of_deleting(self):
        start = git_output(self.repo, "rev-parse", "HEAD")
        (self.repo / "stray.txt").write_text("leftover\n")
        (self.repo / "out" / "deep").mkdir(parents=True)
        (self.repo / "out" / "deep" / "result.log").write_text("log\n")
        result = self.rollback(start)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["quarantined"], ["out/deep/result.log", "stray.txt"])
        self.assertFalse((self.repo / "stray.txt").exists())
        self.assertEqual(files_under(self.repo / "out"), [])
        batches = list((self.state / "quarantine").iterdir())
        self.assertEqual(len(batches), 1)
        self.assertRegex(batches[0].name, r"^\d{8}T\d{6}Z$")
        self.assertEqual((batches[0] / "stray.txt").read_text(), "leftover\n")
        self.assertEqual((batches[0] / "out" / "deep" / "result.log").read_text(), "log\n")

    def test_recovers_ignored_file_moved_with_its_directory(self):
        (self.repo / "lib" / ".env").write_text("LIB_SECRET=1\n")
        self.resnapshot()
        start = git_output(self.repo, "rev-parse", "HEAD")
        run_git(self.repo, "mv", "lib", "library")
        run_git(self.repo, "commit", "-m", "rename lib")
        self.assertTrue((self.repo / "library" / ".env").exists())
        result = self.rollback(start)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["recovered"], ["lib/.env"])
        self.assertEqual(result["quarantined"], [])
        self.assertEqual((self.repo / "lib" / ".env").read_text(), "LIB_SECRET=1\n")
        self.assertEqual(files_under(self.repo / "library"), [])

    def test_recovers_file_moved_into_regenerable_folder_without_backup(self):
        (self.repo / "lib" / ".env").write_text("LIB_SECRET=1\n")
        self.resnapshot()
        (self.state / "backup" / "lib" / ".env").unlink()
        start = git_output(self.repo, "rev-parse", "HEAD")
        run_git(self.repo, "mv", "lib", "bin")
        run_git(self.repo, "commit", "-m", "rename lib to bin")
        result = self.rollback(start)
        self.assertTrue(result["ok"], result)
        self.assertEqual((result["recovered"], result["restored"]), (["lib/.env"], []))
        self.assertEqual((self.repo / "lib" / ".env").read_text(), "LIB_SECRET=1\n")
        self.assertEqual(files_under(self.repo / "bin"), [])

    def test_recovers_moved_file_that_is_no_longer_ignored(self):
        append_line(self.repo / ".gitignore", "lib/secret.txt")
        run_git(self.repo, "commit", "-am", "ignore secret")
        (self.repo / "lib" / "secret.txt").write_text("TOKEN=1\n")
        self.resnapshot()
        start = git_output(self.repo, "rev-parse", "HEAD")
        run_git(self.repo, "mv", "lib", "library")
        run_git(self.repo, "commit", "-m", "rename lib")
        self.assertIn("?? library/secret.txt", git_output(self.repo, "status", "--porcelain"))
        result = self.rollback(start)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["recovered"], ["lib/secret.txt"])
        self.assertEqual(result["quarantined"], [])
        self.assertEqual((self.repo / "lib" / "secret.txt").read_text(), "TOKEN=1\n")
        self.assertEqual(files_under(self.repo / "library"), [])

    def test_refuses_when_not_on_cleanup_branch(self):
        start = git_output(self.repo, "rev-parse", "HEAD")
        run_git(self.repo, "switch", "main")
        (self.repo / "stray.txt").write_text("x\n")
        (self.repo / "lib" / "util.py").write_text("X = 9\n")
        result = self.rollback(start)
        self.assertFalse(result["ok"])
        self.assertTrue((self.repo / "stray.txt").exists())
        self.assertEqual((self.repo / "lib" / "util.py").read_text(), "X = 9\n")
        self.assertFalse((self.state / "quarantine").exists())

    def test_does_not_overwrite_local_file_changed_in_place(self):
        start = git_output(self.repo, "rev-parse", "HEAD")
        (self.repo / ".env").write_text("SECRET=changed-in-place\n")
        result = self.rollback(start)
        self.assertFalse(result["ok"])
        self.assertIn("local file changed: .env", result["violations"])
        self.assertEqual(result["restored"], [])
        self.assertEqual((self.repo / ".env").read_text(), "SECRET=changed-in-place\n")

    def test_restores_missing_local_file_from_backup(self):
        start = git_output(self.repo, "rev-parse", "HEAD")
        (self.repo / ".env").unlink()
        result = self.rollback(start)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["restored"], [".env"])
        self.assertEqual((self.repo / ".env").read_text(), "SECRET=abc\n")

    def test_same_named_file_in_regenerable_folder_does_not_block_restore(self):
        start = git_output(self.repo, "rev-parse", "HEAD")
        (self.repo / "node_modules" / "x").mkdir()
        (self.repo / "node_modules" / "x" / ".env").write_text("PKG=1\n")
        (self.repo / ".env").unlink()
        result = self.rollback(start)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["restored"], [".env"])
        self.assertEqual((self.repo / ".env").read_text(), "SECRET=abc\n")
        self.assertEqual((self.repo / "node_modules" / "x" / ".env").read_text(), "PKG=1\n")

    def test_never_removes_directories(self):
        (self.repo / "logs").mkdir()
        start = git_output(self.repo, "rev-parse", "HEAD")
        (self.repo / "logs" / "run.log").write_text("leftover\n")
        result = self.rollback(start)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["quarantined"], ["logs/run.log"])
        self.assertTrue((self.repo / "logs").is_dir())

    def assert_identical_moved_copies_are_left_alone(self, app_target, lib_target):
        (self.repo / "app").mkdir()
        (self.repo / "app" / "window.py").write_text("W = 1\n")
        run_git(self.repo, "add", "app/window.py")
        run_git(self.repo, "commit", "-m", "add app")
        for folder in ("app", "lib"):
            copy = self.repo / folder / ".env"
            copy.write_text("SAME=1\n")
            os.utime(copy, ns=(1700000000000000000, 1700000000000000000))
        self.resnapshot()
        start = git_output(self.repo, "rev-parse", "HEAD")
        run_git(self.repo, "mv", "app", app_target)
        run_git(self.repo, "mv", "lib", lib_target)
        run_git(self.repo, "commit", "-m", "rename folders")
        result = self.rollback(start)
        self.assertFalse(result["ok"])
        self.assertEqual(result["recovered"], [])
        self.assertEqual(result["ambiguous"], ["app/.env", "lib/.env"])
        self.assertEqual(result["restored"], [])
        for rel in ("app/.env", "lib/.env"):
            self.assertIn(
                "local file not restored, possible moved copy: {} "
                "(candidates: {}/.env, {}/.env)".format(rel, app_target, lib_target),
                result["violations"],
            )
            self.assertFalse((self.repo / rel).exists())
        self.assertTrue((self.repo / app_target / ".env").exists())
        self.assertTrue((self.repo / lib_target / ".env").exists())

    def test_ambiguous_copies_are_neither_moved_nor_restored(self):
        self.assert_identical_moved_copies_are_left_alone("application", "library")

    def test_ambiguous_copies_in_regenerable_folders_are_neither_moved_nor_restored(self):
        self.assert_identical_moved_copies_are_left_alone("bin", "obj")

    def test_quarantine_batches_in_the_same_second_do_not_collide(self):
        start = git_output(self.repo, "rev-parse", "HEAD")
        with mock.patch.object(guard, "utc_timestamp", lambda: "20260916T120000Z"):
            (self.repo / "stray.txt").write_text("first\n")
            self.assertTrue(self.rollback(start)["ok"])
            (self.repo / "stray.txt").write_text("second\n")
            self.assertTrue(self.rollback(start)["ok"])
        quarantine = self.state / "quarantine"
        self.assertEqual(sorted(batch.name for batch in quarantine.iterdir()),
                         ["20260916T120000Z", "20260916T120000Z-2"])
        self.assertEqual((quarantine / "20260916T120000Z" / "stray.txt").read_text(), "first\n")
        self.assertEqual((quarantine / "20260916T120000Z-2" / "stray.txt").read_text(), "second\n")

    def test_failed_move_is_reported_and_the_rest_still_runs(self):
        append_line(self.repo / ".gitignore", "*.local")
        self.commit_all("ignore local settings")
        (self.repo / "conf").mkdir()
        (self.repo / "conf" / "settings.local").write_text("CONF=1\n")
        self.resnapshot()
        start = git_output(self.repo, "rev-parse", "HEAD")
        shutil.move(str(self.repo / "conf"), str(self.repo / "conf2"))
        (self.repo / "conf").write_text("a file where the folder was\n")
        (self.repo / ".env").unlink()
        result = self.rollback(start)
        self.assertFalse(result["ok"])
        self.assertEqual(len(result["errors"]), 1)
        self.assertTrue(result["errors"][0].startswith("recover conf/settings.local: "), result["errors"])
        self.assertEqual(result["quarantined"], ["conf"])
        self.assertEqual(result["restored"], [".env"])
        self.assertIn(
            "local file not restored, possible moved copy: conf/settings.local (candidates: conf2/settings.local)",
            result["violations"],
        )
        self.assertFalse((self.repo / "conf" / "settings.local").exists())
        self.assertEqual((self.repo / "conf2" / "settings.local").read_text(), "CONF=1\n")
        self.assertEqual((self.repo / ".env").read_text(), "SECRET=abc\n")


class RefreshTests(GuardTestCase):
    def test_accepts_moved_base_branch(self):
        run_git(self.repo, "switch", "main")
        (self.repo / "lib" / "util.py").write_text("X = 3\n")
        self.commit_all("user change")
        run_git(self.repo, "switch", BRANCH)
        self.assertFalse(self.verify()["ok"])
        result = guard.cmd_refresh(self.repo, self.state)
        self.assertTrue(result["ok"], result)
        self.assertEqual(self.verify(), {"ok": True, "violations": []})

    def test_accepts_changed_local_file_and_keeps_previous_backup(self):
        (self.repo / ".env").write_text("SECRET=changed-by-user\n")
        self.assertFalse(self.verify()["ok"])
        result = guard.cmd_refresh(self.repo, self.state)
        self.assertTrue(result["ok"], result)
        self.assertEqual(self.verify(), {"ok": True, "violations": []})
        previous = list(self.state.glob("backup-previous-*"))
        self.assertEqual(len(previous), 1)
        self.assertEqual((previous[0] / ".env").read_text(), "SECRET=abc\n")
        self.assertEqual((self.state / "backup" / ".env").read_text(), "SECRET=changed-by-user\n")

    def test_refuses_when_not_on_cleanup_branch(self):
        run_git(self.repo, "switch", "main")
        self.assertFalse(guard.cmd_refresh(self.repo, self.state)["ok"])
        self.assertEqual(list(self.state.glob("backup-previous-*")), [])


class VolatilePathsTests(unittest.TestCase):
    BEFORE = {"size": 10, "mtime_ns": 1}
    AFTER = {"size": 10, "mtime_ns": 2}

    def test_changed_nested_file_marks_its_directory(self):
        before = {"profile/Default/Cookies": self.BEFORE, ".env": self.BEFORE}
        after = {"profile/Default/Cookies": self.AFTER, ".env": self.BEFORE}
        self.assertEqual(guard.volatile_paths(before, after), ["profile/Default"])

    def test_disappeared_file_marks_its_directory(self):
        before = {"logs/run.lock": self.BEFORE}
        self.assertEqual(guard.volatile_paths(before, {}), ["logs"])

    def test_appeared_file_marks_its_directory(self):
        self.assertEqual(guard.volatile_paths({}, {"profile/journal.tmp": self.AFTER}), ["profile"])

    def test_changed_root_file_is_listed_itself(self):
        self.assertEqual(guard.volatile_paths({"app.log": self.BEFORE}, {"app.log": self.AFTER}), ["app.log"])

    def test_unchanged_files_are_not_volatile(self):
        files = {".env": self.BEFORE, "logs/old.log": self.BEFORE}
        self.assertEqual(guard.volatile_paths(files, dict(files)), [])


class VolatileLocalPathTests(GuardTestCase):
    def setUp(self):
        super().setUp()
        append_line(self.repo / ".gitignore", "chrome_profile/")
        self.commit_all("ignore profile")
        self.profile = self.repo / "chrome_profile" / "Default"
        self.profile.mkdir(parents=True)
        (self.profile / "Preferences").write_text("{}\n")

    def mark_volatile(self, paths, unstable=()):
        self.resnapshot()
        snapshot = guard.load_snapshot(self.state)
        snapshot["volatile"] = paths
        snapshot["volatile_unstable"] = list(unstable)
        guard.save_snapshot(self.state, snapshot)

    def test_snapshot_records_paths_that_change_while_settling(self):
        shutil.rmtree(self.state, onerror=force_remove)

        def browser_writes(_seconds):
            (self.profile / "Preferences").write_text('{"changed": true}\n')

        with mock.patch.object(guard.time, "sleep", browser_writes):
            result = guard.cmd_snapshot(self.repo, self.state, "main", settle_seconds=5)
        self.assertTrue(result["ok"], result)
        snapshot = guard.load_snapshot(self.state)
        self.assertEqual(snapshot["volatile"], ["chrome_profile/Default"])
        self.assertEqual(snapshot["volatile_unstable"], ["chrome_profile/Default/Preferences"])

    def test_verify_skips_changed_file_under_volatile_path(self):
        self.mark_volatile(["chrome_profile"])
        (self.profile / "Preferences").write_text('{"changed": true}\n')
        self.assertEqual(self.verify(), {"ok": True, "violations": []})

    def test_verify_reports_removed_volatile_path(self):
        self.mark_volatile(["chrome_profile"])
        shutil.rmtree(self.repo / "chrome_profile", onerror=force_remove)
        self.assertEqual(self.verify()["violations"], [
            "local file missing: chrome_profile/Default/Preferences",
            "local path missing: chrome_profile",
        ])

    def test_restore_and_rollback_skip_unstable_files_only(self):
        (self.profile / "Bookmarks").write_text("[]\n")
        self.mark_volatile(["chrome_profile"], unstable=["chrome_profile/Default/Preferences"])
        (self.profile / "Preferences").unlink()
        (self.profile / "Bookmarks").unlink()
        self.assertEqual(guard.cmd_restore(self.repo, self.state)["restored"], ["chrome_profile/Default/Bookmarks"])
        result = guard.cmd_rollback(self.repo, self.state, "HEAD")
        self.assertTrue(result["ok"], result)
        self.assertEqual((result["recovered"], result["restored"]), ([], []))
        self.assertFalse((self.profile / "Preferences").exists())

    def snapshot_while_browser_writes(self):
        shutil.rmtree(self.state, onerror=force_remove)

        def browser_writes(_seconds):
            (self.profile / "Preferences").write_text('{"live": 1}\n')

        with mock.patch.object(guard.time, "sleep", browser_writes):
            self.assertTrue(guard.cmd_snapshot(self.repo, self.state, "main", settle_seconds=5)["ok"])
        return git_output(self.repo, "rev-parse", "HEAD")

    def move_profile_into_browser_folder(self):
        (self.repo / "browser").mkdir()
        shutil.move(str(self.repo / "chrome_profile"), str(self.repo / "browser" / "chrome_profile"))

    def test_rollback_leaves_live_folder_moved_outside_git_missing(self):
        (self.profile / "Bookmarks").write_text("[]\n")
        start = self.snapshot_while_browser_writes()
        self.move_profile_into_browser_folder()
        result = guard.cmd_rollback(self.repo, self.state, start)
        self.assertFalse(result["ok"])
        self.assertEqual(result["missing_volatile"], ["chrome_profile/Default"])
        self.assertEqual((result["recovered"], result["restored"]), ([], []))
        self.assertIn("local path missing: chrome_profile/Default", result["violations"])
        self.assertFalse((self.repo / "chrome_profile").exists())
        moved = self.repo / "browser" / "chrome_profile" / "Default"
        self.assertTrue((moved / "Preferences").exists())
        self.assertTrue((moved / "Bookmarks").exists())

    def test_rollback_does_not_recreate_missing_parent_of_live_folder(self):
        (self.profile / "Bookmarks").write_text("[]\n")
        (self.repo / "chrome_profile" / "First Run").write_text("")
        start = self.snapshot_while_browser_writes()
        self.move_profile_into_browser_folder()
        result = guard.cmd_rollback(self.repo, self.state, start)
        self.assertFalse(result["ok"])
        self.assertEqual(result["missing_volatile"], ["chrome_profile/Default"])
        self.assertEqual((result["recovered"], result["restored"]), ([], []))
        self.assertIn("local file missing: chrome_profile/First Run", result["violations"])
        self.assertFalse((self.repo / "chrome_profile").exists())
        moved = self.repo / "browser" / "chrome_profile"
        self.assertTrue((moved / "First Run").exists())
        self.assertTrue((moved / "Default" / "Bookmarks").exists())


class LiveFileSiblingTests(GuardTestCase):
    """Reviewer repro: one live file must not strand its stable siblings."""

    def setUp(self):
        super().setUp()
        self.data = self.repo / "data"
        self.data.mkdir()
        (self.data / "schema.sql").write_text("CREATE TABLE t (id INT);\n")
        append_line(self.repo / ".gitignore", "*.sqlite")
        run_git(self.repo, "add", ".gitignore", "data/schema.sql")
        run_git(self.repo, "commit", "-m", "add data")
        (self.data / "app.sqlite").write_text("live\n")
        (self.data / "other.sqlite").write_text("stable\n")
        self.snapshot_while_app_writes()

    def snapshot_while_app_writes(self):
        shutil.rmtree(self.state, onerror=force_remove)

        def app_writes(_seconds):
            (self.data / "app.sqlite").write_text("live, written while settling\n")

        with mock.patch.object(guard.time, "sleep", app_writes):
            result = guard.cmd_snapshot(self.repo, self.state, "main", settle_seconds=5)
        self.assertTrue(result["ok"], result)
        self.start = git_output(self.repo, "rev-parse", "HEAD")

    def anchor_ignore_rule(self):
        gitignore = self.repo / ".gitignore"
        gitignore.write_text(gitignore.read_text().replace("*.sqlite", "/data/*.sqlite"))
        self.commit_all("anchor sqlite ignore rule")
        self.snapshot_while_app_writes()

    def move_data_folder(self, target="db"):
        run_git(self.repo, "mv", "data", target)
        run_git(self.repo, "commit", "-m", "rename data")

    def test_rollback_recovers_stable_sibling_and_flags_moved_live_file(self):
        self.move_data_folder()
        result = guard.cmd_rollback(self.repo, self.state, self.start)
        self.assertFalse(result["ok"])
        self.assertEqual(result["recovered"], ["data/other.sqlite"])
        self.assertEqual((self.data / "other.sqlite").read_text(), "stable\n")
        self.assertIn(
            "local file not restored, possible moved copy: data/app.sqlite (candidates: db/app.sqlite)",
            result["violations"],
        )
        self.assertFalse((self.data / "app.sqlite").exists())
        self.assertTrue((self.repo / "db" / "app.sqlite").exists())

    def test_rollback_does_not_quarantine_moved_live_file_under_anchored_ignore_rule(self):
        self.anchor_ignore_rule()
        self.move_data_folder()
        result = guard.cmd_rollback(self.repo, self.state, self.start)
        self.assertFalse(result["ok"])
        self.assertIn(
            "local file not restored, possible moved copy: data/app.sqlite (candidates: db/app.sqlite)",
            result["violations"],
        )
        self.assertEqual(result["quarantined"], [])
        self.assertEqual((self.repo / "db" / "app.sqlite").read_text(), "live, written while settling\n")

    def test_rollback_keeps_named_candidate_in_place(self):
        self.anchor_ignore_rule()
        (self.data / "other.sqlite").write_text("stable v2, written later by the app\n")
        self.move_data_folder()
        result = guard.cmd_rollback(self.repo, self.state, self.start)
        self.assertFalse(result["ok"])
        self.assertIn(
            "local file not restored, possible moved copy: data/other.sqlite (candidates: db/other.sqlite)",
            result["violations"],
        )
        self.assertEqual(result["quarantined"], [])
        self.assertEqual((self.repo / "db" / "other.sqlite").read_text(), "stable v2, written later by the app\n")

    def test_rollback_recovers_stable_sibling_and_flags_live_file_moved_into_regenerable_folder(self):
        self.move_data_folder("bin")
        result = guard.cmd_rollback(self.repo, self.state, self.start)
        self.assertFalse(result["ok"])
        self.assertIn(
            "local file not restored, possible moved copy: data/app.sqlite (candidates: bin/app.sqlite)",
            result["violations"],
        )
        self.assertEqual((result["recovered"], result["restored"]), (["data/other.sqlite"], []))
        self.assertEqual((self.data / "other.sqlite").read_text(), "stable\n")
        self.assertFalse((self.repo / "bin" / "other.sqlite").exists())
        self.assertTrue((self.repo / "bin" / "app.sqlite").exists())

    def test_rollback_fails_when_stable_sibling_cannot_be_recovered(self):
        self.move_data_folder()
        (self.repo / "db" / "other.sqlite").write_text("edited after the move\n")
        (self.state / "backup" / "data" / "other.sqlite").unlink()
        result = guard.cmd_rollback(self.repo, self.state, self.start)
        self.assertFalse(result["ok"])
        self.assertIn("local file missing: data/other.sqlite", result["violations"])

    def test_rollback_does_not_restore_stale_backup_next_to_moved_copy(self):
        (self.data / "other.sqlite").write_text("stable v2, written later by the app\n")
        self.move_data_folder()
        result = guard.cmd_rollback(self.repo, self.state, self.start)
        self.assertFalse(result["ok"])
        self.assertEqual(result["restored"], [])
        self.assertIn(
            "local file not restored, possible moved copy: data/other.sqlite (candidates: db/other.sqlite)",
            result["violations"],
        )
        self.assertFalse((self.data / "other.sqlite").exists())
        self.assertEqual((self.repo / "db" / "other.sqlite").read_text(), "stable v2, written later by the app\n")

    def test_verify_checks_existence_of_stable_sibling_and_ignores_live_file(self):
        (self.data / "app.sqlite").write_text("live, written again during the run\n")
        (self.data / "other.sqlite").write_text("stable, but content is not checked\n")
        self.assertEqual(self.verify(), {"ok": True, "violations": []})
        (self.data / "other.sqlite").unlink()
        (self.data / "app.sqlite").unlink()
        self.assertEqual(self.verify()["violations"], ["local file missing: data/other.sqlite"])


class CliTests(GuardTestCase):
    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, str(Path(guard.__file__)), *args], capture_output=True, text=True
        )

    def test_verify_exit_codes_and_json(self):
        ok = self.run_cli("verify", str(self.repo), str(self.state))
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
        self.assertTrue(json.loads(ok.stdout)["ok"])
        (self.repo / "stray.txt").write_text("x\n")
        bad = self.run_cli("verify", str(self.repo), str(self.state))
        self.assertEqual(bad.returncode, 1)
        self.assertFalse(json.loads(bad.stdout)["ok"])

    def test_state_dir_command(self):
        result = self.run_cli("state-dir", str(self.repo), BRANCH)
        self.assertEqual(Path(json.loads(result.stdout)["state_dir"]), self.state)

    def test_verify_without_snapshot_fails_cleanly(self):
        result = self.run_cli("verify", str(self.repo), str(self.tmp / "missing-state"))
        self.assertEqual(result.returncode, 1)
        self.assertFalse(json.loads(result.stdout)["ok"])

    def test_snapshot_rollback_and_refresh_commands(self):
        other_state = str(self.tmp / "cli-state")
        snapshot = self.run_cli("snapshot", str(self.repo), other_state, "--base", "main", "--settle-seconds", "0")
        self.assertEqual(snapshot.returncode, 0, snapshot.stdout + snapshot.stderr)
        rollback = self.run_cli("rollback", str(self.repo), str(self.state), "HEAD")
        self.assertEqual(rollback.returncode, 0, rollback.stdout + rollback.stderr)
        self.assertEqual(json.loads(rollback.stdout)["quarantined"], [])
        refresh = self.run_cli("refresh", str(self.repo), str(self.state), "--settle-seconds", "0")
        self.assertEqual(refresh.returncode, 0, refresh.stdout + refresh.stderr)


if __name__ == "__main__":
    unittest.main()
