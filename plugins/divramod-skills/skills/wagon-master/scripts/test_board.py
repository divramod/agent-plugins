"""Hal2 plan 0294 step 7: the wagon master's message board (board.py) on engine_farm.py's farm: every kind's line,
UTC `at`, append-only, the closed kinds, field names only, pruning by whole lines, and the hooks: whole rounds write
the lines of the ready tickets, trains, messages and acks in order, and a post that fails does not stop a round. No
timer, no session, no real queue."""

import contextlib
import datetime as dt
import io
import json
import os
import re
import subprocess
import time
import unittest
from pathlib import Path
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import acks
import board
import mtm_scan
from engine_farm import OWN, Farm
from test_engine import SKILL

UTC = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
SCHEMA = json.loads((SKILL / "schemas/board.schema.json").read_text())
CHECKER = next((str(Path(d) / "hal2-cli-roles") for d in os.environ.get("PATH", "").split(os.pathsep)
                if (Path(d) / "hal2-cli-roles").is_file()), None)  # shutil.which is the fixture's fake


def valid(schema: dict, value, where: str = "line") -> list[str]:
    """The keywords board.schema.json uses (required, type, enum, pattern, minimum, maximum, minLength, items,
    properties), as the problems of `value`; the Rust check is the real one (Files below)."""
    kind = schema.get("type")
    kinds = {"object": dict, "array": list, "string": str, "integer": int}
    if kind and not isinstance(value, kinds[kind]):
        return [f"{where}: not {kind}"]
    bad = []
    if "enum" in schema and value not in schema["enum"]:
        bad.append(f"{where}: {value!r} not in {schema['enum']}")
    if "pattern" in schema and not re.search(schema["pattern"], value):
        bad.append(f"{where}: {value!r} does not match {schema['pattern']}")
    if "minLength" in schema and len(value) < schema["minLength"]:
        bad.append(f"{where}: too short")
    if kind == "integer" and not schema.get("minimum", value) <= value <= schema.get("maximum", value):
        bad.append(f"{where}: out of range")
    if kind == "array":
        bad += [p for i, x in enumerate(value) for p in valid(schema["items"], x, f"{where}[{i}]")]
    if kind == "object":
        bad += [f"{where}: no {k}" for k in schema.get("required", []) if k not in value]
        bad += [p for k, v in value.items() if k in schema["properties"]
                for p in valid(schema["properties"][k], v, f"{where}.{k}")]
        bad += [f"{where}: unknown key {k}" for k in value if k not in schema["properties"]]
    return bad


class Board(Farm):
    def main_dir(self):
        return str(self.main)

    def post(self, kind, frm, to, **kw):
        return board.post(self.main_dir(), kind, frm, to, **kw)

    def kinds(self):
        return [(r["kind"], r["from"], r["to"]) for r in board.lines(self.main_dir())]

    def file_text(self):
        return (self.wm_state / board.FILE).read_text()


class Shapes(Board):
    def test_every_kind_is_a_line_the_schema_allows_with_schema_and_utc_at(self):
        head, cars = "a" * 40, ["07", "09"]
        posted = [
            self.post("ready", "07", OWN, head=head, text="07 is ready"),
            self.post("unhitched", OWN, "09", text="its test fails", train="07+09@2026-10-13T10:00:00Z"),
            self.post("train", OWN, "-", cars=cars, train="07+09@2026-10-13T10:00:00Z", text="formed"),
            self.post("landed", OWN, "-", cars=cars, run="https://github.com/x/runs/9", commit="c0ffee", text="in"),
            self.post("red", OWN, "-", cars=cars, run="https://github.com/x/runs/9", status="gate_failed", text="red"),
            self.post("message", OWN, "07", id="07-1", text="wagon-master [07-1]: your crop is in the barn"),
            self.post("ack", "07", OWN, id="07-1", status="done", text="restocked")]
        self.assertEqual([p["kind"] for p in posted], list(board.KINDS))
        self.assertEqual(posted, board.lines(self.main_dir()))
        for line in posted:
            self.assertEqual((line["schema"], valid(SCHEMA, line)), (1, []), line)
            self.assertRegex(line["at"], UTC)
        self.assertEqual([p["slot"] for p in posted], ["07", "09", OWN, OWN, OWN, "07", "07"],
                         "the envelope's slot is the foreman's field, the carrier's on a train line")
        self.assertEqual((posted[0]["from"], posted[0]["to"], posted[1]["from"], posted[1]["to"]), ("07", OWN, OWN, "09"))
        self.assertEqual((posted[5]["id"], posted[6]["id"], posted[6]["status"]), ("07-1", "07-1", "done"))
        self.assertEqual(posted[2]["cars"], cars)
        self.assertEqual((posted[3]["run"], posted[4]["run"]), ("https://github.com/x/runs/9",) * 2)
        self.assertEqual(SCHEMA["properties"]["kind"]["enum"], list(board.KINDS))

    def test_at_is_utc_with_z_whatever_zone_the_time_comes_in(self):
        berlin = dt.timezone(dt.timedelta(hours=2))
        line = self.post("ready", "07", OWN, head="b" * 40, now=dt.datetime(2026, 10, 13, 12, 0, 5, tzinfo=berlin))
        self.assertEqual(line["at"], "2026-10-13T10:00:05Z")
        self.assertRegex(self.post("train", OWN, "-", cars=["07"])["at"], UTC)

    def test_the_file_is_append_only_a_line_never_rewritten(self):
        self.post("ready", "07", OWN, head="a" * 40)
        first = self.file_text()
        self.post("ready", "09", OWN, head="b" * 40)
        second = self.file_text()
        self.assertTrue(second.startswith(first), "the first line is unchanged")
        self.assertEqual(len(second.splitlines()), 2)
        self.assertTrue(second.endswith("\n"))
        self.assertEqual([r["from"] for r in board.lines(self.main_dir())], ["07", "09"])
        self.assertEqual([r["from"] for r in board.lines(self.main_dir(), "ready", 1)], ["09"])

    def test_the_list_of_kinds_is_closed_and_a_kind_needs_its_keys(self):
        with self.assertRaisesRegex(ValueError, "no board kind 'derailed'"):
            self.post("derailed", OWN, "07", text="x")
        for kind, frm, to, kw in (("ready", "07", OWN, {}), ("train", OWN, "-", {}), ("message", OWN, "07", {"id": "07-1"}),
                                  ("ack", "07", OWN, {"id": "07-1", "status": "maybe"}), ("unhitched", OWN, "07", {}),
                                  ("message", OWN, "07", {"id": "not an id", "text": "x"}),
                                  ("train", OWN, "-", {"cars": ["%54"]})):
            with self.assertRaises(ValueError, msg=(kind, kw)):
                self.post(kind, frm, to, **kw)
        self.assertFalse((self.wm_state / board.FILE).exists(), "nothing written")

    def test_from_and_to_are_field_names_never_a_pane_a_session_or_a_title(self):
        for bad in ("%54", "t:12", "0d1c2b3a-1111-4222-8333-444455556666", "Wagon Master", "09 (foreman)", "", "/x/y"):
            for side in ({"frm": bad, "to": OWN}, {"frm": "07", "to": bad}):
                with self.assertRaises(ValueError, msg=bad):
                    self.post("ready", side["frm"], side["to"], head="a" * 40)
        self.assertEqual(self.post("train", "farmer-hal2", "-", cars=["07"])["from"], "farmer-hal2")
        self.assertFalse(board.lines(self.main_dir(), "ready"))

    def test_the_file_is_pruned_only_by_whole_lines_from_its_start(self):
        with mock.patch.object(board, "PRUNE_AT", 900), mock.patch.object(board, "PRUNE_TO", 450):
            for n in range(1, 13):
                self.post("message", OWN, "07", id=f"07-{n}", text="x" * 40)
        rows = board.lines(self.main_dir())
        ids = [r["id"] for r in rows]
        self.assertEqual(ids[-1], "07-12", "the newest line stays")
        self.assertLess(len(ids), 12)
        self.assertEqual(ids, [f"07-{n}" for n in range(13 - len(ids), 13)], "a run of the newest, none in the middle gone")
        text = self.file_text()
        self.assertEqual(len(text.splitlines()), len(ids), "every kept line whole")
        self.assertFalse((self.wm_state / (board.FILE + ".tmp")).exists())

    def test_no_state_folder_is_a_failed_post_not_a_created_folder(self):
        with mock.patch.object(board.mtm_scan.roles, "state_dir", return_value=self.wm_state / "gone"):
            with self.assertRaises(FileNotFoundError):
                self.post("train", OWN, "-", cars=["07"])
            self.assertIsNone(board.safely(self.main_dir(), "x", board.on_ready, []))
        self.assertFalse((self.wm_state / "gone").exists())


class Command(Board):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = board.main([*argv, "--repo", str(self.main)])
        return code, out.getvalue() or err.getvalue()

    def test_post_list_and_sync(self):
        self.assertEqual(self.run_cli("list"), (0, "the board is empty\n"))
        code, text = self.run_cli("post", "--kind", "train", "--from", OWN, "--to", "-", "--cars", "07,09",
                                  "--text", "formed")
        self.assertEqual((code, json.loads(text)["cars"]), (0, ["07", "09"]))
        self.assertEqual(self.run_cli("post", "--kind", "ready", "--from", "%1", "--to", OWN, "--head", "a" * 40)[0], 1)
        code, text = self.run_cli("list", "--json")
        self.assertEqual((code, [r["kind"] for r in json.loads(text)]), (0, ["train"]))
        self.assertIn("train     wagon-master-hal2 -> -: formed", self.run_cli("list")[1])
        self.assertEqual(self.run_cli("sync"), (0, "0 lines posted\n"))


class Hooks(Board):
    def test_a_round_writes_the_ready_tickets_the_train_the_barn_the_message_and_the_ack_in_order(self):
        self.crop("07", {"seven.txt": "7"}, plan="0294-wagon-master-role")
        self.crop("09", {"nine.txt": "9"})
        self.round()
        self.assertEqual(self.kinds(), [("ready", "07", OWN), ("ready", "09", OWN), ("train", OWN, "-")])
        rows = board.lines(self.main_dir())
        mark = self.gate.of("07")["ready"]
        self.assertEqual((rows[0]["head"], rows[0]["at"], rows[2]["cars"]), (mark["head"], mark["at"], ["07", "09"]))
        self.assertEqual(rows[2]["train"], self.train()["train"])
        self.round()
        self.assertEqual(len(board.lines(self.main_dir(), "ready")), 2, "once per ticket and head")
        self.crop("11", {"eleven.txt": "11"})
        self.round()
        self.assertEqual([r["from"] for r in board.lines(self.main_dir(), "ready")], ["07", "09", "11"],
                         "a ticket first seen later is posted then")

        self.panes = {"07": "%7", "09": "%9"}
        self.ends({"status": "landed", "commit": "c0ffee", "run": "https://github.com/x/runs/9"}, land=True)
        self.round()
        landed = board.lines(self.main_dir(), "landed")[0]
        self.assertEqual((landed["cars"], landed["run"], landed["commit"]),
                         (["07", "09"], "https://github.com/x/runs/9", "c0ffee"))
        sent = board.lines(self.main_dir(), "message")
        self.assertEqual([(m["from"], m["to"], m["id"]) for m in sent], [(OWN, "07", "07-1"), (OWN, "09", "09-1")])
        self.assertIn("your crop is in the barn", sent[0]["text"])
        self.assertEqual(self.kinds()[-3:], [("landed", OWN, "-"), ("message", OWN, "07"), ("message", OWN, "09")])

        with contextlib.redirect_stdout(io.StringIO()):
            acks.main(["ack", "07-1", "done", "restocked", "--role", "wagon-master", "--repo", str(self.main)])
        self.round()
        (ack,) = board.lines(self.main_dir(), "ack")
        self.assertEqual((ack["from"], ack["to"], ack["id"], ack["status"], ack["text"]), ("07", OWN, "07-1", "done", "restocked"))
        self.assertRegex(ack["at"], UTC)
        self.assertEqual(board.sync(self.main_dir()), [], "each message and ack once")
        for row in board.lines(self.main_dir()):
            self.assertEqual(valid(SCHEMA, row), [], row)

    def test_the_frame_s_local_times_become_utc(self):
        zone = os.environ.get("TZ")
        os.environ["TZ"] = "Europe/Berlin"
        time.tzset()
        try:
            for entry in ({"kind": "ask-ack", "slot": "07", "id": "07-1", "text": "wagon-master [07-1]: hi", "at": "2026-10-13T12:00:00"},
                          {"kind": "ack", "slot": "07", "what": "started", "id": "07-1", "at": "2026-10-13T12:05:00"}):
                with (self.wm_state / "log.jsonl").open("a") as f:
                    f.write(json.dumps({"what": "", "note": "", **entry}) + "\n")
            board.sync(self.main_dir())
        finally:
            os.environ.pop("TZ") if zone is None else os.environ.update(TZ=zone)
            time.tzset()
        self.assertEqual([r["at"] for r in board.lines(self.main_dir())], ["2026-10-13T10:00:00Z", "2026-10-13T10:05:00Z"])

    def test_red_unhitched_and_the_split_message_are_lines_too(self):
        self.crop("07", {"seven.txt": "7"})
        self.crop("09", {"nine.txt": "9"})
        self.round()
        self.alive.add(40001)
        self.ends({"status": "gate_failed", "run": "https://github.com/x/runs/9", "red": [{"name": "linux / rust-test"}]})
        self.gate.of(OWN).update(state="held", train=None, hold={"reason": "failed"})
        self.round()
        red = board.lines(self.main_dir(), "red")[0]
        self.assertEqual((red["cars"], red["status"], red["run"]), (["07", "09"], "gate_failed", "https://github.com/x/runs/9"))
        self.assertIn("gate_failed", red["text"])
        self.assertEqual(self.call("unhitch", "09", "--why", "its test fails", repo=self.main)[0], 0)
        (gone,) = board.lines(self.main_dir(), "unhitched")
        self.assertEqual((gone["from"], gone["to"], gone["text"], gone["slot"]), (OWN, "09", "its test fails", "09"))
        self.assertEqual(gone["train"], red["train"], "a car of the red train")
        self.panes = {"09": "%9"}
        self.round()
        self.assertIn(("message", OWN, "09"), self.kinds())

    def test_a_dry_run_posts_nothing(self):
        self.crop("07", {"seven.txt": "7"})
        self.crop("09", {"nine.txt": "9"})
        self.call("tick", "--dry-run", "--json")
        self.call("train", "--dry-run", "--json", repo=self.main)
        self.assertFalse((self.wm_state / board.FILE).exists())

    def test_a_post_that_fails_does_not_stop_the_round_and_is_logged(self):
        self.crop("07", {"seven.txt": "7"})
        self.crop("09", {"nine.txt": "9"})
        with mock.patch.object(board, "write", side_effect=OSError("disk full")):
            self.round()
        self.assertEqual(self.last, [("form", "run", "-")])
        self.assertEqual(self.train()["state"], "landing", "the train formed and its landing started")
        self.assertFalse((self.wm_state / board.FILE).exists())
        failed = [e for e in mtm_scan.entries(self.wm_state / "log.jsonl") if e["kind"] == "board-failed"]
        self.assertTrue(failed)
        self.assertTrue(all("disk full" in e["what"] for e in failed))
        self.assertEqual(self.call("tick", "--json")[0], 0, "and the next round goes on, the board back")
        self.assertEqual(len(board.lines(self.main_dir(), "ready")), 2, "the tickets seen again are posted then")


class Files(Board):
    def test_the_manifest_declares_the_board_and_the_rust_check_reads_it(self):
        manifest = (SKILL / "manifest.toml").read_text()
        self.assertRegex(manifest, r'path = "board.jsonl"\nkind = "event-log"\nschema = "schemas/board.schema.json"')
        self.assertIn("whole lines from its start", manifest)
        self.crop("07", {"seven.txt": "7"})
        self.round()
        self.post("message", OWN, "07", id="07-9", text="hi")
        self.post("ack", "07", OWN, id="07-9", status="started")
        if not CHECKER:
            self.skipTest("no hal2-cli-roles: the Rust check of the manifest did not run")
        args = [CHECKER, "check", str(self.wm_state), "--manifest", str(SKILL / "manifest.toml"), "--json"]
        p = subprocess.run(args, capture_output=True, text=True)
        self.assertEqual((p.returncode, json.loads(p.stdout)["problems"]), (0, []), p.stdout)
        with (self.wm_state / board.FILE).open("a") as f:  # and the check does read the board's schema
            f.write(json.dumps({"schema": 1, "at": board.utc(), "kind": "derailed", "slot": OWN, "from": OWN, "to": "-"}) + "\n")
            f.write(json.dumps({"schema": 1, "at": board.utc(), "kind": "ready", "slot": "%54", "from": "%54", "to": OWN}) + "\n")
        p = subprocess.run(args, capture_output=True, text=True)
        found = json.loads(p.stdout)["problems"]
        self.assertEqual({x["path"].rsplit("/", 1)[-1] for x in found}, {board.FILE}, p.stdout)
        self.assertEqual(len({x["line"] for x in found}), 2, "the unknown kind and the pane id, each line named")


if __name__ == "__main__":
    unittest.main()
