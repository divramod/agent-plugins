"""Hal2 plan 0530 step 4: a tick that fails is never silent. `role_cli.run_tick` with `tick.run` raising: the trace on
stderr, exit 5, the streak in tick-health.json; the 2nd failed round in a row sends one desktop notice and puts the
line at the top of summaries/latest.md, the 3rd sends none; a good round resets it and writes the recovery line. The
same for the tollman's wiring (its own state folder). No real notice: `notice.send` is a recorder, notice.py's own
tests inject the runner. No git: the repo is a plain temp folder, its state under $FARMER_DIR."""

import contextlib
import datetime as dt
import io
import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import due
import mtm_scan
import notice
import role_cli
import roles
import tick
import tick_health

SKILLS = Path(__file__).resolve().parents[2]  # skills/roles/
TOLLMAN = roles.Wiring(role="tollman", cli=SKILLS / "tollman/scripts/tollman.py", skill=SKILLS / "tollman",
                       act="/tollman act", handoff="/tollman handoff", duties=("trains",), subskills={})
GOOD = {"dry": False, "planned": [], "due": []}
Z = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")


class Rounds(unittest.TestCase):
    wiring = roles.FARMER

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = self.tmp / "hal2"  # outside git: its own main checkout
        self.repo.mkdir()
        self.data = self.tmp / "state"
        self.sent = []
        patches = [mock.patch.object(m, "DATA", self.data) for m in (due, mtm_scan)]
        patches += [mock.patch.dict(os.environ, {roles.UNDER_TEST: "1", "FARMER_DIR": str(self.data)}),
                    mock.patch.object(role_cli, "missing", return_value=[]),
                    mock.patch.object(role_cli, "mode", return_value="timer"),
                    mock.patch.object(role_cli, "follow_cron"),
                    mock.patch.object(notice, "send", side_effect=lambda t, b: self.sent.append((t, b)) or
                                      {"ok": True, "error": None}),
                    mock.patch.object(notice, "run", side_effect=AssertionError("a real notice"))]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    @property
    def state(self) -> Path:
        return self.data / "hal2" / ("" if self.wiring.role == roles.ROLE else self.wiring.role)

    def health(self) -> dict:
        return json.loads((self.state / tick_health.FILE).read_text())

    def latest(self) -> str:
        f = self.state / "summaries/latest.md"
        return f.read_text() if f.exists() else ""

    def round_(self, fails: bool, dry: bool = False) -> tuple[int, str]:
        effect = TypeError("can't compare offset-naive and offset-aware datetimes") if fails else None
        err = io.StringIO()
        with mock.patch.object(tick, "run", side_effect=effect, return_value=GOOD | {"dry": dry}), \
                contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = role_cli.run_tick(str(self.repo), dry, True, {}, self.wiring)
        return code, err.getvalue()

    def test_two_failed_rounds_notify_once_and_a_good_round_recovers(self):
        role = self.wiring.role
        line = f"{role} tick failing: TypeError: can't compare offset-naive and offset-aware datetimes"
        code, err = self.round_(fails=True)
        self.assertEqual(code, 5)
        self.assertIn("Traceback (most recent call last)", err)
        self.assertEqual(self.sent, [])
        h = self.health()
        self.assertEqual((h["schema"], h["failures"], h["notified"]), (1, 1, False))
        self.assertRegex(h["at"], Z)
        self.assertEqual(h["error"], "TypeError: can't compare offset-naive and offset-aware datetimes")
        self.assertEqual(self.latest(), "")

        self.assertEqual(self.round_(fails=True)[0], 5)
        self.assertEqual(self.sent, [(f"hal2 {role}", line)])
        self.assertEqual((self.health()["failures"], self.health()["notified"]), (2, True))
        self.assertTrue(self.latest().startswith(line + "\n"))

        self.assertEqual(self.round_(fails=True)[0], 5)
        self.assertEqual(len(self.sent), 1, "one notice per streak")
        self.assertEqual(self.health()["failures"], 3)
        self.assertEqual(self.latest().count(line), 1)

        self.assertEqual(self.round_(fails=False)[0], 0)
        self.assertEqual(self.health(), {"schema": 1, "at": self.health()["at"], "failures": 0, "error": "",
                                         "notified": False})
        self.assertTrue(self.latest().startswith(f"{role} tick recovered after 3 failed rounds\n"))
        self.assertEqual(len(self.sent), 1, "a recovery sends no notice")

        self.round_(fails=True)  # a new streak notifies again at its 2nd round
        self.round_(fails=True)
        self.assertEqual(len(self.sent), 2)

    def test_a_good_round_without_a_streak_writes_no_line(self):
        self.assertEqual(self.round_(fails=False)[0], 0)
        self.assertEqual(self.health()["failures"], 0)
        self.assertEqual(self.latest(), "")

    def test_one_failure_then_a_good_round_resets_without_a_line(self):
        self.round_(fails=True)
        self.round_(fails=False)
        self.round_(fails=True)
        self.assertEqual((self.health()["failures"], self.sent, self.latest()), (1, [], ""))

    def test_a_dry_run_never_counts_nor_notifies(self):
        for _ in range(3):
            code, err = self.round_(fails=True, dry=True)
            self.assertEqual(code, 5)
            self.assertIn("TypeError", err)
        self.assertEqual(self.sent, [])
        self.assertFalse((self.state / tick_health.FILE).exists())
        self.assertEqual(self.latest(), "")

    def test_a_failing_notice_or_summary_never_takes_the_round_down(self):
        with mock.patch.object(notice, "send", side_effect=OSError("no display")), \
                mock.patch.object(mtm_scan, "summary_dir", side_effect=PermissionError("read-only")):
            self.round_(fails=True)
            code, err = self.round_(fails=True)
        self.assertEqual(code, 5)
        self.assertIn("notice not shown", err)
        self.assertIn("latest.md not written", err)
        self.assertTrue(self.health()["notified"])


class TollmanRounds(Rounds):
    """The tollman shares the frame: its streak lives in its own folder, never the farmer's."""
    wiring = TOLLMAN

    def test_the_tollman_s_health_is_its_own(self):
        self.round_(fails=True)
        self.assertTrue((self.data / "hal2/tollman" / tick_health.FILE).exists())
        self.assertFalse((self.data / "hal2" / tick_health.FILE).exists())


class Snapshot(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_an_unreadable_snapshot_starts_clean(self):
        for text in ("", "{", "[]", '{"failures": -3, "notified": "yes"}'):
            (self.tmp / tick_health.FILE).write_text(text)
            self.assertEqual((tick_health.read(self.tmp)["failures"], tick_health.read(self.tmp)["notified"]),
                             (0, False))

    def test_the_write_is_atomic_and_leaves_no_temp_file(self):
        tick_health.write(self.tmp, {"schema": 1})
        self.assertEqual(os.listdir(self.tmp), [tick_health.FILE])

    def test_the_snapshot_matches_its_schema_in_both_roles(self):
        clock = dt.datetime(2026, 10, 31, 9, 52, 24, tzinfo=dt.timezone.utc)
        data = tick_health.failed(self.tmp, self.tmp, "farmer", ValueError("x" * 400), send=lambda t, b: None,
                                  clock=clock)
        self.assertEqual(data["at"], "2026-10-31T09:52:24Z")
        self.assertLessEqual(len(data["error"]), 200)
        on_disk = json.loads((self.tmp / tick_health.FILE).read_text())
        for role in ("farmer", "tollman"):
            schema = json.loads((SKILLS / role / "schemas/tick-health.schema.json").read_text())
            self.assertEqual(set(on_disk), set(schema["properties"]))
            self.assertEqual(set(schema["required"]), set(schema["properties"]))
            self.assertRegex(on_disk["at"], schema["properties"]["at"]["pattern"])

    def test_a_multi_line_message_gives_its_last_line(self):
        self.assertEqual(tick_health.error_line(RuntimeError("first\n  second  ")), "RuntimeError: second")
        self.assertEqual(tick_health.error_line(KeyError()), "KeyError")

    def test_the_line_goes_below_a_front_matter(self):
        (self.tmp / "latest.md").write_text("---\ntype: Round Summary\n---\n# farmer\n")
        tick_health.mark(self.tmp, "farmer tick failing: X")
        self.assertEqual((self.tmp / "latest.md").read_text(),
                         "---\ntype: Round Summary\n---\nfarmer tick failing: X\n\n# farmer\n")


class Manifests(unittest.TestCase):
    def test_both_roles_declare_the_snapshot_before_the_json_glob(self):
        import tomllib
        for role in ("farmer", "tollman"):
            files = tomllib.loads((SKILLS / role / "manifest.toml").read_text())["files"]
            paths = [f["path"] for f in files]
            entry = files[paths.index("tick-health.json")]
            self.assertEqual((entry["kind"], entry["schema"]), ("snapshot", "schemas/tick-health.schema.json"))
            self.assertLess(paths.index("tick-health.json"), paths.index("*.json"), "the first match wins")


class Notice(unittest.TestCase):
    """notice.py's backends with an injected runner and `which`: no real notice."""

    def calls(self, system, tools, code=0):
        seen = []
        result = notice.send("hal2 farmer", "farmer tick failing: " + "y" * 300, system=system,
                             which=lambda t: f"/bin/{t}" if t in tools else None,
                             runner=lambda argv: seen.append(argv) or (code, "boom"))
        return result, seen

    def test_each_system_s_tool(self):
        r, seen = self.calls("darwin", {"terminal-notifier", "osascript"})
        self.assertEqual((r, seen[0][0]), ({"ok": True, "error": None}, "terminal-notifier"))
        self.assertLessEqual(len(seen[0][seen[0].index("-message") + 1]), 200)
        self.assertEqual(self.calls("darwin", {"osascript"})[1][0][0], "osascript")
        self.assertEqual(self.calls("linux", {"notify-send"})[1][0][0], "notify-send")
        self.assertEqual(self.calls("win32", {"pwsh"})[1][0][0], "/bin/pwsh")

    def test_it_never_raises(self):
        self.assertEqual(self.calls("linux", set()), ({"ok": False, "error": "no desktop notification tool found"},
                                                      []))
        r, _ = self.calls("linux", {"notify-send"}, code=1)
        self.assertEqual((r["ok"], r["error"]), (False, "notify-send exit 1: boom"))
        r = notice.send("t", "b", system="linux", which=lambda t: "/bin/x", runner=mock.Mock(side_effect=OSError))
        self.assertFalse(r["ok"])

    def test_quotes_are_escaped_for_osascript(self):
        argv = notice.command('a "t"', 'b "q" \\', "darwin", which=lambda t: t == "osascript")
        self.assertEqual(argv[2], 'display notification "b \\"q\\" \\\\" with title "a \\"t\\""')


if __name__ == "__main__":
    unittest.main()
