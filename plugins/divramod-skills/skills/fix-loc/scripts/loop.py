#!/usr/bin/env python3
"""fix-loc's loop: one tick watches the running servant and, once its plan landed, starts the next unit's.

  loop.py tick   --repo R [--coordinator-model M] [--coordinator-effort E] [--step-model S] [--dry-run] [--json]
                                                            one tick (what the cron job's /fix-loc runs)
  loop.py claim  --repo W --plan <NNNN-slug> [--json]       the servant in checkout W names its plan
  loop.py record --repo R --started|--stopped [--json]      the loop (re)started (cron re-armed) or stopped
  loop.py status --repo R [--json]                          the servant, blocked units, history

The servant is its plan's coordinator: it starts through create-worktree-session's create.py (`--from 30`: a
helper slot without a session and without work) at `--coordinator-model` (`--model`; default claude-sonnet-5-5,
fix-loc's own rule) and `--coordinator-effort` (default medium), and its plan's rows run at `--step-model` (an
Agent tool alias, default sonnet) with medium effort. Each value is the flag, else the one `state.json` keeps under
`settings`, else the default; the tick stores it back. The state is `<state root>/state.json` (scan.state_root;
tick.py documents its fields). `tick --dry-run` decides and prints the next start without starting or writing the
state. Exit 2: a missing tool.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import layout  # noqa: E402
import scan  # noqa: E402
import tick  # noqa: E402

DEFAULTS = {"coordinator_model": "claude-sonnet-5-5", "coordinator_effort": "medium", "step_model": "sonnet"}
EFFORTS = ("low", "medium", "high", "xhigh", "max")
STEP_MODELS = ("haiku", "sonnet", "opus", "fable")  # the Agent tool's aliases (plan 0016's D6)
PROMPT = Path(__file__).resolve().parent.parent / "servant-prompt.md"
CREATE = Path(__file__).resolve().parents[2] / "create-worktree-session" / "scripts" / "create.py"
FINISHED = re.compile(r"^Finished:", re.MULTILINE)


def now_ms():
    return int(time.time() * 1000)


def state_path(repo):
    return scan.state_root(repo) / "state.json"


def load(repo):
    path = state_path(repo)
    state = json.loads(path.read_text()) if path.exists() else {}
    if "worker" in state:  # a state file from before plan 0128 named the servant "worker"
        state.setdefault("servant", state.pop("worker"))
    for key, empty in (("servant", None), ("history", []), ("blocked", {}), ("attempts", {})):
        state.setdefault(key, empty)
    return state


def save(repo, state):
    path = state_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1) + "\n")
    os.replace(tmp, path)


def run_json(args, cwd=None):
    out = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit(f"fix-loc: {' '.join(args[:3])} failed: {out.stderr.strip()}")
    return json.loads(out.stdout)


def main_checkout(repo):
    """The repository's main checkout (the `project` hal2-cli-agents names)."""
    common = layout.git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    return str(Path(common).parent)


def plan_landed(repo, ref, plan):
    """Whether `ref` has `plans/<plan>/plan.md` with its `Finished:` line."""
    if not plan:
        return False
    shown = subprocess.run(["git", "-C", str(repo), "show", f"{ref}:plans/{plan}/plan.md"], capture_output=True, text=True)
    return shown.returncode == 0 and bool(FINISHED.search(shown.stdout))


def current_plan(worktree):
    path = Path(worktree or "", "plans", "CURRENT_PLAN")
    return path.read_text().strip() if worktree and path.exists() else None


def observe(repo, project, servant):
    """What `tick.decide` needs about the running servant, read from hal2 and git."""
    ref = layout.default_branch(repo)
    queue = run_json(["hal2-cli-git", "worktree", "queue", "--json"], cwd=project).get("queue", [])
    plan = servant.get("plan") or current_plan(servant.get("worktree"))
    return {
        "agents": run_json(["hal2-cli-agents", "list", "--json"]),
        "queue": [t for t in queue if not servant.get("worktree") or t.get("worktree") == servant["worktree"]],
        "landed": plan_landed(repo, ref, plan if plan and tick.PLAN_SLUG.match(plan) else None),
        "current_plan": plan,
    }


def settings(state, **given):
    """The loop's coordinator model and effort and step model: each given value, else the stored one, else the
    default; stored back in `state["settings"]`."""
    stored = state.setdefault("settings", {})
    for key, default in DEFAULTS.items():
        stored[key] = given.get(key) or stored.get(key) or default
    return dict(stored)


def fill_prompt(unit, limit, step_model=DEFAULTS["step_model"]):
    names = ", ".join(f"`{f['path']}` ({f['code']})" for f in unit["files"])
    values = {"unit": unit["unit"], "name": unit["unit"].rsplit("/", 1)[-1], "limit": str(limit),
              "files": names, "scripts": str(Path(__file__).resolve().parent), "step_model": step_model}
    text = PROMPT.read_text().strip()
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    return text


def finish(repo, state, now, result):
    """The servant's plan landed: count the unit again, record it, stop the servant's terminal host."""
    servant = state["servant"]
    after = scan.unit_files(repo, servant["unit"], worktree=False)
    over = [f for f in after["files"] if f["code"] > after["limit"]]
    state["history"].append({
        "unit": servant["unit"], "plan": result.get("plan"), "model": servant.get("model"),
        "effort": servant.get("effort"), "step_model": servant.get("step_model"),
        "started_ms": servant["spawned_ms"], "landed_ms": now, "before": servant.get("before", {}),
        "after": {f["path"]: f["code"] for f in after["files"] if f["path"] in servant.get("before", {})},
        "still_over": [f["path"] for f in over],
    })
    note = tick.after_landing(state, servant["unit"], bool(over), now)
    if note:
        result["notify"].append(note)
    if str(servant.get("pane", "")).startswith("t:"):
        subprocess.run(["hal2-cli-agents", "terminal", "kill", servant["pane"][2:]], capture_output=True)
    state["servant"] = None


def watch(repo, state, now, result):
    """Decide about the running servant; True when a next unit may start."""
    servant = state["servant"]
    seen = observe(repo, state["project"], servant)
    decision = tick.decide(state, now, project=state["project"], **seen)
    result.update(decision)
    result["unit"] = servant["unit"]
    if decision.get("plan") and not servant.get("plan"):
        servant["plan"] = decision["plan"]
    if decision["action"] == "landed":
        finish(repo, state, now, result)
        return True
    if decision["action"] == "blocked":
        state["blocked"][servant["unit"]] = now + tick.BLOCK_FOR
        result["notify"].append(f"fix-loc: {servant['unit']} blocked ({decision['reason']}), skipped 7 days")
        state["servant"] = None
        return True
    if decision["action"] == "paused" and not servant.get("paused_notified"):
        servant["paused_notified"] = True
        result["notify"].append(f"fix-loc: paused, {decision['reason']}")
    return False


def spawn_next(repo, state, now, values, dry_run, result):
    found = scan.scan(repo)
    unit = tick.next_unit(found["units"], state, now)
    if unit is None:
        result.update(action="idle", reason="no unit over the limit is free", unit=None)
        return
    prompt = fill_prompt(unit, found["limit"], values["step_model"])
    command = [sys.executable, str(CREATE), "--repo", state["project"], "--from", "30",
               "--model", values["coordinator_model"], "--effort", values["coordinator_effort"],
               "--exact", "--prompt", prompt]
    result.update(action="next", unit=unit["unit"], files=[f["path"] for f in unit["files"]],
                  command=command[:-1] + ["<prompt>"], prompt=prompt, settings=values)
    if dry_run:
        result["dry_run"] = True
        return
    spawned = run_json(command)
    state["servant"] = {
        "unit": unit["unit"], "files": result["files"], "slot": spawned["slot"], "pane": spawned.get("pane"),
        "worktree": spawned.get("worktree"), "plan": None, "model": values["coordinator_model"],
        "effort": values["coordinator_effort"], "step_model": values["step_model"], "spawned_ms": now,
        "before": {f["path"]: f["code"] for f in unit["files"]},
    }
    result["slot"] = spawned["slot"]


def run_tick(repo, model=None, dry_run=False, now=None, effort=None, step_model=None):
    now = now or now_ms()
    state = load(repo)
    values = settings(state, coordinator_model=model, coordinator_effort=effort, step_model=step_model)
    state["project"] = main_checkout(repo)
    state.setdefault("started_ms", now)
    result = {"action": "wait", "reason": "", "notify": [], "rearm": tick.needs_rearm(state, now)}
    subprocess.run(["git", "-C", str(repo), "fetch", "-q", "origin"], capture_output=True)
    if state["servant"] is None or watch(repo, state, now, result):
        spawn_next(repo, state, now, values, dry_run, result)
    if not dry_run:
        save(repo, state)
    return result


def claim(repo, plan):
    state, top = load(repo), layout.git(repo, "rev-parse", "--show-toplevel").strip()
    servant = state["servant"]
    if not servant or Path(servant.get("worktree") or "").resolve() != Path(top).resolve():
        raise SystemExit(f"fix-loc: no fix-loc servant runs in {top}")
    servant["plan"] = plan
    save(repo, state)
    return {"unit": servant["unit"], "plan": plan}


def record(repo, started, stopped):
    state = load(repo)
    if started:
        state["started_ms"] = now_ms()
    if stopped:
        state["stopped_ms"] = now_ms()
    save(repo, state)
    return {"started_ms": state.get("started_ms"), "stopped_ms": state.get("stopped_ms")}


def status(repo):
    state, now = load(repo), now_ms()
    blocked = {unit: until for unit, until in state["blocked"].items() if until > now}
    return {"servant": state["servant"], "blocked": blocked, "history": state["history"][-10:],
            "landed": len(state["history"]), "started_ms": state.get("started_ms"),
            "settings": {**DEFAULTS, **state.get("settings", {})}}


def text_of(command, result):
    if command == "tick":
        line = f"{result['action']}: {result.get('unit') or '-'}  {result.get('reason', '')}".rstrip()
        extra = [f"  {path}" for path in result.get("files", [])] + result["notify"]
        if result.get("command"):
            extra.append("  " + " ".join(result["command"]))
        if result.get("dry_run") and result.get("prompt"):
            extra += ["", result["prompt"]]
        return "\n".join([line, *extra])
    return json.dumps(result, indent=1)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="loop.py")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("tick", "claim", "record", "status"):
        p = sub.add_parser(name)
        p.add_argument("--repo", default=".")
        p.add_argument("--json", action="store_true")
    sub.choices["tick"].add_argument("--coordinator-model", "--model", dest="model")
    sub.choices["tick"].add_argument("--coordinator-effort", dest="effort", choices=EFFORTS)
    sub.choices["tick"].add_argument("--step-model", choices=STEP_MODELS)
    sub.choices["tick"].add_argument("--dry-run", action="store_true")
    sub.choices["claim"].add_argument("--plan", required=True)
    sub.choices["record"].add_argument("--started", action="store_true")
    sub.choices["record"].add_argument("--stopped", action="store_true")
    args = parser.parse_args(argv)
    missing = [tool for tool in ("git", "scc", "hal2-cli-agents", "hal2-cli-git") if shutil.which(tool) is None]
    if missing and args.command == "tick":
        print(f"fix-loc: missing {', '.join(missing)} -> run install-prerequisites.sh", file=sys.stderr)
        return 2
    if args.command == "tick":
        result = run_tick(args.repo, args.model, args.dry_run, effort=args.effort, step_model=args.step_model)
    elif args.command == "claim":
        result = claim(args.repo, args.plan)
    elif args.command == "record":
        result = record(args.repo, args.started, args.stopped)
    else:
        result = status(args.repo)
    print(json.dumps(result, indent=1) if args.json else text_of(args.command, result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
