"""Hal2 plan 0290 step 3 (D23): the farmer's message board, the tollman's board.py with `--role farmer`: the journal's
`ask-ack`, `ack` and note entries become lines of roles/farmer/board.jsonl once each, the tick runs the sync, the
manifest declares the file. The tollman's own tests (tollman/scripts/test_board.py) stay as they were."""

import contextlib
import datetime as dt
import io
import json
import os
import re
import subprocess
import unittest
from pathlib import Path
from unittest import mock

import acks
import board
import farmer
import mtm_scan
import role_cli
from test_farmer import Repo

SKILL = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((SKILL / "schemas/board.schema.json").read_text())
UTC = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
OWN = "farmer-hal2"
CHECKER = next((str(Path(d) / "hal2-cli-roles") for d in os.environ.get("PATH", "").split(os.pathsep)
                if (Path(d) / "hal2-cli-roles").is_file()), None)


def fits(line: dict) -> list[str]:
    """What board.schema.json's required, enum, pattern and type keywords say against `line` (the Rust check is the real one)."""
    bad = [f"no {k}" for k in SCHEMA["required"] if k not in line]
    for key, rule in SCHEMA["properties"].items():
        if key in line and "enum" in rule and line[key] not in rule["enum"]:
            bad.append(f"{key} not in {rule['enum']}")
        if key in line and "pattern" in rule and not re.search(rule["pattern"], str(line[key])):
            bad.append(f"{key} does not match")
    return bad + [f"unknown key {k}" for k in line if k not in SCHEMA["properties"]]


class FarmerBoard(Repo):
    def setUp(self):
        super().setUp()
        self.main_dir = str(self.main)
        self.state = mtm_scan.state_dir(self.main_dir)

    def journal(self, **entry):
        mtm_scan.log(self.main_dir, {"what": "", "note": "", **entry})

    def lines(self, kind=None):
        return board.lines(self.main_dir, kind, role="farmer")

    def stamp(self, slot, text="go on"):
        entry = acks.ask_entry(slot, acks.next_id(mtm_scan.entries(self.state / "log.jsonl"), slot),
                               acks.stamp(f"farmer: {text}", f"{slot}-1"), None, "farmer")
        self.journal(**entry)
        return entry["id"]

    def ack(self, ack_id, status, why=""):
        with contextlib.redirect_stdout(io.StringIO()):
            acks.main(["ack", ack_id, status, *([why] if why else []), "--repo", self.main_dir])


class Sync(FarmerBoard):
    def test_an_ask_ack_and_its_ack_become_two_lines_once(self):
        ack_id = self.stamp("09")
        self.ack(ack_id, "done", "restocked")
        made = board.sync(self.main_dir, "farmer")
        self.assertEqual([(m["kind"], m["from"], m["to"], m["slot"], m["id"]) for m in made],
                         [("message", OWN, "09", "09", "09-1"), ("ack", "09", OWN, "09", "09-1")])
        self.assertIn("farmer [09-1]: go on", made[0]["text"])
        self.assertEqual((made[1]["status"], made[1]["text"]), ("done", "restocked"))
        for line in made:
            self.assertEqual((line["schema"], fits(line)), (1, []), line)
            self.assertRegex(line["at"], UTC)
        self.assertEqual(board.sync(self.main_dir, "farmer"), [], "each once")
        self.assertEqual(len(self.lines()), 2)
        self.ack(ack_id, "started")  # a later ack of the same message is a new line, never a repeat
        self.assertEqual([m["status"] for m in board.sync(self.main_dir, "farmer")], ["started"])
        self.assertEqual(len((self.state / "board.jsonl").read_text().splitlines()), 3)

    def test_the_file_is_the_farmer_s_and_the_tollman_s_stays_untouched(self):
        self.stamp("07")
        self.assertEqual(board.sync(self.main_dir, "farmer")[0]["from"], OWN)
        self.assertTrue((self.state / "board.jsonl").exists())
        self.assertEqual(board.lines(self.main_dir), [], "the default role is the tollman: its board is another file")
        self.assertFalse(board.path(self.main_dir).exists())
        self.assertEqual(board.own(self.main_dir, "farmer"), OWN)

    def test_a_farmer_board_has_message_ack_and_note_only(self):
        for kind, frm, to, kw in (("ready", "07", OWN, {"head": "a" * 40}), ("train", OWN, "-", {"cars": ["07"]}),
                                  ("red", OWN, "-", {"cars": ["07"]}), ("unhitched", OWN, "07", {"text": "x"})):
            with self.assertRaisesRegex(ValueError, "no board kind", msg=kind):
                board.post(self.main_dir, kind, frm, to, role="farmer", **kw)
        board.post(self.main_dir, "message", OWN, "07", role="farmer", id="07-1", text="farmer [07-1]: hi")
        self.assertEqual(SCHEMA["properties"]["kind"]["enum"], list(board.KINDS_OF["farmer"]))
        self.assertEqual(len(self.lines()), 1)

    def test_a_note_is_a_record_entry_of_kind_note_once_never_a_message(self):
        for kind in ("note", "yard-left", "landed"):  # the tollman's note kinds are not the farmer's
            self.journal(kind=kind, slot="09", what=f"{kind} text", by="tick", do="record", key=kind)
        board.sync(self.main_dir, "farmer")
        board.sync(self.main_dir, "farmer")
        self.assertEqual([(r["kind"], r["from"], r["to"], r["text"]) for r in self.lines()],
                         [("note", OWN, "09", "note text")])

    def test_an_entry_the_schema_refuses_is_skipped_and_the_rest_synced(self):
        self.journal(kind="ask-ack", slot="Not A Field", id="x-1", text="farmer [x-1]: hi")
        good = self.stamp("09")
        self.assertEqual([m["id"] for m in board.sync(self.main_dir, "farmer")], [good])

    def test_the_journal_s_local_times_become_utc(self):
        self.journal(kind="ask-ack", slot="09", id="09-1", text="farmer [09-1]: hi", at="2026-10-13T12:00:00")
        (line,) = board.sync(self.main_dir, "farmer")
        self.assertEqual(line["at"], dt.datetime(2026, 10, 13, 12).astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))

    def test_the_command_line_takes_the_role(self):
        self.ack(self.stamp("09"), "started")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(board.main(["sync", "--role", "farmer", "--repo", self.main_dir]), 0)
            self.assertEqual(board.main(["list", "--role", "farmer", "--json", "--repo", self.main_dir]), 0)
        self.assertEqual(out.getvalue().splitlines()[0], "2 lines posted")
        self.assertEqual([r["kind"] for r in json.loads(out.getvalue().split("\n", 1)[1])], ["message", "ack"])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(board.main(["post", "--role", "farmer", "--kind", "message", "--from", OWN, "--to", "09",
                                         "--id", "09-9", "--text", "hi", "--repo", self.main_dir]), 0)
        self.assertEqual(self.lines("message")[-1]["id"], "09-9")


class Tick(FarmerBoard):
    def test_a_real_tick_syncs_before_and_after_the_round_a_dry_run_does_not(self):
        self.ack(self.stamp("07"), "started")
        seen = []

        def round_(repo, dry, *args):
            if not dry:
                seen.append(len(self.lines()))
                self.ack(self.stamp("09"), "done")  # what the round itself sends and gets
            return 0

        with mock.patch.object(role_cli, "run_tick", side_effect=round_):
            self.assertEqual(farmer.run_tick(str(self.slot), True, False), 0)
            self.assertEqual(self.lines(), [], "a dry run writes no board")
            self.assertEqual(farmer.run_tick(str(self.slot), False, False), 0)
        self.assertEqual(seen, [2], "the first sync ran before the round")
        self.assertEqual([(r["kind"], r["slot"]) for r in self.lines()],
                         [("message", "07"), ("ack", "07"), ("message", "09"), ("ack", "09")], "the second after it")

    def test_a_failing_sync_never_stops_the_round_and_is_logged(self):
        self.stamp("07")
        with mock.patch.object(role_cli, "run_tick", return_value=0) as run, \
                mock.patch.object(board, "write", side_effect=OSError("disk full")):
            self.assertEqual(farmer.run_tick(str(self.slot), False, False), 0)
        run.assert_called_once()
        failed = [e for e in mtm_scan.entries(self.state / "log.jsonl") if e["kind"] == "board-failed"]
        self.assertTrue(failed and all("disk full" in e["what"] for e in failed))


class Files(FarmerBoard):
    def test_the_manifest_declares_the_board_and_the_rust_check_reads_it(self):
        manifest = (SKILL / "manifest.toml").read_text()
        self.assertRegex(manifest, r'path = "board.jsonl"\nkind = "event-log"\nschema = "schemas/board.schema.json"')
        if not CHECKER:
            self.skipTest("no hal2-cli-roles: the Rust check of the manifest did not run")
        folder = self.tmp / "fixture"
        folder.mkdir()
        (folder / "ROLE.md").write_text("---\nnotify: never\n---\n\n# farmer\n")
        ack_id = self.stamp("09")
        self.ack(ack_id, "done", "restocked")
        board.sync(self.main_dir, "farmer")
        for name in ("board.jsonl", "log.jsonl"):
            (folder / name).write_bytes((self.state / name).read_bytes())
        args = [CHECKER, "check", str(folder), "--manifest", str(SKILL / "manifest.toml"), "--json"]
        p = subprocess.run(args, capture_output=True, text=True)
        self.assertEqual((p.returncode, json.loads(p.stdout)["problems"]), (0, []), p.stdout)
        with (folder / "board.jsonl").open("a") as f:  # and the check does read the board's schema
            f.write(json.dumps({"schema": 1, "at": board.utc(), "kind": "train", "slot": OWN, "from": OWN, "to": "-"}) + "\n")
            f.write(json.dumps({"schema": 1, "at": board.utc(), "kind": "note", "slot": "%54", "from": OWN, "to": "%54"}) + "\n")
        p = subprocess.run(args, capture_output=True, text=True)
        self.assertEqual(p.returncode, 1, p.stdout)  # problems fail the check: the report is in the error's details
        found = json.loads(p.stderr)["error"]["details"]["problems"]
        self.assertEqual({x["path"].rsplit("/", 1)[-1] for x in found}, {"board.jsonl"}, p.stdout)
        self.assertEqual(len({x["line"] for x in found}), 2, "the tollman's kind and the pane id, each line named")


if __name__ == "__main__":
    unittest.main()
