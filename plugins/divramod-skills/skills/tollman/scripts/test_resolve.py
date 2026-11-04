"""Hal2 plan 0522 D18 (the user via the farmer, 2026-10-31: "conflicts need to be resolved and every hitched wagon
should go into the next train"): a car whose merge conflicts rides; the train waits `resolving`, one resolve order
goes to the later car's foreman, who resolves on the train's branch; the train is marked and its landing (whose
pretest runs before the push) starts only once every conflict is resolved. On engine_farm.py's farm: real git, the
queue as data, no landing ever started (engine.spawn only counts)."""
# enforces .adr/tollman.md and .adr/tollman-decides-trains.md

import json
import unittest
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import acks
import resolve
import train_state
from engine_farm import Farm, out
from test_farmer import git


class Resolving(Farm):
    """Fields 07 and 09 change the same line of shared.txt (the two conflicting cars), 11 is clean behind them."""

    def setUp(self):
        super().setUp()
        self.commit(self.main, "shared.txt", "base\n", push=True)
        git(self.wm, "merge", "-q", "--ff-only", "main")
        self.heads = {f: self.crop(f, files)["ready"]["head"] for f, files in (
            ("07", {"shared.txt": "seven\n"}), ("09", {"shared.txt": "nine\n"}), ("11", {"eleven.txt": "11"}))}
        self.panes = {"07": "%7", "09": "%9", "11": "%11"}

    def resolve(self, field, text, conflicted=False):
        """The foreman's part of the order: the side branch from the train's remote head, its own head merged, the
        conflict resolved (or, `conflicted`, its markers committed as they are), pushed, back on its branch."""
        r = self.train()["resolve"]  # its systematic branch and base (plan 0610 D18: run_names.py)
        path, branch, carrier = self.fields[field], r["branch"], r["ref"]
        git(path, "fetch", "-q", "origin", carrier)
        git(path, "switch", "-q", "-C", branch, f"origin/{carrier}")
        self.assertNotEqual(out_code(path, "merge", "-q", self.heads[field]), 0, "it conflicts as the order says")
        if not conflicted:
            (path / "shared.txt").write_text(text)
        git(path, "add", "shared.txt")
        git(path, "commit", "-q", "--no-edit")
        git(path, "push", "-q", "-f", "origin", branch)
        sha = out(path, "rev-parse", "HEAD")
        git(path, "switch", "-q", field)
        return sha

    def ack(self, sha):
        ack_id = self.typed[0][1].split("]")[0].removeprefix("tollman [")
        self.assertEqual(acks.main(["ack", ack_id, "done", "resolved", sha, "--repo", str(self.wm), "--role",
                                    "tollman"]), 0)

    def never_unhitched(self):
        self.assertNotIn("unhitched", [k for k, _ in self.state()])
        self.assertFalse([c for c in self.gate.calls if "--clear" in c], self.gate.calls)
        self.assertTrue(all(self.gate.of(f)["ready"] for f in ("07", "09", "11")), "every hitch stands")


class Replay(Resolving):
    def test_two_conflicting_cars_both_ride_one_resolve_order_and_the_landing_only_after_the_resolve(self):
        self.round()
        self.assertEqual(self.last, [("form", "run", "-")])
        t = self.train()
        self.assertEqual(([c["field"] for c in t["cars"]], t["state"]), (["07", "09", "11"], "resolving"))
        r = t["resolve"]
        self.assertEqual((r["field"], r["id"], r["files"], r["ahead"], r["branch"], r["head"]),
                         ("09", "09-resolve-1", ["shared.txt"], ["07"], "09-train-1-1-resolve", self.heads["09"]))
        self.assertEqual(r["ref"], "train-1-1", "it starts from run 1's carrier on origin")
        self.assertEqual(self.state(), [("formed", self.carrier()), ("resolving", self.carrier())])
        self.assertEqual((self.gate.calls, self.spawned), ([], []), "nothing marked, nothing lands: no push")
        self.assertEqual(self.subjects()[0], f"Merge branch '07' into {self.branch()}", "07 is in, 09 waits")
        self.assertEqual(out(self.main, "ls-remote", "origin", f"refs/heads/{self.branch()}").split()[0],
                         r["base"], "the train's head published for the foreman")

        self.round()
        self.assertEqual(self.last, [("resolve-order", "send", "09")])
        ((pane, text),) = self.typed
        self.assertEqual(pane, "%9")
        self.assertRegex(text, r"^tollman \[09-\d+\] \(wagon train\): resolve order 09-resolve-1 for field 09: ")
        self.assertIn(f"09-fix merge {self.heads['09']}`", text)
        self.assertIn("checkout -B 09-train-1-1-resolve origin/train-1-1", text, "its systematic branch (D18)")
        self.assertIn("conflicts with the cars ahead (07) in shared.txt", text)
        self.round()
        self.assertEqual((self.last, len(self.typed)), ([], 1), "one order for the conflict, never a second")

        bad = self.resolve("09", "", conflicted=True)
        self.ack(bad)
        self.round()
        self.assertEqual(self.last, [("resolved", "run", "09")])
        self.assertEqual(self.train()["state"], "resolving", "refused: the order stays open")
        self.assertIn("conflict markers are left in shared.txt", self.typed[-1][1])
        self.assertEqual((self.gate.calls, self.spawned), ([], []))

        good = self.resolve("09", "seven\nnine\n")
        self.ack(good)
        self.round()
        self.assertEqual(self.last, [("resolved", "run", "09")])
        self.assertEqual(self.state()[2:], [("resolved", self.carrier()), ("started", self.carrier())])
        self.assertEqual(self.gate.calls, [["worktree", "queue", "train", self.carrier(), "07", "09", "11", "--train",
                                            "1", "--attempt", "1"]], "marked once every conflict is resolved")
        self.assertEqual(self.spawned, [self.carrier()], "its landing starts: its pretest runs before the push")
        self.assertEqual(out(self.cw, "show", "HEAD:shared.txt"), "seven\nnine", "both sides' intent kept")
        self.assertEqual(out(self.cw, "merge-base", "--is-ancestor", good, "HEAD"), "", "the resolve rides")
        self.assertEqual(self.train()["state"], "landing")
        self.never_unhitched()
        schema = json.loads((Path(resolve.__file__).parents[1] / "schemas/train.schema.json").read_text())
        self.assertLessEqual({k for e in train_state.lines(str(self.main)) for k in e}, set(schema["properties"]) | {"at", "slot"})

    def test_a_car_behind_that_conflicts_only_after_the_resolve_gets_its_own_one_order(self):
        self.commit(self.fields["11"], "shared.txt", "eleven\n")  # 11 conflicts with 07 too, and with 09's resolve
        git(self.fields["11"], "push", "-q", "origin", "HEAD")
        self.gate.of("11")["ready"]["head"] = self.heads["11"] = out(self.fields["11"], "rev-parse", "HEAD")
        self.round()
        self.assertEqual([c.get("conflict") for c in self.train()["cars"]], [None, ["shared.txt"], ["shared.txt"]])
        self.round()
        self.ack(self.resolve("09", "seven\nnine\n"))
        self.round()
        r = self.train()["resolve"]
        self.assertEqual((self.train()["state"], r["field"], r["id"], r["ahead"]), ("resolving", "11", "11-resolve-1",
                                                                                    ["07", "09"]))
        self.round()
        self.assertEqual([p for p, _ in self.typed], ["%9", "%11"], "the next conflict's order, once")
        self.assertEqual((self.gate.calls, self.spawned), ([], []))
        self.never_unhitched()

    def test_the_round_s_order_names_the_train_and_its_answer_word(self):
        rows = [{"kind": "formed", "train": "t", "slot": "c", "cars": [{"field": "09", "branch": "09", "head": "h"}]},
                {"kind": "resolving", "train": "t", "slot": "c", "field": "09", "id": "09-resolve-1", "head": "a" * 40,
                 "base": "b" * 40, "branch": "09-train-resolve", "files": ["x"], "ahead": []}]
        (order,) = resolve.actions("/f", rows, {}, [])
        self.assertIn("conflicts with the barn in x", order["text"])
        self.assertEqual(train_state.standing(rows[:1] + rows[1:] + [
            {"kind": "resolved", "train": "t", "slot": "c", "id": "09-resolve-1"}])["state"], "formed")
        self.assertIsNotNone(resolve.WORD.search("done resolved 0123abcd"))


def out_code(cwd, *args) -> int:
    import subprocess
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True).returncode


if __name__ == "__main__":
    unittest.main()
