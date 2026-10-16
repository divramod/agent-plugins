#!/usr/bin/env python3
"""Set the user's merge-queue order and say what each affected worktree must hear.

  adapt.py <worktree>... [--note WHY] [--by WHO] [--repo DIR] [--instruct] [--json]
  adapt.py clear [--by WHO] [--repo DIR] [--instruct] [--json]

hal2 owns the order (`hal2-cli-git worktree queue order`, hal2 plan 0143): the listed worktrees land first, in this
order, before every other waiting landing, also one enqueued later; the holder is never preempted. A listed worktree is a
reservation: without a ticket it gets one at its place, and at the front the queue waits for it until its own
merge-to-main takes it over. `clear` drops the list and every reservation. The order is stamped with who sets it
(`--by`, hal2 plan 0313 D18): by default this session's own field (`hal2/17`, `hal2/farmer-hal2`; `<repo>/main` in the
main checkout); `--by user` when the session relays the user's own words (hal2 then shows `the user (via hal2/17)`).

Then it prints the queue before and after and one message per worktree to tell:
each listed worktree its place (a worktree whose work is finished but not queued: land now, it takes its
place; one still working: keep working, the place waits), each other worktree that moved back, each worktree
whose reservation went. It sends nothing: the caller does (SendMessage).
--instruct stamps every message with the farmer's ack id (acks.py instruct: the farmer session). Exit 2 when
hal2-cli-git is missing, 1 when hal2 refuses the order.

A `land` message is the boss's go (`<boss>: land now`): on a farm with a working wagon master (hal2 plan 0294; the
farmer skill's roles.boss asks the mtm skill's wagon-master.sh) it is sent in the wagon master's boss's name and says
that /mtm reports the work ready for the next train; on a farm without one it is the line as ever.
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

FARMER = Path(__file__).resolve().parents[2] / "farmer" / "scripts"
ACKS = FARMER / "acks.py"
sys.path.insert(0, str(FARMER))
import roles  # noqa: E402  (the farmer skill's: who says `land now`)

BOSS = roles.BOSS
LANDS = {roles.BOSS: "it takes this reserved place and lands when its turn comes. What is committed lands",
         roles.WAGON_MASTER_BOSS: "it reports your work ready at this reserved place and the wagon master's next "
                                  "train lands it. What is committed and pushed lands"}


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


def own_field(repo: Path, main: Path) -> str:
    """This session's field as the queue's stamps write it: `<repo>/<slot>`, `<repo>/main` in the main checkout."""
    top = run(["git", "rev-parse", "--show-toplevel"], repo).stdout.strip()
    slot = Path(top).name if top and Path(top).resolve() != main.resolve() else "main"
    return f"{main.name}/{slot}"


def queue(main: Path, order: list[str] | None = None, by: str = "") -> dict:
    """`worktree queue --json`, or `worktree queue order <order> --by <who> --json` (it answers with the queue after)."""
    args = ["hal2-cli-git", "worktree", "queue", *(["order", *order, "--by", by] if order is not None else []),
            "--json"]
    r = run(args, main)
    if r.returncode != 0 and by and "unknown argument" in (r.stderr + r.stdout) and "--by" in args:
        # The installed hal2-cli-git predates `--by` (skills and CLI are delivered separately): once without.
        i = args.index("--by")
        args = args[:i] + args[i + 2:]
        print("adapt.py: this hal2-cli-git does not know --by yet: ordered without it, hal2 stamps its own setter",
              file=sys.stderr)
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


def messages(before: dict, after: dict, note: str, is_finished, boss=lambda: BOSS) -> list[dict]:
    """What each affected worktree hears: places are 1-based, place 1 is the front. `boss()` names who says `land
    now` (roles.boss), asked only when a worktree is told to land."""
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
                who = boss()
                kind, text = "land", (f"{who}: land now. The user put worktree {slot} at {of}{why}: run /mtm now, "
                                      f"{LANDS[who]}; unfinished steps land after it.")
            elif pure:
                kind, text = "reserved", (f"farmer: the user reserved {of} for worktree {slot}{why}. Keep working: your "
                                          "plan's end (/mtm) takes this place. It lands there, and at the front the "
                                          "queue waits for you; where the farm has a wagon master it reports your "
                                          "work ready at this place and the next wagon train brings it in.")
            else:
                kind, text = "place", (f"farmer: the user moved your landing to {of}{why}. Where the farm has a wagon "
                                  "master, a ready wagon keeps this place in the next train's order.")
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
                        "text": f"farmer: the user took worktree {t['slot']}'s reserved place out of the merge queue; "
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
    what = "reserved, waits for its turn" if reserved and not t.get("pid") else t.get("state", "waiting")
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
    p.add_argument("slots", nargs="+", help="worktrees in landing order, or `clear`")
    p.add_argument("--note", default="", help="why, as the worktrees hear it")
    p.add_argument("--by", default="", help="who sets the order: default this session's field, `user` when relaying "
                   "the user's words")
    p.add_argument("--repo", default=".")
    p.add_argument("--instruct", action="store_true", help="stamp each message with a farmer ack id")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    repo = Path(args.repo).resolve()
    main_dir = main_checkout(repo)
    if args.slots == ["clear"]:
        order = ["--clear"]
    elif "clear" in args.slots:
        die("`clear` stands alone")
    else:
        order = args.slots
    before = queue(main_dir)
    after = queue(main_dir, order, args.by or own_field(repo, main_dir))
    default = default_branch(main_dir)
    sent = messages(before, after, args.note, lambda w: finished(w, default), lambda: roles.boss(main_dir))
    if args.instruct:
        sent = [instruct(main_dir, m) for m in sent]
    if args.json:
        print(json.dumps({"before": before, "after": after, "messages": sent}, indent=1))
    else:
        print(render(before, after, sent))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
