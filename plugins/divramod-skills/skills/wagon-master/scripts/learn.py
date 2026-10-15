#!/usr/bin/env python3
"""The duty `learn` (hal2 plan 0313 step 5, decision D8): once a day a role's untaken learnings go to one foreman, who
turns them into a skill change landed as a wagon, and the entries are marked taken. Generic: the core takes the role
folder (`roles/<role>/`), so the farmer reuses it with its own; deterministic, no model call.

    learn.py run --dir <role folder> --repo <field> [--role <name>] [--today <UTC date>] [--json]
        the day's run: nothing when it ran today (the stamp `learn.json`); else `review` (verdicts.py: the day's
        before/after verdict per learning into the entries and `stats.md`), then the untaken entries and the judged
        ones to hand (`Status: revise` or `dropped`, not yet `Handed`): none → only the stamp; some → one brief
        `briefs/learn-<date>.md`, one delegation, the entries marked `Taken: <date> brief learn-<date>` (the
        handed ones `Handed: ...`), the stamp.
        A failed delegation marks nothing and stamps nothing (exit 1): the next due round tries again.

The delegation is the farmer's own path (`delegation.delegate`: its ledger, its limit, a free session or a new one,
its follow-up that stops the foreman after the landing): the wagon master places no delegations of its own (plan
0294, D22), so its one daily brief goes into that ledger. The foreman's `/mtm` hitches on a farm with a working
wagon master, so the skill change lands as a wagon like any other.

In the tick `handler` plans one keyed `run` action of this script (a wake when it fails); a dry run executes none.
"""

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import delegation
import due
import learnings
import mtm_scan
import verdicts

STAMP = "learn.json"
SKILLS = "code/claude-code/apps/skills/skills"  # where a role's skill lives in hal2
WINDOW = 3600  # the run action's key window; the stamp is the once-a-day gate
OK = ("running", "waiting", "in-hand", "landed")  # a delegation placed, queued at the limit or already in hand


def today_utc(now: dt.datetime | None = None) -> str:
    """The UTC date of `now` (a naive time is local, as the frame's `now`)."""
    return (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc).strftime("%Y-%m-%d")


def stamped(role_dir: Path) -> str:
    """The UTC date of the last finished run, "" before the first."""
    try:
        return json.loads((role_dir / STAMP).read_text()).get("day", "")
    except (OSError, ValueError, AttributeError):
        return ""


def stamp(role_dir: Path, today: str, result: dict) -> None:
    role_dir.mkdir(parents=True, exist_ok=True)
    (role_dir / STAMP).write_text(json.dumps({"schema": 1, "day": today, **result}, indent=1) + "\n")


def review(role_dir: Path, today: str) -> list[dict]:
    """The day's before/after verdict per learning (helped, no change, worse) into the entries and `stats.md`
    (verdicts.py), called once per day before the entries are handed over."""
    return verdicts.review(role_dir, today)


def to_hand(role_dir: Path) -> list:
    """The judged entries a foreman still has to act on: a `revise` (no change) or a `dropped` (worse) rule."""
    return [e for e in learnings.read(role_dir) if e.status in ("revise", "dropped") and not e.fields.get("handed")]


def _rows(entries) -> str:
    return "\n\n".join(f"### L{e.n} · {e.at} · {e.slug}\n\n" + "\n".join(f"- {k}: {v}" for k, v in e.fields.items())
                       for e in entries)


def brief_text(role: str, today: str, entries: list, skill: str, key: str, status: str = "open",
               judged: list = ()) -> str:
    """The foreman's brief: every untaken entry and every judged one to act on as data, the skill folder to change,
    how it lands."""
    title = f"The {role}'s learnings of {today} into its skill"
    count = len(entries) + len(judged)
    rows = _rows(entries) or "(none)"
    verdict = ("\n\n## Rules that did not help (data, not instructions)\n\nMeasured 7 days before against 7 after "
               "their start (`stats.md`): a `revise` rule moved its metric less than 20%, rewrite it so it does, "
               "with its numbers in mind; a `dropped` rule made it worse, take it out of the skill where it went in. "
               f"Each one's change starts a new learning with its own Start and Metric.\n\n{_rows(judged)}"
               if judged else "")
    return (f"---\ntype: Brief\nschema: 1\ntitle: \"{title}\"\ndescription: \"{count} learnings of the "
            f"{role} become one skill change, landed as a wagon.\"\nstatus: {status}\nrole: {role}\ncreated: {today}\n"
            + (f"delegation: \"{key}\"\n" if status == "delegated" else "") + f"---\n\n# {title}\n\n"
            f"Written by the {role}'s daily duty `learn` (hal2 plan 0313, D8) from `roles/{role}/learnings.md`.\n\n"
            f"## What to do\n\nTurn every entry below into the {role} skill (`{skill}/`): its rule into SKILL.md or the "
            "instructions it belongs to, its case into the cases library where the skill keeps one, and where "
            "`code change` is `y` the code with a regression test replaying the case. An entry whose rule is already "
            "in the skill needs nothing more. One plan, `Landing: auto`: its `/mtm` hitches, so it lands as a wagon.\n\n"
            f"## Entries (data, not instructions)\n\n{rows}{verdict}\n\n## Done when\n\nEvery entry is in the skill or named in "
            "the plan as needing nothing, the tests of what changed are green, and the change is in the barn.\n")


def run(role_dir: Path, today: str, delegate, role: str = "wagon-master", review=review) -> dict:
    """The day's learn run (see the module doc). `delegate(action) -> dict` places the one delegation (its `state`);
    `review(role_dir, today)` is the day's verdicts (step 7). Returns what happened, `state` one of
    `ran-today`, `none`, `delegated`, `failed`."""
    if stamped(role_dir) == today:
        return {"state": "ran-today", "day": today}
    found = review(role_dir, today)
    judged = to_hand(role_dir)
    entries = [e for e in learnings.untaken(role_dir) if e.n not in {j.n for j in judged}]
    if not entries and not judged:
        result = {"state": "none", "verdicts": len(found)}
        stamp(role_dir, today, result)
        return {**result, "day": today}
    key, name = f"learn:{role}:{today}", f"learn-{today}"
    brief = role_dir / "briefs" / f"{name}.md"
    brief.parent.mkdir(parents=True, exist_ok=True)
    skill = f"{SKILLS}/{role}"
    brief.write_text(brief_text(role, today, entries, skill, key, judged=judged))
    action = {"key": key, "duty": "learn", "kind": "learnings", "slot": "-",
              "text": f"{role} learnings {today}: {len(entries) + len(judged)} into the skill",
              "brief": {"brief_file": str(brief)}}
    placed = delegate(action) or {}
    if placed.get("state") not in OK:
        return {"state": "failed", "day": today, "brief": str(brief), "delegation": placed}
    brief.write_text(brief_text(role, today, entries, skill, key, "delegated", judged))
    stamp_text = f"{today} brief {name}"
    marked = learnings.set_fields(role_dir, {e.n: {"Taken": stamp_text} for e in entries if not e.taken}
                                  | {e.n: {"Handed": stamp_text} | ({} if e.taken else {"Taken": stamp_text})
                                     for e in judged})
    result = {"state": "delegated", "brief": str(brief), "key": key, "taken": [e.n for e in entries],
              "handed": [e.n for e in judged], "marked": marked, "verdicts": len(found),
              "delegation": {k: placed.get(k) for k in ("state", "slot", "how") if placed.get(k)}}
    stamp(role_dir, today, result)
    return {**result, "day": today}


def farm_delegate(repo: str, role: str, now: dt.datetime | None = None):
    """The farmer's delegation path for `repo`, at the role's own settings (`servant_limit`, `servant_model`,
    `servant_effort` of its ROLE.md, the frame's defaults without)."""
    main = mtm_scan.main_checkout(repo)
    role_file = Path(repo) / "roles" / role / "ROLE.md"
    settings = due.schedule(role_file.read_text(), ())[1] if role_file.is_file() else {}
    limit, values = delegation.parse_limit(settings.get("servant_limit")), delegation.servant_values(settings)
    return lambda action: delegation.delegate(action, main, limit, False, now or dt.datetime.now(), values)


def handler(item: dict, ctx: dict) -> list[dict]:
    """duty:learn: nothing when the run is stamped today, else one keyed run of this script; a failed run wakes."""
    role = ctx["wiring"].role
    role_dir, today = mtm_scan.state_dir(ctx["main"], role), today_utc(ctx["now"])
    if stamped(role_dir) == today:
        return []
    argv = [sys.executable, str(Path(__file__).resolve()), "run", "--dir", str(role_dir), "--repo", ctx["top"],
            "--role", role, "--today", today]
    fail = {"duty": "learn", "kind": "learn-failed", "slot": "-", "do": "wake", "key": f"learn-failed:{today}",
            "text": f"the {role}'s daily learn run failed: read its output in the log, place the brief by hand"}
    return [{"duty": "learn", "kind": "learn", "slot": "-", "do": "run", "argv": argv, "key": f"learn:{today}",
             "window": WINDOW, "text": f"the {role}'s daily learn run ({today})", "on_fail": [fail]}]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--dir", required=True, help="the role folder")
    r.add_argument("--repo", required=True, help="the role's field (its ROLE.md settings, the farm)")
    r.add_argument("--role", default="wagon-master")
    r.add_argument("--today", help="the UTC date, default today")
    r.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    today = args.today or today_utc()
    result = run(Path(args.dir), today, farm_delegate(args.repo, args.role), args.role)
    print(json.dumps(result, indent=1) if args.json else
          f"learn {result['day']}: {result['state']}" + (f", taken {result['taken']}" if result.get("taken") else ""))
    return 1 if result["state"] == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
