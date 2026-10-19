"""Tests of stream.py on canned stream-json (the shapes the spike of plan 0390 step 1 saw)."""

import json
import unittest

import fake_claude
import stream


def text_of(events):
    return "".join(json.dumps(event) + "\n" for event in events)


class StreamTest(unittest.TestCase):
    def test_success_facts(self):
        events = fake_claude.stream_for("Q1: open", [("Skill", {"skill": "get-open-questions"}),
                                                     ("Bash", {"command": "python3 q.py"})])
        facts = stream.parse(text_of(events))
        self.assertIsNone(facts["error"])
        self.assertEqual(facts["final_text"], "Q1: open")
        self.assertEqual([c["name"] for c in facts["tool_calls"]], ["Skill", "Bash"])
        self.assertEqual(facts["tool_calls"][1]["input"], {"command": "python3 q.py"})
        self.assertEqual(facts["skills"], ["get-open-questions"])
        self.assertEqual(facts["usage"], {"input": 8, "output": 1082, "cache_read": 73162, "cache_creation": 10714,
                                          "total": 84966})
        self.assertEqual((facts["num_turns"], facts["subtype"], facts["cost_usd"]), (3, "success", 0.0034))
        kinds = [step["type"] for step in facts["transcript"]]
        self.assertEqual(kinds, ["tool_use", "tool_result", "tool_use", "tool_result", "text"])

    def test_budget_stop_takes_the_largest_count(self):
        # error_max_budget_usd: result.usage is partial, modelUsage and the summed messages are not
        events = fake_claude.stream_for("x", [("Skill", {"skill": "s"})], subtype="error_max_budget_usd")
        result = events[-1]
        result["usage"] = {"input_tokens": 2, "cache_creation_input_tokens": 3036, "cache_read_input_tokens": 7988,
                           "output_tokens": 100}
        result["modelUsage"] = {"claude-haiku-5-5": {"inputTokens": 4, "outputTokens": 271,
                                                     "cacheReadInputTokens": 19012, "cacheCreationInputTokens": 4209}}
        for event in events:
            if event["type"] == "assistant":
                event["message"]["usage"] = {"input_tokens": 2, "cache_creation_input_tokens": 2000,
                                             "cache_read_input_tokens": 9506, "output_tokens": 9}
        facts = stream.parse(text_of(events))
        self.assertEqual(facts["usage"], {"input": 4, "output": 271, "cache_read": 19012, "cache_creation": 4209,
                                          "total": 23496})
        self.assertTrue(facts["error"].startswith("error_max_budget_usd; stopped"))
        self.assertEqual(facts["final_text"], "")

    def test_same_message_counted_once(self):
        usage = {"input_tokens": 3, "cache_creation_input_tokens": 10, "cache_read_input_tokens": 100,
                 "output_tokens": 5}
        block = {"type": "assistant", "message": {"id": "m1", "usage": usage,
                                                  "content": [{"type": "text", "text": "partial"}]}}
        facts = stream.parse(text_of([block, block]))  # no result event: a killed run
        self.assertEqual(facts["usage"]["total"], 118)
        self.assertEqual(facts["error"], "no result event")
        self.assertEqual(facts["final_text"], "partial")

    def test_junk_lines_and_empty(self):
        facts = stream.parse("Warning: no stdin\nnot json\n[1]\n{bad\n")
        self.assertEqual(facts["usage"]["total"], 0)
        self.assertEqual(facts["tool_calls"], [])
        self.assertEqual(stream.parse("")["error"], "no result event")

    def test_long_texts_are_cut(self):
        events = fake_claude.stream_for("y" * 5000)
        facts = stream.parse(text_of(events))
        self.assertEqual(len(facts["final_text"]), 5000)
        self.assertTrue(facts["transcript"][-1]["text"].endswith(" [cut]"))


if __name__ == "__main__":
    unittest.main()
