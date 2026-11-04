"""Tests of checks/network.py with a fake `hal2-cli-machine` (a script printing a status document), run from the
scripts folder: python3 checks/test_network.py"""
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CHECK = os.path.join(HERE, "network.py")

FAKE = """#!/usr/bin/env python3
import os, sys
assert sys.argv[1:] == ["net", "status", "--json"], sys.argv
code = int(os.environ.get("FAKE_EXIT", "0"))
print(open(os.environ["FAKE_DOC"]).read())
sys.exit(code)
"""


def episode(since, away, until=None, check="dns"):
    return {"since": since, "check": check, "title": "DNS" if check == "dns" else "GitHub HTTPS",
            "detail": "github.com does not resolve", "until": until, "away": away}


class NetworkCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fake = os.path.join(self.tmp.name, "fake-machine")
        with open(self.fake, "w") as fh:
            fh.write(FAKE)
        os.chmod(self.fake, os.stat(self.fake).st_mode | stat.S_IEXEC)
        self.doc_path = os.path.join(self.tmp.name, "doc.json")

    def tearDown(self):
        self.tmp.cleanup()

    def run_check(self, doc, exit_code=0, cli=None):
        with open(self.doc_path, "w") as fh:
            fh.write(json.dumps(doc) if isinstance(doc, dict) else doc)
        env = dict(os.environ, LOOKOUT_NETWORK_CLI=cli or self.fake, FAKE_DOC=self.doc_path, FAKE_EXIT=str(exit_code))
        done = subprocess.run([sys.executable, CHECK], capture_output=True, text=True, env=env, timeout=30)
        lines = [json.loads(line) for line in done.stdout.splitlines() if line.strip()]
        return done.returncode, lines, done.stderr

    def doc(self, episodes, stale=False):
        return {"schema": 1, "action": "status", "node": "t460p", "ok": not episodes, "stale": stale,
                "checked_at": "2026-11-03T08:05:00Z", "checks": [], "episodes": episodes}

    def test_only_away_stretches_are_found_with_stable_ids(self):
        code, lines, _ = self.run_check(self.doc([
            episode("2026-11-02T10:00:00Z", False, "2026-11-02T10:10:00Z"),
            episode("2026-11-03T08:00:00Z", True),
            episode("2026-11-03T09:00:00Z", None),
        ]))
        self.assertEqual(code, 10)
        self.assertEqual([l["id"] for l in lines], ["network-t460p-2026-11-03T08:00:00Z-red"])
        self.assertIn("t460p: DNS fails", lines[0]["summary"])

    def test_an_ended_away_stretch_also_reports_its_recovery(self):
        code, lines, _ = self.run_check(self.doc([episode("2026-11-03T08:00:00Z", True, "2026-11-03T08:20:00Z")]))
        self.assertEqual(code, 10)
        self.assertEqual([l["id"].rsplit("-", 1)[1] for l in lines], ["red", "recovered"])
        self.assertTrue(all(len(l["summary"]) <= 200 for l in lines))

    def test_nothing_away_is_quiet_and_stale_is_not_checkable(self):
        self.assertEqual(self.run_check(self.doc([]))[0], 0)
        code, _, err = self.run_check(self.doc([], stale=True))
        self.assertEqual(code, 75)
        self.assertIn("stale", err)

    def test_a_missing_cli_is_not_checkable_and_bad_output_broken(self):
        self.assertEqual(self.run_check(self.doc([]), cli=os.path.join(self.tmp.name, "nope"))[0], 75)
        self.assertEqual(self.run_check("not json")[0], 1)
        self.assertEqual(self.run_check(dict(self.doc([]), schema=2))[0], 1)
        self.assertEqual(self.run_check(self.doc([]), exit_code=1)[0], 1)


if __name__ == "__main__":
    unittest.main()
