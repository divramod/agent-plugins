"""Hal2 plan 0611 step 2: the shared record store role_records.py: add, close, fold, torn line, the lock, the prune
that keeps open records, and a second role with its own kinds. A scratch state folder, no real sleep."""

import datetime as dt
import json
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import mtm_scan
import role_records as rr
import roletime

T0 = dt.datetime(2026, 11, 1, 10, 0, 0, tzinfo=dt.timezone.utc)
SCHEMA = json.loads((Path(__file__).resolve().parents[2] / "tollman/schemas/records.schema.json").read_text())


class Store(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(self.tmp)]))
        patch = mock.patch.object(mtm_scan, "state_dir", lambda main, role="farmer": self.tmp / role)
        patch.start()
        self.addCleanup(patch.stop)
        saved = dict(rr.KINDS)
        rr.KINDS.clear()
        self.addCleanup(lambda: (rr.KINDS.clear(), rr.KINDS.update(saved)))
        rr.register("tollman", {"fix-order": rr.Kind("fix_order", ("orders.py",), hows=("void",)),
                                "standing": rr.Kind("none")})
        self.main = "/repo"

    def add(self, type="fix-order", slot="12", what="fix 12", now=T0, **kw):
        return rr.add(self.main, "tollman", type, slot, what, kw.pop("by", "tollman"), now=now, **kw)


class AddAndClose(Store):
    def test_add_writes_a_numbered_open_line_that_fits_the_schema(self):
        a = self.add(event={"file": "train.jsonl", "kind": "order", "id": "12-fix-1"}, order="12-fix-1")
        b = self.add(slot="14")
        self.assertEqual((a["id"], b["id"]), ("R1", "R2"))
        self.assertEqual(a["at"], "2026-11-01T10:00:00Z")
        for key in SCHEMA["required"]:
            self.assertIn(key, a)
        self.assertEqual(a["event"]["id"], "12-fix-1")
        raw = json.loads(rr.path(self.main, "tollman").read_text().splitlines()[0])
        self.assertEqual((raw["record"], "id" in raw), ("R1", False))
        self.assertEqual([r["id"] for r in rr.open_(self.main, "tollman")], ["R1", "R2"])

    def test_a_type_the_role_did_not_register_is_refused(self):
        with self.assertRaises(ValueError):
            self.add(type="hand-merge")
        with self.assertRaises(ValueError):
            self.add(what="  ")
        with self.assertRaises(ValueError):
            self.add(by="somebody")

    def test_close_by_its_closer_is_idempotent_and_leaves_the_open_set(self):
        rid = self.add()["id"]
        self.assertTrue(rr.close(self.main, "tollman", rid, "fix_order", "fixed line at 10:05"))
        self.assertFalse(rr.close(self.main, "tollman", rid, "fix_order", "again"))
        self.assertEqual(rr.open_(self.main, "tollman"), [])
        folded = rr.fold(rr.lines(self.main, "tollman"))[rid]
        self.assertEqual((folded["closed"], folded["how"], folded["evidence"]), (True, "fix_order", "fixed line at 10:05"))

    def test_close_refuses_another_closer_but_takes_user_and_the_types_extra_way(self):
        a, b, c = self.add()["id"], self.add()["id"], self.add()["id"]
        with self.assertRaises(ValueError):
            rr.close(self.main, "tollman", a, "restart", "x")
        with self.assertRaises(ValueError):
            rr.close(self.main, "tollman", a, "fix_order", " ")
        self.assertTrue(rr.close(self.main, "tollman", b, "user", "the user's words", by="user"))
        self.assertTrue(rr.close(self.main, "tollman", c, "void", "24 h"))
        self.assertEqual([r["id"] for r in rr.open_(self.main, "tollman")], [a])

    def test_closing_an_unknown_id_is_false(self):
        self.assertFalse(rr.close(self.main, "tollman", "R9", "user", "x", by="user"))


class Reading(Store):
    def test_a_torn_last_line_is_skipped_and_the_next_add_still_works(self):
        self.add()
        f = rr.path(self.main, "tollman")
        with f.open("a") as fh:
            fh.write('{"schema": 1, "at": "2026-11-0')
        self.assertEqual([r["id"] for r in rr.lines(self.main, "tollman")], ["R1"])
        self.assertEqual(self.add()["id"], "R2")

    def test_the_counter_never_reuses_a_pruned_number(self):
        a = self.add()["id"]
        rr.close(self.main, "tollman", a, "fix_order", "e", now=T0)
        later = T0 + dt.timedelta(days=40)
        self.assertEqual(rr.prune(self.main, "tollman", later), 1)
        self.assertEqual(self.add(now=later)["id"], "R2")

    def test_concurrent_adds_get_distinct_numbers_and_whole_lines(self):
        threads = [threading.Thread(target=self.add, kwargs={"slot": str(i)}) for i in range(12)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        ids = [r["id"] for r in rr.lines(self.main, "tollman")]
        self.assertEqual(sorted(ids, key=lambda i: int(i[1:])), [f"R{i}" for i in range(1, 13)])
        self.assertEqual(len(rr.path(self.main, "tollman").read_text().splitlines()), 12)


class Prune(Store):
    def test_prune_keeps_open_and_recent_and_drops_closed_older_than_30_days(self):
        old, recent, still = (self.add()["id"] for _ in range(3))
        rr.close(self.main, "tollman", old, "fix_order", "e", now=T0)
        rr.close(self.main, "tollman", recent, "fix_order", "e", now=T0 + dt.timedelta(days=20))
        now = T0 + dt.timedelta(days=35)
        self.assertEqual(rr.prune(self.main, "tollman", now), 1)
        left = rr.fold(rr.lines(self.main, "tollman"))
        self.assertEqual(sorted(left), [recent, still])
        self.assertFalse(left[still]["closed"])
        self.assertTrue(left[recent]["closed"])
        self.assertEqual(rr.prune(self.main, "tollman", now), 0)

    def test_an_open_record_older_than_30_days_stays(self):
        rid = self.add()["id"]
        self.assertEqual(rr.prune(self.main, "tollman", T0 + dt.timedelta(days=400)), 0)
        self.assertEqual([r["id"] for r in rr.open_(self.main, "tollman")], [rid])

    def test_prune_without_a_file_is_zero(self):
        self.assertEqual(rr.prune(self.main, "tollman", T0), 0)


class Sweep(Store):
    def test_sweep_closes_what_the_closer_proves_and_reports_a_closer_that_raised(self):
        seen = []

        def check(rec, facts):
            seen.append(rec["slot"])
            if rec["slot"] == "bad":
                raise RuntimeError("queue unreadable")
            return "fixed line" if rec["slot"] == "12" else None

        rr.register("tollman", {"fix-order": rr.Kind("fix_order", (), check)})
        a, _, c = self.add(slot="12")["id"], self.add(slot="13")["id"], self.add(slot="bad")["id"]
        out = rr.sweep(self.main, "tollman", T0)
        self.assertEqual(out, [f"{a} closed by fix_order: fixed line", f"{c} closer failed: queue unreadable"])
        self.assertEqual([r["slot"] for r in rr.open_(self.main, "tollman")], ["13", "bad"])
        self.assertEqual(rr.sweep(self.main, "tollman", T0, {}), [f"{c} closer failed: queue unreadable"])

    def test_a_type_without_a_closer_function_is_left_alone(self):
        self.add(type="standing")
        self.assertEqual(rr.sweep(self.main, "tollman", T0), [])


class SecondRole(Store):
    def test_another_role_registers_its_own_kinds_and_keeps_its_own_file(self):
        rr.register("farmer", {"promise": rr.Kind("promises")})
        with self.assertRaises(ValueError):
            rr.add(self.main, "farmer", "fix-order", "12", "x", "code")
        rr.add(self.main, "farmer", "promise", "main", "land plan 7", "code", now=T0)
        self.add()
        self.assertEqual([r["type"] for r in rr.open_(self.main, "farmer")], ["promise"])
        self.assertEqual([r["type"] for r in rr.open_(self.main, "tollman")], ["fix-order"])
        self.assertEqual(rr.path(self.main, "farmer").parent.name, "farmer")


class Listing(Store):
    def test_list_prints_open_records_and_json(self):
        import contextlib
        import io
        rid = self.add()["id"]
        self.add(slot="14")
        rr.close(self.main, "tollman", rid, "user", "words", by="user")
        with mock.patch.object(mtm_scan, "main_checkout", lambda r: self.main):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rr.main(["list", "--role", "tollman", "--open"])
                rr.main(["list", "--role", "tollman", "--json"])
        text = out.getvalue()
        self.assertIn("R2 fix-order 14: fix 12", text)
        self.assertEqual(text.count('"closed": true'), 1)
        self.assertTrue(roletime.parse("2026-11-01T10:00:00Z"))


if __name__ == "__main__":
    unittest.main()
