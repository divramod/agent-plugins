"""Hal2 plan 0313 steps 5 and 7 (D8, D9, D10): the duty `learn` (learn.py) and its before/after review (verdicts.py).
Not opted in: the round has no such item; opted in and no untaken entry: nothing is delegated; untaken entries:
exactly one delegation, the entries marked taken; the same UTC day again: nothing. A failed delegation marks nothing.
Each learning with a Start and a Metric is judged once its 7 days after are over: helped (kept), worse (dropped, no
longer applied), no change (revise, handed into the next brief with its numbers), not enough data yet; stats.md holds
the verdicts and the day's summary. Hermetic (D5): a tmp role folder with fixture train lines, the ci-analyzer and
the delegation fakes, the farmer's `delegation.delegate` patched; no session, tmux, queue, GitHub or git."""

import contextlib
import datetime as dt
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import farmer_frame  # noqa: F401
import delegation
import due
import learn
import learnings
import metrics
import roles
import verdicts
import wagon_master

TODAY, TOMORROW = "2026-10-14", "2026-10-15"
ROLE = """---
duties:
  trains: "*/5 * * * *"
  mtm: "*/10 * * * *"
{learn}notify: every-round
servant_model: sonnet
servant_effort: high
---
"""


class Fake:
    """The delegation: records each action, answers with `state`."""

    def __init__(self, state="running"):
        self.state, self.calls = state, []

    def __call__(self, action):
        self.calls.append(action)
        return {"key": action["key"], "state": self.state, "slot": "04", "how": "new"}


class Folder(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name) / "roles" / "wagon-master"
        self.dir.mkdir(parents=True)
        # the default review never asks GitHub here: its ci-analyzer is "unknown"
        patch = mock.patch.object(metrics, "fetch_ci", side_effect=metrics.CiUnknown("no ci-analyzer in a test"))
        patch.start()
        self.addCleanup(patch.stop)

    def add(self, case, code="n"):
        return learnings.add(self.dir, case, "because", f"from now on: {case}", code, at=f"{TODAY} 08:40Z")


class OptIn(unittest.TestCase):
    def test_not_opted_in_the_round_has_no_learn_item_and_the_template_opts_in(self):
        off = due.schedule(ROLE.format(learn=""), wagon_master.WIRING.duties)
        on = due.schedule(ROLE.format(learn='  learn: "17 6 * * *"\n'), wagon_master.WIRING.duties)
        self.assertEqual((off[2], on[2]), ([], []))
        self.assertNotIn("duty:learn", off[0])
        self.assertEqual(on[0]["duty:learn"], "17 6 * * *")
        self.assertIs(wagon_master.HANDLERS["duty:learn"], learn.handler)
        template = (Path(learn.__file__).parent.parent / "templates/ROLE.md").read_text()
        self.assertIn("duty:learn", due.schedule(template, wagon_master.WIRING.duties)[0])
        self.assertEqual(due.interval_minutes(on[0]["duty:learn"]), 24 * 60, "once a day")


class Run(Folder):
    def test_opted_in_and_no_entry_nothing_is_delegated(self):
        fake, seen = Fake(), []
        r = learn.run(self.dir, TODAY, fake, review=lambda d, t: seen.append(t) or [])
        self.assertEqual((r["state"], fake.calls, seen), ("none", [], [TODAY]))
        self.assertEqual(learn.stamped(self.dir), TODAY)
        self.assertFalse((self.dir / "briefs").exists())

    def test_entries_make_exactly_one_delegation_and_are_marked_taken(self):
        self.add("the carrier's remote keeps a dead train", "y")
        self.add("a car rides without proof")
        fake = Fake()
        r = learn.run(self.dir, TODAY, fake)
        self.assertEqual((r["state"], r["taken"], len(fake.calls)), ("delegated", [1, 2], 1))
        a = fake.calls[0]
        self.assertEqual((a["key"], a["duty"], a["slot"]), (f"learn:wagon-master:{TODAY}", "learn", "-"))
        brief = Path(a["brief"]["brief_file"])
        self.assertEqual(brief, self.dir / "briefs" / f"learn-{TODAY}.md")
        text = brief.read_text()
        for want in ("type: Brief", "status: delegated", f'delegation: "learn:wagon-master:{TODAY}"',
                     "### L1 ·", "### L2 ·", "code change: y", "code/claude-code/apps/skills/skills/wagon-master/"):
            self.assertIn(want, text)
        self.assertEqual(learnings.untaken(self.dir), [])
        self.assertEqual({e.taken for e in learnings.read(self.dir)}, {f"{TODAY} brief learn-{TODAY}"})

    def test_the_same_day_again_does_nothing_and_the_next_day_hands_only_the_new_entries(self):
        self.add("first")
        fake, seen = Fake(), []
        learn.run(self.dir, TODAY, fake)
        self.add("second")
        r = learn.run(self.dir, TODAY, fake, review=lambda d, t: seen.append(t) or [])
        self.assertEqual((r["state"], len(fake.calls), seen), ("ran-today", 1, []), "the day's review ran once")
        r = learn.run(self.dir, TOMORROW, fake)
        self.assertEqual((r["state"], r["taken"], len(fake.calls)), ("delegated", [2], 2))
        self.assertIn("### L2 ·", Path(fake.calls[1]["brief"]["brief_file"]).read_text())
        self.assertNotIn("### L1 ·", Path(fake.calls[1]["brief"]["brief_file"]).read_text())

    def test_a_failed_delegation_marks_nothing_and_leaves_no_stamp(self):
        self.add("first")
        r = learn.run(self.dir, TODAY, Fake("error"))
        self.assertEqual((r["state"], learn.stamped(self.dir), len(learnings.untaken(self.dir))), ("failed", "", 1))
        self.assertEqual(learn.run(self.dir, TODAY, Fake())["state"], "delegated", "the next due round tries again")


class Tick(Folder):
    def ctx(self, now):
        return {"main": "/m", "top": "/f", "now": now, "wiring": wagon_master.WIRING}

    def test_the_handler_plans_one_keyed_run_with_a_wake_on_failure_and_nothing_once_stamped(self):
        with mock.patch.object(learn.mtm_scan, "state_dir", return_value=self.dir):
            planned = learn.handler({"name": "duty:learn"}, self.ctx(dt.datetime(2026, 10, 14, 12, 0)))
            self.assertEqual(len(planned), 1)
            a = planned[0]
            self.assertEqual((a["do"], a["duty"], a["key"]), ("run", "learn", f"learn:{TODAY}"))
            self.assertEqual(a["argv"][2:], ["run", "--dir", str(self.dir), "--repo", "/f", "--role", "wagon-master",
                                             "--today", TODAY])
            self.assertEqual([(f["do"], f["kind"]) for f in a["on_fail"]], [("wake", "learn-failed")])
            self.assertTrue(all(f.get("key") for f in [a, *a["on_fail"]]), "D22: every action carries a key")
            learn.stamp(self.dir, TODAY, {"state": "none"})
            self.assertEqual(learn.handler({"name": "duty:learn"}, self.ctx(dt.datetime(2026, 10, 14, 13, 0))), [])

    def test_the_cli_run_places_the_brief_through_the_farmer_s_delegation_at_the_role_s_settings(self):
        field = self.dir.parents[1]
        (self.dir / "ROLE.md").write_text(ROLE.format(learn='  learn: "17 6 * * *"\n').replace("high", "max"))
        self.add("first", "y")
        calls = []

        def delegate(a, main, limit, dry, now, values):
            calls.append((a, limit, dry, values))
            return {"key": a["key"], "state": "waiting"}

        out = io.StringIO()
        with mock.patch.object(delegation, "delegate", delegate), \
                mock.patch.object(learn.mtm_scan, "main_checkout", return_value=str(field)), \
                contextlib.redirect_stdout(out):
            code = learn.main(["run", "--dir", str(self.dir), "--repo", str(field), "--today", TODAY, "--json"])
        self.assertEqual((code, json.loads(out.getvalue())["state"]), (0, "delegated"), "waiting at the limit is placed")
        (a, limit, dry, values), = calls
        self.assertEqual((limit, dry, values), ("auto", False, {"model": "sonnet", "effort": "max"}))
        self.assertTrue(Path(a["brief"]["brief_file"]).is_file(), "the given brief: delegation writes none of its own")
        self.assertEqual(learnings.untaken(self.dir), [])


class Generic(Folder):
    def test_the_core_takes_any_role_folder(self):
        farmer = self.dir.parent / "farmer"
        learnings.add(farmer, "a farmer case", "c", "r", "n", role="farmer")
        fake = Fake()
        r = learn.run(farmer, TODAY, fake, role="farmer")
        self.assertEqual((r["state"], fake.calls[0]["key"]), ("delegated", f"learn:farmer:{TODAY}"))
        self.assertIn("skills/farmer/", Path(fake.calls[0]["brief"]["brief_file"]).read_text())
        self.assertEqual(roles.ROLE, "farmer")


START, JUDGE_DAY = "2026-10-08 00:00Z", "2026-10-16"  # the after window ends 10-15 00:00, before the judging day


def trains(day: str, green: int, red: int) -> list[dict]:
    """One day's train lines: `green` trains landed at first try, `red` trains red and never landed."""
    out = []
    for i in range(green + red):
        name, at = f"t{i}@{day}", f"{day}T{10 + i:02d}:00:00Z"
        out.append({"schema": 1, "at": at, "kind": "started", "slot": "wagon-master-hal2", "train": name})
        out.append({"schema": 1, "at": at.replace(":00:00Z", ":30:00Z"), "slot": "wagon-master-hal2", "train": name,
                    **({"kind": "landed", "cars": ["07"]} if i < green else
                       {"kind": "red", "status": "gate_failed", "why": "07/python-test: a car's test"})})
    return out


class Verdicts(Folder):
    """The before/after verdict of one learning: 7 days before its start against 7 after (D10)."""

    def setUp(self):
        super().setUp()
        self.ci_calls = 0

    def ci(self):
        self.ci_calls += 1
        return []

    def history(self, before: tuple, after: tuple):
        rows = trains("2026-10-03", *before) + trains("2026-10-10", *after)
        (self.dir / "train.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))

    def rule(self, metric="first_try_green_rate"):
        return learnings.add(self.dir, "cars rode without proof", "no proof", "a car rides with its proof", "n",
                             at="2026-10-07 18:00Z", metric=metric, start=START)

    def review(self, today=JUDGE_DAY):
        return verdicts.review(self.dir, today, ci=self.ci)

    def verdict(self, before, after):
        self.history(before, after)
        self.rule()
        found, = self.review()
        return found, learnings.read(self.dir)[0]

    def test_the_writer_fills_start_and_the_session_names_the_metric(self):
        e = learnings.add(self.dir, "a case", "c", "r", "n", at="2026-10-14 08:40Z", metric="landings")
        self.assertEqual((e.fields["start"], e.fields["metric"]), ("2026-10-14 08:40Z", "landings"))
        self.assertEqual(self.rule().fields["start"], START)

    def test_helped_the_rule_is_kept_with_its_numbers(self):
        a, e = self.verdict(before=(2, 3), after=(4, 1))
        self.assertEqual((a["verdict"], a["before"], a["after"], a["change"]), ("helped", 0.4, 0.8, 1.0))
        self.assertEqual((e.status, a["trains_before"], a["trains_after"]), ("kept", 5, 5))
        self.assertIn("0.4 -> 0.8 (+100%)", e.fields["verdict"])
        self.assertEqual(self.ci_calls, 1, "the ci-analyzer is asked once per review")

    def test_worse_the_rule_is_dropped_and_no_longer_applied(self):
        a, e = self.verdict(before=(4, 1), after=(2, 3))
        self.assertEqual((a["verdict"], a["change"], e.status), ("worse", -0.5, "dropped"))
        self.assertIn("[dropped: not applied]", learnings.rules_text(self.dir))

    def test_no_change_the_rule_is_to_revise(self):
        a, e = self.verdict(before=(4, 1), after=(4, 1))
        self.assertEqual((a["verdict"], e.status), ("no change", "revise"))
        self.assertNotIn("[dropped", learnings.rules_text(self.dir))

    def test_a_move_under_20_percent_is_no_change(self):
        self.assertEqual(verdicts.judge({"trains": 9, "landings": 10}, {"trains": 9, "landings": 11},
                                        "landings")["verdict"], "no change")
        lower = verdicts.judge({"trains": 5, "red_causes": {"car": 5}}, {"trains": 5, "red_causes": {"car": 3}},
                               "red_car")
        self.assertEqual((lower["verdict"], lower["good"]), ("helped", "lower"), "fewer car reds is better")
        zero = verdicts.judge({"trains": 5, "restarts": 0}, {"trains": 6, "restarts": 2}, "restarts")
        self.assertEqual(zero["verdict"], "worse", "from 0 to 2 restarts")

    def test_not_enough_data_yet_under_5_trains_a_side_and_no_status(self):
        a, e = self.verdict(before=(4, 1), after=(2, 1))
        self.assertEqual((a["verdict"], a["trains_after"], e.status), ("not enough data yet", 3, ""))

    def test_an_open_window_is_measuring_and_an_entry_without_metric_unmeasured(self):
        self.history((4, 1), (2, 3))
        self.rule()
        learnings.add(self.dir, "legacy", "c", "r", "n", at="2026-10-07 18:00Z")
        found = self.review("2026-10-14")
        self.assertEqual([a["verdict"] for a in found], ["measuring", "unmeasured"])
        self.assertEqual([e.status for e in learnings.read(self.dir)], ["", ""])

    def test_the_first_verdict_stands_and_stats_md_holds_the_numbers_and_the_summary(self):
        self.verdict(before=(4, 1), after=(2, 3))
        self.history((4, 1), (4, 1))  # the numbers change later: the entry keeps its first verdict
        self.review("2026-10-17")
        self.assertEqual(learnings.read(self.dir)[0].fields["status"], f"dropped {JUDGE_DAY}")
        stats = (self.dir / verdicts.STATS).read_text()
        for want in ("type: Ledger", "# wagon-master stats\n", "## Summary: the last 7 days", "## L1 · cars-rode-without-proof · no change",
                     "first_try_green_rate (higher is better) 0.8 -> 0.8", "Status: dropped"):
            self.assertIn(want, stats)

    def test_the_drop_and_the_revise_go_into_the_next_brief_with_their_numbers_once(self):
        self.history((4, 1), (2, 3))
        self.rule()
        learnings.mark_taken(self.dir, {1}, "plan 0400", "2026-10-08")
        learnings.add(self.dir, "a second rule", "c", "r", "n", at="2026-10-07 18:00Z", metric="red_runner",
                      start=START)
        fake = Fake()
        r = learn.run(self.dir, JUDGE_DAY, fake, review=lambda d, t: verdicts.review(d, t, ci=self.ci))
        self.assertEqual((r["state"], r["taken"], r["handed"], r["verdicts"]), ("delegated", [], [1, 2], 2))
        text = Path(fake.calls[0]["brief"]["brief_file"]).read_text()
        self.assertIn("## Rules that did not help", text)
        self.assertIn("status: dropped", text)
        self.assertIn("worse: first_try_green_rate (higher is better) 0.8 -> 0.4 (-50%)", text)
        self.assertIn("status: revise", text)
        self.assertIn("no change: red_runner (lower is better) 0 -> 0 (+0%)", text)
        e1, e2 = learnings.read(self.dir)
        self.assertEqual((e1.taken, e1.fields["handed"]), ("2026-10-08 plan 0400", f"{JUDGE_DAY} brief learn-{JUDGE_DAY}"))
        self.assertEqual((e2.taken, e2.fields["handed"]), (f"{JUDGE_DAY} brief learn-{JUDGE_DAY}",) * 2)
        r = learn.run(self.dir, "2026-10-17", fake, review=lambda d, t: verdicts.review(d, t, ci=self.ci))
        self.assertEqual((r["state"], len(fake.calls)), ("none", 1), "a handed verdict is not handed again")


if __name__ == "__main__":
    unittest.main()
