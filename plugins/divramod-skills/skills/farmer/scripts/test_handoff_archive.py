"""Hal2 plan 0383 step 9 (rule 8, D9): `handoff --rewrite` moves the old handoff.md to `handoff-archive/<UTC time>.md`,
the new file holds only the template's sections plus what the session passes, and `--clear` warns above 80 lines."""
# enforces .adr/deterministic-first.md, .adr/no-committed-runtime-state.md

import datetime as dt
import io
import os
import subprocess
from contextlib import redirect_stderr

import handoff
from test_farmer import NOW
import test_handoff

OLD = "# farmer handoff\n\n## DO FIRST\n\nsuperseded: rerun train 3\n\n## Next\nold\n"


class Archive(test_handoff.Handoff):
    def test_rewrite_archives_the_old_file_and_shows_the_template_alone(self):
        f = handoff.path(self.main)
        f.write_text(OLD)
        os.utime(f, (NOW.timestamp(), NOW.timestamp()))
        code, out = self.run_cli("--rewrite")
        self.assertEqual(code, 0)
        archived = f.parent / "handoff-archive" / f"{dt.datetime.now(dt.timezone.utc):%Y%m%d}"
        files = sorted((f.parent / "handoff-archive").iterdir())
        self.assertEqual(len(files), 1)
        self.assertTrue(files[0].name.startswith(archived.name) and files[0].name.endswith("Z.md"), files)
        self.assertEqual(files[0].read_text(), OLD)
        self.assertFalse(f.exists(), "the old file is moved, not copied")
        self.assertIn(str(files[0]), out)
        self.assertIn("## DO FIRST", out)
        self.assertNotIn("superseded", out, "the template shows no old content")
        self.assertIsNone(handoff.written(self.main), "nothing is written until the session writes")

    def test_the_new_file_is_a_fresh_write_not_the_archived_mtime(self):
        f = handoff.path(self.main)
        f.write_text(OLD)
        os.utime(f, (NOW.timestamp(), NOW.timestamp()))
        self.run_cli("--rewrite")
        f.write_text("# farmer handoff\n\n## DO FIRST\n\nrerun train 20\n")
        self.assertGreater(handoff.written(self.main), NOW.timestamp() + 60)
        self.assertEqual(handoff.do_first(self.main), "rerun train 20")
        self.assertNotIn("superseded", f.read_text())

    def test_two_rewrites_in_one_second_keep_both_archives(self):
        f = handoff.path(self.main)
        when = dt.datetime(2026, 10, 19, 12, 0, 0, tzinfo=dt.timezone.utc)
        for text in ("one", "two"):
            f.write_text(text)
            handoff.archive(self.main, when)
        names = sorted(p.name for p in (f.parent / "handoff-archive").iterdir())
        self.assertEqual(names, ["20261019T120000Z-1.md", "20261019T120000Z.md"])

    def test_rewrite_without_a_handoff_archives_nothing(self):
        code, out = self.run_cli("--rewrite")
        self.assertEqual(code, 0)
        self.assertIn("missing", out)
        self.assertFalse((handoff.path(self.main).parent / "handoff-archive").exists())

    def test_the_archive_is_ignored_by_the_state_folders_gitignore(self):
        d = handoff.path(self.main).parent
        (d / ".gitignore").write_text(handoff.roles.GITIGNORE)
        (d / "handoff-archive").mkdir()
        (d / "handoff-archive" / "x.md").write_text("old")
        subprocess.run(["git", "-C", str(d), "init", "-q"], check=True)
        ignored = subprocess.run(["git", "-C", str(d), "check-ignore", "-q", "handoff-archive/x.md"])
        self.assertEqual(ignored.returncode, 0, "git ignores the archive: runtime state, never committed")

    def test_clear_warns_on_stderr_above_80_lines_and_still_clears(self):
        f = handoff.path(self.main)
        f.write_text("# farmer handoff\n" + "x\n" * 80)
        err = io.StringIO()
        with redirect_stderr(err):
            code, _ = self.run_cli("--clear")
        self.assertEqual(code, 0)
        self.assertIn("81 lines (over 80)", err.getvalue())
        f.write_text("# farmer handoff\n" + "x\n" * 79)
        err = io.StringIO()
        with redirect_stderr(err):
            self.run_cli("--clear")
        self.assertEqual(err.getvalue(), "")
