"""Hal2 plan 0294, step 12: the proof that the pieces fit. The real `hal2-cli-git` built from this checkout
(`cargo build -p hal2-cli-git` in code/rust; `$HAL2_CLI_GIT` names another) and the real `wagon_master.py`, each as
its own process, on a scratch farm in a temporary folder: a bare origin, the yard `hal2`, the foremen's fields 07,
09 and 11 with a pushed commit each, and the wagon master's field `wagon-master-hal2`. The home, hal2's state and
so the merge queue (`<home>/.hal/git/worktree/hal2/.merge-queue`) lie inside that folder, as in hal2-cli-git's own
integration tests (`HOME`, `HAL2_HOME`, `HAL2_STATE_DIR`): this machine's queue, GitHub, a timer and a session are
never touched, and no landing is started.

Skipped without the built binary (the gate job `agents-test` builds no Rust, and the published plugin
has no Cargo workspace beside it) and with one that predates the hitch and the train mark.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import roles

HERE = Path(__file__).resolve().parent
OWN = "wagon-master-hal2"
BUILD = "cargo build -p hal2-cli-git in code/rust, or HAL2_CLI_GIT=<path>"


def built() -> tuple[str | None, str]:
    """The hal2-cli-git to prove with and, without one, why not: `$HAL2_CLI_GIT`, else the debug binary of the
    Cargo workspace beside this unit (`$CARGO_TARGET_DIR` when set)."""
    exe = os.environ.get("HAL2_CLI_GIT")
    if not exe:
        code = next((p for p in HERE.parents if (p / "rust/Cargo.toml").is_file()), None)
        if code is None:
            return None, f"no Cargo workspace beside this unit, so no built hal2-cli-git ({BUILD})"
        target = Path(os.environ.get("CARGO_TARGET_DIR") or code / "rust/target")
        exe = str(target / "debug" / ("hal2-cli-git.exe" if os.name == "nt" else "hal2-cli-git"))
    if not os.access(exe, os.X_OK):
        return None, f"no built hal2-cli-git at {exe} ({BUILD}): the end-to-end proof did not run"
    usage = subprocess.run([exe, "--help"], capture_output=True, text=True).stdout
    if "worktree queue ready" not in usage or "worktree queue train" not in usage:
        return None, f"{exe} predates `worktree queue ready` and `train` ({BUILD}): the proof did not run"
    return exe, ""


EXE, WHY_NOT = built()


@unittest.skipUnless(EXE, WHY_NOT)
class Proof(unittest.TestCase):
    """One farm for the four checks, each leaving the queue and the yard as it found them: 07 and 09 hitched."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="hal2-wagon-master-e2e-")).resolve()
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)
        cls.home, cls.yard, origin, bin_dir = cls.tmp / "home", cls.tmp / "hal2", cls.tmp / "hal2.git", cls.tmp / "bin"
        bin_dir.mkdir()
        (bin_dir / "hal2-cli-git").symlink_to(EXE)  # the built binary, first on the PATH
        keep = {k: v for k, v in os.environ.items() if k not in ("TMUX", "TMUX_PANE", "FARMER_DIR", "GIT_DIR")}
        cls.env = {**keep, "HOME": str(cls.home), "HAL2_HOME": str(cls.home), "HAL2_TERMINAL": "tnone",
                   "HAL2_STATE_DIR": str(cls.tmp / "state"), "PATH": f"{bin_dir}{os.pathsep}{keep.get('PATH', '')}",
                   "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                   "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
        cls.home.mkdir()
        cls.git(cls.tmp, "init", "-q", "--bare", "-b", "main", str(origin))
        cls.git(cls.tmp, "clone", "-q", str(origin), str(cls.yard))
        cls.git(cls.yard, "checkout", "-q", "-B", "main")
        role = cls.yard / "roles/wagon-master"
        role.mkdir(parents=True)
        shutil.copy(HERE.parent / "templates/ROLE.md", role / "ROLE.md")
        (role / ".gitignore").write_text(roles.GITIGNORE)  # as the farm has it: the role folder is in the barn
        cls.write(cls.yard, "docs/readme.md", "the farm\n")
        cls.git(cls.yard, "add", ".")
        cls.git(cls.yard, "commit", "-qm", "init")
        cls.git(cls.yard, "push", "-q", "-u", "origin", "main")
        cls.git(cls.yard, "remote", "set-head", "origin", "main")
        cls.wm = cls.field(OWN)
        # 11's crop adds the file 07's adds, with other words: clean on the barn, a conflict behind 07.
        cls.fields = {name: cls.field(name, file, text) for name, file, text in (
            ("07", "seven.txt", "seven\n"), ("09", "nine.txt", "nine\n"), ("11", "seven.txt", "eleven\n"))}
        cls.heads = {name: cls.git(path, "rev-parse", "HEAD") for name, path in cls.fields.items()}
        for name in ("07", "09"):
            cls.cli(cls.fields[name], "worktree", "queue", "ready")

    @classmethod
    def run_(cls, argv, cwd) -> subprocess.CompletedProcess:
        return subprocess.run([str(a) for a in argv], cwd=cwd, env=cls.env, capture_output=True, text=True)

    @classmethod
    def git(cls, cwd, *args) -> str:
        done = cls.run_(["git", *args], cwd)
        assert done.returncode == 0, f"git {args}: {done.stderr}"
        return done.stdout.strip()

    @classmethod
    def cli(cls, cwd, *args):
        """`hal2-cli-git <args> --json` by the name the PATH resolves, as the skill's code calls it."""
        done = cls.run_(["hal2-cli-git", *args, "--json"], cwd)
        assert done.returncode == 0, f"hal2-cli-git {args}: {done.stdout}{done.stderr}"
        return json.loads(done.stdout)

    @classmethod
    def write(cls, top, name, text):
        (top / name).parent.mkdir(parents=True, exist_ok=True)
        (top / name).write_text(text)

    @classmethod
    def field(cls, name, file=None, text=""):
        """A field as hal2 lays it out, with one pushed commit when it gets a file."""
        path = cls.home / ".hal/git/worktree/hal2" / name
        cls.git(cls.yard, "worktree", "add", "-q", "-b", name, str(path))
        if file:
            cls.write(path, file, text)
            cls.git(path, "add", ".")
            cls.git(path, "commit", "-qm", f"the crop of {name}")
            cls.git(path, "push", "-q", "-u", "origin", name)
        return path

    def queue(self) -> list[dict]:
        return self.cli(self.yard, "worktree", "queue")["queue"]

    def dry_run(self, *flags):
        done = self.run_([sys.executable, HERE / "wagon_master.py", "train", "--dry-run", *flags,
                          "--repo", self.yard], self.tmp)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout) if "--json" in flags else done.stdout

    def farm(self) -> dict:
        """Everything a dry run could change: the queue's files, each checkout's branch, head and uncommitted
        files, every ref of the repository and of its origin, and the wagon master's role folder (its cache/ aside: a
        car's proof verdict, proof.py, may be kept by a dry run too)."""
        tops = [self.yard, self.wm, *self.fields.values()]
        queue = self.home / ".hal/git/worktree/hal2/.merge-queue"
        files = sorted(p for d in (queue, self.wm / "roles") for p in d.rglob("*") if p.is_file() and p.name != ".lock"
                       and "cache" not in p.relative_to(d).parts)
        return {"files": {str(p): p.read_bytes() for p in files},
                "tops": [self.git(t, "status", "--porcelain=v1", "--branch", "--untracked-files=all") for t in tops],
                "refs": [self.git(t, "for-each-ref") for t in (self.yard, self.tmp / "hal2.git")]}

    def test_1_two_fields_hitch_and_the_queue_shows_two_ready_tickets(self):
        tickets = self.queue()
        self.assertEqual([(t["slot"], t["pid"], t["state"], t["holding"]) for t in tickets],
                         [("07", 0, "waiting", False), ("09", 0, "waiting", False)], "no process waits, none holds")
        for t in tickets:
            name = t["slot"]
            self.assertEqual((t["ready"]["head"], t["ready"]["by"], t["branch"]),
                             (self.heads[name], f"hal2/{name}", name))
            self.assertEqual((t["train"], t["rides_with"], Path(t["worktree"])), (None, None, self.fields[name]))

    def test_2_the_dry_run_names_one_train_of_the_two_cars_and_writes_nothing(self):
        before = self.farm()
        d = self.dry_run("--json")
        self.assertEqual((d["field"], d["standing"], d["alone"], d["unhitched"], d["waiting"]),
                         (OWN, None, False, [], []))
        self.assertEqual([(c["field"], c["branch"], c["head"]) for c in d["cars"]],
                         [(n, n, self.heads[n]) for n in ("07", "09")], "one train, in the queue's order")
        self.assertEqual(d["base"], "origin/main", "the wagon master's field holds nothing beyond the barn")
        self.assertEqual(d["yard"], {"skipped": None, "placed": [], "left": []})
        text = self.dry_run()
        self.assertIn(f"next train: 07 (07, {self.heads['07'][:12]}), 09 (09, {self.heads['09'][:12]})", text)
        self.assertIn("standing: no train", text)
        self.assertEqual(self.farm(), before, "a dry run writes nothing: no queue file, ref, commit, state or board")
        for name in ("train.jsonl", "board.jsonl", "log.jsonl"):
            self.assertFalse((self.wm / "roles/wagon-master" / name).exists(), name)

    def test_3_a_crop_that_conflicts_with_a_car_is_unhitched_in_the_dry_run_with_its_reason(self):
        self.cli(self.fields["11"], "worktree", "queue", "ready")
        self.addCleanup(self.cli, self.yard, "worktree", "queue", "ready", "11", "--clear")
        before = self.farm()
        d = self.dry_run("--json")
        self.assertEqual([c["field"] for c in d["cars"]], ["07", "09"], "the rest rides")
        self.assertEqual(len(d["unhitched"]), 1, d["unhitched"])
        gone = d["unhitched"][0]
        self.assertEqual((gone["field"], gone["head"], gone["tell"], gone["files"], gone["ahead"]),
                         ("11", self.heads["11"], "conflict", ["seven.txt"], ["07", "09"]), "clean on the barn alone")
        self.assertEqual(gone["why"], "conflicts with the cars ahead in seven.txt")
        self.assertIn("unhitched: 11: conflicts with the cars ahead in seven.txt", self.dry_run())
        self.assertEqual(self.farm(), before, "the dry run only names it")
        self.assertEqual([(t["slot"], bool(t["ready"])) for t in self.queue()],
                         [("07", True), ("09", True), ("11", True)], "its ticket is still marked ready")

    def test_4_the_yard_s_placeable_file_is_placed_and_its_secret_shaped_one_left(self):
        for name, text in (("docs/note.md", "a note\n"), (".env", "KEY=value\n")):
            self.write(self.yard, name, text)
            self.addCleanup(os.remove, self.yard / name)
        before = self.farm()
        yard = self.dry_run("--json")["yard"]
        self.assertIsNone(yard["skipped"])
        self.assertEqual([(e["path"], e["deleted"]) for e in yard["placed"]], [("docs/note.md", False)])
        self.assertEqual([(x["path"], x["why"]) for x in yard["left"]], [(".env", "secret-shaped")])
        text = self.dry_run()
        self.assertIn("yard: placed: docs/note.md\n", text)
        self.assertIn("yard: left: .env: secret-shaped\n", text)
        self.assertEqual(self.farm(), before, "both files lie in the yard as they were")

    def test_5_a_place_reserved_for_a_field_that_is_not_ready_holds_the_train_back(self):
        """Step 10's open point, on the real queue: the user's order puts the place in front, a landing waits
        behind it, so the planner forms no train before that field hitches; then the order is the user's."""
        self.cli(self.yard, "worktree", "queue", "order", "11")
        self.addCleanup(self.cli, self.yard, "worktree", "queue", "order", "--clear")
        place = self.queue()[0]
        self.assertEqual((place["slot"], place["pid"], bool(place["reserved"]), place["ready"]), ("11", 0, True, None))
        d = self.dry_run("--json")
        self.assertEqual((d["cars"], d["unhitched"], [w["field"] for w in d["waiting"]]), ([], [], ["07", "09"]))
        self.assertIn("the place reserved for field 11 stands in the queue and 11 is not ready", d["waiting"][0]["why"])
        self.cli(self.fields["11"], "worktree", "queue", "ready")  # the hitch, at the reserved place
        self.addCleanup(self.cli, self.yard, "worktree", "queue", "ready", "11", "--clear")
        d = self.dry_run("--json")
        self.assertEqual(([c["field"] for c in d["cars"]], [u["field"] for u in d["unhitched"]], d["waiting"]),
                         (["11", "09"], ["07"], []), "11 rides first, and now 07 is the one that conflicts")


if __name__ == "__main__":
    unittest.main()
