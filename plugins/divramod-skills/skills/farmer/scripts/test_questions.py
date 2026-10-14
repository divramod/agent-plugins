"""Hal2 plan 0268 (D9, D11): the farmer's question store and the one list `farmer.py questions` prints."""

import datetime as dt
import json
import re
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

import farmer
import mtm_scan
import questions

QUESTION = "Q9: Land it now?\n  a) (Recommended) yes — now\n  b) no — later\n  c) ask — wait"
OPEN_Q = "\n## Q{n} · 2026-10-09 · agent · open\n\n**Q:** {text}\n  a) (Recommended) x — y\n  b) z — w\n  c) v — u\n"


def git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True, capture_output=True)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name).resolve()
        self.state = self.dir / "state"
        self.folder = self.state / "hal2"
        self.main = self.dir / "hal2"
        self.main.mkdir()
        git(self.main, "init", "-q", "-b", "main")
        git(self.main, "commit", "-q", "--allow-empty", "-m", "x")
        old, mtm_scan.DATA = mtm_scan.DATA, self.state
        self.addCleanup(setattr, mtm_scan, "DATA", old)

    def slot(self, name, text=None):
        path = self.dir / "slots" / name
        git(self.main, "worktree", "add", "-q", "-b", name, str(path))
        if text is not None:
            (path / "QUESTIONS.md").write_text(text)
        return path

    def call(self, *argv):
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = farmer.main([*argv, "--repo", str(self.main)])
        return code, out.getvalue(), err.getvalue()


class Store(Base):
    def test_numbers_count_on_and_are_never_reused(self):
        self.folder.mkdir(parents=True)
        a = questions.add(self.folder, "05", "First?")
        questions.close(self.folder, a["n"], "dropped")
        b = questions.add(self.folder, "farmer", "Second?")
        c = questions.add(self.folder, "07", "Third?", "the answer")
        self.assertEqual((a["n"], b["n"], c["n"]), (1, 2, 3))
        questions.close(self.folder, 3, "dropped")
        self.assertEqual(questions.add(self.folder, "07", "Fourth?")["n"], 4)

    def test_a_line_is_a_keyed_log_line_with_schema_and_utc_time(self):
        self.folder.mkdir(parents=True)
        questions.add(self.folder, "05", QUESTION, "the landing")
        questions.close(self.folder, 1, "answered", "yes")
        lines = [json.loads(x) for x in (self.folder / "questions.jsonl").read_text().splitlines()]
        self.assertEqual([x["state"] for x in lines], ["open", "answered"])
        for x in lines:
            self.assertEqual(x["schema"], 1)
            self.assertRegex(x["at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual((lines[1]["answer"], lines[1]["waits"], lines[1]["slot"]), ("yes", "the landing", "05"))
        self.assertEqual(lines[1]["asked"], lines[0]["at"])

    def test_the_question_gets_its_own_number_in_front(self):
        self.folder.mkdir(parents=True)
        self.assertEqual(questions.add(self.folder, "05", QUESTION)["text"].split(":")[0], "Q1")
        self.assertEqual(questions.add(self.folder, "05", "Plain?")["text"], "Q2: Plain?")

    def test_errors_are_values_not_tracebacks(self):
        self.folder.mkdir(parents=True)
        with self.assertRaises(ValueError):
            questions.close(self.folder, 1, "answered", "x")  # no store yet
        questions.add(self.folder, "05", "A?")
        questions.close(self.folder, 1, "answered", "x")
        for bad in (lambda: questions.close(self.folder, 1, "dropped"), lambda: questions.close(self.folder, 7, "dropped"),
                    lambda: questions.add(self.folder, "", "A?"), lambda: questions.add(self.folder, "05", " ")):
            with self.assertRaises(ValueError):
                bad()
        with self.assertRaises(ValueError):
            questions.add(self.state / "none", "05", "A?")

    def test_a_torn_or_foreign_line_is_skipped(self):
        self.folder.mkdir(parents=True)
        questions.add(self.folder, "05", "A?")
        with (self.folder / "questions.jsonl").open("a") as f:
            f.write('{"n": "x"}\nnot json\n{"n": 2, "state": "open", "sl')
        self.assertEqual([e["n"] for e in questions.load(self.folder)], [1])

    def test_reading_never_creates_the_folder(self):
        self.assertEqual(self.call("questions")[1], "no open questions\n")
        self.assertEqual(self.call("question", "list")[1], "no open questions\n")
        self.assertFalse(self.state.exists())


class Cli(Base):
    def test_add_answer_drop_list(self):
        code, out, _ = self.call("question", "add", "--slot", "05", "--text", QUESTION, "--waits", "the landing")
        self.assertEqual((code, out), (0, "Q1 added for 05\n"))
        self.call("question", "add", "--slot", "farmer", "--text", "Q?: Other?")
        self.assertEqual(self.call("question", "answer", "1", "--text", "yes")[1], "Q1 answered\n")
        self.assertEqual(self.call("question", "drop", "2")[1], "Q2 dropped\n")
        self.assertEqual(self.call("question", "list")[1], "no open questions\n")
        answered = self.call("question", "list", "--answered")[1]
        self.assertIn("Answer (", answered)
        self.assertIn("Waits for: the landing", answered)
        data = json.loads(self.call("question", "list", "--all", "--json")[1])
        self.assertEqual([e["state"] for e in data["entries"]], ["answered", "dropped"])

    def test_a_wrong_call_exits_1_with_one_line(self):
        self.folder.mkdir(parents=True)
        for argv in (("question", "answer", "3", "--text", "x"), ("question", "answer", "1"), ("question", "drop"),
                     ("question", "add", "--slot", "05")):
            code, out, err = self.call(*argv)
            self.assertEqual((code, out, err.count("\n")), (1, "", 1), argv)


class Joined(Base):
    def setUp(self):
        super().setUp()
        self.folder.mkdir(parents=True)
        self.slot("10", "")
        self.slot("05", "# Questions\n" + OPEN_Q.format(n=31, text="Which one?"))
        self.slot("02")
        (self.main / "QUESTIONS.md").write_text(OPEN_Q.format(n=1, text="Main's?"))
        questions.add(self.folder, "05", QUESTION, "the landing of 05")
        questions.add(self.folder, "farmer", "Own?")
        now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        log = [{"at": now, "kind": "ask", "slot": "10", "what": "needs the user's go", "note": "money"},
               {"at": now, "kind": "ask", "slot": "02", "what": "old", "note": ""},
               {"at": now, "kind": "decision", "slot": "02", "what": "go", "note": ""},
               {"at": now, "kind": "ask-ack", "slot": "02", "id": "02-1", "what": "land now", "text": "farmer [02-1]: land now\nReply"}]
        (self.folder / "log.jsonl").write_text("".join(json.dumps(e) + "\n" for e in log))

    def test_one_list_sorted_by_slot_then_number(self):
        _, out, _ = self.call("questions")
        self.assertTrue(out.startswith("6 open questions in 5 worktrees\n\n"), out)
        slots = re.findall(r"^\*\*(\S+)\*\*", out, re.M)
        self.assertEqual(slots, ["02", "05", "05", "10", "farmer", "main"])
        self.assertIn("**05** (the farmer's list)\nQ1: Land it now?", out)
        self.assertIn("Waits for: the landing of 05", out)
        self.assertIn("**05** (QUESTIONS.md)\nQ31: Which one?\n  a) (Recommended) x — y", out)
        self.assertIn("**10** (open ask in the farmer's log)\nneeds the user's go\nmoney", out)
        self.assertIn("**02** (instruction not acked)\n02-1: farmer [02-1]: land now", out)
        self.assertNotIn("old", out)  # an ask the user answered is closed

    def test_modes_and_nothing_open(self):
        questions.close(self.folder, 1, "answered", "yes")
        _, out, _ = self.call("questions", "a")
        self.assertTrue(out.startswith("1 answered question in 1 worktree\n"), out)
        self.assertIn("Answer (", out)
        _, out, _ = self.call("questions", "l")
        self.assertTrue(out.startswith("6 questions in 5 worktrees, 5 open\n"), out)
        (self.dir / "slots" / "05" / "QUESTIONS.md").unlink()
        (self.main / "QUESTIONS.md").unlink()
        (self.folder / "log.jsonl").unlink()
        questions.close(self.folder, 2, "dropped")
        self.assertEqual(self.call("questions")[1], "no open questions\n")
        self.assertEqual(self.call("questions", "a")[1].split("\n")[0], "1 answered question in 1 worktree")

    def test_json_and_an_unreadable_store_is_named(self):
        (self.dir / "slots" / "02" / "QUESTIONS.md").write_text("## Q1 broken\n")
        _, out, _ = self.call("questions", "--json")
        data = json.loads(out)
        self.assertEqual((data["mode"], data["open"], data["slots"]), ("open", 6, 5))
        self.assertEqual([e["slot"] for e in data["entries"]], ["02", "05", "05", "10", "farmer", "main"])
        self.assertEqual(len(data["problems"]), 1)
        self.assertTrue(data["problems"][0].startswith("02: QUESTIONS.md:"))
        self.assertIn("(not read: 02: QUESTIONS.md:", self.call("questions")[1])
        self.assertTrue(set(data["entries"][0]) >= {"slot", "source", "n", "state", "text", "waits", "at", "store"})


if __name__ == "__main__":
    unittest.main()
