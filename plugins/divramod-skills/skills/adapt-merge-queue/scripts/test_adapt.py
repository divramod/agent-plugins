import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import adapt

sys.path.insert(0, next(str(_p / "scripts") for _p in Path(__file__).resolve().parents if (_p / ".claude-plugin").is_dir()))
from skillpath import repo_root, sibling  # noqa: E402  (the skills unit's scripts/, plan 0360 D20)
HERE = Path(__file__).resolve().parent
# hal2's hal2-cli-git with `worktree queue order ... --by` (plans 0143, 0313 step 11): this worktree's own build, else
# the one in HAL2_CLI_GIT; the installed one may predate it.
HAL2_CLI_GIT = os.environ.get("HAL2_CLI_GIT") or str(repo_root(__file__) / "code/rust/target/debug/hal2-cli-git")


def has_by(binary: str) -> bool:
    """Whether the binary knows `worktree queue order --by`."""
    if not Path(binary).exists():
        return False
    r = subprocess.run([binary, "help"], capture_output=True, text=True)
    return "queue order" in r.stdout and "--by" in r.stdout


def ticket(slot, pid=7, reserved=False, state="waiting"):
    t = {"slot": slot, "pid": pid, "state": state, "worktree": f"/w/{slot}"}
    if reserved:
        t["reserved"] = {"by": "the user", "since": "T"}
    return t


class Finished(unittest.TestCase):
    def test_a_plan_pointer_in_the_git_dir_means_not_finished(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
            ahead = subprocess.CompletedProcess([], 0, stdout="3\n")
            with mock.patch.object(adapt.subprocess, "run", return_value=ahead):
                self.assertTrue(adapt.finished(tmp, "main"))
                (Path(tmp) / ".git" / "hal").mkdir()
                (Path(tmp) / ".git" / "hal" / "CURRENT_PLAN").write_text("0090-x\n")
                self.assertFalse(adapt.finished(tmp, "main"))


class Messages(unittest.TestCase):
    def test_each_listed_slot_hears_its_place_and_each_moved_slot_that_it_moved(self):
        before = {"queue": [ticket("16", state="active"), ticket("15"), ticket("12")]}
        after = {"queue": [ticket("16", state="active"), ticket("12", reserved=True), ticket("18", 0, True),
                           ticket("15", reserved=True), ticket("20")],
                 "priority": {"slots": ["12", "18", "15"]}}
        out = adapt.messages(before, after, "n8n first", lambda w: False)
        self.assertEqual([(m["slot"], m["kind"]) for m in out],
                         [("12", "place"), ("18", "reserved"), ("15", "place")])
        self.assertIn("place 2 of 5 in the merge queue (n8n first)", out[0]["text"])
        self.assertIn("Keep working", out[1]["text"])

    def test_a_finished_slot_without_a_landing_lands_now(self):
        after = {"queue": [ticket("18", 0, True)], "priority": {"slots": ["18"]}}
        out = adapt.messages({"queue": []}, after, "", lambda w: w == "/w/18")
        self.assertEqual(out[0]["kind"], "land")
        self.assertEqual(out[0]["text"], "merge-to-main boss: land now. The user put worktree 18 at place 1 of 1 in "
                         "the merge queue: run /merge-to-main now, it takes this reserved place and lands when its turn "
                         "comes. What is committed lands; unfinished steps land after it.")

    def test_on_a_farm_with_a_tollman_its_boss_says_land_now(self):
        after = {"queue": [ticket("18", 0, True)], "priority": {"slots": ["18"]}}
        out = adapt.messages({"queue": []}, after, "", lambda w: True, lambda: adapt.roles.TOLLMAN_BOSS)
        self.assertEqual(out[0]["kind"], "land")
        self.assertTrue(out[0]["text"].startswith("tollman (merge-to-main boss): land now. The user put worktree "
                                                  "18 at place 1 of 1"), out[0]["text"])
        self.assertIn("run /merge-to-main now, it reports your work ready at this reserved place and the tollman's next "
                      "train lands it.", out[0]["text"])

    def test_the_boss_is_asked_only_for_a_slot_told_to_land(self):
        def never():
            raise AssertionError("no slot lands: nobody asks who the boss is")
        after = {"queue": [ticket("18", 0, True), ticket("12", reserved=True)], "priority": {"slots": ["18", "12"]}}
        out = adapt.messages({"queue": []}, after, "", lambda w: False, never)
        self.assertEqual([m["kind"] for m in out], ["reserved", "place"])

    def test_an_unlisted_slot_moved_back_and_a_dropped_reservation_are_told(self):
        before = {"queue": [ticket("15"), ticket("18", 0, True)], "priority": {"slots": ["18"]}}
        after = {"queue": [ticket("12", reserved=True), ticket("15")], "priority": {"slots": ["12"]}}
        out = adapt.messages(before, after, "", lambda w: False)
        self.assertEqual([(m["slot"], m["kind"]) for m in out], [("12", "place"), ("15", "moved"),
                                                                  ("18", "unreserved")])
        self.assertIn("back to place 2 of 2 in the merge queue (was place 1)", out[1]["text"])

    def test_the_queue_before_and_after(self):
        text = adapt.render({"queue": []}, {"queue": [ticket("18", 0, True)], "priority": {"slots": ["18"]}}, [])
        self.assertEqual(text, "before:\n  (empty)\nafter:\n  1. 18: reserved, waits for its turn (reserved by "
                               "the user)\npriority: 18\ntell: nobody")


class Setter(unittest.TestCase):
    """Hal2 plan 0313 step 12 (D18): the order names who set it (`queue order ... --by <who>`)."""

    def argv(self, *args):
        """The `queue order` command line adapt.py builds for `args`, with hal2 and git faked."""
        from unittest import mock
        seen = []

        def fake(argv, cwd=None, **kw):
            seen.append(argv)
            out = {"queue": [], "priority": None}
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(out), stderr="")
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(adapt, "run", side_effect=fake), \
                mock.patch.object(adapt, "main_checkout", return_value=Path("/h/a/hal2")), \
                mock.patch.object(adapt, "default_branch", return_value="main"), \
                mock.patch.object(adapt, "own_field", return_value="hal2/17") as own, \
                mock.patch("sys.stdout"):
            adapt.main([*args, "--repo", d])
        orders = [a for a in seen if "order" in a]
        return orders[0], own.called

    def test_the_default_setter_is_this_sessions_field(self):
        argv, _ = self.argv("12", "18")
        self.assertEqual(argv, ["hal2-cli-git", "worktree", "queue", "order", "12", "18", "--by", "hal2/17", "--json"])

    def test_clear_is_stamped_too_and_a_relayed_user_decision_says_user(self):
        self.assertEqual(self.argv("clear")[0][-4:], ["--clear", "--by", "hal2/17", "--json"])
        argv, own = self.argv("12", "--by", "user")
        self.assertEqual(argv[-3:], ["--by", "user", "--json"])
        self.assertFalse(own, "an explicit --by needs no field lookup")

    def test_an_installed_cli_without_by_is_retried_once_without_it_and_says_so(self):
        import io
        from unittest import mock
        seen = []

        def fake(argv, cwd=None, **kw):
            seen.append(argv)
            if "--by" in argv:
                return subprocess.CompletedProcess(argv, 2, stdout="", stderr='unknown argument "--by"')
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps({"queue": []}), stderr="")
        err = io.StringIO()
        with mock.patch.object(adapt, "run", side_effect=fake), mock.patch("sys.stderr", err):
            out = adapt.queue(Path("/h/a/hal2"), ["12"], "hal2/17")
        self.assertEqual(out, {"queue": []})
        self.assertEqual(seen, [["hal2-cli-git", "worktree", "queue", "order", "12", "--by", "hal2/17", "--json"],
                                ["hal2-cli-git", "worktree", "queue", "order", "12", "--json"]])
        self.assertIn("does not know --by", err.getvalue())

    def test_another_refusal_is_not_retried(self):
        from unittest import mock
        fake = mock.Mock(return_value=subprocess.CompletedProcess([], 1, stdout="", stderr="unknown worktree 99"))
        with mock.patch.object(adapt, "run", fake), self.assertRaises(SystemExit):
            adapt.queue(Path("/h/a/hal2"), ["99"], "hal2/17")
        self.assertEqual(fake.call_count, 1)

    def test_the_own_field_is_repo_slash_slot_and_repo_slash_main_in_the_main_checkout(self):
        from unittest import mock
        top = lambda path: mock.patch.object(adapt, "run", return_value=subprocess.CompletedProcess(
            [], 0, stdout=path + "\n", stderr=""))
        with top("/h/wt/hal2/farmer-hal2"):
            self.assertEqual(adapt.own_field(Path("."), Path("/h/a/hal2")), "hal2/farmer-hal2")
        with top("/h/a/hal2"):
            self.assertEqual(adapt.own_field(Path("."), Path("/h/a/hal2")), "hal2/main")


@unittest.skipUnless(has_by(HAL2_CLI_GIT), "needs a hal2-cli-git with `worktree queue order --by`")
class EndToEnd(unittest.TestCase):
    def test_order_then_clear_against_a_real_queue(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            home, bin_dir = d / "home", d / "bin"
            bin_dir.mkdir()
            (bin_dir / "hal2-cli-git").symlink_to(HAL2_CLI_GIT)
            env = dict(os.environ, HOME=str(home), PATH=f"{bin_dir}:{os.environ['PATH']}",
                       GIT_CONFIG_GLOBAL="/dev/null")
            git = lambda *a, cwd=d: subprocess.run(["git", *a], cwd=cwd, env=env, check=True, capture_output=True)
            git("init", "-q", "--bare", "origin.git")
            git("clone", "-q", "origin.git", "r")
            repo, base = d / "r", home / ".hal/git/worktree/r"
            git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init", cwd=repo)
            git("push", "-q", "origin", "HEAD:main", cwd=repo)
            git("branch", "-q", "-M", "main", cwd=repo)
            git("remote", "set-head", "origin", "main", cwd=repo)
            for slot in ("12", "18"):
                git("worktree", "add", "-q", str(base / slot), "-b", slot, cwd=repo)
            run = lambda *a: subprocess.run([sys.executable, str(HERE / "adapt.py"), *a, "--repo", str(repo),
                                             "--json"], env=env, capture_output=True, text=True)
            r = run("18", "12")
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
            self.assertEqual([t["slot"] for t in out["after"]["queue"]], ["18", "12"])
            self.assertEqual([m["kind"] for m in out["messages"]], ["reserved", "reserved"])
            self.assertEqual(out["after"]["priority"]["by"], "r/main", "stamped with the calling field")
            r = run("18", "12", "--by", "user")
            self.assertEqual(json.loads(r.stdout)["after"]["priority"]["by"], "the user (via r/main)", r.stderr)
            r = run("clear")
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
            self.assertEqual(out["after"]["queue"], [])
            self.assertEqual([m["kind"] for m in out["messages"]], ["unreserved", "unreserved"])
            self.assertNotEqual(run("12", "clear").returncode, 0, "clear stands alone")


if __name__ == "__main__":
    unittest.main()
