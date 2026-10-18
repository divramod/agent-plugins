"""design.py end to end in a scratch repository (hal2 plan 0364): new, render, list, a spec-only folder."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "design.py"


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".git").mkdir()
        self.folder = self.root / "plans" / "0050-search"
        self.folder.mkdir(parents=True)
        (self.folder / "spec.md").write_text("# Spec 0050: full text search\n")
        (self.root / "plans" / "CURRENT_PLAN").write_text("0050-search\n")

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args, cwd=None):
        return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=cwd or self.root,
                              capture_output=True, text=True)

    def test_new_render_list_in_a_spec_only_folder(self):
        made = self.run_cli("new", "search", "gui", "--title", "results page", "--json")
        self.assertEqual(made.returncode, 0, made.stderr)
        meta = json.loads(made.stdout)
        self.assertEqual(meta["id"], "search/gui/v1")
        Path(meta["path"], "screen.html").write_text("<h1>results</h1>")
        again = self.run_cli("new", "search", "gui")
        self.assertIn("started from v1: screen.html", again.stdout)
        shown = self.run_cli("render")
        self.assertEqual(shown.returncode, 0, shown.stderr)
        page = (self.folder / "design.html").read_text()
        self.assertIn("plan 0050 full text search - design", page)
        self.assertFalse((self.folder / "plan.md").exists())
        listed = json.loads(self.run_cli("list", "--json").stdout)
        self.assertEqual([d["id"] for d in listed["designs"]], ["search/gui/v1", "search/gui/v2"])
        self.assertEqual([d["latest"] for d in listed["designs"]], [False, True])
        self.assertEqual(listed["designs"][1]["files"], ["screen.html"])
        self.assertEqual(listed["plan"]["name"], "full text search")

    def test_plan_option_and_subfolder_cwd(self):
        other = self.root / "plans" / "0051-other"
        other.mkdir()
        sub = self.root / "code"
        sub.mkdir()
        made = self.run_cli("new", "x", "flow", "--plan", "51", cwd=sub)
        self.assertEqual(made.returncode, 0, made.stderr)
        self.assertTrue((other / "design" / "x" / "flow" / "v1" / "meta.json").is_file())
        out = self.root / "out.html"
        self.assertEqual(self.run_cli("render", "--plan", "0051-other", "--out", str(out)).returncode, 0)
        self.assertIn("plan 0051 other - design", out.read_text())

    def test_errors_exit_1_with_a_message(self):
        bad = self.run_cli("new", "Bad Name", "gui")
        self.assertEqual(bad.returncode, 1)
        self.assertIn("kebab-case", bad.stderr)
        missing = self.run_cli("list", "--plan", "99")
        self.assertEqual(missing.returncode, 1)
        self.assertIn("no plan folder", missing.stderr)

    def test_list_text(self):
        self.run_cli("new", "search", "erd", "--title", "index tables")
        out = self.run_cli("list").stdout
        self.assertIn("search/erd/v1", out)
        self.assertIn("open", out)

    def test_status_and_accepted_json(self):
        self.run_cli("new", "search", "gui", "--title", "results page")
        self.run_cli("new", "search", "gui")
        none = json.loads(self.run_cli("accepted", "--json").stdout)
        self.assertEqual(none["accepted"], [])
        state = self.folder / "design" / "state.json"
        state.write_text(json.dumps({"schema": 1, "designs": {"search/gui/v1": {"accepted": True, "comments": [
            {"at": "2026-10-18T10:00:00Z", "by": "user", "text": "wider", "anchor": "screen.html"}]}}}))
        status = json.loads(self.run_cli("status", "--json").stdout)
        kind = status["feats"][0]["kinds"][0]
        self.assertEqual((kind["accepted"], kind["latest"]), ("search/gui/v1", "search/gui/v2"))
        self.assertEqual(kind["versions"][0]["comments"][0]["text"], "wider")
        self.assertEqual(status["counts"], {"designs": 2, "accepted": 1, "comments": 1})
        found = json.loads(self.run_cli("accepted", "--json").stdout)["accepted"]
        self.assertEqual([(a["id"], a["superseded"]) for a in found], [("search/gui/v1", True)])
        text = self.run_cli("status").stdout
        self.assertIn("accepted search/gui/v1 (latest search/gui/v2)", text)
        self.assertIn("[screen.html]", text)
        self.assertIn("search/gui/v1 (superseded)", self.run_cli("accepted").stdout)

    def test_serve_refuses_another_host(self):
        out = self.run_cli("serve", "--host", "0.0.0.0")
        self.assertEqual(out.returncode, 1)
        self.assertIn("refusing host", out.stderr)


if __name__ == "__main__":
    unittest.main()
