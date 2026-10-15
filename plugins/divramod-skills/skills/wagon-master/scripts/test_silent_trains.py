"""Hal2 plan 0349 step 10 (D6): `wagon_master.py silence`. A silenced real round prints one table line per train with a
"joined" column and nothing else; a dry run, --json and `unsilence` bring the full output back. Whole rounds on
test_wagon_master's farm (no queue, no session); the train lines over a hand-written train state."""

import json
import unittest
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import mtm_scan
import silence
import tick
import train_state
import wagon_master
from test_farmer import git  # noqa: F401
from test_wagon_master import Field

AT = "2026-10-15T10:00:00Z"
CARS = [{"field": "07", "branch": "07", "head": "7" * 40, "plan": "a"}, {"field": "09", "branch": "09", "head": "9" * 40}]


class Silent(Field):
    def setUp(self):
        super().setUp()
        self.typed, real = [], tick.sh

        def sh(argv, cwd, timeout=900):
            return (0, json.dumps({"status": "ok"})) if argv[0] == "hal2-cli-git" else real(argv, cwd, timeout)

        for p in (mock.patch.object(mtm_scan, "run_json", lambda args, cwd=None: {"queue": []}),
                  mock.patch.object(tick, "sh", sh),
                  mock.patch.object(tick.deliver, "send", lambda pane, text, s=None: self.typed.append((pane, text)))):
            p.start()
            self.addCleanup(p.stop)
        self.call("mode", "timer")

    def train(self, *kinds, name="07+09@" + AT):
        for kind in kinds:
            extra = {"cars": CARS, "base": "b" * 40} if kind == "formed" else {"files": [{"path": "a"}]} if kind == "yard" else {}
            train_state.append(str(self.main), kind, "wagon-master-hal2", train=name, **extra)

    def test_the_verbs_set_and_clear_the_role_s_own_marker(self):
        self.assertEqual(self.call("silence"), (0, "wagon-master: silent\n"))
        self.assertEqual((self.wm_state / silence.FILE).read_text(), "on\n")
        self.assertFalse((self.data / "hal2" / "farmer" / silence.FILE).exists(), "the farmer's is another file")
        self.assertEqual(self.call("unsilence"), (0, "wagon-master: not silent\n"))
        self.assertFalse((self.wm_state / silence.FILE).exists())

    def test_a_silenced_round_prints_one_table_line_with_joined_and_nothing_else(self):
        self.call("silence")
        code, out = self.call("tick")
        self.assertEqual((code, out), (0, "| wagon-master | no train | joined - |\n"))
        self.assertEqual(self.call("unsilence")[0], 0)
        self.assertIn("wagon-master tick (round)", self.call("tick")[1])

    def test_a_dry_run_and_json_stay_full(self):
        self.call("silence")
        self.assertIn("wagon-master tick (dry run)", self.call("tick", "--dry-run")[1])
        self.assertEqual(json.loads(self.call("tick", "--json")[1])["dry"], False)

    def test_one_line_per_train_naming_the_fields_that_joined(self):
        since = train_state.utc()
        self.train("formed", "yard", "started")
        r = {"done": []}
        self.assertEqual(wagon_master.silent_lines(str(self.main), r, since),
                         ["| wagon-master | train 07+09@" + AT + ": landing | joined 07, 09, yard |"])
        self.train("landed")
        self.train("formed", name="11@" + AT)
        lines = wagon_master.silent_lines(str(self.main), r, since)
        self.assertEqual([x.split(" | ")[1].split(": ")[1] for x in lines], ["in the barn", "formed"])
        self.assertTrue(all(x.count("\n") == 0 and "joined" in x for x in lines))
        self.assertEqual(wagon_master.silent_lines(str(self.main), r, "9999-01-01T00:00:00Z"),
                         ["| wagon-master | train 11@" + AT + ": formed | joined 07, 09 |"], "the standing one stays")

    def test_a_round_that_cannot_run_is_one_line_too(self):
        self.assertEqual(wagon_master.silent_lines(str(self.main), {"problem": "not the field\nsecond"}, ""),
                         ["| wagon-master | problem: not the field second | joined - |"])


if __name__ == "__main__":
    unittest.main()
