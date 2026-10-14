import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import adapt

HERE = Path(__file__).resolve().parent
# hal2's hal2-cli-git with `worktree queue order` (plan 0143); the installed one may predate it.
HAL2_CLI_GIT = os.environ.get("HAL2_CLI_GIT") or str(
    Path.home() / ".hal/git/worktree/hal2/18/code/rust/target/debug/hal2-cli-git")


def ticket(slot, pid=7, reserved=False, state="waiting"):
    t = {"slot": slot, "pid": pid, "state": state, "worktree": f"/w/{slot}"}
    if reserved:
        t["reserved"] = {"by": "the user", "since": "T"}
    return t


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
                         "the merge queue: run /mtm now, it takes this reserved place and lands when its turn "
                         "comes. What is committed lands; unfinished steps land after it.")

    def test_on_a_farm_with_a_wagon_master_its_boss_says_land_now(self):
        after = {"queue": [ticket("18", 0, True)], "priority": {"slots": ["18"]}}
        out = adapt.messages({"queue": []}, after, "", lambda w: True, lambda: adapt.roles.WAGON_MASTER_BOSS)
        self.assertEqual(out[0]["kind"], "land")
        self.assertTrue(out[0]["text"].startswith("wagon-master (merge-to-main boss): land now. The user put worktree "
                                                  "18 at place 1 of 1"), out[0]["text"])
        self.assertIn("run /mtm now, it reports your work ready at this reserved place and the wagon master's next "
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


@unittest.skipUnless(Path(HAL2_CLI_GIT).exists(), "needs a hal2-cli-git with `worktree queue order`")
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
            r = run("clear")
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
            self.assertEqual(out["after"]["queue"], [])
            self.assertEqual([m["kind"] for m in out["messages"]], ["unreserved", "unreserved"])
            self.assertNotEqual(run("12", "clear").returncode, 0, "clear stands alone")


if __name__ == "__main__":
    unittest.main()
