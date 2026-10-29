#!/usr/bin/env python3
"""The deterministic parts of the skill `/transplant` (hal2 plan 0286, D13, D24, D25); stdlib only.

  transplant.py check [<from>] <to> [--repo DIR] [--min-free-gb 50]   everything that can stop a transplant, then the
                                                                       CLI's dry run; JSON, exit 1 with `stop`
  transplant.py free <from> <to> [--repo DIR]     stop an idle session in <to> by signal; a refusal cancels the
                                                  prepared transplant itself (exit 3)
  transplant.py push <from> <to> [--repo DIR]     the target's branch, and from <from>'s own session origin's <from>
  transplant.py start <to> [--repo DIR]           the foreman in <to> by `/handoff c` at the plan's model and effort
  transplant.py advice <reason> [<from> <to>]     what to do about a refusal's `reason` word

Every call prints JSON (advice: a line). Exit 0 done, 1 a stop (`stop` is a code, `advice` the way out), 2 a missing
tool, 3 a refused `free`. A session starts only through create-worktree-session's `start` (`hal2-cli-git worktree
run`) and stops only through delete-field's `stop.py` (by signal): never `claude` itself, never `/exit`.
"""
import argparse
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fieldgit  # noqa: E402

sys.path.insert(0, next(str(_p / "scripts") for _p in Path(__file__).resolve().parents if (_p / ".claude-plugin").is_dir()))
from skillpath import load, pointers, sibling  # noqa: E402  (the skills unit's scripts/, plan 0360 D20)
planread = load("plan", "planread", __file__)  # a plan's files in either home (hal2 plan 0409 step 9)
STOP = sibling("delete-field") / "scripts/stop.py"
CREATE = sibling("create-worktree-session") / "scripts/create.py"
EFFORTS = ("low", "medium", "high", "xhigh", "max")
OPEN = ("driven", "arrived")
ADVICE = {
    "same": "name another field than the foreman's own as the target.",
    "main": "the yard (main) is never moved and never a target: name a numbered field.",
    "role": "a role's field is never moved and never a target: name a numbered field.",
    "no-source": "field {frm} does not exist: `hal2-cli-git worktree list` shows the fields.",
    "servant": "a servant's field never moves, its foreman merges its branch: transplant the foreman's field.",
    "nothing": "field {frm} holds no plan and no commit the barn lacks: there is nothing to move.",
    "off-branch": "field {frm} is not on its own branch: `git switch {frm}` (commit or move what is on the other "
                  "branch), then run the same command again.",
    "dirty": "commit the files named, then run the same command again.",
    "at-the-gate": "a landing of field {frm} or {to} is queued or running: wait until it has ended, then run the same "
                   "command again.",
    "target-taken": "field {to} holds a plan, work or another transplant: take a free field "
                    "(`hal2-cli-git worktree list`) or end what holds it.",
    "target-busy": "a session works in field {to}: take another field, or run the same command again once it rests.",
    "conflict": "restock field {frm} (`/mfm` in it), commit, then run the same command again: the merge was aborted, "
                "nothing changed.",
    "side-branch": "a side branch {to}-<topic> exists already: rename or delete it, then run the same command again.",
    "prepared-elsewhere": "field {frm} is in another open transplant: the message names it and its command; let it "
                          "arrive or end it (that command with `--cancel`), then run the same command again.",
    "not-prepared": "field {frm} has no transplant that can be cancelled: none is prepared, or its work is in the "
                    "target already and the message names the command that finishes it.",
    "error": "a fault was undone (read the message): run the same command again.",
}


def emit(result) -> None:
    print(json.dumps(result, indent=2, ensure_ascii=False))


def advice(reason: str, frm: str = "<from>", to: str = "<to>") -> str:
    return ADVICE.get(reason, "read the reason, then run the same command again.").format(frm=frm, to=to)


def halt(code: str, message: str, way: str = "", **extra) -> NoReturn:
    emit({"ok": False, "stop": code, "message": message, "advice": way, **extra})
    sys.exit(1)


def field(name: str) -> str:
    return name.zfill(2) if name.isdigit() else name


def cli(repo: Path, *args: str) -> subprocess.CompletedProcess:
    fieldgit.need("hal2-cli-git")
    return subprocess.run(["hal2-cli-git", *args], cwd=repo, capture_output=True, text=True)


def cli_json(repo: Path, *args: str) -> tuple[int, dict]:
    r = cli(repo, *args)
    try:
        return r.returncode, json.loads(r.stdout)
    except ValueError:
        return r.returncode, {"status": "error", "message": (r.stderr or r.stdout).strip()[-300:] or "no output"}


def sessions(main: Path) -> list[dict]:
    """delete-field's `stop.py list`: the repository's running sessions."""
    r = subprocess.run([sys.executable, str(STOP), "list", "--repo", str(main)], capture_output=True, text=True)
    if r.returncode != 0:
        fieldgit.die(f"stop.py list failed: {(r.stderr or r.stdout).strip()[-300:]}", 2 if r.returncode == 2 else 1)
    return json.loads(r.stdout)


def create_module():
    """create-worktree-session's create.py, imported (its `start` knows which variables a new session must not
    inherit: no second copy of that list here)."""
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("create", CREATE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def cmd_check(a) -> int:
    for tool in ("git", "hal2-cli-git", "hal2-cli-agents"):
        fieldgit.need(tool)
    here = Path(a.repo).resolve()
    main, own = fieldgit.main_checkout(here), fieldgit.own_field(here)
    to = field(a.fields[-1])
    frm = field(a.fields[0]) if len(a.fields) == 2 else own
    if len(a.fields) == 1 and not (len(own) == 2 and own.isdigit()):
        halt("call", f"this session is in '{own}', not a numbered field: name the source, `/transplant <from> <to>`")
    helped = cli(here, "--help")
    if "worktree transplant" not in helped.stdout + helped.stderr:
        halt("no-command", "the installed hal2-cli-git has no `worktree transplant`: it comes with plan 0286's "
             "bring in; nothing was changed", "stop here and tell the user")
    foreign = [s for s in sessions(main) if s["slot"] == frm] if frm != own else []
    if foreign:
        halt("live-session", f"field {frm} has a live session ({foreign[0]['pane_id']}): it is never driven from "
             "another session", f"relay the user's order to it as a decision; it runs `/transplant {to}` itself")
    if to not in fieldgit.fields(main) and create_module().free_gb(main) < a.min_free_gb:
        halt("disk", f"field {to} must be created and fewer than {a.min_free_gb:g} GB are free",
             "prune a field first (the tollman's prune duty), then run the same command again")
    code, dry = cli_json(here, "worktree", "transplant", frm, to, "--dry-run", "--json")
    if dry.get("status") == "refused":
        refused = dry.get("refused") or {}
        reason = refused.get("reason", "")
        halt("refused", refused.get("detail", ""), advice(reason, frm, to), reason=reason,
             files=refused.get("files", []), checks=dry.get("checks", []))
    if dry.get("status") != "ok" or code != 0:
        halt("error", dry.get("message") or f"the dry run exited {code}", advice("error"))
    emit({"ok": True, "from": frm, "to": to, "own": own, "creates": bool((dry.get("would") or {}).get("creates")),
          "would": dry.get("would"), "checks": dry.get("checks", []), "notes": dry.get("notes", [])})
    return 0


def cmd_free(a) -> int:
    fieldgit.need("hal2-cli-agents")
    here = Path(a.repo).resolve()
    main, frm, to = fieldgit.main_checkout(here), field(a.frm), field(a.to)
    stopped = []
    for s in (s for s in sessions(main) if s["slot"] == to):
        r = subprocess.run([sys.executable, str(STOP), "stop", s["pane_id"], "--repo", str(main), "--wait", "15"],
                           capture_output=True, text=True)
        if r.returncode == 0:
            stopped.append(s["pane_id"])
            continue
        why = (json.loads(r.stdout or "{}").get("refused") if r.returncode == 3 else None) or \
            f"did not stop: {(r.stdout + r.stderr).strip()[-300:]}"
        _, ended = cli_json(here, "worktree", "transplant", frm, "--cancel", "--json")
        emit({"freed": False, "refused": why, "pane": s["pane_id"], "cancelled": ended.get("status") == "ok",
              "advice": f"nothing was moved and the transplant is cancelled: tell the user why, and run the same "
                        f"command again once the session in field {to} rests"})
        return 3
    emit({"freed": True, "stopped": stopped})
    return 0


def plan_run(target: Path) -> tuple[str | None, str | None]:
    """The model and effort of the plan CURRENT_PLAN names in `target` (its `run: <model> <effort> <window>`)."""
    slug = pointers(__file__).read(target, "CURRENT_PLAN")  # the git dir's, else plans/ (step 12)
    plan = planread.plan_dir(target, slug) / "plan.md"
    if not slug or "/" in slug or not plan.is_file():
        return None, None
    found = re.search(r"^[Rr]un:[ \t]*(.+)$", plan.read_text(), re.M)
    words = [w.strip("`") for w in found.group(1).split()] if found else []
    model = words[0] if words and words[0] != "-" else None
    if model and len(words) > 2 and words[2] == "1m" and "[" not in model:
        model += "[1m]"
    return model, words[1] if len(words) > 1 and words[1] in EFFORTS else None


def cmd_start(a) -> int:
    for tool in ("git", "hal2-cli-git", "hal2-cli-agents"):
        fieldgit.need(tool)
    here = Path(a.repo).resolve()
    main, to = fieldgit.main_checkout(here), field(a.to)
    _, history = cli_json(here, "worktree", "transplants", "--json")
    newest = next((t for t in history.get("transplants", []) if t.get("to") == to), None)
    if newest is None or newest.get("state") not in OPEN:
        halt("not-driven", f"no transplant into field {to} has been driven (newest: "
             f"{(newest or {}).get('state', 'none')}): no session is started", advice("error"))
    live = [s for s in sessions(main) if s["slot"] == to]
    if live:
        emit({"started": False, "left": live[0]["pane_id"], "slot": to,
              "note": "a session runs there already (the farmer's orphan rule?): left as it is"})
        return 0
    target = fieldgit.fields(main).get(to)
    if target is None:
        fieldgit.die(f"field {to} does not exist")
    model, effort = plan_run(target)
    argv = (["--model", model] if model else []) + (["--effort", effort] if effort else [])
    report = create_module().start(main, to, argv, "/handoff c")
    emit({"started": True, "slot": report.get("slot") or to, "pane": report.get("pane"), "mode": report.get("mode"),
          "worktree": report.get("worktree"), "model": model, "effort": effort,
          "attach": f"hal2-cli-agents attach {main.name}/{to}"})
    return 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0], formatter_class=argparse.RawTextHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("check", "free", "push", "start"):
        s = sub.add_parser(name)
        s.add_argument("--repo", default=".")
        if name == "check":
            s.add_argument("fields", nargs="+", metavar="[from] to")
            s.add_argument("--min-free-gb", type=float, default=50)
        elif name == "start":
            s.add_argument("to")
        else:
            s.add_argument("frm", metavar="from")
            s.add_argument("to")
    s = sub.add_parser("advice")
    s.add_argument("reason")
    s.add_argument("fields", nargs="*", metavar="from to")
    a = p.parse_args(argv)
    if a.cmd == "check" and len(a.fields) > 2:
        p.error("check takes [<from>] <to>")
    if a.cmd == "advice":
        print(advice(a.reason, *(field(f) for f in a.fields[:2])) if len(a.fields) >= 2 else advice(a.reason))
        return 0
    if a.cmd == "push":
        emit(fieldgit.push(Path(a.repo).resolve(), field(a.frm), field(a.to)))
        return 0
    return {"check": cmd_check, "free": cmd_free, "start": cmd_start}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
