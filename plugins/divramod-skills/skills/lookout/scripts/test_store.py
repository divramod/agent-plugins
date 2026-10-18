"""Tests of store.py and the store commands: records, validation, the change log, locks (scratch folders only)."""

import contextlib
import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import lookout
import paths
import store
import watchfile

CHECK = "{python} -c 'print(1)'"


class StoreBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        self.cfg, self.state = self.tmp / "cfg", self.tmp / "state"
        patch = mock.patch.dict(os.environ, {"LOOKOUT_DIR": str(self.cfg), "LOOKOUT_STATE_DIR": str(self.state),
                                             "LOOKOUT_BY": "tester"})
        patch.start()
        self.addCleanup(patch.stop)
        self.farm = self.tmp / "alpha"
        self.farm.mkdir()
        self.name, self.path = store.farm_of(self.farm)

    def add(self, watch_id="replies", **fields):
        fields = dict({"title": "Replies", "cron": "0 */3 * * *", "check": CHECK}, **fields)
        return store.add(self.name, self.path, watch_id, fields)

    def changes(self):
        return store.read_changes()

    def cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = lookout.main(list(argv))
        return code, out.getvalue(), err.getvalue()


class AddTest(StoreBase):
    def test_add_writes_the_daybook_format_and_one_change_line(self):
        record = self.add(judge="@judge.md", budget="0.1", timeout="90", notify="desktop,telegram")
        text = (self.cfg / "alpha.yaml").read_text()
        _comments, watches = watchfile.parse(text)  # the daybook's own reader
        self.assertEqual(watches, [record])
        self.assertEqual(record["farm"], str(self.farm.resolve()))
        self.assertEqual((record["budget"], record["timeout"], record["by"], record["active"]),
                         ("0.1", 90, "tester", True))
        self.assertEqual(watchfile.dump(*watchfile.parse(text)), text)  # a round trip changes nothing
        lines = self.changes()
        self.assertEqual(len(lines), 1)
        self.assertEqual((lines[0]["farm"], lines[0]["watch"], lines[0]["op"], lines[0]["by"]),
                         ("alpha", "replies", "add", "tester"))
        self.assertEqual(lines[0]["changes"]["cron"], [None, "0 */3 * * *"])
        self.assertTrue(lines[0]["at"])

    def test_add_refuses_what_is_wrong(self):
        self.add()
        cases = [("Bad_Id", {}, "kebab"), ("replies", {}, "exists already"),
                 ("x", {"cron": "61 * * * *"}, "out of range"), ("x", {"check": "no-such-program-xyz"}, "does not exist"),
                 ("x", {"budget": "0.9"}, "out of range"), ("x", {"timeout": "999"}, "out of range"),
                 ("x", {"notify": "pager"}, "notify is"), ("x", {"title": ""}, "add needs --title")]
        for watch_id, fields, word in cases:
            with self.assertRaises(store.StoreError, msg=word) as ctx:
                self.add(watch_id, **fields)
            self.assertIn(word, str(ctx.exception))
        self.assertEqual(len(self.changes()), 1)  # nothing refused was logged

    def test_a_relative_program_is_looked_up_in_the_farm(self):
        script = self.farm / "check.sh"
        with self.assertRaises(store.StoreError):
            self.add("rel", check="./check.sh")
        script.write_text("#!/bin/sh\n")
        self.assertEqual(self.add("rel", check="./check.sh")["check"], "./check.sh")

    def test_two_farms_with_one_name_are_refused(self):
        self.add()
        other = self.tmp / "elsewhere" / "alpha"
        other.mkdir(parents=True)
        name, path = store.farm_of(other)
        self.assertEqual(name, self.name)
        with self.assertRaisesRegex(store.StoreError, "two farms with one name"):
            store.add(name, path, "x", {"title": "t", "cron": "* * * * *", "check": CHECK})


class SetEndTest(StoreBase):
    def test_set_logs_old_and_new_and_skips_a_no_op(self):
        self.add()
        changes = store.set_keys(self.name, "replies", {"title": "Mail", "cron": "0 * * * *"})
        self.assertEqual(changes, {"title": ["Replies", "Mail"], "cron": ["0 */3 * * *", "0 * * * *"]})
        line = self.changes()[-1]
        self.assertEqual((line["op"], line["changes"]), ("set", changes))
        self.assertEqual(store.set_keys(self.name, "replies", {"title": "Mail"}), {})
        self.assertEqual(len(self.changes()), 2)
        self.assertEqual(store.load(self.name)[1][0]["title"], "Mail")

    def test_set_empty_removes_an_optional_key_and_refuses_the_rest(self):
        self.add(judge="x", notify="none")
        store.set_keys(self.name, "replies", {"judge": ""})
        self.assertNotIn("judge", store.load(self.name)[1][0])
        for fields, word in (({"title": ""}, "empty"), ({"id": "z"}, "cannot set"), ({"state": "x"}, "cannot set"),
                             ({"farm": "/x"}, "cannot set"), ({}, "at least one")):
            with self.assertRaisesRegex(store.StoreError, word):
                store.set_keys(self.name, "replies", fields)

    def test_end_keeps_history_and_logs_once(self):
        self.add()
        self.assertEqual(store.end(self.name, "replies", reason="found a job"), {"active": [True, False]})
        self.assertEqual(store.end(self.name, "replies"), {})
        self.assertIs(store.load(self.name)[1][0]["active"], False)
        lines = self.changes()
        self.assertEqual([c["op"] for c in lines], ["add", "end"])
        self.assertEqual(lines[1]["reason"], "found a job")

    def test_find_watch_across_farms(self):
        self.add()
        other = self.tmp / "beta"
        other.mkdir()
        store.add("beta", store.farm_of(other)[1], "replies", {"title": "t", "cron": "* * * * *", "check": CHECK})
        with self.assertRaisesRegex(store.StoreError, "several farms"):
            store.find_watch("replies")
        self.assertEqual(store.find_watch("replies", "beta"), "beta")
        with self.assertRaisesRegex(store.StoreError, "no watch"):
            store.find_watch("nope")


class RunKeysTest(StoreBase):
    def test_the_tick_writes_run_keys_without_a_change_line(self):
        self.add()
        store.update_run_keys(self.name, "replies", {"last_run": "2026-10-14T09:00:00+02:00", "state": "quiet",
                                                     "last_result": "ok", "title": "IGNORED"})
        record = store.load(self.name)[1][0]
        self.assertEqual((record["state"], record["last_result"], record["title"]), ("quiet", "ok", "Replies"))
        self.assertEqual(len(self.changes()), 1)

    def test_a_settled_check_ends_the_watch_as_the_tick(self):
        self.add()
        store.update_run_keys(self.name, "replies", {"state": "found"}, end_reason="check settled (exit 11)")
        self.assertIs(store.load(self.name)[1][0]["active"], False)
        line = self.changes()[-1]
        self.assertEqual((line["op"], line["by"], line["reason"]), ("end", "lookout tick", "check settled (exit 11)"))


class LockTest(StoreBase):
    def test_a_held_lock_is_refused_and_a_stale_one_taken_over(self):
        path = self.tmp / "x.lock"
        first = store.Lock(path, wait=0)
        self.assertTrue(first.acquire())
        self.assertFalse(store.Lock(path, wait=0).acquire())
        first.release()
        self.assertTrue(store.Lock(path, wait=0).acquire())  # released: free again
        old = time.time() - 700
        os.utime(path, (old, old))
        self.assertTrue(store.Lock(path, wait=0, stale=600).acquire())

    def test_a_change_waits_for_the_lock_then_raises(self):
        self.add()
        held = store.Lock(self.cfg / ".store.lock")
        held.acquire()
        self.addCleanup(held.release)
        with mock.patch.object(store, "store_lock", lambda: store.Lock(self.cfg / ".store.lock", wait=0.1)):
            with self.assertRaises(store.LockError):
                store.end(self.name, "replies")


class CliTest(StoreBase):
    def test_add_list_log_set_end_through_the_cli(self):
        code, out, err = self.cli("add", "replies", "--farm", str(self.farm), "--title", "Replies", "--cron",
                                  "0 */3 * * *", "--check", CHECK, "--by", "me")
        self.assertEqual((code, out.strip(), err), (0, "added alpha/replies", ""))
        code, out, _ = self.cli("list", "--farm", str(self.farm))
        self.assertIn("alpha/replies\tactive\t-\t-\t0 */3 * * *\tReplies", out)
        code, out, _ = self.cli("set", "replies", "--title", "Mail", "--by", "me")
        self.assertIn("title 'Replies' -> 'Mail'", out)
        code, out, _ = self.cli("log", "replies", "--json")
        self.assertEqual([json.loads(x)["op"] for x in out.splitlines()], ["add", "set"])
        code, out, _ = self.cli("log", "--farm", str(self.farm), "--since", "2999-01-01")
        self.assertEqual(out, "")
        self.assertEqual(self.cli("end", "replies", "--reason", "done")[1].strip(), "ended alpha/replies")
        code, out, _ = self.cli("list", "--all", "--json")
        self.assertIs(json.loads(out)["watches"][0]["active"], False)

    def test_a_refusal_prints_and_exits_2(self):
        code, out, err = self.cli("add", "Bad", "--farm", str(self.farm), "--title", "t", "--cron", "* * * * *",
                                  "--check", CHECK)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("lookout.py: watch id 'Bad' is not kebab case", err)

    def test_finds_reads_the_farms_record(self):
        line = {"at": "2026-10-14T09:00:00+02:00", "watch": "replies", "event": "e1", "title": "Acme"}
        folder = paths.state_root() / "state" / "alpha"
        folder.mkdir(parents=True)
        (folder / "finds.jsonl").write_text(json.dumps(line) + "\n")
        code, out, _ = self.cli("finds", "--farm", str(self.farm))
        self.assertEqual(out.strip(), "2026-10-14T09:00:00+02:00\treplies\te1\tAcme")
        self.assertEqual(self.cli("finds", "--farm", str(self.farm), "--since", "2026-11-01")[1], "")


if __name__ == "__main__":
    unittest.main()
