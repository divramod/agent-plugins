#!/usr/bin/env python3
"""Set the user's merge-queue order and say what each affected slot must hear.

  adapt.py <slot>... [--note WHY] [--repo DIR] [--instruct] [--json]
  adapt.py clear [--repo DIR] [--instruct] [--json]

hal2 owns the order (`hal2-cli-git worktree queue order`, hal2 plan 0143): the listed slots land first, in this
order, before every other waiting landing, also one enqueued later; the holder is never preempted. A listed slot is a
reservation: without a ticket it gets one at its place, and at the front the queue waits for it until its own
merge-to-main takes it over. `clear` drops the list and every reservation.

Then it prints the queue before and after and one message per slot to tell: each listed slot its place (a slot whose
work is finished but not queued: land now, it takes its place; one still working: keep working, the place waits),
each other slot that moved back, each slot whose reservation went. It sends nothing: the caller does (SendMessage).
--instruct stamps every message with the farmer's ack id (acks.py instruct: the farmer session). Exit 2 when
hal2-cli-git is missing, 1 when hal2 refuses the order.
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

ACKS = Path(__file__).resolve().parents[2] / "farmer" / "scripts" / "acks.py"
BOSS = "merge-to-main boss"


def die(message: str, code: int = 1) -> NoReturn:
    print(f"adapt.py: {message}", file=sys.stderr)
    sys.exit(code)


def run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    if not shutil.which(args[0]):
        die(f"{args[0]} is missing: run scripts/install-prerequisites.sh (needs hal2)", 2)
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)


def main_checkout(repo: Path) -> Path:
    out = run(["git", "worktree", "list", "--porcelain"], repo).stdout
    first = out.splitlines()[0] if out else ""
    return Path(first.split(" ", 1)[1]) if first.startswith("worktree ") else repo


def queue(main: Path, order: list[str] | None = None) -> dict:
    """`worktree queue --json`, or `worktree queue order <order> --json` (it answers with the queue after)."""
    args = ["hal2-cli-git", "worktree", "queue", *(["order", *order] if order is not None else []), "--json"]
    r = run(args, main)
    if r.returncode != 0:
        die((r.stderr or r.stdout).strip() or f"{' '.join(args)} failed")
    return json.loads(r.stdout)


def finished(worktree: str, default: str) -> bool:
    """Work to land and no plan running: commits not on origin's default branch, plans/CURRENT_PLAN names nothing."""
    path = Path(worktree)
    plan = path / "plans" / "CURRENT_PLAN"
    if not path.is_dir() or (plan.exists() and plan.read_text().strip()):
        return False
    r = subprocess.run(["git", "rev-list", "--count", f"origin/{default}..HEAD"], cwd=path, capture_output=True,
                       text=True)
    return r.returncode == 0 and r.stdout.strip() not in ("", "0")


def default_branch(main: Path) -> str:
    r = subprocess.run(["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"], cwd=main, capture_output=True,
                       text=True)
    return r.stdout.strip().removeprefix("origin/") or "main"


def messages(before: dict, after: dict, note: str, is_finished) -> list[dict]:
    """What each affected slot hears: places are 1-based, place 1 is the front."""
    old = [t["slot"] for t in before.get("queue", [])]
    new = after.get("queue", [])
    listed = (after.get("priority") or {}).get("slots", [])
    why = f" ({note})" if note else ""
    out = []
    for place, t in enumerate(new, 1):
        slot, of = t["slot"], f"place {place} of {len(new)} in the merge queue"
        if slot in listed:
            pure = bool(t.get("reserved")) and not t.get("pid")
            if pure and is_finished(t["worktree"]):
                kind, text = "land", (f"{BOSS}: land now. The user put slot {slot} at {of}{why}: run /mtm now, it "
                                      "takes this reserved place and lands when its turn comes. What is committed "
                                      "lands; unfinished steps land after it.")
            elif pure:
                kind, text = "reserved", (f"farmer: the user reserved {of} for slot {slot}{why}. Keep working: your "
                                          "plan's landing (/mtm at its end) takes this place, and at the front the "
                                          "queue waits for you.")
            else:
                kind, text = "place", f"farmer: the user moved your landing to {of}{why}."
        elif slot in old and place > old.index(slot) + 1:
            kind, text = "moved", (f"farmer: the user's merge-queue priority moved your landing back to {of} "
                                   f"(was place {old.index(slot) + 1}); it lands when its turn comes.")
        else:
            continue
        out.append({"slot": slot, "kind": kind, "worktree": t["worktree"], "text": text})
    gone = {t["slot"] for t in new}
    for t in before.get("queue", []):
        if t.get("reserved") and not t.get("pid") and t["slot"] not in gone:
            out.append({"slot": t["slot"], "kind": "unreserved", "worktree": t["worktree"],
                        "text": f"farmer: the user took slot {t['slot']}'s reserved place out of the merge queue; "
                                "land with /mtm as usual when your work is done."})
    return out


def instruct(main: Path, m: dict) -> dict:
    r = subprocess.run([sys.executable, str(ACKS), "instruct", m["slot"], m["text"], "--repo", str(main), "--json"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        die(f"acks.py instruct {m['slot']}: {(r.stderr or r.stdout).strip()}")
    stamped = json.loads(r.stdout)
    return dict(m, id=stamped["id"], text=stamped["text"])


def line(place: int, t: dict) -> str:
    reserved = t.get("reserved")
    what = "reserved, waits for its slot" if reserved and not t.get("pid") else t.get("state", "waiting")
    by = f" (reserved by {reserved['by']})" if reserved else ""
    return f"  {place}. {t['slot']}: {what}{by}"


def render(before: dict, after: dict, sent: list[dict]) -> str:
    out = ["before:"] + ([line(i, t) for i, t in enumerate(before.get("queue", []), 1)] or ["  (empty)"])
    out += ["after:"] + ([line(i, t) for i, t in enumerate(after.get("queue", []), 1)] or ["  (empty)"])
    if after.get("priority"):
        out.append("priority: " + " ".join(after["priority"]["slots"]))
    out.append("tell:" if sent else "tell: nobody")
    out += [f"- {m['slot']} ({m['kind']}, {m['worktree']}): {m['text']}" for m in sent]
    return "\n".join(out)


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("slots", nargs="+", help="slots in landing order, or `clear`")
    p.add_argument("--note", default="", help="why, as the slots hear it")
    p.add_argument("--repo", default=".")
    p.add_argument("--instruct", action="store_true", help="stamp each message with a farmer ack id")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    main_dir = main_checkout(Path(args.repo).resolve())
    if args.slots == ["clear"]:
        order = ["--clear"]
    elif "clear" in args.slots:
        die("`clear` stands alone")
    else:
        order = args.slots
    before = queue(main_dir)
    after = queue(main_dir, order)
    default = default_branch(main_dir)
    sent = messages(before, after, args.note, lambda w: finished(w, default))
    if args.instruct:
        sent = [instruct(main_dir, m) for m in sent]
    if args.json:
        print(json.dumps({"before": before, "after": after, "messages": sent}, indent=1))
    else:
        print(render(before, after, sent))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
