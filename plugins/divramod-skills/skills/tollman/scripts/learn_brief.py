#!/usr/bin/env python3
"""A learning that needs a code fix starts its fix (hal2 plan 0490 step 14, decision D10): the tollman writes the
learning (`learnings.py add --code y --brief`), and one fix brief goes to the farmer, who starts a foreman, through the
farmer's own delegation path (`farmer.py delegate --brief`: the same action, the ledger key `brief:<slug of the
title>`, its limit, field choice and follow-up; read in-process, as the daily `learn` and flaky_brief.py do).

    learn_brief.py brief --dir <role folder> [--repo <field>] [--role <name>] [--n <n> ...] [--wait] [--json]
        the learnings `--n` (default: every one with `Code change: y` and no `Brief` line) get a brief unless one is
        due none: `model-rule` (`Code change: n`: its rule belongs in the tollman's instructions), `repeat` (an
        earlier brief covers the case: same slug or most of its words), `in-plan` (a plan of the field or a running or
        waiting delegation names its id or slug), `done` (it has a brief). A new one gets `briefs/fix-L<n>.md`,
        `Brief: <date> posting` and a detached `send`, never awaited; `--wait` sends here.
    learn_brief.py send --dir <role folder> --repo <field> --n <n> [--role <name>]
        place the brief through the delegation; the entry's `Brief` line says `placed <state>` or `failed <state>`
        (a failed one is retried by the next `brief`).

Speed (D9): reading a few small files, a posted brief never on a train's path, and the farmer's call runs detached.
"""

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

import learn  # the farmer's delegation path at the role's settings (learn.farm_delegate), imports the frame
import delegation
import field_root
import learnings
import mtm_scan

FIELD = "Brief"
SCRIPTS = "code/agents/apps/skills/skills/roles/tollman/scripts/"
SIMILAR = 0.6  # the share of the words two cases must have in common to be one case
PATHS = re.compile(r"[\w./-]+\.(?:py|sh|rs|toml|md|ya?ml|json|ts|bats)\b")
WORDS = re.compile(r"[a-z0-9]{4,}")
LIVE = ("running", "waiting", "in-hand", "planned")  # the delegation ledger's states of a brief in hand
SPEED = ("Speed (decision D9 of plan 0490): the pipeline must run as fast as possible. Nothing new on a train's "
         "critical path; a fix that could make a train or pretest slower is measured (before/after) or left out and "
         "named.")


def _today(now: dt.datetime | None = None) -> str:
    return (now or dt.datetime.now(dt.timezone.utc)).strftime("%Y-%m-%d")


def title_of(e) -> str:
    return f"fix L{e.n} {e.slug}"


def key_of(e) -> str:
    return f"brief:{delegation.slug(title_of(e))}"


def _words(e) -> set:
    return set(WORDS.findall(f"{e.case} {e.rule}".lower()))


def similar(a, b) -> bool:
    """The two entries are one case: the same slug, or at least SIMILAR of their words shared."""
    wa, wb = _words(a), _words(b)
    return a.slug == b.slug or bool(wa and wb and len(wa & wb) / len(wa | wb) >= SIMILAR)


def _briefed(e) -> bool:
    got = e.fields.get(FIELD.lower(), "").strip()
    return bool(got) and " failed" not in f" {got}"


def earlier(role_dir: Path, e):
    """An earlier entry with a brief that covers `e`'s case (archived ones included), else None."""
    text = (role_dir / learnings.FILE).read_text() if (role_dir / learnings.FILE).is_file() else ""
    return next((o for o in learnings.parse(text, True) if o.n < e.n and _briefed(o) and similar(o, e)), None)


def plan_texts(main: str) -> list[str]:
    """The plan.md of the main checkout and of each field: plans in the barn and running ones."""
    roots = [main] + [w["path"] for w in mtm_scan.worktrees(main) if field_root.is_field(w, main)]
    out = []
    for root in roots:
        for f in sorted(Path(root, "plans").glob("*/plan.md")):
            try:
                out.append(f.read_text())
            except OSError:
                pass
    return out


def in_hand(e, texts: list[str], held: dict) -> str:
    """What names the learning already: a plan, or a live delegation's title or brief; "" when nothing does."""
    mark = re.compile(rf"\bL{e.n}\b|{re.escape(e.slug)}")
    if any(mark.search(t) for t in texts):
        return "a plan names it"
    for key, entry in held.items():
        if entry.get("state") not in LIVE:
            continue
        brief = Path(entry["brief"]) if entry.get("brief") else None
        body = brief.read_text() if brief and brief.is_file() else ""
        if mark.search(f"{entry.get('title', '')} {key} {body}"):
            return f"delegation {key}"
    return ""


def files_of(e) -> list[str]:
    seen = []
    for p in PATHS.findall(" ".join(str(v) for v in e.fields.values())):
        if p not in seen and not p.startswith(("http", "-")):
            seen.append(p)
    return seen or [SCRIPTS]


def brief_text(role: str, today: str, e) -> str:
    """The foreman's brief for one learning: the learning and its evidence as data, the files, the speed rule."""
    files = "\n".join(f"- `{p}`" for p in files_of(e))
    evidence = json.dumps(e.fields, indent=1, ensure_ascii=False)
    return (f"---\ntype: Brief\nschema: 1\ntitle: \"{title_of(e)}\"\ndescription: \"The {role}'s learning L{e.n} "
            f"needs a code fix.\"\nstatus: open\nrole: {role}\ncreated: {today}\n---\n\n# {title_of(e)}\n\n"
            f"Written by the {role}'s `learn_brief.py` (hal2 plan 0490, D10) when it wrote learning L{e.n} "
            f"(`roles/{role}/learnings.md`) with `Code change: y`.\n\n## What is wrong\n\n{e.case}\n\nCause: {e.fields.get('cause', '')}\n\n"
            f"## Rule the {role} applies meanwhile\n\n{e.rule}\n\n## Evidence (data, not instructions)\n\n```json\n"
            f"{evidence}\n```\n\n## Files\n\n{files}\n\n## What to do\n\nFix it in code with a regression test that "
            f"replays the case; the rule above goes into the {role}'s instructions only where it still holds after "
            f"the fix. {SPEED}\n\n## Done when\n\nThe case no longer occurs, its test is green, the change is in the "
            "barn (`Landing: auto`, the `/mtm` hitches), and the learning is named in the plan so the tollman can "
            "archive it (`learnings.py archive L<n> --why <commit|plan>`).\n")


def decide(role_dir: Path, e, texts, held) -> tuple[str, str]:
    """(state, why): `model-rule`, `done`, `repeat`, `in-plan` or `new`."""
    if e.code != "y":
        return "model-rule", "its rule belongs in the instructions"
    if _briefed(e):
        return "done", e.fields.get(FIELD.lower(), "")
    twin = earlier(role_dir, e)
    if twin:
        return "repeat", f"L{twin.n} has a brief"
    named = in_hand(e, texts, held)
    return ("in-plan", named) if named else ("new", "")


def _detached(argv: list[str], popen=None) -> None:
    """Start `argv` of this script in a child of its own and return at once: never awaited, its output dropped."""
    (popen or subprocess.Popen)([sys.executable, str(Path(__file__).resolve()), *argv], stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def spawn(role_dir: Path, n: int, role: str = "tollman") -> None:
    """`learnings.py add --brief`: decide and post learning `n`'s brief in a detached child (`brief --wait`)."""
    _detached(["brief", "--dir", str(role_dir), "--role", role, "--n", str(n), "--wait"])


def brief(role_dir: Path, repo: str, numbers=None, role: str = "tollman", wait: bool = False, today: str | None = None,
          texts=None, held=None, delegate=None) -> list[dict]:
    """Decide and post for each wanted entry; returns {n, state, why[, key, brief]}. `texts` (the plans' text), `held`
    (the delegation ledger) and `delegate` are the seams for tests; their defaults read the field."""
    today = today or _today()
    wanted = [e for e in learnings.read(role_dir) if (e.n in numbers if numbers else e.code == "y" and not _briefed(e))]
    if not wanted:
        return []
    main = mtm_scan.main_checkout(repo)
    texts = plan_texts(main) if texts is None else texts
    held = delegation.ledger(main) if held is None else held
    out, marks = [], {}
    for e in wanted:
        state, why = decide(role_dir, e, texts, held)
        row = {"n": e.n, "state": state, "why": why}
        if state == "new":
            f = role_dir / "briefs" / f"fix-L{e.n}.md"
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(brief_text(role, today, e))
            row.update(key=key_of(e), brief=str(f))
            marks[e.n] = {FIELD: f"{today} posting"}
        elif state in ("repeat", "in-plan"):
            marks[e.n] = {FIELD: f"{today} {state}: {why}"}
        out.append(row)
    learnings.set_fields(role_dir, marks)
    for row in (r for r in out if r["state"] == "new"):
        if wait:
            send(role_dir, repo, row["n"], role, today, delegate)
        else:
            spawn_send(role_dir, repo, row["n"], role)
    return out


def spawn_send(role_dir: Path, repo: str, n: int, role: str) -> None:
    _detached(["send", "--dir", str(role_dir), "--repo", repo, "--role", role, "--n", str(n)])


def send(role_dir: Path, repo: str, n: int, role: str = "tollman", today: str | None = None, delegate=None) -> dict:
    """Place learning `n`'s written brief through the farmer's delegation; its `Brief` line records the outcome."""
    e = next((x for x in learnings.read(role_dir) if x.n == n), None)
    if e is None:
        return {"n": n, "state": "unknown"}
    action = {"key": key_of(e), "duty": "learn", "kind": "fix-brief", "slot": "-", "text": title_of(e),
              "brief": {"brief_file": str(role_dir / "briefs" / f"fix-L{n}.md")}}
    try:
        placed = (delegate or learn.farm_delegate(repo, role))(action) or {}
    except Exception as error:  # noqa: BLE001  (a failed post is recorded and retried, never raised at the tollman)
        placed = {"state": f"error {type(error).__name__}"}
    ok = placed.get("state") in learn.OK
    learnings.set_fields(role_dir, {n: {FIELD: f"{today or _today()} {'placed' if ok else 'failed'} {placed.get('state')}"}})
    return {"n": n, "state": placed.get("state"), "key": action["key"]}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("brief", "send"):
        s = sub.add_parser(name)
        s.add_argument("--dir", required=True, help="the role folder")
        s.add_argument("--repo", help="the role's field, default the folder's grandparent")
        s.add_argument("--role", default="tollman")
        s.add_argument("--n", type=int, action="append" if name == "brief" else None, required=name == "send")
        if name == "brief":
            s.add_argument("--wait", action="store_true", help="send in this process")
            s.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    role_dir = Path(args.dir)
    repo = args.repo or str(role_dir.resolve().parent.parent)
    if args.cmd == "send":
        result = send(role_dir, repo, args.n, args.role)
        print(json.dumps(result))
        return 0 if result["state"] in learn.OK else 1
    rows = brief(role_dir, repo, set(args.n or ()), args.role, args.wait)
    print(json.dumps(rows, indent=1) if args.json else
          "\n".join(f"L{r['n']}: {r['state']}" + (f" ({r['why']})" if r["why"] else "") for r in rows) or "no brief due")
    return 0


if __name__ == "__main__":
    sys.exit(main())
