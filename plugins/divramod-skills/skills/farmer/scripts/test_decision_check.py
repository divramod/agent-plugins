"""Skills plan 0008: a servant's `decision check <slot>` after its clear, answered as code from the farmer's log."""

import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import acks
import decision_check as dc
import decision_log
import farmer
import mtm_scan
from test_farmer import Repo, git

BUMPS = {"at": "2026-10-05T21:30:00", "kind": "decision", "slot": "12",
         "what": "version bumps: conventional commits, dependents get a patch bump",
         "note": 'user: "every lib or app, which changed, should also be version bumped"'}
RUNS = {"at": "2026-10-05T21:41:34", "kind": "decision", "slot": "12",
        "what": "delete all old GitHub Actions workflow runs",
        "note": 'user: "it should delete all the old workflow runs"'}
HANDOFF = {"at": "2026-10-05T22:04:13", "kind": "decision", "slot": "-",
           "what": "handoff skill: after clear-and-continue a servant asks the farmer 'did I forget a decision?'; "
                   "built now by a servant in ~/a/skills (slot 04)",
           "note": 'user: "can we adapt the handoff" then "1"'}
OTHER = {"at": "2026-10-05T09:00:00", "kind": "decision", "slot": "07", "what": "use sqlite", "note": "x"}
LOG = [BUMPS, RUNS, HANDOFF, OTHER, {"at": "2026-10-05T10:00:00", "kind": "ask", "slot": "12", "what": "q"}]


def check(message, trees=("12", "04", "07")):
    return dc.check(message, "hal2", LOG, list(trees))


class Check(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())  # no real ~/.hal/git/worktree slot counts as known
        p = mock.patch.object(dc, "WORKTREES", self.root)
        p.start()
        self.addCleanup(p.stop)

    def test_a_missing_decision_comes_back_with_its_date_and_the_users_words(self):
        code, text, entry = check("decision check 12: I have these decisions: version bumps by conventional commits, "
                                  "dependents get a patch bump. Did I forget one?")
        self.assertEqual(code, 0)
        self.assertEqual(text.splitlines()[0][:44], "farmer: decision check 12: 1 missing (data: ")
        self.assertEqual(text.splitlines()[1], '- 2026-10-05 · 12 · "it should delete all the old workflow runs"')
        self.assertNotIn("version bumps", text)
        self.assertEqual((entry["kind"], entry["slot"], entry["what"]), ("decision-check", "12", "1 missing"))

    def test_none_missing(self):
        code, text, _ = check("decision check 12: I have these decisions: version bumps (conventional commits, "
                              "dependents patch bump); delete the old GitHub Actions workflow runs. Did I forget one?")
        self.assertEqual((code, text), (0, "farmer: decision check 12: none missing"))

    def test_an_unknown_slot(self):
        code, text, entry = check("decision check 09: I have these decisions: none. Did I forget one?")
        self.assertEqual((code, entry), (1, {}))
        self.assertIn("unknown slot", text)
        self.assertEqual(check("hello")[0], 1)

    def test_a_repo_wide_entry_counts_for_the_slot_it_names(self):
        (self.root / "skills" / "04").mkdir(parents=True)
        code, text, _ = check("decision check skills/04: I have these decisions: nothing yet", trees=())
        self.assertEqual(code, 0)
        self.assertIn("handoff skill: after clear-and-continue", text)
        self.assertIn('- 2026-10-05 · - · "can we adapt the handoff" / "1" [handoff skill: after clear-and-continue', text)
        self.assertNotIn("workflow runs", text)  # hal2's slot 12, not skills/04
        self.assertIn("none missing", check("decision check 07: use sqlite")[1])
        relayed = {**OTHER, "slot": "-", "what": "commit the skills edits", "note": "12 told skills is free"}
        self.assertFalse(decision_log.concerns(relayed, "12", "hal2"))  # a note naming a slot is bookkeeping

    def test_a_slot_is_a_standalone_token(self):
        self.assertTrue(decision_log.names("in ~/a/skills (slot 04).", "04"))
        self.assertFalse(decision_log.names("on 2026-10-04 at 10:04", "04"))
        self.assertFalse(decision_log.names("plan 0004", "04"))


# hal2's slot 12 as the farmer's evidence of 2026-10-05 showed it (shortened): the servant listed "1a/2a/3a CI
# redesign, version bumps" and got 22 back.
REDESIGN = {"at": "2026-10-05T21:22:06", "kind": "decision", "slot": "12",
            "what": "1a gate+merge on a label shared by the Linux runner and the Mac host runner; 2a build+publish+deliver "
                    "inside land.yml; 3a Copilot reviews off", "note": 'user: "1a, 2a, 3a" (to the farmer\'s 3 questions)'}
DEPLOY = {"at": "2026-10-04T18:23:29", "kind": "decision", "slot": "12",
          "what": "user: go for hal2-ci-wake production deploy (1a), CCX33 (2a); runner parked whenever nothing merges",
          "note": "relayed to 12 ~18:40"}
ORDER = {"at": "2026-10-04T15:26:14", "kind": "decision", "slot": "02,10,12",
         "what": "user's order: 02 and 10 land now, then 12; nothing else until 12 has landed", "note": "user"}
FINISH = {"at": "2026-10-05T16:26:11", "kind": "decision", "slot": "-",
          "what": "the user decided: \"you forgot the goal again? finish 12 before other things\"",
          "note": "every other slot pauses until 0131 is finished"}
EFFORT = {"at": "2026-10-05T09:02:29", "kind": "decision", "slot": "12", "what": "user set 12's effort to High",
          "note": "plan 0131 is careful infra work"}
MIX = {"at": "2026-10-05T09:04:30", "kind": "decision", "slot": "12", "what": "user: \"12 needs to be fast but also high "
       "quality. So we need to find a mix.\"", "note": "landing-time report"}
VERSION = {**BUMPS, "what": "version bumps: 1a conventional commits (feat minor, fix/perf patch), 2a dependents get a "
           "patch bump, 3a 12 builds it as steps appended to plan 0131"}
TWELVE = [REDESIGN, DEPLOY, ORDER, FINISH, EFFORT, MIX, VERSION, RUNS, OTHER]
# Both forms of the mark: a `supersede` entry, and a `supersedes` key on the later decision itself.
MARKED = [e if e is not MIX else {**MIX, "supersedes": EFFORT["at"]} for e in TWELVE] + [
    {"at": "2026-10-05T22:30:00", "kind": "supersede", "slot": "02,10,12", "what": ORDER["at"],
     "supersedes": [ORDER["at"]], "note": f"by {FINISH['at']}"}]


class Tightened(unittest.TestCase):
    """Plan 0009: only current decisions, only those really missing, short forms count."""

    def run_check(self, have, log=MARKED):
        return dc.check(f"decision check 12: I have these decisions: {have}. Did I forget one?", "hal2", log, ["12"])

    def test_a_short_form_counts_as_present(self):
        code, text, _ = self.run_check("1a/2a/3a CI redesign, version bumps")
        self.assertNotIn(REDESIGN["at"][:10] + " · 12 · \"1a, 2a, 3a\"", text)
        self.assertNotIn("conventional commits", text)
        self.assertTrue(dc.present(DEPLOY, "runner parked whenever nothing"))  # 4 words of the decision
        self.assertTrue(dc.present(HANDOFF, "decision check; after clear-and-continue a servant"))  # an item in it
        self.assertFalse(dc.present(HANDOFF, "the user decided"))  # too few key words
        for have in ("12-33 deploy go", "the old workflow runs, nothing else", "2026-10-05 delete workflow runs"):
            entry = {**RUNS, "note": RUNS["note"] + " relayed as 12-33"}
            self.assertTrue(dc.present(entry, have), have)

    def test_an_option_id_set_covers_only_the_same_set(self):
        self.assertFalse(dc.present(DEPLOY, "1a/2a/3a CI redesign"))
        self.assertTrue(dc.present(DEPLOY, "1a/2a production deploy go"))

    def test_a_superseded_entry_is_never_reported(self):
        _, text, _ = self.run_check("nothing")
        self.assertNotIn("02 and 10 land now", text)
        self.assertNotIn("effort to High", text)
        self.assertIn("finish 12 before other things", text)
        self.assertIn("find a mix", text)

    def test_a_real_missing_one_is_reported_one_line_each(self):
        _, text, _ = self.run_check("1a/2a/3a CI redesign, version bumps")
        lines = text.splitlines()
        self.assertEqual(lines[0][:44], "farmer: decision check 12: 4 missing (data: ")
        self.assertEqual(lines[1:], [
            '- 2026-10-04 · 12 · "user: go for hal2-ci-wake production deploy (1a), CCX33 (2a); runner parked whenever '
            'nothing merges"',
            '- 2026-10-05 · - · "you forgot the goal again? finish 12 before other things"',
            '- 2026-10-05 · 12 · "12 needs to be fast but also high quality. So we need to find a mix."',
            '- 2026-10-05 · 12 · "it should delete all the old workflow runs"'])

    def test_none_missing(self):
        have = ("1a/2a/3a CI redesign, version bumps, 1a/2a production deploy and parked runner, finish 12 before "
                "other things, fast but also high quality, delete the old workflow runs")
        self.assertEqual(self.run_check(have)[1], "farmer: decision check 12: none missing")


class SharedAt(unittest.TestCase):
    """The farmer logs several decisions in one second: they get `<at>#<n>` ids, and a mark hits only its own."""

    def test_decisions_sharing_an_at_are_marked_one_by_one(self):
        at = "2026-10-05T08:07:38"
        log = [{**RUNS, "at": at, "what": "commit them"}, {**RUNS, "at": at, "what": "not away from the Mac"},
               {**RUNS, "at": "2026-10-05T09:04:56", "what": "I'm AFK"}]
        self.assertEqual([e["id"] for e in decision_log.decisions(log)], [f"{at}#1", f"{at}#2", "2026-10-05T09:04:56"])
        with self.assertRaisesRegex(ValueError, "2 decisions match"):
            decision_log.find(log, at)
        log.append({"at": "2026-10-05T23:00:00", **decision_log.mark(log, [f"{at}#2"], "2026-10-05T09:04", "")})
        self.assertEqual([e["what"] for e in decision_log.decisions(log)], ["commit them", "I'm AFK"])
        log.append({"at": "2026-10-05T23:01:00", "kind": "supersede", "supersedes": at})  # a bare `at`: both
        self.assertEqual([e["what"] for e in decision_log.decisions(log)], ["I'm AFK"])


# hal2's log of 2026-10-05, trimmed: the farmer's relays of 12's decisions (plan 0010's Notes).
def ask(at, ack_id, text, slot="12"):
    return {"at": at, "kind": "ask-ack", "slot": slot, "id": ack_id, "text": f"farmer [{ack_id}]: {text}"}


COPILOT = {"at": "2026-10-05T21:26:40", "kind": "decision", "slot": "12",
           "what": "3a done: the user switched off Copilot's automatic code review",
           "note": 'user: "done, copilot review is off"'}
RELAYS = [EFFORT, MIX, ask("2026-10-05T09:04:38", "12-6", 'the user decided: "12 needs to be fast but also high quality. '
                           'So we need to find a mix." Spend tokens freely; your effort is now High.'),
          REDESIGN, ask("2026-10-05T21:22:06", "12-30", 'the user decided: "1a, 2a, 3a" on the CI redesign'), COPILOT,
          RUNS, ask("2026-10-05T21:41:34", "12-35", 'the user decided: "it should delete all the old workflow runs".')]


class Links(unittest.TestCase):
    """Plan 0010: each decision knows the ack ids of the farmer instructions that relayed it."""

    def links(self, log):
        return {e["id"]: e["links"] for e in decision_log.decisions(log, True)}

    def test_the_back_fill_links_quotes_key_words_and_inherited_option_ids(self):
        self.assertEqual(self.links(RELAYS), {
            EFFORT["at"]: ["12-6"],  # no quote: its key words (effort, high) in 12-6, within an hour
            MIX["at"]: ["12-6"],  # 4 words of the quote
            REDESIGN["at"]: ["12-30"],  # a whole quote of 3 words
            COPILOT["at"]: ["12-30"],  # {3a} a strict subset of 21:22:06's option ids, 4 minutes later
            RUNS["at"]: ["12-35"]})

    def test_no_link_to_another_slot_too_late_or_too_short(self):
        log = [MIX, ask("2026-10-05T09:05:00", "07-1", "12 needs to be fast but also high quality", slot="07"),
               RUNS, ask("2026-10-06T10:00:00", "12-40", "it should delete all the old workflow runs"),
               EFFORT, ask("2026-10-05T11:00:00", "12-41", "your effort is now High"),
               {**OTHER, "slot": "12", "note": 'user: "go on"'}, ask("2026-10-05T09:00:10", "12-42", "go on, then")]
        self.assertEqual(set(map(tuple, self.links(log).values())), {()})

    def test_explicit_links_from_the_decision_and_from_decision_link_entries(self):
        log = [{**OTHER, "ack": "07-3"}, {**RUNS, "acks": ["12-33", "12-34"]},
               {"at": "2026-10-05T22:00:00", "kind": "decision-link", "slot": "12", "decision": RUNS["at"], "ack": "12-50"}]
        self.assertEqual(self.links(log), {OTHER["at"]: ["07-3"], RUNS["at"]: ["12-33", "12-34", "12-50"]})


# 12's exact message after its /clear (the farmer's report, 2026-10-05), and the decisions under its check, trimmed.
TWELVES_MESSAGE = (
    "decision check 12: after a /clear I have these decisions in plan 0131 (Decisions + step rows): 12-6 fast/high "
    "quality, 12-12 no iOS in pipelines, 12-15 a running main always finishes, the one-time hotfix to main, 12-29/30 "
    "park the Linux runner ASAP (1a,2a,3a), 12-33 steps 19+20 before the next landing (version bump every changed "
    "unit), 12-34 step 20's design, 12-35 delete all old main.yml/deliver.yml/macos.yml runs after the landing, 12-36 "
    "publish+deliver are jobs of the land run (step 21, built in 5bf85ed9, folded into this landing).")
TOKENS = {"at": "2026-10-05T09:04:38", "kind": "decision", "slot": "12",
          "what": 'user clarified: "I mean tokens spent." (tokens are not important, not server money)'}
AFK = {"at": "2026-10-05T09:04:56", "kind": "decision", "slot": "-", "what": 'user: "Just push 12. I\'m AFK."'}
HOTFIX = {"at": "2026-10-05T19:12:10", "kind": "decision", "slot": "12",
          "what": "the user answered 12 directly: option 1 (hotfix pushed to main outside CI)", "note": "per 12's report"}
HELP = {"at": "2026-10-05T20:30:22", "kind": "decision", "slot": "12",
        "what": 'the user decided: "no, if 12 doesnt know alone, help him"'}
PARK = {"at": "2026-10-05T21:00:20", "kind": "decision", "slot": "12",
        "what": "the user: park the Linux runner right after the last Linux job; 12 does it",
        "note": 'user\'s words: "yes, park right after the last linux job. i think 12 should do that."'}
PUBLISH = {"at": "2026-10-05T22:10:02", "kind": "decision", "slot": "12",
           "what": "publish and deliver are jobs of the land workflow itself, not a separately dispatched run",
           "note": 'user: "we said, we want only one, which does everything?"'}
TWELVES_LOG = [
    DEPLOY, EFFORT, {**MIX, "supersedes": EFFORT["at"]}, TOKENS,
    ask("2026-10-05T09:04:38", "12-6", 'the user decided: "12 needs to be fast but also high quality. So we need to '
        'find a mix." and then "I mean tokens spent."'), AFK, HOTFIX, HELP,
    ask("2026-10-05T20:30:08", "12-27", 'help is coming (the user: "if 12 doesnt know alone, help him")'), PARK,
    ask("2026-10-05T21:00:21", "12-29", 'the user decided: "yes, park right after the last linux job."'), REDESIGN,
    ask("2026-10-05T21:22:06", "12-30", 'the user decided: "1a, 2a, 3a" on the CI redesign'), COPILOT, VERSION,
    ask("2026-10-05T21:30:12", "12-33", 'the user decided: "every lib or app, which changed, should also be version '
        'bumped"'), RUNS, ask("2026-10-05T21:41:34", "12-35", 'the user decided: "it should delete all the old '
                              'workflow runs".'), PUBLISH,
    ask("2026-10-05T22:10:02", "12-36", 'the user decided: "we said, we want only one, which does everything?"')]


class ByRelay(unittest.TestCase):
    """Plan 0010: a servant naming the farmer's instruction ids or a distinctive topic has those decisions."""

    def test_twelves_exact_message_misses_only_what_it_does_not_name(self):
        slot, have = dc.parse(TWELVES_MESSAGE)
        gone = dc.missing(TWELVES_LOG, slot, "hal2", have)
        self.assertEqual([e["at"] for e in gone], [DEPLOY["at"], AFK["at"], HELP["at"]])

    def test_a_short_range_names_each_instruction(self):
        self.assertEqual(dc.acks_in("12-29/30 park, 07-3/4/5, 12-33; not 2026-10-05 or 10:04-10:05"),
                         {"12-29", "12-30", "07-3", "07-4", "07-5", "12-33"})
        self.assertTrue(dc.present({**HELP, "links": ["12-27"]}, "12-26/27 help"))
        self.assertFalse(dc.present({**HELP, "links": ["12-27"]}, "12-26 help, 12-28"))

    def test_two_shared_key_words_count_only_with_a_distinctive_one(self):
        self.assertTrue(dc.present(HOTFIX, "the one-time hotfix to main", {"hotfix", "answered"}))
        self.assertFalse(dc.present(HOTFIX, "the one-time hotfix to main"))  # "hotfix" also in another decision
        self.assertFalse(dc.present(HOTFIX, "a main hotfix", {"answered"}))


class Cli(Repo):
    """`farmer.py decision-check` reads the farmer's log and logs the check."""

    def test_the_cli_answers_from_the_log_and_records_the_check(self):
        p = mock.patch.object(dc, "WORKTREES", self.tmp / "no-worktrees")
        p.start()
        self.addCleanup(p.stop)
        git(self.main, "worktree", "add", "-q", "-b", "12", str(self.tmp / "wt" / "12"))
        log = mtm_scan.state_dir(str(self.main)) / "log.jsonl"
        log.write_text("".join(json.dumps(e) + "\n" for e in LOG))
        out = io.StringIO()
        with redirect_stdout(out):
            code = farmer.main(["decision-check", "--message", "decision check 12: I have these decisions: none",
                                "--repo", str(self.slot)])
        self.assertEqual(code, 0)
        self.assertIn("2 missing", out.getvalue())
        self.assertEqual(json.loads(log.read_text().splitlines()[-1])["kind"], "decision-check")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(farmer.main(["decision-check", "09", "--have", "x", "--repo", str(self.slot)]), 1)

    def test_supersede_appends_a_mark_and_list_shows_it(self):
        log = mtm_scan.state_dir(str(self.main)) / "log.jsonl"
        log.write_text("".join(json.dumps(e) + "\n" for e in TWELVE))

        def cli(*argv):
            out = io.StringIO()
            with redirect_stdout(out):
                code = farmer.main(["decision", *argv, "--repo", str(self.slot)])
            return code, out.getvalue()

        self.assertEqual(cli("supersede", "2026-10-05T09:02", "--by", "2026-10-05T09:04:30", "--dry-run")[0], 0)
        self.assertNotIn("supersede", log.read_text())
        code, out = cli("supersede", "2026-10-05T09:04:30", "--by", "2026-10-05T09:02")
        self.assertEqual((code, "not later" in out), (1, True))
        self.assertEqual(cli("supersede", "2026-10-05", "--by", "2026-10-05T09:04:30")[0], 1)  # matches several
        code, out = cli("supersede", "2026-10-05T09:02", "--by", "2026-10-05T09:04:30", "--why", "a mix, not High")
        self.assertEqual((code, out.splitlines()[0][:46]), (0, "superseded 2026-10-05T09:02:29 [12] user set 1"))
        mark = json.loads(log.read_text().splitlines()[-1])
        self.assertEqual((mark["kind"], mark["supersedes"], mark["note"]),
                         ("supersede", [EFFORT["at"]], "by 2026-10-05T09:04:30: a mix, not High"))
        self.assertNotIn("effort to High", cli("list", "--slot", "12")[1])
        self.assertIn("(superseded) user set 12's effort", cli("list", "--all")[1])

    def test_instruct_with_decision_links_the_relay_and_list_shows_it(self):
        log = mtm_scan.state_dir(str(self.main)) / "log.jsonl"
        log.write_text("".join(json.dumps(e) + "\n" for e in TWELVE))
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), mock.patch("sys.stderr", err):
            self.assertEqual(acks.main(["instruct", "12", "x", "--decision", "2026-10-05", "--repo", str(self.slot)]), 1)
            self.assertEqual(log.read_text().count("ask-ack"), 0)  # an ambiguous id sends nothing
            self.assertEqual(acks.main(["instruct", "12", "the user decided: delete them", "--decision",
                                        RUNS["at"][:16], "--repo", str(self.slot)]), 0)
        self.assertIn("decisions match", err.getvalue())
        link = json.loads(log.read_text().splitlines()[-1])
        self.assertEqual((link["kind"], link["decision"], link["ack"]), ("decision-link", RUNS["at"], "12-1"))
        listed = io.StringIO()
        with redirect_stdout(listed):
            farmer.main(["decision", "list", "--slot", "12", "--repo", str(self.slot)])
        self.assertIn("delete all old GitHub Actions workflow runs (relayed as 12-1)", listed.getvalue())


STOP_TRAIN = {"at": "2026-10-06T10:16:35", "kind": "decision", "slot": "04",
              "what": 'the user: "stop the 04-train. 12 should finish first"', "note": "04 waits for the go"}
CLEANUP = {"at": "2026-10-06T09:39:21", "kind": "decision", "slot": "04",
           "what": 'the user: "ok, i want to clean up. i want 06, 08 and 04 to be merged to main after 12. one train, 04 '
                   'should take the lead. are there other open ones?"', "note": "order: 12, then 04's train"}


class InTheCheckout(unittest.TestCase):
    """Skills plan 0012: a decision whose quote stands in the asking checkout's HANDOFF.md, current plan or INTENT.md
    is not missing."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        p = mock.patch.object(dc, "WORKTREES", self.root)
        p.start()
        self.addCleanup(p.stop)
        self.slot = self.root / "hal2" / "04"
        (self.slot / "plans" / "0094-x").mkdir(parents=True)

    def gone(self, trees=None, have="the cleanup train"):
        msg = f"decision check 04: I have these decisions: {have}. Did I forget one?"
        _, text, _ = dc.check(msg, "hal2", [STOP_TRAIN, CLEANUP], trees if trees is not None else {"04": str(self.slot)})
        return [line[2:12] + line[14:22] for line in text.splitlines()[1:]] if "none missing" not in text else []

    def test_nothing_in_the_checkout_reports_both(self):
        self.assertEqual(len(self.gone()), 2)

    def test_the_handoffs_index_holds_it(self):
        (self.slot / "HANDOFF.md").write_text('## Decisions\n- 2026-10-06 "Stop the 04-train!  12 should finish\n'
                                              '  first" (via farmer 04-9) · home: plan\n')
        self.assertEqual(len(self.gone()), 1)

    def test_the_current_plan_holds_it(self):
        (self.slot / "plans" / "CURRENT_PLAN").write_text("0094-x\n")
        (self.slot / "plans" / "0094-x" / "plan.md").write_text(
            '## Decisions\n- 2026-10-06 (the user, via the farmer 04-9): wait. User: "stop the 04-train. 12 should '
            'finish first"\n')
        self.assertEqual(len(self.gone()), 1)

    def test_the_current_plans_ledger_holds_it(self):
        # hal2 plan 0206: a plan in the record format keeps its decisions in decisions.md, not in plan.md.
        (self.slot / "plans" / "CURRENT_PLAN").write_text("0094-x\n")
        (self.slot / "plans" / "0094-x" / "plan.md").write_text("---\ntype: Plan\n---\n\n# Plan 0094: x\n")
        (self.slot / "plans" / "0094-x" / "decisions.md").write_text(
            '## D1 · 2026-10-06 · user · in-force\n\n**D:** Wait for 12.\n**Words:** "stop the 04-train. 12 should '
            'finish first"\n**Via:** farmer 04-9\n')
        self.assertEqual(len(self.gone()), 1)

    def test_the_plan_the_handoff_links_holds_it(self):
        (self.slot / "HANDOFF.md").write_text("## Plan\n[Plan 0094](plans/0094-x/plan.md): 9/9\n")
        (self.slot / "plans" / "0094-x" / "plan.md").write_text('User: "stop the 04-train. 12 should finish first"')
        self.assertEqual(len(self.gone()), 1)

    def test_intent_holds_a_long_quote_by_a_distinctive_run(self):
        (self.slot / "INTENT.md").write_text('| 2026-10-06 | cleanup | (the user: "i want 06, 08 and 04 to be merged to '
                                             'main after 12. one train, 04 should take the lead") |\n')
        self.assertEqual(len(self.gone()), 1)

    def test_a_short_or_partial_match_is_no_match(self):
        (self.slot / "INTENT.md").write_text("stop the 04-train later; one train, 04 should take\n")
        self.assertEqual(len(self.gone()), 2)

    def test_no_checkout_changes_nothing(self):
        self.assertEqual(len(self.gone(trees=["04"])), 2)
        self.assertEqual(len(self.gone(trees={"04": str(self.root / "gone")})), 2)

    def test_another_repos_slot_is_read_from_the_worktree_root(self):
        other = self.root / "skills" / "04"
        other.mkdir(parents=True)
        (other / "INTENT.md").write_text('"stop the 04-train. 12 should finish first"')
        self.assertEqual(dc.checkout("skills/04", "hal2", {}), other)
        self.assertEqual(dc.checkout("hal2/04", "hal2", {"04": "/x/04"}), Path("/x/04"))


class Subject(unittest.TestCase):
    """Skills plan 0012: a repo-wide decision concerns a slot when the slot is its subject, not an aside."""

    ASK = {"at": "2026-10-05T07:12:28", "kind": "decision", "slot": "-",
           "what": "user: ask every farmer round: (a) is the user away from the Mac, so UI tests may run (06 three "
                   "classes, 04 plan 0094 step 7, 09 node UI tests)? (b) may slot 11 measure its benchmarks?"}
    BUILT = {"at": "2026-10-05T22:04:13", "kind": "decision", "slot": "-",
             "what": "handoff skill: a servant asks the farmer; built now by a servant in ~/a/skills (slot 04)"}
    QUOTED = {"at": "2026-10-06T09:30:59", "kind": "decision", "slot": "-",
              "what": 'the user: "if there is a conflict (who does what), then i prefer 02" (02 gets the work)'}

    def test_a_slot_named_only_in_an_aside_is_not_concerned(self):
        self.assertFalse(decision_log.concerns(self.ASK, "04", "hal2"))
        self.assertFalse(decision_log.concerns(self.ASK, "06", "hal2"))
        self.assertFalse(decision_log.concerns(self.BUILT, "04", "hal2"))
        self.assertFalse(decision_log.concerns(self.BUILT, "hal2/04", "hal2"))

    def test_another_repos_slot_counts_with_its_repo_named(self):
        self.assertTrue(decision_log.concerns(self.BUILT, "skills/04", "hal2"))

    def test_a_slot_named_in_the_sentence_or_the_users_words_is(self):
        self.assertTrue(decision_log.concerns(self.ASK, "11", "hal2"))
        self.assertTrue(decision_log.concerns(self.QUOTED, "02", "hal2"))
        self.assertTrue(decision_log.concerns({**self.BUILT, "what": "04 builds the handoff skill"}, "04", "hal2"))

    def test_nested_asides_go_too(self):
        self.assertEqual(decision_log.subject("a (b (04) c) d").split(), ["a", "d"])


SLOT04 = Path(__file__).resolve().parent / "testdata" / "slot04"
MESSAGE04 = ("decision check 04: I have these decisions: plan 0094's Decisions (2026-10-01/02: scope, instances, pinned "
             "n8n 2.41.5, writes by diff, webhook-only run, backups without the key, hardening, gates without Docker, "
             "pane layout, run now, name matching, push rules), INTENT.md 2026-10-06 rows (Swift abandoned after the "
             "train lands, the cleanup train 04+06,08,11,16,20,22, 09 joins before a reland if done and pushed, a red "
             "landing keeps the queue). Did I forget one? Status: land run red in bash-lint + rust-test, both already "
             "fixed on 04; relanding as soon as macos/bash finishes and the running merge-to-main exits.")


class Replay04(unittest.TestCase):
    """Skills plan 0012: hal2 slot 04's decision check of 2026-10-06 10:54 (5 reported, 1 really missing), replayed
    with 04's checkout and the farmer log (trimmed fixtures in testdata/slot04)."""

    def setUp(self):
        self.log = [json.loads(line) for line in (SLOT04 / "log.jsonl").read_text().splitlines() if line.strip()]
        self.tmp = Path(tempfile.mkdtemp())
        self.slot = self.tmp / "04"
        shutil.copytree(SLOT04, self.slot)
        p = mock.patch.object(dc, "WORKTREES", self.tmp / "none")
        p.start()
        self.addCleanup(p.stop)

    def reported(self, log=None):
        code, text, entry = dc.check(MESSAGE04, "hal2", self.log if log is None else log, {"04": str(self.slot)})
        self.assertEqual(code, 0, text)
        return entry["note"].split("; ") if entry["note"] else []

    def test_only_the_stop_of_the_04_train_is_missing(self):
        self.assertEqual(self.reported(), ["2026-10-06T10:16:35"])
        _, text, _ = dc.check(MESSAGE04, "hal2", self.log, {"04": str(self.slot)})
        self.assertIn('"stop the 04-train. 12 should finish first"', text)

    def test_the_stale_entry_goes_by_its_supersede_not_by_text(self):
        before = [e for e in self.log if e["at"] < "2026-10-06T10:56"]
        self.assertEqual(self.reported(before), ["2026-10-03T11:23:12", "2026-10-06T10:16:35"])

    def test_without_the_checkout_the_cleanup_train_was_missing_too(self):
        _, _, entry = dc.check(MESSAGE04, "hal2", self.log, ["04"])
        self.assertEqual(entry["note"].split("; "), ["2026-10-06T09:39:21", "2026-10-06T10:16:35"])

    def test_once_the_handoff_indexes_the_stop_nothing_is_missing(self):
        handoff = self.slot / "HANDOFF.md"
        handoff.write_text(handoff.read_text().replace("## Read first", """## Decisions

- 2026-10-06 "stop the 04-train. 12 should finish first" (via farmer 04-9) · home: plan · ended 2026-10-06: 12 landed,
  go 04-11

## Read first"""))
        self.assertEqual(self.reported(), [])


if __name__ == "__main__":
    unittest.main()
