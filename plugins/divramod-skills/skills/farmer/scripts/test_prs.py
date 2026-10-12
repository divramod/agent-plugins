import datetime as dt
import unittest

import due
import duties
import pr_scan
import tick

NOW = dt.datetime(2026, 10, 6, 10, 0)
T = NOW.timestamp()


def pr(number, head, login="divramod", updated="2026-10-06T09:00:00", draft=False):
    return {"number": number, "title": f"pr {number}", "author": {"login": login}, "headRefName": head,
            "updatedAt": updated, "createdAt": updated, "url": f"https://x/pull/{number}", "isDraft": draft}


DEPS = [pr(8, "dependabot/cargo/code/rust/cargo-a8", "app/dependabot"),
        pr(2, "dependabot/bun/code/typescript/apps/hal2-mermaid/bun-61", "app/dependabot")]


def ctx():
    return {"top": "/x/farmer", "main": "/x/hal2", "now": NOW, "log": [], "duties": {"prs"}, "panes": {},
            "agents_by_pane": {}, "landing": set()}


def plan(prs, queued=(), superseded=(), ahead=None, held=None):
    found = pr_scan.findings(prs, set(queued), set(superseded), ahead or {}, T)
    return tick.fresh(duties.plan_prs({}, ctx(), {"findings": found}, held or {}), [], NOW)


class Scan(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual([pr_scan.kind_of(p) for p in DEPS + [pr(16, "land/08"), pr(9, "feature")]],
                         ["dependabot", "dependabot", "landing", "other"])

    def test_dependabot_prs_are_one_batch_in_number_order(self):
        found = pr_scan.findings(DEPS, set(), set(), {}, T)
        self.assertEqual([(f["kind"], f.get("numbers")) for f in found], [("dependabot", [2, 8])])

    def test_a_landing_pr_is_stale_only_without_a_ticket_for_a_day(self):
        old = pr(7, "land/00", updated="2026-10-04T09:00:00")
        self.assertEqual(pr_scan.findings([old], {"00"}, set(), {}, T), [])
        self.assertEqual(pr_scan.findings([pr(16, "land/08")], set(), set(), {}, T), [])
        self.assertEqual([f["kind"] for f in pr_scan.findings([old], set(), set(), {}, T)], ["land-stale"])

    def test_drafts_are_left_alone(self):
        self.assertEqual(pr_scan.findings([pr(9, "feature", draft=True)], set(), set(), {}, T), [])


class Plan(unittest.TestCase):
    def test_the_batch_goes_to_one_servant_with_its_own_task(self):
        [a] = plan(DEPS)
        self.assertEqual((a["do"], a["key"]), ("delegate", "prs:dependabot:2-8"))
        self.assertIn("#2, #8", a["text"])
        self.assertIn("git merge --no-ff", a["task"])
        self.assertEqual([p["number"] for p in a["brief"]["prs"]], [2, 8])

    def test_no_second_batch_while_one_is_in_hand(self):
        held = {"prs:dependabot:2": {"state": "running", "slot": "05"}}
        self.assertEqual(plan(DEPS, held=held), [])
        self.assertEqual(len(plan(DEPS, held={"prs:dependabot:2": {"state": "landed"}})), 1)

    def test_a_pr_main_holds_is_closed_and_left_out_of_the_batch(self):
        actions = plan(DEPS, superseded={8})
        self.assertEqual([(a["do"], a["kind"]) for a in actions], [("delegate", "dependabot"), ("run", "superseded")])
        self.assertEqual(actions[1]["argv"][:4], ["gh", "pr", "close", "8"])
        self.assertEqual(actions[0]["key"], "prs:dependabot:2")

    def test_a_stale_landing_pr_is_closed_only_when_its_slot_holds_nothing(self):
        old = pr(7, "land/00", updated="2026-10-04T09:00:00")
        self.assertEqual([(a["do"], a["slot"]) for a in plan([old], ahead={"00": 0})], [("run", "00")])
        self.assertEqual([(a["do"], a["slot"]) for a in plan([old], ahead={"00": 3})], [("wake", "00")])

    def test_another_pr_is_a_notice_once_a_week(self):
        actions = duties.plan_prs({}, ctx(), {"findings": pr_scan.findings([pr(9, "feature")], set(), set(), {}, T)}, {})
        self.assertEqual([a["do"] for a in tick.fresh(actions, [], NOW)], ["notify"])
        log = [{"at": NOW.isoformat(), "key": "prs:other:9"}]
        self.assertEqual(tick.fresh(actions, log, NOW), [])

    def test_prs_is_a_known_duty(self):
        self.assertIn("prs", due.DUTIES)


if __name__ == "__main__":
    unittest.main()
