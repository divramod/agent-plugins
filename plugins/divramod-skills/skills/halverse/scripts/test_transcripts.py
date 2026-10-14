import json
import os
import tempfile
import unittest
from datetime import datetime, timezone

import transcripts

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "fixtures", "projects")
NOW = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)


def texts(days=3, root=ROOT):
    return [m.text for m in transcripts.user_messages(days, root=root, now=NOW)]


class UserMessages(unittest.TestCase):
    def test_real_message_is_kept(self):
        self.assertIn("please harvest the worktree and tell the farmer", texts())

    def test_tool_result_is_dropped(self):
        self.assertFalse([t for t in texts() if "slot slot slot" in t])

    def test_cross_session_message_is_dropped(self):
        self.assertFalse([t for t in texts() if "Another Claude session" in t or "uds:" in t])

    def test_task_notification_is_dropped(self):
        self.assertFalse([t for t in texts() if "lead lead" in t or "task-id" in t])

    def test_system_reminder_is_cut_but_the_rest_stays(self):
        self.assertIn("land the branch", texts())
        self.assertFalse([t for t in texts() if "The slot is free" in t])

    def test_meta_skill_body_is_dropped(self):
        self.assertFalse([t for t in texts() if "# Skill" in t])

    def test_skill_body_inside_a_message_is_cut(self):
        self.assertIn("before text", texts())
        self.assertFalse([t for t in texts() if "# Body" in t])

    def test_pasted_content_is_cut(self):
        self.assertIn("look: and then land it", texts())

    def test_command_wrapper_keeps_the_arguments(self):
        self.assertIn("3 and the one-shot thing", texts())

    def test_typed_slash_command_loses_the_command_keeps_the_arguments(self):
        self.assertIn("now please", texts())
        self.assertFalse([t for t in texts() if "/mtm" in t])

    def test_command_without_arguments_leaves_nothing(self):
        self.assertFalse([t for t in texts() if "clear" in t])

    def test_subagent_line_is_dropped(self):
        self.assertFalse([t for t in texts() if "in a subagent" in t])

    def test_meta_line_is_dropped(self):
        self.assertFalse([t for t in texts() if "meta slot line" in t])

    def test_message_older_than_the_window_is_dropped(self):
        self.assertFalse([t for t in texts() if "an old slot message" in t])
        self.assertIn("an old slot message", texts(days=60))

    def test_text_blocks_are_joined_and_images_and_placeholders_cut(self):
        self.assertIn("the shot looks wrong", texts())

    def test_code_urls_and_paths_are_cut(self):
        self.assertIn("code and and and and end", texts())

    def test_compact_summary_is_dropped(self):
        self.assertFalse([t for t in texts() if "being continued" in t])

    def test_broken_json_and_bad_timestamp_are_skipped(self):
        self.assertFalse([t for t in texts() if "bad time" in t])
        self.assertIn("no origin key, an older line", texts())

    def test_file_older_than_the_window_is_skipped_by_mtime(self):
        old = os.path.join(ROOT, "-old", "old.jsonl")
        self.assertIn("in an old file", texts())
        before = os.stat(old)
        try:
            os.utime(old, (1.0, 1.0))
            self.assertNotIn("in an old file", texts())
        finally:
            os.utime(old, (before.st_atime, before.st_mtime))

    def test_missing_root_and_unreadable_file_yield_nothing(self):
        self.assertEqual(texts(root=os.path.join(HERE, "no-such-dir")), [])

    def test_root_comes_from_the_environment(self):
        os.environ[transcripts.ROOT_ENV] = ROOT
        try:
            self.assertTrue([m for m in transcripts.user_messages(3, now=NOW)])
        finally:
            del os.environ[transcripts.ROOT_ENV]

    def test_message_carries_time_and_path(self):
        first = next(transcripts.user_messages(3, root=ROOT, now=NOW))
        self.assertEqual(first.timestamp.year, 2026)
        self.assertTrue(first.path.endswith(".jsonl"))


class GeneratedPrompts(unittest.TestCase):
    """Prompts another session or hal2 types into a session look typed; their first line tells them apart."""

    def test_launch_prompts_and_agent_messages_are_generated(self):
        for raw in ("Run /mfm (merge-from-main) first, then:\n\nbrief text", "Run /mfm first, then:\nbrief",
                    "/mfm, then you are a servant", "You are a SUBSERVANT of the demo repo", "You are the milestone servant",
                    "farmer [01-7] (merge-to-main boss): go: /continue", "owner (merge train): you carry on",
                    "merge-to-main boss: land now", "wagon-master [07-1] (wagon train): your crop is in the barn",
                    "wagon-master (merge-to-main boss): land now", "Coordinator (plan 0082): your second step",
                    "hal2 stopped this turn: context at 35%", "hal2 resumed this session: x", "# Post watch digest (headless)",
                    "<!-- IMPORTANT: output the file -->"):
            self.assertTrue(transcripts.is_generated(raw), raw)

    def test_the_users_own_words_are_not_generated(self):
        for raw in ("Run the tests first, then tell me", "you are right, and the farmer should know", "farmer, please look",
                    "i asked the owner: what now", "wagon-master is slow today", "hal2 is slow today", "Run /mfm", "/mfm"):
            self.assertFalse(transcripts.is_generated(raw), raw)

    def test_a_generated_prompt_is_not_a_message_a_typed_one_beside_it_is(self):
        stamp = "2026-10-12T10:00:00.000Z"
        rows = [{"type": "user", "timestamp": stamp, "message": {"role": "user", "content": c},
                 "origin": {"kind": "human"}, "promptSource": "typed"}
                for c in ("Run /mfm (merge-from-main) first, then:\n\nbrief with a slot", "my own slot words")]
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "-demo"))
            with open(os.path.join(root, "-demo", "a.jsonl"), "w", encoding="utf-8") as handle:
                handle.write("\n".join(json.dumps(r, separators=(",", ":")) for r in rows) + "\n")  # compact, as Claude Code writes
            self.assertEqual(texts(root=root), ["my own slot words"])


class ReadingIsCheap(unittest.TestCase):
    def test_lines_that_cannot_be_typed_are_not_parsed(self):
        self.assertTrue(transcripts._may_be_typed('{"type":"user","message":{}}'))
        self.assertTrue(transcripts._may_be_typed('{"type": "user", "message": {}}'))
        self.assertFalse(transcripts._may_be_typed('{"type":"assistant","message":{}}'))
        self.assertFalse(transcripts._may_be_typed('{"type":"user","message":{"content":[{"type":"tool_result"}]}}'))

    def test_a_typed_text_mentioning_tool_result_is_still_read(self):
        row = {"type": "user", "timestamp": "2026-10-12T10:00:00.000Z", "message": {"role": "user", "content": 'a "tool_result" word'}}
        self.assertTrue(transcripts._may_be_typed(json.dumps(row, separators=(",", ":"))))


class Clean(unittest.TestCase):
    def test_hyphenated_word_survives(self):
        self.assertEqual(transcripts.clean("a one-shot idea"), "a one-shot idea")

    def test_plain_words_with_a_slash_survive(self):
        self.assertEqual(transcripts.clean("and/or he/she"), "and/or he/she")

    def test_unterminated_fence_cuts_to_the_end(self):
        self.assertEqual(transcripts.clean("see\n```\nslot"), "see")


if __name__ == "__main__":
    unittest.main()
