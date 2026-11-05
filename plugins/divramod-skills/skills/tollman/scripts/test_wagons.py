"""The wagon status and the fact store (hal2 plan 0604 step 7, D11; L225, L228): wagon_status.py from facts and git,
wagon_store.py on temporary folders, the manifest's store declaration. The table, the verb and the duty are
test_wagon_table.py. Never the tollman's real state: python3 -m unittest test_wagons (in scripts/)."""
# enforces .adr/tollman.md

import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import wagon_store as ws
from wagon_status import status

SKILL = Path(__file__).resolve().parents[1]
T0, T1, T2 = "2026-11-04T10:00:00Z", "2026-11-04T10:30:00Z", "2026-11-04T11:00:00Z"


def order(f, i, at=T0):
    return {"kind": "order", "field": f, "id": i, "at": at}


def answer(f, i, ack, sha=None, at=T1):
    r = {"kind": "answer", "field": f, "id": i, "ack": ack, "at": at}
    if sha:
        r["sha"] = sha
    return r


def run(fs, *, car=True, head=None, merged=(), unknown=(), fix=None, resolving=False):
    def in_carrier(s):
        return None if s in unknown else s in merged
    return status("14", fs, is_car=car, queue_head=head, in_carrier=in_carrier,
                  fix_head=lambda f: fix, resolving=resolving)


class Status(unittest.TestCase):
    def test_car_without_orders_is_boarded(self):
        self.assertEqual(run([], head="aaa", merged={"aaa"}), ("boarded", ""))

    def test_open_order_is_entering(self):
        self.assertEqual(run([order("14", "14-25")], head="aaa", merged={"aaa"})[0], "entering")

    def test_started_is_still_entering(self):
        st = run([order("14", "14-25"), answer("14", "14-25", "started")], head="a", merged={"a"})
        self.assertEqual(st, ("entering", "14-25"))

    def test_done_with_sha_not_merged_is_ready(self):
        fs = [order("14", "14-25"), answer("14", "14-25", "done", "88e2261933")]
        self.assertEqual(run(fs, head="a", merged={"a"}), ("ready", "88e2261933"))

    def test_done_sha_merged_is_boarded(self):
        fs = [order("14", "14-25"), answer("14", "14-25", "done", "88e2261933")]
        self.assertEqual(run(fs, head="a", merged={"a", "88e2261933"}), ("boarded", ""))

    def test_done_without_sha_uses_newer_fix_branch(self):
        fs = [order("56", "56-6"), answer("56", "56-6", "done")]
        self.assertEqual(run(fs, head="a", merged={"a"}, fix=("fc7a323b25", T1))[0], "ready")

    def test_older_fix_branch_is_ignored(self):
        fs = [order("56", "56-6", at=T1), answer("56", "56-6", "done", at=T2)]
        self.assertEqual(run(fs, head="a", merged={"a"}, fix=("old", T0))[0], "boarded")

    def test_refused_stays_entering(self):
        fs = [order("14", "14-25"), answer("14", "14-25", "refused")]
        self.assertEqual(run(fs, head="a", merged={"a"}), ("entering", "refused 14-25"))

    def test_closed_order_is_not_open(self):
        fs = [order("14", "14-25"), {"kind": "close", "field": "14", "id": "14-25", "at": T1}]
        self.assertEqual(run(fs, head="a", merged={"a"})[0], "boarded")

    def test_two_orders_one_open(self):
        fs = [order("57", "57-4"), order("57", "57-5"), answer("57", "57-4", "done", "bbb")]
        self.assertEqual(run(fs, head="a", merged={"a"}), ("entering", "57-5"))

    def test_rider_answered_waits_for_merge(self):
        fs = [order("50", "50-10"), answer("50", "50-10", "done")]
        self.assertEqual(run(fs, car=False, head="602"), ("ready", "602"))

    def test_plain_hitch_is_hitched(self):
        self.assertEqual(run([], car=False, head="602"), ("hitched", ""))

    def test_need_waits_until_merged(self):
        fs = [{"kind": "need", "field": "47", "sha": "186c", "at": T1}]
        self.assertEqual(run(fs, head="a", merged={"a"}), ("ready", "186c"))
        self.assertEqual(run(fs, head="a", merged={"a", "186c"})[0], "boarded")

    def test_unknown_commit_never_boards(self):
        fs = [order("14", "14-25"), answer("14", "14-25", "done", "zzz")]
        self.assertEqual(run(fs, head="a", merged={"a"}, unknown={"zzz"}), ("ready", "zzz?"))

    def test_resolving_is_entering(self):
        self.assertEqual(run([], head="a", resolving=True), ("entering", "resolving"))

    def test_moved_car_head_is_ready(self):
        self.assertEqual(run([], head="new", merged={"old"})[0], "ready")

    def test_short_and_full_sha_count_once(self):
        fs = [order("05", "05-38"), answer("05", "05-38", "done", "f81bc31ed3")]
        st = run(fs, head="f81bc31ed3b40ff0", merged=set())
        self.assertEqual(st, ("ready", "f81bc31ed3"))


class Store(unittest.TestCase):
    def setUp(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(d, ignore_errors=True))
        self.dir, self.store, self.log = d, d / "wagons.jsonl", d / "log.jsonl"
        recs = [
            {"at": T0, "kind": "ask-ack", "slot": "14", "id": "14-25",
             "text": "tollman [14-25]: tollman, train 51 (final head dea4 on x): inline-tests red"},
            {"at": T0, "kind": "ask-ack", "slot": "57 0543", "id": "57 0543-1",
             "text": "tollman [57 0543-1]: tollman, train 51 (x): move tests"},
            {"at": T0, "kind": "ask-ack", "slot": "47", "id": "47-12",
             "text": "tollman [47-12]: tollman, train 51: thanks, 7327ee27ae taken"},
            {"at": T0, "kind": "ask-ack", "slot": "19", "id": "19-15",
             "text": "tollman [19-15] (wagon train): your crop is in the barn (the train of 19)"},
            {"at": T1, "kind": "ack", "slot": "14", "id": "14-25", "what": "started"},
            {"at": T2, "kind": "ack", "slot": "14", "id": "14-25", "what": "done",
             "note": "fixed 88e2261933"},
        ]
        self.log.write_text("\n".join(json.dumps(r) for r in recs) + "\nnot json\n")

    def test_ingest_is_idempotent(self):
        self.assertEqual(ws.ingest(self.store, self.log), 4)
        self.assertEqual(ws.ingest(self.store, self.log), 0)
        fs = ws.facts(self.store)
        self.assertEqual([r["field"] for r in fs if r["kind"] == "order"], ["14", "57"])
        done = [r for r in fs if r.get("ack") == "done"]
        self.assertEqual(done[0]["sha"], "88e2261933")

    def test_notices_are_no_orders(self):
        ws.ingest(self.store, self.log)
        ids = {r["id"] for r in ws.facts(self.store) if r["kind"] == "order"}
        self.assertNotIn("47-12", ids)
        self.assertNotIn("19-15", ids)

    def test_torn_line_is_skipped(self):
        ws.ingest(self.store, self.log)
        with self.store.open("a") as fh:
            fh.write('{"kind": "order", "fie')
        self.assertEqual(len(ws.facts(self.store)), 4)
        ws.add("need", "47", self.store, sha="186c", why="re-hitch")
        self.assertEqual(len(ws.facts(self.store)), 5)  # the new fact is not glued to it

    def test_train_merges_are_needs(self):
        t = self.dir / "train.jsonl"
        t.write_text(json.dumps({"at": T2, "kind": "resolved", "field": "45", "id": "45-resolve-1",
                                 "sha": "abc", "commit": "abc"}) + "\n")
        ws.ingest(self.store, self.log, t)
        needs = [r for r in ws.facts(self.store) if r["kind"] == "need"]
        self.assertEqual([(r["field"], r["sha"]) for r in needs], [("45", "abc")])
        self.assertEqual(ws.ingest(self.store, self.log, t), 0)

    def test_facts_survive_a_pruned_log(self):
        ws.ingest(self.store, self.log)
        self.log.write_text("")
        ws.ingest(self.store, self.log)
        self.assertEqual(len(ws.facts(self.store)), 4)

    def test_lock_sits_beside_the_store(self):
        ws.add("need", "47", self.store, sha="186c", why="x")
        self.assertTrue((self.dir / "wagons.lock").exists())

    def test_the_store_leaves_by_whole_lines_past_its_limit(self):
        with mock.patch.object(ws, "MAX_BYTES", 2000), mock.patch.object(ws, "KEEP_BYTES", 1000):
            for i in range(60):
                ws.add("need", "47", self.store, sha=f"{i:040x}", why="fill")
            size = self.store.stat().st_size
            self.assertLessEqual(size, 2000 + 300)
            lines = self.store.read_text().splitlines()
            self.assertTrue(all(json.loads(x)["kind"] == "need" for x in lines))  # no half line
            self.assertEqual(json.loads(lines[-1])["sha"], f"{59:040x}")  # the newest stays

    def test_a_line_of_before_plan_0604_is_read_and_migrated(self):
        old = {"schema": 1, "kind": "need", "field": "47", "sha": "186c0ab", "why": "x", "at": T1}
        self.store.write_text(json.dumps(old) + "\n" + json.dumps({**old, "field": "14"}) + "\n")
        self.assertEqual([r["field"] for r in ws.facts(self.store)], ["47", "14"])
        self.assertEqual(ws.migrate(self.store), 2)
        rows = [json.loads(x) for x in self.store.read_text().splitlines()]
        self.assertEqual([(r["slot"], "field" in r) for r in rows], [("47", False), ("14", False)])
        self.assertEqual(ws.migrate(self.store), 0)
        self.assertEqual([r["field"] for r in ws.facts(self.store)], ["47", "14"])

    def test_every_fact_has_a_slot(self):
        ws.ingest(self.store, self.log)
        self.assertTrue(all(json.loads(x)["slot"] for x in self.store.read_text().splitlines()))

    def test_the_cli_writes_into_the_state_folder_of_the_repo(self):
        with mock.patch.object(ws, "folder", return_value=self.dir):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(ws.main(["--repo", "x", "need", "47", "186c", "--why", "by hand"]), 0)
                self.assertEqual(ws.main(["--repo", "x", "answer", "14", "14-25", "done", "--sha", "ab12"]), 0)
        self.assertEqual([r["kind"] for r in ws.facts(self.store)], ["need", "answer"])


class Manifest(unittest.TestCase):
    def test_the_manifest_declares_the_store_and_the_rust_check_reads_its_facts(self):
        manifest = (SKILL / "manifest.toml").read_text()
        self.assertRegex(manifest, r'path = "wagons.jsonl"\nkind = "event-log"\nschema = "schemas/wagons.schema.json"')
        self.assertIn("Retention (size)", manifest)
        checker = next((str(Path(d) / "hal2-cli-roles") for d in os.environ.get("PATH", "").split(os.pathsep)
                        if (Path(d) / "hal2-cli-roles").is_file()), None)
        if not checker:
            self.skipTest("no hal2-cli-roles: the Rust check of the manifest did not run")
        with tempfile.TemporaryDirectory() as d:
            store = Path(d) / "wagons.jsonl"
            ws.add("order", "14", store, id="14-1")
            ws.add("answer", "14", store, id="14-1", ack="done", sha="88e2261933")
            ws.add("need", "47", store, sha="186c0ab", why="re-hitch")
            ws.add("close", "14", store, id="14-1", why="no answer needed")
            args = [checker, "check", d, "--manifest", str(SKILL / "manifest.toml"), "--json"]
            p = subprocess.run(args, capture_output=True, text=True)
            self.assertEqual((p.returncode, json.loads(p.stdout)["problems"]), (0, []), p.stdout)
            with store.open("a") as f:  # and the check does read the store's schema
                f.write(json.dumps({"schema": 1, "kind": "derailed", "slot": "14", "at": T0}) + "\n")
            p = subprocess.run(args, capture_output=True, text=True)
            self.assertNotEqual(p.returncode, 0, p.stdout)


if __name__ == "__main__":
    unittest.main()
