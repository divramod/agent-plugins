"""Prune's disk phase (disk_phase.py, disk_facts.py; hal2 plan 0514 step 7, D18): idle fields' Rust build folders
deleted while the disk is low, until the mark, never deferred by a workqueue hold, never a busy field, never a
folder holding tracked work, sized without `du`. The unit tests use fakes; the farm tests a scratch farm behind fake
CLIs (fake_clis.py). Nothing outside the scratch folders is touched."""

import contextlib
import io
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import batch
import disk_facts
import disk_phase
import executor
import fake_clis
import prune
from fake_clis import jobs, parse
from test_farmer import git

REL = disk_facts.TARGETS[0]


def field(slot: str, busy: str | None = None, sessions: int = 0, stamp: int = 1) -> dict:
    return {"slot": slot, "path": f"/f/{slot}", "rel": REL, "target": f"/f/{slot}/{REL}", "busy": busy,
            "sessions": sessions, "stamp": stamp}


class World:
    """The outside world of a phase: fields, a disk that gains `per` GB with each deletion, the deletions done."""

    def __init__(self, fields: list[dict], free: float, per: float = 40.0, refuse: dict | None = None):
        self.fields, self.base, self.per, self.refuse = fields, free, per, refuse or {}
        self.deleted: list[str] = []
        self.later: dict[str, str] = {}  # slot: busy reason it has when read again just before its deletion

    def free(self, main):
        return self.base + self.per * len(self.deleted)

    def read(self, main, only=None):
        if only is not None:
            return [{**f, "busy": self.later.get(f["slot"], f["busy"])} for f in self.fields
                    if f["slot"] == only and f["target"] not in self.deleted]
        return [f for f in self.fields if f["target"] not in self.deleted]

    def proof(self, path, rel):
        return self.refuse.get(Path(path).name)

    def delete(self, target):
        self.deleted.append(target)
        return None

    def run(self, dry=False, main="/m"):
        lines: list[str] = []
        with mock.patch.object(disk_facts, "limits", return_value=({"below_gb": 80, "until_gb": 150}, None)):
            rows = disk_phase.run(main, dry, disk_phase.Out(lines.append), free=self.free, read=self.read,
                                  proof=self.proof, delete=self.delete)
        return rows, lines


class Phase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        env = mock.patch.dict("os.environ", {"HAL_PRUNE_DIR": str(self.tmp / "prune")})
        env.start()
        self.addCleanup(env.stop)

    def test_low_disk_deletes_idle_targets_session_less_and_oldest_first_until_the_mark(self):
        w = World([field("13", sessions=1, stamp=1), field("24", stamp=9), field("25", stamp=2), field("26", stamp=3)],
                  free=50.0)
        rows, lines = w.run()
        self.assertEqual(w.deleted, [f"/f/25/{REL}", f"/f/26/{REL}", f"/f/24/{REL}"])  # 50 + 3 x 40 = 170 >= 150
        self.assertEqual([r["status"] for r in rows], ["success"] * 3)
        self.assertEqual(rows[0]["bytes"], 40 * 10**9)  # what the deletion freed: the free space it added, no du
        self.assertIn("stopped: 170.0 GB free, the mark of 150 GB reached", lines)

    def test_a_busy_field_is_kept_and_said(self):
        w = World([field("13", busy="its agent %13 is working"), field("24", busy="a build or test runs in it"),
                   field("25")], free=50.0, per=200.0)
        rows, lines = w.run()
        self.assertEqual(w.deleted, [f"/f/25/{REL}"])
        self.assertIn("kept 13: its agent %13 is working", lines)
        self.assertIn("kept 24: a build or test runs in it", lines)

    def test_a_live_hold_never_defers_the_phase_only_its_field_is_kept(self):
        """D18: a train's workqueue hold stands; the phase runs anyway, the holding field keeps its build folder."""
        w = World([field("31", busy="it holds the workqueue hold h1"), field("13"), field("24")], free=20.0)
        with mock.patch("busy.reason", return_value="deferred: train building (hold h1 of field 31)") as held:
            rows, lines = w.run()
        held.assert_not_called()
        self.assertEqual(w.deleted, [f"/f/13/{REL}", f"/f/24/{REL}"])
        self.assertIn("kept 31: it holds the workqueue hold h1", lines)

    def test_read_again_before_each_deletion_a_field_busy_by_then_is_skipped(self):
        w = World([field("13"), field("24")], free=50.0, per=200.0)
        w.later["13"] = "its agent %13 is starting"
        rows, lines = w.run()
        self.assertEqual(w.deleted, [f"/f/24/{REL}"])
        self.assertEqual((rows[0]["field"], rows[0]["status"], rows[0]["why"]), ("13", "skipped", "its agent %13 is starting"))

    def test_the_proof_refuses_a_folder_holding_tracked_work(self):
        w = World([field("13"), field("24")], free=50.0, per=200.0, refuse={"13": "holds tracked files"})
        rows, _ = w.run()
        self.assertEqual(w.deleted, [f"/f/24/{REL}"])
        self.assertEqual(rows[0]["why"], "holds tracked files")

    def test_disk_fine_reads_no_field(self):
        w = World([field("13")], free=120.0)
        w.read = mock.Mock(side_effect=AssertionError("no field read when the disk is fine"))
        rows, lines = w.run()
        self.assertEqual((rows, w.deleted), ([], []))
        self.assertIn("skipped: disk fine (120 GB free)", lines)

    def test_a_dry_run_deletes_nothing_and_names_every_idle_field(self):
        w = World([field("13"), field("24", busy="its landing runs")], free=50.0)
        rows, lines = w.run(dry=True)
        self.assertEqual(w.deleted, [])
        self.assertEqual([(r["field"], r["status"]) for r in rows], [("13", "would")])

    def test_a_second_phase_says_already_running(self):
        import store
        w = World([field("13")], free=50.0)
        with store.farm_lock("/m", disk_phase.LOCK):
            rows, lines = w.run()
        self.assertEqual((rows, w.deleted), ([], []))
        self.assertTrue(lines[-1].startswith("already running: pid"), lines)


class Facts(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_busy_reasons(self):
        f = {"slot": "13", "path": str(self.tmp / "hal2/13")}
        idle = batch.Processes(listing="1 /bin/sh\n")
        real = os.path.realpath(f["path"])  # cleanup's busy matches the real path (/var is /private/var on macOS)
        sh = batch.Processes(listing=f"7 cargo build --manifest-path {real}/code/rust/Cargo.toml\n")
        agent = {"checkout": f["path"], "pane_id": "%1", "state": "working"}
        cases = [
            (None, {}, set(), idle, "the agents list cannot be read"),
            ([agent], {}, set(), idle, "its agent %1 is working"),
            ([{**agent, "state": "idle"}], {}, set(), idle, None),
            ([], {"holds": [{"id": "h1", "field": "hal2/13"}]}, set(), idle, "it holds the workqueue hold h1"),
            ([], {"running": [{"cwd": f["path"] + "/code/rust", "class": "build"}]}, set(), idle,
             "a workqueue job runs in it (build)"),
            ([], {"holds": [{"id": "h1", "field": "hal2/31"}]}, set(), idle, None),
            ([], {}, {"13"}, idle, "its landing runs"),
            ([], {}, set(), sh, "a build or test runs in it"),
        ]
        for rows, wq, landing, procs, want in cases:
            self.assertEqual(disk_facts.busy_why(f, rows, wq, landing, procs), want, (rows, wq, landing))

    def test_the_proof_on_a_real_scratch_repository(self):
        repo = self.tmp / "hal2/13"
        repo.mkdir(parents=True)
        git(repo, "init", "-q")
        (repo / ".gitignore").write_text("target/\n")
        (repo / "code/rust/target/debug").mkdir(parents=True)
        (repo / "code/rust/target/debug/x.o").write_text("x")
        self.assertIsNone(disk_facts.refusal(str(repo), REL))
        self.assertIn("not a build folder", disk_facts.refusal(str(repo), "code"))
        (repo / "code/rust/target/kept.txt").write_text("work")
        git(repo, "add", "-f", "code/rust/target/kept.txt")
        self.assertEqual(disk_facts.refusal(str(repo), REL), "holds tracked files")
        git(repo, "rm", "-q", "--cached", "code/rust/target/kept.txt")
        (repo / ".gitignore").write_text("")
        self.assertEqual(disk_facts.refusal(str(repo), REL), "not git-ignored")
        shutil.rmtree(repo / "code/rust/target")
        (repo / "code/rust/target").symlink_to(self.tmp)
        self.assertEqual(disk_facts.refusal(str(repo), REL), "no real folder")

    def test_the_marks_come_from_prune_toml_and_a_bad_file_keeps_the_defaults(self):
        (self.tmp / ".hal").mkdir()
        self.assertEqual(disk_phase.due(str(self.tmp), lambda m: 79.0)["due"], True)
        self.assertEqual(disk_phase.due(str(self.tmp), lambda m: 81.0)["due"], False)
        (self.tmp / ".hal/prune.toml").write_text("[disk]\nbelow_gb = 30\nuntil_gb = 60\n")
        self.assertEqual({k: v for k, v in disk_phase.due(str(self.tmp), lambda m: 40.0).items() if k != "note"},
                         {"due": False, "free_gb": 40.0, "below_gb": 30, "until_gb": 60})
        (self.tmp / ".hal/prune.toml").write_text("[disk]\nbelow_gb = 90\nuntil_gb = 60\n")
        state = disk_phase.due(str(self.tmp), lambda m: 70.0)
        self.assertEqual((state["due"], state["below_gb"], state["until_gb"]), (True, 80, 150))
        self.assertIn("until_gb must not be lower", state["note"])


class Farm(fake_clis.Farm):
    """The phase on a scratch farm: real git, fake hal2 CLIs, the free space rising 60 GB per deleted build folder."""

    def setUp(self):
        super().setUp()
        quiet = mock.patch.object(batch.Processes, "text", return_value="1 /bin/sh\n")  # no real process decides
        quiet.start()
        self.addCleanup(quiet.stop)
        self.fields: list[str] = []

    def next_gb(self, main):
        return 50.0 + 60.0 * sum(not (self.base / s / REL).exists() for s in self.fields)

    def plant(self, *slots: str) -> None:
        for s in slots:
            path = self.add(s)
            (path / REL / "debug").mkdir(parents=True)
            (path / REL / "debug/lib.rlib").write_text("build")
            self.fields.append(s)

    def test_low_disk_under_a_hold_deletes_idle_targets_and_keeps_busy_ones(self):
        """The row's done-when: low disk deletes idle targets under a hold, a busy field kept."""
        self.plant("13", "24", "25", "31")
        self.busy = "deferred: train building (hold h1 of field hal2/31, holding)"  # busy.reason: a live hold
        self.feed(agents=[self.agent("25", "working"), self.agent("24", "idle")],
                  workqueue={"holds": [{"id": "h1", "field": "hal2/31", "state": "holding"}], "running": []})
        lines: list[str] = []
        rows = disk_phase.run(str(self.main), False, disk_phase.Out(lines.append))
        self.assertEqual([(r["field"], r["status"]) for r in rows], [("13", "success"), ("24", "success")], lines)
        self.assertFalse((self.base / "13" / REL).exists())
        self.assertFalse((self.base / "24" / REL).exists())
        self.assertTrue((self.base / "25" / REL / "debug/lib.rlib").exists())  # its agent works
        self.assertTrue((self.base / "31" / REL / "debug/lib.rlib").exists())  # it holds the hold
        self.assertIn("kept 25: its agent %25 is working", lines)
        self.assertIn("kept 31: it holds the workqueue hold h1", lines)
        self.assertTrue((self.base / "13/file0.txt").exists())  # the field itself stays

    def test_prune_run_starts_with_the_disk_phase_also_under_a_hold(self):
        self.plant("13", "31")
        self.busy = "deferred: train building (hold h1 of field hal2/31, holding)"
        self.feed(workqueue={"holds": [{"id": "h1", "field": "hal2/31", "state": "holding"}]})
        code, lines = self.prune()
        self.assertEqual(code, 0, lines)
        self.assertEqual(jobs(lines)[:2], ["disk", "facts"])
        self.assertEqual([(s[0], s[1]) for s in parse(lines)["disk"]], [("field 13", "success")])
        self.assertIn("kept 31: it holds the workqueue hold h1", lines)

    def test_a_field_run_has_no_disk_phase(self):
        self.plant("13")
        code, lines = self.prune("13")
        self.assertNotIn("disk", jobs(lines))
        self.assertFalse(any("delete 13 code/rust/target" in x for x in lines))

    def test_the_cli_disk_and_due(self):
        self.plant("13")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(prune.main(["disk", "--due", "--json", "--repo", str(self.main)]), 0)
            self.assertEqual(prune.main(["disk", "--dry-run", "--repo", str(self.main)]), 0)
        self.assertIn('"due": true', out.getvalue())
        self.assertIn("would delete 13 code/rust/target", out.getvalue())
        self.assertTrue((self.base / "13" / REL).exists())
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(prune.main(["disk", "--repo", str(self.main)]), 0)
        self.assertFalse((self.base / "13" / REL).exists())


if __name__ == "__main__":
    unittest.main()
