import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

import halverse
import sources
import transcripts

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLE = os.path.join(HERE, "fixtures", "sources")


def line(text, when):
    return json.dumps({"type": "user", "timestamp": when.isoformat(), "message": {"role": "user", "content": text}})


class Learn(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        project = os.path.join(self.tmp.name, "projects", "-demo")
        os.makedirs(project)
        now = datetime.now(timezone.utc)
        rows = [line("please mtm the shots, one shot more, a screenshot", now - timedelta(hours=1)),
                line("bring it in and a todo list", now - timedelta(hours=2)),
                line("the VM slot", now - timedelta(days=1)),
                line("shot shot shot", now - timedelta(days=20)),
                json.dumps({"type": "user", "isSidechain": True, "timestamp": now.isoformat(),
                            "message": {"content": "mtm mtm mtm"}})]
        with open(os.path.join(project, "a.jsonl"), "w") as handle:
            handle.write("\n".join(rows) + "\n")
        self.env = {"HALVERSE_PROJECTS_ROOT": os.path.join(self.tmp.name, "projects"),
                    "HALVERSE_GLOSSARY": os.path.join(SAMPLE, "GLOSSARY.md"),
                    "HALVERSE_ONTOLOGY": os.path.join(SAMPLE, "ontology.md")}
        self.saved = {k: os.environ.get(k) for k in self.env}
        os.environ.update(self.env)

    def tearDown(self):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.tmp.cleanup()

    def run_cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = halverse.main(list(args))
        self.assertEqual(code, 0)
        return out.getvalue()

    def test_text_table_default_seven_days(self):
        out = self.run_cli("learn")
        self.assertIn("3 typed prompts of the last 7 days", out)
        self.assertIn("bring in", out)
        self.assertIn('ambiguous for field: "slot" 1', out)
        self.assertIn("practise: seed (for shot, 2 old uses), daybook (for daily to-do list, to-do list, 1 old use), bring in",
                      " ".join(out.split()))  # the line is wrapped at 100 columns

    def test_days_window(self):
        self.assertIn("4 typed prompts of the last 30 days", self.run_cli("learn", "--days", "30"))

    def test_json_has_rows_practise_and_the_warnings(self):
        data = json.loads(self.run_cli("learn", "--json"))
        rows = {r["new"]: r for r in data["rows"]}
        self.assertEqual((rows["seed"]["old_uses"], rows["bring in"]["old_uses"], rows["bring in"]["new_uses"]), (2, 1, 1))
        self.assertEqual(rows["bring in"]["example"][:6], "please")
        self.assertEqual([p["new"] for p in data["practise"]], ["seed", "daybook", "bring in"])
        self.assertEqual(data["messages"], 3)
        self.assertEqual(data["warnings"], [])

    def test_a_farm_word_without_a_pair_warns_at_run_time(self):
        path = os.path.join(self.tmp.name, "o.md")
        with open(path, "w") as handle:
            handle.write("| Farm word | Stands for | Status |\n|---|---|---|\n| scythe | cutting | in force |\n")
        os.environ["HALVERSE_ONTOLOGY"] = path
        self.assertIn('warning: farm word "scythe"', self.run_cli("learn"))
        self.assertEqual(len(json.loads(self.run_cli("learn", "--json"))["warnings"]), 1)

    def test_missing_source_files_still_print_the_table(self):
        os.environ["HALVERSE_GLOSSARY"] = os.path.join(self.tmp.name, "none.md")
        os.environ["HALVERSE_ONTOLOGY"] = os.path.join(self.tmp.name, "none2.md")
        self.assertIn("old word", self.run_cli("learn"))

    def test_script_runs_as_a_program_and_exits_zero(self):
        env = dict(os.environ)
        result = subprocess.run([sys.executable, os.path.join(HERE, "halverse.py"), "learn"], capture_output=True,
                                text=True, env=env, cwd=self.tmp.name)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("old word", result.stdout)

    def test_no_command_is_an_error(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            halverse.main([])


INNER = "HALVERSE_TESTS_INNER_RUN"


class NoLiveFiles(unittest.TestCase):
    """No test reads the user's own files (plan 0273 D7): they change daily outside the repository, so a test that
    read them could go red without a change here. `learn` reads them at call time and only warns."""

    def test_the_tests_pass_with_a_home_whose_files_are_nonsense(self):
        if os.environ.get(INNER):
            self.skipTest("the inner run of this test")
        with tempfile.TemporaryDirectory() as home:
            os.makedirs(os.path.join(home, ".claude", "projects", "-x"))
            for name in ("GLOSSARY.md", "HALVERSE-ONTOLOGY.md", "DICTATION.md", os.path.join("projects", "-x", "a.jsonl")):
                with open(os.path.join(home, ".claude", name), "w") as handle:
                    handle.write("no glossary, no table, no transcript\n")
            env = {k: v for k, v in os.environ.items() if not k.startswith(("HALVERSE_", "HAL2_"))}
            env.update({"HOME": home, "USERPROFILE": home, INNER: "1"})
            result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", HERE, "-p", "test_*.py"],
                                    capture_output=True, text=True, env=env, cwd=home)
        self.assertEqual(result.returncode, 0, result.stderr[-3000:])
        self.assertIn("skipped=1", result.stderr)  # the inner run of this test, nothing else


if __name__ == "__main__":
    unittest.main()
