"""Tests of reflect.py and llm.py on the fake `claude` (never the real one, 0 tokens)."""

import json
import os
import tempfile
import unittest
from pathlib import Path

import budget
import edits
import fake_claude
import llm
import reflect

SKILL = "---\nname: demo\ndescription: d\n---\n\n# demo\n\nRun `python3 q.py`.\nPrint its output.\n"
EDIT_SET = [{"op": "replace", "anchor": "Print its output.", "text": "Print its output unchanged."}]
REFLECTION = "The skill lets the agent summarize the output; it must print it unchanged."


def failure(eval_id, split="train", score=0.0, error=None, prompt=None):
    case = {"id": eval_id, "split": split, "prompt": prompt or f"PROMPT-{eval_id}",
            "checks": [{"op": "contains", "value": "Q1"}]}
    result = {"eval_id": eval_id, "final_text": f"FINAL-{eval_id}", "error": error,
              "tool_calls": [{"id": "t1", "name": "Bash", "input": {"command": f"python3 q.py {eval_id}"}}]}
    judged = {"eval_id": eval_id, "score": score, "error": error,
              "checks": [{"op": "contains", "value": "Q1", "passed": score >= 1, "detail": f"DETAIL-{eval_id}"}]}
    return {"eval": case, "result": result, "judged": judged}


class PromptTest(unittest.TestCase):
    def test_reflection_prompt_holds_the_failures(self):
        prompt = reflect.reflection_prompt(SKILL, [failure("t1"), failure("t2", score=1.0)])
        for part in (SKILL, "PROMPT-t1", "FINAL-t1", "python3 q.py t1", "DETAIL-t1", '"op": "contains"'):
            self.assertIn(part, prompt)
        self.assertNotIn("PROMPT-t2", prompt)  # passed: not shown

    def test_reflection_never_sees_validation_tasks(self):
        with self.assertRaises(ValueError):
            reflect.reflection_prompt(SKILL, [failure("t1"), failure("v1", split="val", prompt="VAL-SECRET")])
        with self.assertRaises(ValueError):
            reflect.reflection_prompt(SKILL, [failure("x", split=None)])

    def test_no_failure_is_an_error(self):
        with self.assertRaises(ValueError):
            reflect.reflection_prompt(SKILL, [failure("t1", score=1.0)])

    def test_run_error_counts_as_failure(self):
        prompt = reflect.reflection_prompt(SKILL, [failure("t1", score=1.0, error="timeout")])
        self.assertIn("Run error: timeout", prompt)

    def test_failures_and_tool_calls_are_bounded(self):
        many = [failure(f"t{n}") for n in range(12)]
        many[0]["result"]["tool_calls"] *= 20
        many[0]["result"]["final_text"] = "z" * 5000
        prompt = reflect.reflection_prompt(SKILL, many)
        self.assertIn("PROMPT-t7", prompt)
        self.assertNotIn("PROMPT-t8", prompt)
        self.assertIn("... 8 more", prompt)
        self.assertNotIn("z" * 1501, prompt)

    def test_edit_prompt(self):
        rejected = [{"edits": [{"op": "delete", "anchor": "REJECTED-ANCHOR"}], "margin": -0.25}]
        prompt = reflect.edit_prompt(SKILL, REFLECTION, rejected, proposed=[[{"op": "delete", "anchor": "P1"}]])
        for part in (SKILL, REFLECTION, "REJECTED-ANCHOR", "-0.250", "P1", reflect.SCHEMA, "at most 4 edits",
                     f"at most {edits.size_cap(SKILL)} characters (now {len(SKILL)})", "```json"):
            self.assertIn(part, prompt)
        self.assertNotIn("Rejected edit sets", reflect.edit_prompt(SKILL, REFLECTION))


class ExtractTest(unittest.TestCase):
    def test_forms(self):
        bare = json.dumps(EDIT_SET)
        self.assertEqual(reflect.extract_edits(bare), EDIT_SET)
        self.assertEqual(reflect.extract_edits(f"Here:\n```json\n{bare}\n```\nDone."), EDIT_SET)
        self.assertEqual(reflect.extract_edits(f"```\n{json.dumps({'edits': EDIT_SET})}\n```"), EDIT_SET)
        self.assertEqual(reflect.extract_edits(f"The set is {bare} as asked."), EDIT_SET)

    def test_parse_errors(self):
        for reply in ("", "no json here", "```json\n{not json\n```", '{"op": "add"}'):
            with self.assertRaises(edits.EditError, msg=reply):
                reflect.extract_edits(reply)


class ModelCallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.bin = self.tmp / "bin"
        fenced = f"```json\n{json.dumps(EDIT_SET)}\n```"
        self.claude = fake_claude.install(self.bin, rules=[
            {"prompt": "## Failed train rollouts", "stream": fake_claude.stream_for(text=REFLECTION)},
            {"prompt": "NOJSON", "stream": fake_claude.stream_for(text="I cannot.")},
            {"prompt": "## Edit set schema", "stream": fake_claude.stream_for(text=fenced)}])
        self.ledger = budget.Ledger(self.tmp / "run" / "ledger.jsonl")
        self.env = {"PATH": os.environ.get("PATH", ""), "HOME": str(self.tmp), "ANTHROPIC_API_KEY": "k",
                    "CLAUDECODE": "1", "CLAUDE_CODE_ENTRYPOINT": "cli"}
        self.kw = {"ledger": self.ledger, "claude": self.claude, "env": self.env, "cwd": self.tmp / "cwd"}
        (self.tmp / "cwd").mkdir()

    def test_reflect_is_a_lean_charged_call(self):
        out = reflect.reflect(SKILL, [failure("t1")], model="haiku", epoch=1, **self.kw)
        self.assertIsNone(out["error"])
        self.assertEqual(out["text"], REFLECTION)
        self.assertEqual(out["usage"]["total"], 84966)
        [call] = fake_claude.calls(self.bin)
        argv = call["argv"]
        self.assertEqual(argv[argv.index("--tools") + 1], "")
        for flag in ("--safe-mode", "--no-session-persistence", "--strict-mcp-config"):
            self.assertIn(flag, argv)
        self.assertEqual(argv[argv.index("--setting-sources") + 1], "")  # review 6: no user settings, no apiKeyHelper
        self.assertEqual(argv[argv.index("--model") + 1], "haiku")
        self.assertEqual(argv[argv.index("--max-turns") + 1], "1")
        self.assertEqual(set(call["env"]), set())  # no API key, no session coupling
        self.assertEqual(call["skills"], {})
        self.assertEqual((self.ledger.spent, self.ledger.rollouts), (84966, 0))
        line = json.loads((self.tmp / "run" / "ledger.jsonl").read_text().splitlines()[-1])
        self.assertEqual((line["kind"], line["epoch"], line["model"]), ("reflect", 1, "haiku"))

    def test_propose_parses_the_edit_set(self):
        out = reflect.propose(SKILL, REFLECTION, rejected=[{"edits": EDIT_SET, "margin": 0.0}], **self.kw)
        self.assertIsNone(out["error"])
        self.assertEqual(out["edits"], EDIT_SET)
        self.assertIn("margin +0.000", fake_claude.calls(self.bin)[0]["prompt"])
        self.assertTrue(edits.apply(SKILL, out["edits"])["changed"])
        self.assertEqual(self.ledger.spent, 84966)

    def test_unparsable_reply_is_an_error_still_charged(self):
        out = reflect.propose(SKILL, "NOJSON " + REFLECTION, **self.kw)
        self.assertIsNone(out["edits"])
        self.assertTrue(out["error"].startswith("parse: "), out["error"])
        self.assertEqual(self.ledger.spent, 84966)

    def test_failed_call_is_charged(self):
        fake_claude.set_rules(self.bin, default={"stream": fake_claude.stream_for(subtype="error_max_budget_usd"),
                                                 "exit": 1})
        out = reflect.propose(SKILL, REFLECTION, **self.kw)
        self.assertIsNone(out["edits"])
        self.assertIn("error_max_budget_usd", out["error"])
        self.assertEqual(self.ledger.spent, 84966)

    def test_regression_cut_off_call_is_charged_its_estimate(self):  # review 2
        for n, rule in enumerate(({"stream": "garbage\n", "exit": 1}, {"sleep": 5, "stream": fake_claude.stream_for()})):
            with self.subTest(rule=sorted(rule)):
                ledger = budget.Ledger(self.tmp / f"cut-{n}.jsonl")
                fake_claude.set_rules(self.bin, default=rule)
                out = reflect.reflect(SKILL, [failure("t1")], timeout=1, **dict(self.kw, ledger=ledger))
                self.assertTrue(out["truncated"])
                self.assertEqual(ledger.spent, llm.ESTIMATES["reflect"])
                line = json.loads(ledger.path.read_text().splitlines()[-1])
                self.assertTrue(line["floored"])

    def test_no_cwd_leaves_no_folder(self):  # review 4: the default cwd is removed after the call
        del self.kw["cwd"]
        reflect.reflect(SKILL, [failure("t1")], **self.kw)
        [call] = fake_claude.calls(self.bin)
        self.assertFalse(Path(call["cwd"]).exists())

    def test_missing_binary(self):
        self.kw["claude"] = str(self.tmp / "no-claude")
        out = reflect.reflect(SKILL, [failure("t1")], **self.kw)
        self.assertTrue(out["error"].startswith("start: "), out["error"])

    def test_cap_stops_before_the_call(self):
        ledger = budget.Ledger(self.tmp / "capped.jsonl", max_tokens=100_000)
        ledger.charge({"total": 90_000}, kind="rollout")
        self.kw["ledger"] = ledger
        with self.assertRaises(budget.BudgetExceeded):
            reflect.reflect(SKILL, [failure("t1")], **self.kw)  # estimate 65k > 10k left
        with self.assertRaises(budget.BudgetExceeded):
            reflect.propose(SKILL, REFLECTION, estimate=20_000, **self.kw)
        self.assertEqual(fake_claude.calls(self.bin), [])
        self.assertEqual(ledger.spent, 90_000)

    def test_rollout_cap_does_not_stop_reflection(self):
        ledger = budget.Ledger(self.tmp / "rolls.jsonl", max_rollouts=1)
        ledger.charge({"total": 10}, kind="rollout")
        self.kw["ledger"] = ledger
        self.assertIsNone(reflect.reflect(SKILL, [failure("t1")], **self.kw)["error"])


class RejectedBufferTest(unittest.TestCase):
    def test_add_reload_recent(self):
        path = Path(tempfile.mkdtemp()) / "run" / "rejected.jsonl"
        buf = reflect.RejectedBuffer(path)
        self.assertEqual(len(buf), 0)
        for n in range(7):
            buf.add([{"op": "delete", "anchor": f"a{n}"}], margin=-0.1 * n, epoch=1, candidate=f"c{n}")
        with path.open("a", encoding="utf-8") as fh:
            fh.write("not json\n")
        again = reflect.RejectedBuffer(path)
        self.assertEqual(len(again), 7)
        self.assertEqual([e["candidate"] for e in again.recent()], ["c2", "c3", "c4", "c5", "c6"])
        self.assertEqual(again.recent(0), [])
        self.assertEqual(again.entries[0]["edits"], [{"op": "delete", "anchor": "a0"}])
        self.assertIn("at", again.entries[0])


if __name__ == "__main__":
    unittest.main()
