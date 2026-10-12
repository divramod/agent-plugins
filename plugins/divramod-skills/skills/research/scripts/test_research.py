"""research.py: scaffolding from the template, the front matter subset parser, check, set, log; the workflow's
control flow through workflow_harness.mjs; every doc `new` writes passes hal2's records checker (hal2 plan 0214
step 6: `$HAL2_CLI_RECORDS`, else `hal2-cli-records` on PATH; those tests are skipped without it)."""
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import checker  # noqa: E402
import research  # noqa: E402

SCRIPT = HERE / "research.py"
ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
       "GIT_COMMITTER_EMAIL": "t@t"}
TODAY = dt.date.today().isoformat()
needs_checker = unittest.skipUnless(checker.binary(), f"{checker.NAME} is not installed and ${checker.ENV} is unset")


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, env=ENV, text=True, capture_output=True, check=True).stdout


class TemplateTest(unittest.TestCase):
    def test_template_h2s_and_keys_match_the_script(self):
        text = research.TEMPLATE.read_text()
        self.assertEqual([h for _, h in research.headings(text.split("\n"), 2)], research.ORDER)
        filled = text.format(id=1, number="0001", title="t", description="d", question="q", kind="survey",
                             date="2026-01-01",
                             revisit="2026-07-01", author="a", origin="user request", plan="")
        meta = research.parse_yaml(research.split_doc(filled)[0])
        self.assertEqual(list(meta), research.KEYS)
        self.assertEqual(meta["claims"], {"total": 0, "verified": 0, "disputed": 0})
        self.assertIsNone(meta["plan"])
        self.assertEqual(meta["status"], "planned")


class YamlTest(unittest.TestCase):
    def test_subset(self):
        lines = [
            "title: \"A: quoted\"",
            "question: >-",
            "  first line",
            "  second line",
            "status: done  # a comment",
            "origin: shotfiles/x.md#3",
            "related: [2, 8, 'x y']",
            "claims: {total: 3, verified: 1, disputed: 0}",
            "tags:",
            "  - a",
            "  - b",
            "decision:",
            "literal: |",
            "  keep",
            "  lines",
        ]
        meta = research.parse_yaml(lines)
        self.assertEqual(meta["title"], "A: quoted")
        self.assertEqual(meta["question"], "first line second line")
        self.assertEqual(meta["status"], "done")
        self.assertEqual(meta["origin"], "shotfiles/x.md#3")
        self.assertEqual(meta["related"], [2, 8, "x y"])
        self.assertEqual(meta["claims"], {"total": 3, "verified": 1, "disputed": 0})
        self.assertEqual(meta["tags"], ["a", "b"])
        self.assertIsNone(meta["decision"])
        self.assertEqual(meta["literal"], "keep\nlines")

    def test_rejects_what_yaml_would_misread(self):
        for bad in (["title: a: b"], ["x: 1", "x: 2"], ["  indented: 1"], ["nocolon"]):
            with self.assertRaises(research.ResearchError, msg=bad):
                research.parse_yaml(bad)

    def test_dump_round_trips(self):
        for value in ["plain", "a: b", "#x", "12", "", [1, "a b"], {"total": 2}]:
            line = research.dump_field("k", value)[0]
            self.assertEqual(research.parse_yaml([line])["k"], value)


class RepoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "repo"
        self.root.mkdir()
        git(self.root, "init", "-q", "-b", "main")
        git(self.root, "commit", "-q", "--allow-empty", "-m", "init")

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=self.root, env=ENV, text=True,
                              capture_output=True)

    def cli_json(self, *args):
        result = self.run_cli(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def new(self, title="Pick a parser", *extra):
        return self.cli_json("new", title, *extra)

    def doc(self, slug):
        return self.root / "research" / slug / "research.md"

    def test_new_scaffolds_a_valid_doc_with_unique_numbers(self):
        first = self.new("Pick a parser: YAML or TOML?", "--question", "Which parser?", "--plan",
                         "plans/0003-research-x/plan.md", "--origin", "shotfiles/a.md#2", "--kind", "decision")
        self.assertEqual(first["slug"], "0001-pick-a-parser-yaml-or-toml")
        self.assertEqual(first["problems"], [])
        self.assertEqual(first["title"], "Pick a parser: YAML or TOML?")
        self.assertEqual(first["question"], "Which parser?")
        self.assertEqual(first["plan"], "plans/0003-research-x/plan.md")
        self.assertEqual(first["kind"], "decision")
        self.assertEqual(first["created"], TODAY)
        self.assertTrue(first["revisit"] > TODAY)
        self.assertIn("# Research 0001: Pick a parser: YAML or TOML?", self.doc(first["slug"]).read_text())
        (self.root / "research" / "0007-old").mkdir()
        self.assertEqual(self.new("Second")["number"], 8)
        self.assertEqual(self.run_cli("check").returncode, 1)  # 0007-old has no research.md

    def test_check_passes_and_reports_problems(self):
        slug = self.new()["slug"]
        ok = self.run_cli("check")
        self.assertEqual(ok.returncode, 0, ok.stdout)
        self.assertIn("1 research docs valid", ok.stdout)
        path = self.doc(slug)
        text = path.read_text()
        broken = (text.replace("id: 1\n", "id: 4\n").replace("kind: investigation", "kind: guess")
                  .replace("## Risks", "## Summary").replace("revisit: ", "revisit: soon #"))
        broken = broken.replace("## Log", "```\n## Answer\n```\n\n## Log")  # an H2 inside a fence is not a heading
        answer = broken.index("## Answer")
        method = broken.index("## Method")
        broken = broken[:answer] + broken[method:]  # drops Answer..Question and scope
        path.write_text(broken)
        out = self.run_cli("check").stdout
        for expected in ["id 4 is not the folder's number 1", "kind 'guess'", "unknown H2 `Summary`",
                         "required H2 `Answer` is missing", "`revisit` is not a YYYY-MM-DD date"]:
            self.assertIn(expected, out)
        self.assertNotIn("H2 `Answer` appears", out)

    def test_order_and_duplicates(self):
        slug = self.new()["slug"]
        text = self.doc(slug).read_text()
        swapped = text.replace("## Recommendation", "## TMP").replace("## Key findings", "## Recommendation")
        self.doc(slug).write_text(swapped.replace("## TMP", "## Key findings"))
        shutil.copytree(self.root / "research" / slug, self.root / "research" / "0001-twin")
        out = self.run_cli("check").stdout
        self.assertIn("not in the template's order", out)
        self.assertIn("0001 is used by: 0001-pick-a-parser, 0001-twin", out)

    def test_done_needs_a_real_answer_and_decided_a_record(self):
        slug = self.new()["slug"]
        self.assertEqual(self.run_cli("set", "1", "status", "decided").returncode, 0)
        out = self.run_cli("check").stdout
        self.assertIn("placeholder", out)
        self.assertIn("names no record", out)

    def test_set_updates_fields_keeps_comments_and_bumps_updated(self):
        slug = self.new()["slug"]
        path = self.doc(slug)
        path.write_text(path.read_text().replace(f"updated: {TODAY}", "updated: 2020-01-01"))
        doc = self.cli_json("set", "0001", "status", "done")
        self.assertEqual((doc["status"], doc["updated"]), ("done", TODAY))
        self.assertIn("status: done  # planned | researching", path.read_text())
        self.assertEqual(self.cli_json("set", "1", "tags", "a, b c")["tags"], ["a", "b c"])
        self.assertEqual(self.cli_json("set", "1", "related", "[3, 4]")["related"], [3, 4])
        self.assertEqual(self.cli_json("set", "1", "claims", "total: 5, verified: 4")["claims"],
                         {"total": 5, "verified": 4, "disputed": 0})
        answer = "Use YAML front matter: it parses everywhere. " * 4
        doc = self.cli_json("set", slug, "answer", answer)
        self.assertEqual(doc["answer"], answer.strip())
        self.assertIn("answer: >-\n  Use YAML", path.read_text())
        self.assertEqual(self.cli_json("set", "1", "title", "A: b")["title"], "A: b")
        self.assertEqual(self.run_cli("set", "1", "status", "finished").returncode, 1)
        self.assertEqual(self.run_cli("set", "1", "nope", "x").returncode, 1)
        self.assertEqual(self.run_cli("set", "9", "status", "done").returncode, 1)

    def test_log_appends_a_dated_entry(self):
        slug = self.new()["slug"]
        path = self.doc(slug)
        path.write_text(path.read_text().replace(f"updated: {TODAY}", "updated: 2020-01-01"))
        doc = self.cli_json("log", "1", "verification pass re-run: 4/5 verified")
        self.assertEqual(doc["updated"], TODAY)
        text = path.read_text()
        self.assertTrue(text.rstrip().endswith(f"- {TODAY}: verification pass re-run: 4/5 verified"), text[-200:])
        self.assertEqual(self.run_cli("check").returncode, 0)

    def test_list_and_status(self):
        self.new("One")
        self.new("Two")
        docs = self.cli_json("list")
        self.assertEqual([d["number"] for d in docs], [1, 2])
        self.assertEqual(docs[0]["missing"], [])
        self.assertIn("Answer", docs[0]["sections"])
        self.assertEqual(self.cli_json("status", "0002-two")["title"], "Two")

    def test_new_writes_the_record_envelope_and_a_legacy_doc_needs_none(self):
        long = "Which of the many parsers " + "and many more " * 20 + "fits? And a second sentence."
        doc = self.new("Pick: a parser", "--question", long)
        self.assertEqual((doc["type"], doc["schema"], doc["problems"]), ("Research", 1, []))
        self.assertLessEqual(len(doc["description"]), 200)
        self.assertEqual(self.new('"Quoted" # title')["description"], '"Quoted" # title')
        path = self.doc(doc["slug"])
        legacy = "\n".join(line for line in path.read_text().split("\n")
                           if not line.startswith(("type:", "schema:", "description:")))
        path.write_text(legacy)
        self.assertEqual(self.cli_json("status", "1")["problems"], [])
        path.write_text(legacy.replace("---\n", "---\ntype: Research\n", 1))
        self.assertIn("front matter: `schema` is missing", self.cli_json("status", "1")["problems"])

    @needs_checker
    def test_every_new_doc_passes_the_records_checker(self):
        self.new("Pick: a parser", "--question", "Which parser? Two sentences.", "--kind", "decision")
        self.new('"Quoted" # title [x]', "--plan", "plans/0003-research-x/plan.md", "--origin", "shotfiles/a.md#2")
        self.new("Plain")
        self.cli_json("log", "2", "verification pass")
        self.cli_json("set", "3", "status", "researching")
        out = subprocess.run([checker.binary(), "check", "--json", "--repo", str(self.root)], capture_output=True,
                             text=True)
        self.assertEqual(out.returncode, 0, out.stdout)
        self.assertEqual((json.loads(out.stdout)["valid"], json.loads(out.stdout)["problems"]), (3, []))
        result = self.run_cli("check")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotIn(checker.NOT_INSTALLED, result.stdout)

    @needs_checker
    def test_check_prints_the_checker_s_problems(self):
        path = self.doc(self.new()["slug"])
        path.write_text(path.read_text().replace("schema: 1", "schema: 2"))
        result = self.run_cli("check")
        self.assertEqual(result.returncode, 1)
        self.assertIn("research/0001-pick-a-parser/research.md: ", result.stdout)
        self.assertIn("(spec:", result.stdout)

    def test_without_the_checker_check_is_advisory(self):
        self.new()
        env = {**ENV, checker.ENV: str(self.root / "no-such-binary")}
        result = subprocess.run([sys.executable, str(SCRIPT), "check"], cwd=self.root, env=env, text=True,
                                capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(result.stdout.split("\n")[0], checker.NOT_INSTALLED)
        env = {k: v for k, v in ENV.items() if k != checker.ENV}
        env["PATH"] = "/usr/bin:/bin"  # git, never hal2-cli-records
        result = subprocess.run([sys.executable, str(SCRIPT), "check"], cwd=self.root, env=env, text=True,
                                capture_output=True)
        self.assertEqual((result.returncode, result.stdout.split("\n")[0]), (0, checker.NOT_INSTALLED))

    def test_stale_after_revisit(self):
        slug = self.new()["slug"]
        self.cli_json("set", "1", "status", "done")
        self.cli_json("set", "1", "revisit", "2000-01-01")
        self.assertTrue(self.cli_json("status", "1")["stale"])


@unittest.skipUnless(shutil.which("node"), "node is missing")
class WorkflowTest(unittest.TestCase):
    HARNESS = HERE / "workflow_harness.mjs"

    def run_harness(self, *args, scenario="normal"):
        result = subprocess.run(["node", str(self.HARNESS), *args], text=True, capture_output=True,
                                env={**os.environ, "SCENARIO": scenario})
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_script_compiles(self):
        self.assertIn("ok: syntax", self.run_harness("--check"))

    def test_verification_counts_sources_and_citation_check(self):
        out = json.loads(self.run_harness())
        result = out["result"]
        self.assertEqual(out["calls"], ["planner", "researcher-1", "researcher-2", "verifier-1", "verifier-2",
                                        "premortem", "report-writer"])
        self.assertEqual(result["counts"], {"total": 4, "verified": 2, "partly": 0, "disputed": 2, "unverified": 0})
        self.assertEqual([s["id"] for s in result["sources"]], ["S1", "S2"])  # a #fragment is the same source
        self.assertTrue(any("S9" in note for note in result["coverage"]))  # cited id backing no verified claim
        self.assertEqual(result["status"], "partial")

    def test_a_failed_researcher_is_reported_not_fatal(self):
        result = json.loads(self.run_harness(scenario="research-fails"))["result"]
        self.assertIn("sub-question 2 failed; not covered", result["coverage"])
        self.assertEqual(result["counts"]["total"], 2)


if __name__ == "__main__":
    unittest.main()
