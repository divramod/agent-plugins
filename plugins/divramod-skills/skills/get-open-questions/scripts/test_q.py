"""q.py finds the session's question store and prints its entries in the Q form."""
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, next(str(_p / "scripts") for _p in Path(__file__).resolve().parents if (_p / ".claude-plugin").is_dir()))
from skillpath import repo_root, sibling  # noqa: E402  (the skills unit's scripts/, plan 0360 D20)
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(sibling("handoff") / "scripts"))
import qform  # noqa: E402  (handoff's: the one Q form, D9)

SCRIPT = Path(__file__).resolve().parent / "q.py"
NO_CLI = "/nonexistent/hal2-cli-plans"  # q.py then prints through its own parser

# Q31 and Q32 of plan 0263 as 08 wrote them (e43448cdc): every option inline in the question, verbatim.
INLINE = r'''
## Q31 · 2026-10-14 · agent · open

**Q:** The CI watcher (the small service that starts the Hetzner servers and the Azure Windows machine when a job waits and parks them after a minute without work, D67) is finished and merged into branch 08 (bf446d0c7, 184 tests green; nothing has run against Hetzner, Azure or GitHub yet). D80 keeps its deploy to the production server (hal9k.app, beside the hub and the download server) for you to allow. Until it runs there, the pipelines keep their own wake and park jobs. May it be deployed? a) (Recommended) Yes, once branch 08 is on main and the watcher's image builds green: I prepare the deploy, it goes out with wt 02's next production deploy, and its first real start and park are watched before the pipelines' own wake and park jobs are removed. b) Yes, but as a deploy of its own right after branch 08 has landed, not waiting for wt 02's next deploy: sooner, one more production deploy. c) Not yet: the watcher stays undeployed, the pipelines keep their wake and park jobs, and the row that removes them waits.

## Q32 · 2026-10-14 · agent · open

**Q:** The merge queue (one landing at a time) used to stay held until every job of a landing's run had ended, including the deliveries and publishes after the merge: one landing held it 48 minutes after its merge. Since row 85 (633cc8694, on branch 08) a landing frees the queue as soon as its merge to main is green; the jobs after it run on, are never cancelled, and a check run still holds its place to its end. This narrows your "strictly one run at a time" of 2026-10-06 and D129 ("we cannot loose runs"). Keep it? a) (Recommended) Yes: the next landing starts while the previous one's deliveries finish; no run is lost or cancelled, landings wait minutes instead of up to 48. b) Yes, but only for deliveries and tags; publishes still hold the queue: slower, safer for publishes that share a runner. c) No: back to holding the queue until every job has ended, row 85 reverted.
'''
STORE = """---
type: Questions
---

# Questions and answers

<!-- ## Q9 · 2026-01-01 · agent · open  (the head comment shows the format; it is no entry) -->

## Q1 · 2026-10-07 · agent · answered 2026-10-08

**Q:** Windows code signing?
  a) (Recommended) unsigned for now — fast
  b) a certificate — costs money
  c) later — nothing now
**A:** "unsigned for now"
**Decision:** D1

## Q2 · 2026-10-09 · user · open

**Q:** "Tell me if the install worked"

## Q3 · 2026-10-09 · agent · open

**Q:** Which one?
  a) (Recommended) this — x
  b) that — y
  c) none — z

## Q4 · 2026-10-09 · agent · dropped 2026-10-10

**Q:** May it land itself?
**A:** no longer needed
"""


class Base(unittest.TestCase):
    """A checkout with plan 0003-x and the helpers to run q.py in it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        (self.root / ".git").mkdir()
        (self.root / "plans" / "0003-x").mkdir(parents=True)
        (self.root / "plans" / "0003-x" / "plan.md").write_text("# Plan 0003: x\n")

    def tearDown(self):
        self.tmp.cleanup()

    def q(self, *args, cwd=None, cli=NO_CLI):
        env = {**os.environ, "HAL2_CLI_PLANS": cli}
        return subprocess.run(["python3", str(SCRIPT), *args], cwd=cwd or self.root, text=True, capture_output=True, env=env)

    def plan_store(self, text=STORE):
        (self.root / "plans" / "CURRENT_PLAN").write_text("0003-x\n")
        (self.root / "plans" / "0003-x" / "questions.md").write_text(text)


class Q(Base):
    def test_the_store_is_the_current_plans_questions(self):
        self.plan_store()
        self.assertEqual(self.q("--path").stdout.strip(), "plans/0003-x/questions.md")

    def test_current_plan_may_sit_in_the_git_dir_only(self):
        (self.root / ".git" / "hal").mkdir()
        (self.root / ".git" / "hal" / "CURRENT_PLAN").write_text("0003-x\n")
        self.assertEqual(self.q("--path").stdout.strip(), "plans/0003-x/questions.md")

    def test_current_plan_may_hold_a_path(self):
        (self.root / "plans" / "CURRENT_PLAN").write_text("plans/0003-x/\n")
        self.assertEqual(self.q("--path").stdout.strip(), "plans/0003-x/questions.md")

    def test_the_store_is_the_plan_the_handoff_links_when_current_plan_names_a_task(self):
        (self.root / "plans" / "CURRENT_PLAN").write_text("fix-login\n")
        (self.root / "HANDOFF.md").write_text("[x](plans/0003-x/plan.md): 1/2\n")
        self.assertEqual(self.q("--path").stdout.strip(), "plans/0003-x/questions.md")

    def test_without_a_plan_the_store_is_the_root_questions_file(self):
        (self.root / "plans" / "CURRENT_PLAN").write_text("fix-login\n")
        self.assertEqual(self.q("--path").stdout.strip(), "QUESTIONS.md")
        (self.root / "QUESTIONS.md").write_text(STORE)
        self.assertIn("2 open questions (QUESTIONS.md)", self.q().stdout)

    def test_open_prints_the_entries_as_they_stand_in_the_q_form(self):
        self.plan_store()
        out = self.q()
        self.assertEqual(out.returncode, 0)
        self.assertEqual(out.stdout, "2 open questions (plans/0003-x/questions.md)\n\n"
                         'Q2: "Tell me if the install worked"\n\n'
                         "Q3: Which one?\n  a) (Recommended) this — x\n  b) that — y\n  c) none — z\n")

    def test_answered_follows_each_entry_with_its_answer(self):
        self.plan_store()
        out = self.q("a").stdout
        self.assertEqual(out, "1 answered question (plans/0003-x/questions.md)\n\n"
                         "Q1: Windows code signing?\n  a) (Recommended) unsigned for now — fast\n"
                         "  b) a certificate — costs money\n  c) later — nothing now\n"
                         'Answer (2026-10-08): "unsigned for now"\n')
        self.assertEqual(self.q("answered").stdout, out)

    def test_list_has_the_open_first_then_the_answered_and_dropped_by_number(self):
        self.plan_store()
        out = self.q("l").stdout
        self.assertTrue(out.startswith("4 questions, 2 open (plans/0003-x/questions.md)\n"))
        order = [ln.split(":")[0] for ln in out.splitlines() if ln.startswith("Q")]
        self.assertEqual(order, ["Q2", "Q3", "Q1", "Q4"])
        self.assertIn("Dropped (2026-10-10): no longer needed", out)
        self.assertEqual(self.q("list").stdout, out)

    def test_an_entry_without_options_gets_none_invented(self):
        self.plan_store()
        self.assertNotIn(" a) ", self.q().stdout.split("Q3")[0])

    def test_no_store_or_no_entries_is_one_line_and_exit_0(self):
        for mode, line in (("", "no open questions"), ("a", "no answered questions"), ("l", "no questions")):
            out = self.q(*([mode] if mode else []))
            self.assertEqual((out.returncode, out.stdout), (0, line + "\n"))
        self.plan_store(STORE.split("## Q1")[0])
        self.assertEqual(self.q().stdout, "no open questions\n")

    def test_only_answered_entries_print_no_open_questions(self):
        self.plan_store("## Q1 · 2026-10-07 · agent · answered 2026-10-08\n\n**Q:** x?\n**A:** y\n")
        self.assertEqual(self.q().stdout, "no open questions\n")

    def test_json_has_the_same_entries(self):
        self.plan_store()
        data = json.loads(self.q("l", "--json").stdout)
        self.assertEqual(data["store"], "plans/0003-x/questions.md")
        self.assertEqual([e["n"] for e in data["entries"]], [2, 3, 1, 4])
        self.assertEqual(data["entries"][1]["question"], "Which one?")
        self.assertEqual(data["entries"][1]["options"], ["(Recommended) this — x", "that — y", "none — z"])
        self.assertEqual(data["entries"][2]["date"], "2026-10-08")
        self.assertEqual([e["n"] for e in json.loads(self.q("--json").stdout)["entries"]], [2, 3])

    def test_a_broken_store_is_one_line_naming_the_file_and_exit_1(self):
        self.plan_store("## Q1 - today - open\n\n**Q:** x?\n")
        out = self.q()
        self.assertEqual(out.returncode, 1)
        self.assertEqual(len(out.stdout.splitlines()), 1)
        self.assertTrue(out.stdout.startswith("plans/0003-x/questions.md: heading does not match"))
        self.assertNotIn("Traceback", out.stderr)

    def test_a_duplicate_number_is_a_broken_store(self):
        self.plan_store(STORE + "\n## Q2 · 2026-10-09 · user · open\n\n**Q:** again?\n")
        out = self.q()
        self.assertEqual(out.returncode, 1)
        self.assertIn("Q2: the number is used twice", out.stdout)

    def test_repo_names_another_checkout_and_a_subfolder_finds_its_own(self):
        self.plan_store()
        other = Path(tempfile.mkdtemp())
        try:
            self.assertEqual(self.q("--path", "--repo", str(self.root), cwd=other).stdout.strip(),
                             "plans/0003-x/questions.md")
            self.assertEqual(self.q("--path", cwd=self.root / "plans").stdout.strip(), "plans/0003-x/questions.md")
        finally:
            other.rmdir()


class InlineOptions(Base):
    """Q31 and Q32 as 08 wrote them put a) b) c) inline: the fallback prints each on its own line and warns."""

    def test_the_fallback_splits_the_inline_options_onto_their_own_lines(self):
        self.plan_store(INLINE)
        out = self.q().stdout
        q31 = out.split("Q32:")[0].split("Q31:")[1].split("\n")
        self.assertTrue(q31[0].endswith("May it be deployed?"), q31[0])
        self.assertEqual([ln[:17] for ln in q31[1:4]],
                         ["  a) (Recommended", "  b) Yes, but as ", "  c) Not yet: the"])
        self.assertIn("  c) No: back to holding the queue until every job has ended, row 85 reverted.", out)
        self.assertNotIn("a) (Recommended) Yes, once branch 08 is on main and the watcher's image builds green: I "
                         "prepare the deploy, it goes out with wt 02's next production deploy, and its first real start "
                         "and park are watched before the pipelines' own wake and park jobs are removed. b)", out)

    def test_the_fallback_warns_once_after_the_list(self):
        self.plan_store(INLINE)
        lines = self.q().stdout.splitlines()
        self.assertEqual(lines[-1], "warning: Q31, Q32: " + qform.INLINE)
        self.assertEqual(sum(ln.startswith("warning:") for ln in lines), 1)

    def test_a_well_formed_store_has_no_warning(self):
        self.plan_store()
        self.assertNotIn("warning", self.q("l").stdout)

    def test_an_open_agent_entry_with_two_options_is_warned(self):
        self.plan_store("## Q1 · 2026-10-09 · agent · open\n\n**Q:** Which?\n  a) (Recommended) x\n  b) y\n")
        self.assertEqual(self.q().stdout.splitlines()[-1], "warning: Q1: 2 option lines; the Q form needs "
                         "exactly three, a) b) c), each on its own line")

    def test_a_question_that_mentions_a_once_is_not_torn(self):
        text = "## Q5 · 2026-10-14 · agent · open\n\n**Q:** Does step a) of the plan hold? Say so or not.\n"
        self.plan_store(text)
        out = self.q().stdout
        self.assertIn("Q5: Does step a) of the plan hold? Say so or not.\n", out)
        self.assertNotIn("\n  a) ", out)
        self.assertEqual(qform.split_inline("Go? a) x b) y c) z")[1], ["x", "y", "z"])
        for text in ("a) x b) y c) z", "Go? b) y a) x c) z", "Go? a) x b) y c) z or a) again", "Go? a) x b) y"):
            self.assertIsNone(qform.split_inline(text), text)

    def test_json_is_the_same_data_through_the_fallback(self):
        self.plan_store(INLINE)
        data = json.loads(self.q("--json").stdout)
        self.assertEqual([e["n"] for e in data["entries"]], [31, 32])
        q31 = data["entries"][0]  # the CLI's keys: question without options, options without prefix, inline
        self.assertEqual(q31["state"], "open")
        self.assertTrue(q31["question"].endswith("May it be deployed?") and q31["inline"] and "date" not in q31)
        self.assertEqual(len(q31["options"]), 3)
        self.assertTrue(q31["options"][0].startswith("(Recommended) Yes, once branch 08"))
        self.assertEqual((q31["answer"], q31["decision"]), ("", None))
        self.assertEqual([p["n"] for p in data["problems"]], [31, 32])

    def test_json_of_the_answered_has_date_answer_and_decision(self):
        self.plan_store()
        e = json.loads(self.q("a", "--json").stdout)["entries"][0]
        self.assertEqual((e["n"], e["state"], e["date"], e["answer"], e["decision"]),
                         (1, "answered", "2026-10-08", '"unsigned for now"', 1))
        self.assertEqual((e["question"], e["inline"], len(e["options"])), ("Windows code signing?", False, 3))
        self.assertEqual(e["options"][1], "b) a certificate — costs money".split(") ", 1)[1])


class ViaCli(Base):
    """q.py prints what `hal2-cli-plans questions list` prints (a stub script stands in for the built CLI)."""

    def stub(self, stdout="", problems=(), entries=(), code=0):
        """A script that answers `list` (stdout, exit code), `list --all --json` (the entries) and `check --json`
        (the problems, exit 1 when there are any); every call's arguments are appended to `stub-cli.args`."""
        path = self.root / "stub-cli"
        check = json.dumps({"store": "x", "problems": list(problems)})
        everything = json.dumps({"store": "x", "mode": "all", "entries": list(entries), "problems": list(problems)})
        path.write_text(f"""#!/bin/sh
echo "$@" >> "$0.args"
case "$*" in
  *check*) cat <<'EOT'
{check}
EOT
    exit {1 if problems else 0} ;;
  *"list --all --json"*) cat <<'EOT'
{everything}
EOT
    exit 0 ;;
esac
cat <<'EOT'
{stdout.rstrip(chr(10))}
EOT
exit {code}
""")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return str(path)

    def args(self):
        return (self.root / "stub-cli.args").read_text().splitlines()[0]

    def test_it_prints_the_cli_list_as_it_is(self):
        self.plan_store()
        cli = self.stub("1 open question (plans/0003-x/questions.md)\n\nQ3: Which?\n  a) x\n")
        out = self.q("l", cli=cli)
        self.assertEqual(out.stdout, "1 open question (plans/0003-x/questions.md)\n\nQ3: Which?\n  a) x\n")
        self.assertEqual(self.args(), "questions list --all --markdown --store plans/0003-x/questions.md")
        (self.root / "stub-cli.args").unlink()
        self.q("a", cli=cli)
        self.assertEqual(self.args(), "questions list --answered --markdown --store plans/0003-x/questions.md")

    def test_json_goes_through_the_clis_json(self):
        self.plan_store()
        cli = self.stub('{"store": "x", "entries": []}\n')
        self.assertEqual(json.loads(self.q("--json", cli=cli).stdout), {"store": "x", "entries": []})
        self.assertEqual(self.args(), "questions list --open --json --store plans/0003-x/questions.md")

    def open_agent(self, n, **more):
        return {"n": n, "asked": "2026-10-14", "by": "agent", "state": "open", "question": "Go?", "options": [],
                "answer": "", "decision": None, "inline": True, **more}

    def test_the_clis_form_problems_become_one_warning_line_after_the_list(self):
        self.plan_store(INLINE)
        why = qform.INLINE
        problems = [{"n": 31, "message": why}, {"n": 32, "message": why}]
        cli = self.stub("2 open questions (x)\n\nQ31: a\n  a) x\n", problems, [self.open_agent(31), self.open_agent(32)])
        lines = self.q(cli=cli).stdout.splitlines()
        self.assertEqual(lines[-1], f"warning: Q31, Q32: {why}")
        self.assertEqual(sum(ln.startswith("warning:") for ln in lines), 1)

    def test_a_problem_the_entries_do_not_explain_as_a_form_problem_breaks_the_store(self):
        self.plan_store()
        cases = {
            "a heading that did not parse": ([{"n": None, "message": "heading does not match `## Q<n>`: ## Q1 - today"}], []),
            "a number used twice": ([{"n": 2, "message": "Q2: the number is used twice"}],
                                    [self.open_agent(2), self.open_agent(2)]),
            "an open entry with an answer": ([{"n": 2, "message": "open, but it has an answer"}],
                                             [self.open_agent(2, answer="yes")]),
            "an entry without question": ([{"n": 2, "message": "no **Q:** line"}], [self.open_agent(2, question="")]),
            "a user entry": ([{"n": 2, "message": "x"}], [self.open_agent(2, by="user")]),
        }
        for name, (problems, entries) in cases.items():
            out = self.q(cli=self.stub("2 open questions (x)\n", problems, entries))
            self.assertEqual((out.returncode, out.stdout),
                             (1, f"plans/0003-x/questions.md: {problems[0]['message']}\n"), name)

    def test_a_failing_cli_falls_back_to_the_own_parser(self):
        self.plan_store()
        out = self.q(cli=self.stub("", code=3))
        self.assertTrue(out.stdout.startswith("2 open questions (plans/0003-x/questions.md)\n"), out.stdout)

    def test_a_check_that_cannot_be_read_falls_back_too(self):
        self.plan_store()
        path = Path(self.stub("from cli\n"))
        path.write_text(path.read_text().replace('{"store": "x", "problems": []}', "not json"))
        out = self.q(cli=str(path))
        self.assertTrue(out.stdout.startswith("2 open questions (plans/0003-x/questions.md)\n"), out.stdout)

    def test_the_cli_on_path_is_used_when_the_variable_is_unset(self):
        self.plan_store()
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        cli = Path(self.stub("from path\n"))
        (bin_dir / "hal2-cli-plans").write_text(cli.read_text())
        (bin_dir / "hal2-cli-plans").chmod(0o755)
        env = {k: v for k, v in os.environ.items() if k != "HAL2_CLI_PLANS"}
        env["PATH"] = f"{bin_dir}:{env['PATH']}"
        out = subprocess.run(["python3", str(SCRIPT)], cwd=self.root, text=True, capture_output=True, env=env)
        self.assertEqual(out.stdout, "from path\n")


class TollmanSlot(Base):
    """In the tollman's own field `tollman-<repo>` the store is always its root QUESTIONS.md (plan 0360 step 8, D9):
    its CURRENT_PLAN names a train's cars (`yard + <plan>`), whose merged plan folders are no store of the tollman's."""

    def test_the_tollman_field_s_store_is_its_root_file_whatever_its_current_plan_names(self):
        field = self.root / "tollman-x"
        (field / ".git").mkdir(parents=True)
        (field / "plans" / "0003-x").mkdir(parents=True)
        (field / "plans" / "0003-x" / "plan.md").write_text("# Plan 0003: x\n")
        (field / "plans" / "0003-x" / "questions.md").write_text(STORE)
        for current in ("0003-x\n", "yard + 0003-x\n"):
            (field / "plans" / "CURRENT_PLAN").write_text(current)
            self.assertEqual(self.q("--path", cwd=field).stdout.strip(), "QUESTIONS.md", current)
        self.assertEqual(self.q(cwd=field).stdout.strip(), "no open questions")
        self.plan_store()
        self.assertEqual(self.q("--path").stdout.strip(), "plans/0003-x/questions.md", "elsewhere the plan's")


class FarmerSlot(unittest.TestCase):
    """In the farmer's own worktree `farmer-<repo>` /q is the farmer's joined list (plan 0268, D14)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name).resolve()
        self.state = base / "state"
        (self.state / "farmer-x").mkdir(parents=True)
        (self.state / "farmer-x" / "questions.jsonl").write_text(json.dumps(
            {"schema": 1, "at": "2026-10-13T10:00:00Z", "n": 1, "slot": "05", "text": "Q1: Land it?", "waits": "the landing",
             "state": "open", "asked": "2026-10-13T10:00:00Z", "answer": "", "closed": ""}) + "\n")
        self.root = base / "farmer-x"
        self.root.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        (self.root / "QUESTIONS.md").write_text("## Q2 · 2026-10-09 · user · open\n\n**Q:** \"Own store?\"\n")

    def run_q(self, *args, root=None):
        env = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", ""), "FARMER_DIR": str(self.state),
               "HAL2_CLI_PLANS": NO_CLI}
        return subprocess.run(["python3", str(SCRIPT), *args], cwd=root or self.root, text=True, capture_output=True, env=env)

    def test_the_farmer_slot_prints_the_joined_list(self):
        out = self.run_q()
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue(out.stdout.startswith("2 open questions in 2 worktrees\n"), out.stdout)
        self.assertIn("**05** (the farmer's list)\nQ1: Land it?\nWaits for: the landing", out.stdout)
        self.assertIn("**main** (QUESTIONS.md)\nQ2: \"Own store?\"", out.stdout)
        self.assertEqual(json.loads(self.run_q("--json").stdout)["open"], 2)
        self.assertEqual(self.run_q("--path").stdout.strip(), "QUESTIONS.md")  # --path still names the own store

    def test_another_checkout_keeps_its_own_store(self):
        other = self.root.parent / "03"
        other.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=other, check=True)
        (other / "QUESTIONS.md").write_text("## Q7 · 2026-10-09 · user · open\n\n**Q:** \"Mine?\"\n")
        self.assertEqual(self.run_q(root=other).stdout, "1 open question (QUESTIONS.md)\n\nQ7: \"Mine?\"\n")


if __name__ == "__main__":
    unittest.main()
