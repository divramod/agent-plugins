"""Tests of judge.py with a fake `claude` (never the real one)."""

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import fakes
import judge
import paths

NOW = dt.datetime(2026, 10, 14, 9, 0, tzinfo=dt.timezone(dt.timedelta(hours=2)))
EVENT = {"id": "email-1", "summary": "Acme <hr@acme.de>: Ihre Bewerbung", "data": {"from": "hr@acme.de"}}


class JudgeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.claude = fakes.fake_claude(self.tmp / "bin")
        self.log = self.tmp / "log.jsonl"
        self.record = {"id": "replies", "title": "Replies", "farm": str(self.tmp), "judge": "Classify the mail.",
                       "budget": "0.05"}
        self.env = dict(fakes.base_env(), ANTHROPIC_API_KEY="k", ANTHROPIC_AUTH_TOKEN="t", CLAUDECODE="1",
                        CLAUDE_CODE_ENTRYPOINT="cli", CLAUDE_CODE_OAUTH_TOKEN="o", KEEP_ME="1")

    def run_judge(self, record=None, settings=None):
        return judge.judge(record or self.record, "jobsearch", EVENT, self.tmp / "w", claude=self.claude,
                           env=self.env, now=NOW, settings={} if settings is None else settings, log=self.log)

    def test_success_command_stdin_env_and_log(self):
        verdict = self.run_judge()
        self.assertEqual(verdict, {"ok": True, "verdict": "act", "title": "Acme: invitation",
                                   "notify": "Acme: invitation", "data": {"kind": "invitation"}})
        (call,) = fakes.calls(self.tmp / "bin")
        argv = call["argv"]
        self.assertEqual(argv[0], "-p")
        self.assertTrue(argv[1].startswith("Classify the mail.\n\nReply only with the JSON"))
        self.assertEqual(argv[2:6], ["--safe-mode", "--tools", "", "--model"])
        self.assertEqual(argv[6:9], ["sonnet", "--max-budget-usd", "0.05"])
        self.assertIn("--no-session-persistence", argv)
        self.assertEqual(argv[argv.index("--output-format") + 1], "json")
        self.assertEqual(json.loads(argv[argv.index("--json-schema") + 1]), judge.JUDGE_SCHEMA)
        self.assertEqual(json.loads(call["stdin"]), {"farm": "jobsearch", "watch": "replies", "title": "Replies",
                                                     "event": EVENT})
        self.assertEqual(Path(call["cwd"]).resolve(), (self.tmp / "w").resolve())
        for gone in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"):
            self.assertNotIn(gone, call["env"])
        self.assertEqual(call["env"]["CLAUDE_CODE_OAUTH_TOKEN"], "o")
        self.assertEqual(call["env"]["KEEP_ME"], "1")
        (line,) = paths.read_log(self.log)
        self.assertEqual(line["kind"], "judge")
        self.assertEqual((line["watch"], line["event"], line["farm"]), ("replies", "email-1", "jobsearch"))
        self.assertEqual((line["input_tokens"], line["cache_creation_input_tokens"], line["output_tokens"]),
                         (407, 2094, 96))
        self.assertEqual((line["cost_usd"], line["ms"], line["turns"]), (0.0102, 2100, 2))
        self.assertEqual((line["subtype"], line["verdict"], line["model"]), ("success", "act", "sonnet"))

    def test_budget_is_capped_and_defaulted(self):
        self.assertEqual(judge.budget({"budget": "2"}), "0.50")
        self.assertEqual(judge.budget({}), "0.05")
        self.assertEqual(judge.budget({"budget": "x"}), "0.05")
        self.assertEqual(judge.budget({"budget": "0.10"}), "0.10")
        self.run_judge(dict(self.record, budget="9", model="haiku"))
        argv = fakes.calls(self.tmp / "bin")[0]["argv"]
        self.assertEqual(argv[argv.index("--max-budget-usd") + 1], "0.50")
        self.assertEqual(argv[argv.index("--model") + 1], "haiku")

    def test_daily_cap_skips_the_run(self):
        paths.append_log({"kind": "judge", "at": "2026-10-14T08:00:00+02:00", "cost_usd": 0.6}, self.log)
        paths.append_log({"kind": "judge", "at": "2026-10-13T08:00:00+02:00", "cost_usd": 5}, self.log)
        self.assertTrue(self.run_judge(settings={"daily_budget_usd": 1.0})["ok"])
        paths.append_log({"kind": "judge", "at": "2026-10-14T08:30:00+02:00", "cost_usd": 0.4}, self.log)
        verdict = self.run_judge(settings={"daily_budget_usd": 1.0})
        self.assertEqual(verdict, {"ok": False, "reason": "daily cap", "skipped": True})
        self.assertEqual(len(fakes.calls(self.tmp / "bin")), 1)
        self.assertEqual(paths.read_log(self.log)[-1]["subtype"], "daily_cap")

    def test_failures(self):
        for result, reason in ((dict(fakes.SUCCESS, subtype="error_max_budget_usd", is_error=True),
                                "error_max_budget_usd"),
                               ("not json", "bad json"),
                               (dict(fakes.SUCCESS, structured_output={"verdict": "maybe", "title": "x"}), "schema"),
                               (dict(fakes.SUCCESS, structured_output=None), "no structured_output")):
            fakes.set_result(self.tmp / "bin", result)
            verdict = self.run_judge()
            self.assertEqual(verdict, {"ok": False, "reason": reason, "skipped": False})
        self.assertEqual(len(paths.read_log(self.log)), 4)

    def test_timeout_kills_the_run(self):
        (self.tmp / "bin" / "sleep").write_text("30")
        with mock.patch.object(judge, "TIMEOUT", 1):
            verdict = self.run_judge()
        self.assertEqual(verdict, {"ok": False, "reason": "timeout", "skipped": False})
        self.assertEqual(paths.read_log(self.log)[-1]["subtype"], "timeout")

    def test_prompt_file_relative_to_farm(self):
        (self.tmp / "prompts").mkdir()
        (self.tmp / "prompts" / "replies.md").write_text("From the file.")
        self.run_judge(dict(self.record, judge="@prompts/replies.md"))
        self.assertTrue(fakes.calls(self.tmp / "bin")[0]["argv"][1].startswith("From the file."))
        verdict = self.run_judge(dict(self.record, judge="@prompts/missing.md"))
        self.assertFalse(verdict["ok"])
        self.assertFalse(verdict["skipped"])

    def test_stdin_is_cut_to_32_kb(self):
        big = dict(EVENT, data={"body": "ä" * 40000})
        data = judge.stdin_payload("f", self.record, big)
        self.assertLessEqual(len(data), judge.STDIN_LIMIT)
        data.decode("utf-8")

    def test_unjudged_uses_the_summary(self):
        self.assertEqual(judge.unjudged(EVENT), {"verdict": "act", "title": EVENT["summary"],
                                                 "notify": EVENT["summary"], "data": EVENT["data"]})

    def test_binary_from_env(self):
        with mock.patch.dict("os.environ", {"LOOKOUT_CLAUDE": "/x/claude"}):
            self.assertEqual(judge.claude_binary(), "/x/claude")
        self.assertEqual(judge.claude_binary("/y"), "/y")


if __name__ == "__main__":
    unittest.main()


class ReviewRegressionTest(JudgeTest):
    def test_a_tiny_budget_is_never_zero(self):
        self.assertEqual(judge.budget({"budget": "0.004"}), "0.004")

    def test_a_prompt_file_that_is_not_text_is_a_skip_not_a_crash(self):
        (self.tmp / "bad.md").write_bytes(b"\xff\xfe\x00bad")
        verdict = self.run_judge(dict(self.record, judge="@bad.md"))
        self.assertFalse(verdict["ok"])
        self.assertTrue(verdict["reason"].startswith("prompt:"))
