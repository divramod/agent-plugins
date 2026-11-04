"""Hal2 plan 0610 step 4 (D5, D21; audit E26): a hitch is forever. No code path of the tollman's or the farmer's
scripts, or the merge-to-main skill's, clears a ready mark or takes a hitch out of the queue but the user's own
`--by-user` (`engine_car.unhitch`); a head already in the barn is settled as landed, its mark kept; no message text
tells a foreman to unhitch or hitch again."""
# enforces .adr/hitch-is-forever.md

import ast
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import engine
import engine_car
import modes
import orders_text
import run_triage_text
import trains

HERE = Path(__file__).resolve().parent
SKILLS = HERE.parents[2]  # code/agents/apps/skills/skills
REPO = SKILLS.parents[4]
ROOTS = (HERE, SKILLS / "roles" / "farmer" / "scripts", SKILLS / "actions" / "merge-to-main" / "scripts",
         REPO / "roles" / "tollman", REPO / "roles" / "farmer")
# the only code that may clear a ready mark: the user's own unhitch, refused without `--by-user`
ALLOWED = {("engine_car.py", "unhitch")}
SHELL = re.compile(r"queue\s+(ready\b[^\n]*--clear|remove\b)")
TOLD = re.compile(r"\bre-?hitch\b|\bhitch (it |yourself )?again\b|\bready again\b|\bunhitch (it|yourself)\b|"
                  r"queue ready[^\n]*--clear", re.I)


def clears(path: Path) -> list[tuple[str, str, int]]:
    """Every list or tuple literal of `path` that names a ready mark's clear (`queue ready ... --clear`) or a
    queue entry's removal (`queue remove`): (file, function, line)."""
    found: list[tuple[str, str, int]] = []

    def visit(node: ast.AST, name: str) -> None:  # each literal under its innermost function
        for n in ast.iter_child_nodes(node):
            if isinstance(n, (ast.List, ast.Tuple)):
                words = {e.value for e in n.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)}
                if {"ready", "--clear"} <= words or {"queue", "remove"} <= words:
                    found.append((path.name, name, n.lineno))
            visit(n, n.name if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) else name)
    visit(ast.parse(path.read_text()), "<module>")
    return found


def scripts(*endings: str) -> list[Path]:
    return [f for r in ROOTS if r.is_dir() for e in endings for f in sorted(r.glob(f"*{e}"))
            if not f.name.startswith("test_")]


class Callers(unittest.TestCase):
    def test_only_the_users_unhitch_clears_a_ready_mark(self):
        found = {(f, fn) for p in scripts(".py") for f, fn, _ in clears(p)}
        self.assertEqual(found, ALLOWED, "a ready mark is cleared only by the user's `--by-user` (D5)")

    def test_no_shell_script_clears_a_ready_mark(self):
        hits = [f"{p.name}:{i}" for p in scripts(".sh", ".bash") for i, line in enumerate(p.read_text().splitlines(), 1)
                if SHELL.search(line) and not line.lstrip().startswith("#")]
        self.assertEqual(hits, [])

    def test_the_scan_sees_a_clear(self):
        with tempfile.TemporaryDirectory() as tmp:
            sample = Path(tmp) / "sample.py"
            sample.write_text('def f(cli):\n    cli(["worktree", "queue", "ready", "07", "--clear"])\n')
            self.assertEqual(clears(sample), [("sample.py", "f", 2)])


class Unhitch(unittest.TestCase):
    TOP = "/no/such/farm/tollman-hal2"

    def run_it(self, train=None, user=False):
        calls = []
        with mock.patch.object(engine, "here", return_value=("/no/such/farm", "tollman-hal2", train, self.TOP)), \
                mock.patch.object(engine, "cli", side_effect=lambda args, cwd: calls.append(args) or (0, "{}")), \
                mock.patch.object(engine_car.train_state, "append"):
            return engine_car.unhitch(self.TOP, "07", "its test fails", user=user), calls

    def test_a_session_never_unhitches_a_waiting_hitch(self):
        (code, text), calls = self.run_it()
        self.assertEqual((code, calls), (1, []))
        self.assertIn("a hitched wagon never leaves the queue", text)

    def test_a_session_never_unhitches_a_car_of_a_red_train(self):
        red = {"train": "07@x", "state": "red", "cars": [{"field": "07"}], "yard": [], "unhitched": []}
        (code, _), calls = self.run_it(train=red)
        self.assertEqual((code, calls), (1, []))

    def test_only_the_users_word_clears_it(self):
        (code, _), calls = self.run_it(user=True)
        self.assertEqual(code, 0)
        self.assertEqual(calls, [["worktree", "queue", "ready", "07", "--clear", "--json"]])


class Barn(unittest.TestCase):
    """Plan 0610 D21: a hitch whose head is in the barn is settled as landed: its mark stays, nothing asks."""
    HEAD = "9" * 40

    def test_the_barn_verb_settles_and_keeps_the_mark(self):
        calls, lines = [], []
        with mock.patch.object(modes.mtm_scan, "main_checkout", return_value="/no/such/farm"), \
                mock.patch.object(modes.train_state, "append", side_effect=lambda *a, **k: lines.append((a, k))), \
                mock.patch.object(modes.train_state, "lines", return_value=[]), \
                mock.patch.object(engine, "cli", side_effect=lambda args, cwd: calls.append(args) or (0, "{}")):
            for how in ("hitch", "formed", "running"):
                code, said = modes.barn("/no/such/farm/tollman-hal2", "09", self.HEAD, how, "07@x")
                self.assertEqual(code, 0)
                self.assertIn("settled as landed, its hitch stays", said)
        self.assertEqual(calls, [], "no ready mark cleared")
        self.assertEqual([a[1] for a, _ in lines], ["barn"] * 3)

    def test_a_settled_hitch_is_not_found_again(self):
        ticket = {"slot": "09", "ready": {"head": self.HEAD}, "state": "waiting"}
        settled = [{"kind": "barn", "slot": "09", "head": self.HEAD, "how": "hitch"}]
        with mock.patch.object(modes.trial, "git", return_value=(0, "")):
            for rows, want in (([], ["09"]), (settled, [])):
                with mock.patch.object(modes.train_state, "lines", return_value=rows):
                    self.assertEqual([c["field"] for c in modes.in_barn("/m", "origin/main", [ticket], None, "x")],
                                     want)

    def test_the_texts_say_settled_never_cleared(self):
        for what in modes.WHAT.values():
            self.assertNotIn("cleared", what)


class Texts(unittest.TestCase):
    def test_no_message_tells_a_foreman_to_unhitch_or_hitch_again(self):
        texts = {**{f"trains.{k}": v for k, v in trains.TEXT.items()},
                 **{f"orders_text.{k}": v for k, v in orders_text.TEXT.items()},
                 "orders_text.PROOF": orders_text.PROOF, "run_triage_text.ORDER": run_triage_text.ORDER}
        told = {k: m.group(0) for k, v in texts.items() if isinstance(v, str) and (m := TOLD.search(v))}
        self.assertEqual(told, {})

    def test_the_split_text_sends_the_answer_where_it_is_read(self):
        """D21: after the user's split no fix order stands, so no `done fixed` to the tollman: the farmer relays."""
        text = trains.TEXT["split"]
        self.assertNotIn("done fixed", text)
        self.assertIn("tell the farmer", text)


if __name__ == "__main__":
    unittest.main()
