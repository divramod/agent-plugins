#!/usr/bin/env python3
"""The code part of `/continue` (plan 0593 step 8; plan 0592's D3, D12-D18). No model call.

  continue.py [--repo DIR] [--fetch] [--json]   what this session continues with: role, handoff, pause record,
                                                 restock (mfm), the consistency check, the role's way
  continue.py checked [--repo DIR]               mark this field's check passed (`/continue all` waits for it)
  continue.py checked --repo DIR --after UTC     exit 0 when that field's check passed at or after UTC, else 1
  continue.py all [--repo DIR] [--json]          the farmer's list: paused and unfinished foremen, oldest first
  continue.py rewrite --verdicts FILE|- [--repo DIR]
                                                 write the model's verdicts: ledger entries, superseded own
                                                 entries, rows and step notes (rewrite.py)

`--json` of the first: {schema: 1, role: {...role_facts}, handoff: {...handoffs.resolve}, pause: {record, exists},
mfm: {run, why, behind}, check: {state, plan, why, items, steps}, way: {role, load, way, then}}. `check.state`
`empty` means: no judgment, carry on at once. `--fetch` runs `git fetch -q origin` first (restock needs a fresh
origin/main).

Exit 0 printed, 1 refused (rewrite), 2 usage or git missing.
"""

import argparse
import datetime as dt
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import clis  # noqa: E402
import foremen  # noqa: E402
import freshness  # noqa: E402
import handoffs  # noqa: E402
import rewrite  # noqa: E402
import role_facts  # noqa: E402
import since_check  # noqa: E402
import ways  # noqa: E402

sys.path.insert(0, next(str(_p / "scripts") for _p in HERE.parents if (_p / ".claude-plugin").is_dir()))
from skillpath import load  # noqa: E402

pause = load("pause", "pause")
SCHEMA = 1


def pause_record(checkout: str | None) -> dict:
    """The pause skill's record of the checkout (`<PAUSE_ROOT>/<slug>.md`), as pause.py names it."""
    path = pause.root() / f"{re.sub(r'[^A-Za-z0-9]', '-', checkout or '')}.md"
    return {"record": str(path), "exists": path.is_file()}


def check_plan(facts: dict) -> str | None:
    """The plan the check runs on: a foreman's current plan, a servant's foreman's (its LEAD), else none."""
    if facts["role"] == "servant":
        return (facts.get("lead") or {}).get("plan") or facts.get("plan")
    if facts["role"] == "foreman":
        plan = facts.get("plan")
        return plan if plan and "/" not in plan else None
    return None


def gather(repo: Path, fetch: bool = False) -> dict:
    facts = role_facts.facts(repo)
    root = Path(facts["checkout"] or repo)
    if fetch and facts["role"] in freshness.FIELD_ROLES:
        subprocess.run(["git", "-C", str(root), "fetch", "-q", "origin"], capture_output=True, timeout=120)
    return {"schema": SCHEMA, "role": facts, "handoff": handoffs.resolve(root, facts["role"], facts["main"]),
            "pause": pause_record(facts["checkout"]), "mfm": freshness.decide(root, facts["role"], facts["field"]),
            "check": since_check.check(root, check_plan(facts)), "way": ways.way(facts["role"], facts)}


def text(doc: dict) -> str:
    r, h, m, c, w = doc["role"], doc["handoff"], doc["mfm"], doc["check"], doc["way"]
    lines = [f"role: {r['role'] or 'none'} ({r['field'] or '-'}: {r['why']}) [{r['source']}]",
             f"handoff: {h['found'] or 'none'}" + ("" if h["exists"] or not h["found"] else f" (old place; new: {h['file']})"),
             f"pause: {doc['pause']['record'] if doc['pause']['exists'] else 'none'}",
             f"mfm: {'run /mfm' if m['run'] else 'skip'}: {m['why']}",
             f"check: {c['state']}: {c['why']}"]
    strong = [i for i in c["items"] if i["strength"] == "strong"]
    lines += [f"  {i['ref']} (steps {', '.join(i['steps']) or '-'}): {i['text'][:160]}" for i in strong]
    weak = {}
    for i in (i for i in c["items"] if i["strength"] == "weak"):
        for step in i["steps"] or ["-"]:
            weak[step] = weak.get(step, 0) + 1
    lines += [f"  weak, step {step}: {n} (--json lists them)" for step, n in weak.items()]
    lines.append(f"then: {w['load'] + '; ' if w['load'] else ''}{w['then']}")
    return "\n".join(lines)


def cmd_checked(repo: Path, after: str | None) -> int:
    if after is not None:
        at = foremen.checked_at(repo)
        return 0 if at and at >= after else 1
    facts = role_facts.facts(repo)
    path = foremen.marker(facts["checkout"] or repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    head = clis.git(facts["checkout"] or repo, "rev-parse", "--short", "HEAD")
    at = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    path.write_text(json.dumps({"schema": 1, "at": at, "plan": facts.get("plan"), "head": head}) + "\n")
    print(path)
    return 0


def cmd_all(repo: Path, as_json: bool) -> int:
    facts = role_facts.facts(repo)
    found = foremen.listing(facts["main"] or repo)
    if found is None:
        print("continue.py: `hal2-cli-git worktree list --json` gave no answer", file=sys.stderr)
        return 2
    if as_json:
        print(json.dumps({"schema": 1, "foremen": found}))
        return 0
    for f in found:
        state = f"paused by {f['paused'].get('by')}" if f["paused"] else "no session"
        print(f"{f['field']}  {f['plan']}  {f['done']}/{f['total']}  {state}  next {f['next'] or '-'}")
    print(f"{len(found)} foremen to continue" if found else "no paused or unfinished foreman")
    return 0


def cmd_rewrite(repo: Path, source: str) -> int:
    facts = role_facts.facts(repo)
    if facts["role"] != "foreman":
        print(f"continue.py: a {facts['role'] or 'session without a role'} never rewrites a plan "
              "(a servant reports the verdicts to its foreman)", file=sys.stderr)
        return 1
    found = handoffs.resolve(facts["checkout"], facts["role"], facts["main"])
    if not found["plan"] or not found["decisions"]:
        print("continue.py: no record plan to rewrite (CURRENT_PLAN names none)", file=sys.stderr)
        return 1
    verdicts = json.loads(sys.stdin.read() if source == "-" else Path(source).read_text())
    try:
        done = rewrite.apply(Path(found["plan"]), Path(found["decisions"]), verdicts)
    except rewrite.Refused as error:
        print(f"continue.py: {error}", file=sys.stderr)
        return 1
    print(json.dumps(done))
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("command", nargs="?", default="plan", choices=("plan", "checked", "all", "rewrite"))
    ap.add_argument("--repo", type=Path, default=Path("."))
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--verdicts", help="the verdicts' JSON file, - for stdin (rewrite)")
    ap.add_argument("--after", help="checked: only ask whether the check passed at or after this UTC time")
    args = ap.parse_args(argv)
    if not shutil.which("git"):
        print("continue.py: git is missing; run install-prerequisites.sh", file=sys.stderr)
        return 2
    repo = args.repo.resolve()
    if args.command == "checked":
        return cmd_checked(repo, args.after)
    if args.command == "all":
        return cmd_all(repo, args.json)
    if args.command == "rewrite":
        if not args.verdicts:
            ap.error("rewrite needs --verdicts FILE|-")
        return cmd_rewrite(repo, args.verdicts)
    doc = gather(repo, args.fetch)
    print(json.dumps(doc) if args.json else text(doc))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
