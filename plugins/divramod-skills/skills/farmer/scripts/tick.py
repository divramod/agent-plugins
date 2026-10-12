"""The farmer's round frame as code: what `farmer.py tick` plans and does each round.

A round is planned as actions (plain dicts), then carried out by `execute`, so a dry run plans the same
round and does nothing. An action:

  {"duty": "frame"|<duty>|"task", "kind": <what>, "slot": <slot or "-">, "do": <how>, ...}

with `do` one of
  run     argv: run a command (the result decides follow-ups, see `stay_current`)
  ran     name: due.py's run record for a duty or task
  record  text: a log line only
  send    pane, text: a templated message typed into an idle session's empty prompt (deliver.py); refused
          (busy, a draft, a dialog) it becomes a `relay`
  relay   text: a templated message the woken session sends verbatim with SendMessage (busy sessions)
  delegate text, brief: a fix for a servant (delegation.py starts it; a failed start wakes the model)
  wake    text: an item that needs the model (wake.py hands these to the woken session)
  notify  text: a notice for the user (the woken session pushes them, batched)

An action may carry a `key` (the log keeps it) and a `window` in seconds (default a week): `fresh` drops an action
whose key was logged within its window, and an action `after` a dropped key with it. Messages and wakes for a slot
that waits for the user (an `ask` in the log with no `answered` after it) are dropped too, and so are
messages and wakes about the farmer's own slot (its session is the one woken).

Every executed action except `ran` goes into the farmer's log with `"by": "tick"`.

The round times itself (plan 0011): `out["timing"]` holds the seconds of the frame (merge-from-main, the role edit),
the planners' shared context, each due item (its planning plus its actions' execution), acks, delegations, wake and
summary, in round order; farmer.py prints them as one `timing:` line (tick.log).
"""

import datetime as dt
import json
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

import acks
from logstate import paused, read_log, waiting_for_user  # noqa: F401  (tick.<name> for callers)
import delegation
import deliver
import due
import gh_runs
import mtm_scan
import roles
import wake

OFFLINE = 75  # EX_TEMPFAIL: a recheck that could not tell (this machine is offline) is not a failure

ROLE = roles.ROLE_FILE
ROLE_FILES = (roles.ROLE_FILE, roles.ROLE_IGNORE)  # what the farmer slot may change
MFM = ["hal2-cli-git", "worktree", "merge-from-main", "--json"]


def sh(argv: list[str], cwd: str, timeout: int = 900) -> tuple[int, str]:
    try:
        p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, str(e)


def git(repo: str, *args: str) -> str:
    """git's stdout (leading whitespace kept: porcelain status columns), "" on failure."""
    try:
        p = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return p.stdout.rstrip("\n") if p.returncode == 0 else ""


def default_ref(repo: str) -> str:
    return git(repo, "symbolic-ref", "--short", "refs/remotes/origin/HEAD") or "origin/main"


def slot_problem(repo: str) -> str | None:
    """None when `repo` is the farmer slot (`farmer-<project>`) holding nothing but changes of its role files
    (ROLE_FILES), else why not."""
    top = git(repo, "rev-parse", "--show-toplevel")
    if top and Path(top).name == roles.ROLE:
        return (f"the farmer slot {top} is not migrated to {roles.slot_name(top)}: "
                f"run `farmer.py migrate --repo {top}`")
    if not top or not roles.is_slot(top):
        slot = roles.slot_name(top or repo)
        return f"not the farmer slot {slot} ({top or repo}): start me with `hal2-cli-git worktree run {slot} --agent claude`"
    changed = set(git(top, "diff", "--name-only", f"{default_ref(top)}...HEAD").split())
    changed |= {line[3:].strip() for line in git(top, "status", "--porcelain", "-uall").splitlines()}
    other = sorted(changed - {*ROLE_FILES, ""})
    return f"the farmer slot holds more than {ROLE}: {', '.join(other)}" if other else None


@contextmanager
def timed(timing: dict, name: str):
    """Add the block's wall time to `timing[name]` (seconds, insertion order kept)."""
    start = time.monotonic()
    try:
        yield
    finally:
        timing[name] = round(timing.get(name, 0.0) + time.monotonic() - start, 2)


def act(duty: str, kind: str, do: str, slot: str = "-", **fields) -> dict:
    return {"duty": duty, "kind": kind, "slot": slot, "do": do, **fields}


def role_edit(top: str) -> tuple[list[dict], bool]:
    """The user's uncommitted role file edit (ROLE_FILES): commit it when valid. Returns (actions, round may go on)."""
    if not git(top, "status", "--porcelain", "-uall", "--", *ROLE_FILES):
        return [], True
    path = Path(top) / ROLE
    if not path.exists():
        return [act("frame", "role-gone", "notify", text=f"{ROLE} was deleted in the farmer slot: nothing runs")], False
    problems = due.schedule(path.read_text())[2]
    if problems:
        return [act("frame", "role-invalid", "notify",
                    text=f"{ROLE} edit not committed, nothing runs: " + "; ".join(problems))], False
    files = [f for f in ROLE_FILES if (Path(top) / f).exists()]
    return [act("frame", "role-add", "run", argv=["git", "add", "--", *files], text=f"staged the user's {ROLE} edit"),
            act("frame", "role-commit", "run", argv=["git", "commit", "-q", "-m", "farmer-role: the user's change",
                                                    "--", *files], text=f"committed the user's {ROLE} edit")], True


def due_items(top: str, now: dt.datetime | None = None, all_due: bool = False) -> tuple[list[dict], dict, list[str]]:
    """(the due duties and tasks, the settings, problems) from the slot's role file (ROLE); `all_due` counts every
    opted-in item due (a dry run's measurement, farmer.py tick --all-due)."""
    path = Path(top) / ROLE
    if not path.exists():
        return [], {}, [f"no {ROLE}: nothing is opted in"]
    items, settings, problems = due.schedule(path.read_text())
    if problems:
        return [], settings, problems
    now, last = now or dt.datetime.now(), due.last_runs(top)
    rows = [{"name": n, "cron": c, "last": last[n].isoformat() if n in last else None}
            for n, c in items.items() if all_due or due.is_due(c, last.get(n), now)]
    return rows, settings, []


def item_actions(item: dict, handlers: dict, ctx: dict) -> list[dict]:
    """The planned actions of one due duty or task, ending with its run record. A handler gets the item and
    `ctx` (top, main, now, dry, log: the farmer's log entries) and returns planned actions."""
    kind, _, name = item["name"].partition(":")
    handler = handlers.get(item["name"]) or handlers.get(f"{kind}:*")
    planned = handler(item, ctx) if handler else [
        act(name if kind == "duty" else "task", "no-handler", "wake",
            text=f"{item['name']} has no tick handler yet: run it as the skill says")]
    return planned + [act(name if kind == "duty" else "task", "ran", "ran", name=item["name"])]


WEEK = 7 * 24 * 3600


def fresh(actions: list[dict], log: list[dict], now: dt.datetime) -> list[dict]:
    """The actions an earlier round has not done yet (see the module doc)."""
    seen: dict[str, dt.datetime] = {}
    for e in log:
        if e.get("key"):
            t = dt.datetime.fromisoformat(e["at"])
            seen[e["key"]] = max(t, seen.get(e["key"], t))
    asked, dropped, out = waiting_for_user(log), set(), []
    for a in actions:
        key = a.get("key")
        old = key and key in seen and (now - seen[key]).total_seconds() < a.get("window", WEEK)
        talk = a["do"] in ("send", "relay", "wake")
        # An open ask holds what the farmer would type; a lead wake still reaches it: it finds the answer (plan 0137).
        judge = a["do"] == "wake" and a.get("duty") == "lead"
        held = (a["slot"] in asked and ((talk and not judge) or a["kind"] == "orphan")) \
            or (roles.is_farmer_label(a["slot"]) and talk)
        if old or held or a.get("after") in dropped:
            dropped.add(key)
            continue
        out.append(a)
    return out


WAITS = {("lead", "idle-in-plan"), ("watch", "judge")}  # a stop that only means "waits in the queue or a pause"


def waiting_noise(actions: list[dict], waiting: set[str]) -> list[dict]:
    """Drop the wakes that only say a slot waits: idle in its plan or ended early while it is queued or paused."""
    return [a for a in actions if not (a["do"] == "wake" and (a["duty"], a["kind"]) in WAITS and a["slot"] in waiting)]


def context(top: str, main: str, items: dict, now: dt.datetime, dry: bool) -> dict:
    """What every duty's planner reads: the log, the opted-in duties, the agents by pane, each slot's pane and the
    slots whose landing runs or holds the queue (never touched)."""
    agents = deliver.cli("list", "--json")[1]
    try:
        data = json.loads(agents)
    except json.JSONDecodeError:
        data = []
    rows = data.get("list", []) if isinstance(data, dict) else data
    queue = mtm_scan.run_json(["hal2-cli-git", "worktree", "queue", "--json"], main) or {}
    tickets = queue.get("queue", [])
    landing = {t.get("slot") for t in tickets if t.get("state") == "active"
               or (t.get("hold") or {}).get("reason") == "reserved"}
    return {"top": top, "main": main, "now": now, "dry": dry, "log": read_log(main),
            "duties": {n.split(":", 1)[1] for n in items if n.startswith("duty:")},
            "agents_by_pane": {a.get("pane_id"): a for a in rows},
            "panes": {a["slot"]: a.get("pane_id") for a in rows if a.get("slot") and a.get("checkout")
                      and Path(a["checkout"]).parent == Path.home() / ".hal/git/worktree" / Path(main).name},
            "landing": landing, "waiting": {t.get("slot") for t in tickets} | paused(read_log(main), now)}


def plan_round(top: str, handlers: dict, now: dt.datetime | None = None, dry: bool = True,
               timing: dict | None = None, all_due: bool = False) -> dict:
    """Plan everything after the frame's git work: the due items and their actions, each tagged with its `item`
    (whose time its execution adds to)."""
    timing = timing if timing is not None else {}
    items, settings, problems = due_items(top, now, all_due)
    if problems:
        return {"due": [], "settings": settings, "actions": [act("frame", "role-invalid", "notify",
                                                                 text="; ".join(problems))], "stop": True}
    main = mtm_scan.main_checkout(top)
    with timed(timing, "context"):
        ctx = context(top, main, due.schedule((Path(top) / ROLE).read_text())[0], now or dt.datetime.now(), dry)
    actions = []
    for item in items:
        with timed(timing, item["name"]):
            planned = waiting_noise(fresh(item_actions(item, handlers, ctx), ctx["log"], ctx["now"]), ctx["waiting"])
        ctx.setdefault("told", set()).update(a["slot"] for a in planned if a["do"] in ("send", "relay"))
        actions += [{**a, "item": item["name"]} for a in planned]
    with timed(timing, "acks"):
        actions += [{**a, "item": "acks"} for a in fresh(acks.plan(ctx["log"], ctx["now"], ctx["panes"]),
                                                          ctx["log"], ctx["now"])]
    return {"due": items, "settings": settings, "actions": actions, "stop": False}


def execute(a: dict, top: str, main: str, out: dict) -> None:
    """Carry out one planned action; wake and notify items are collected in `out`."""
    if a["do"] == "ran":
        due.record_run(top, a["name"], out.get("now"))
        return
    if a["do"] == "run":
        code, text = sh(a["argv"], a.get("cwd") or top)
        a["exit"], a["output"] = code, text[-2000:]
        for follow in a.get("on_fail", []) if code and code != OFFLINE else []:
            execute(follow, top, main, out)
    if a["do"] == "send":
        acks.stamp_send(a, main)  # an id and the ack asked for, also when it falls back to a relay (plan 0137)
        states = set(a.get("states", ())) | deliver.READY
        refused = deliver.send(a["pane"], a["text"], states) if a.get("pane") else "no session"
        if refused:
            a.update(do="relay", why=f"{a.get('why', '')} not typed: {refused}".strip())
    if a["do"] == "delegate":  # delegation.delegate logs it once it is placed
        out.setdefault("delegate", []).append(a)
        return
    if a["do"] in ("wake", "notify", "relay"):
        out.setdefault(a["do"], []).append(a)
    note = a.get("why", "") + (f" (exit {a['exit']})" if a.get("exit") else "")
    mtm_scan.log(main, {"kind": a["kind"], "slot": a["slot"], "what": a.get("text") or " ".join(a.get("argv", [])),
                        "note": note, "by": "tick", "duty": a["duty"], "do": a["do"], "key": a.get("key", "")})


def stay_current(top: str, main: str, out: dict) -> None:
    """Merge the default branch into the farmer slot the way /mfm does; a failure needs the model."""
    a = act("frame", "stay-current", "run", argv=MFM, text="merge-from-main in the farmer slot")
    execute(a, top, main, out)
    if a["exit"]:
        try:
            status = json.loads(a["output"].splitlines()[-1]).get("status", "error")
        except (ValueError, IndexError, AttributeError):
            status = "error"
        execute(act("frame", "mfm-failed", "wake", text=f"merge-from-main in the farmer slot: {status}",
                    evidence=a["output"]), top, main, out)


def slot_state(main: str) -> dict[str, dict]:
    """Each worktree slot's CURRENT_PLAN and commits not on main (what the delegation follow-up reads)."""
    out = {}
    for w in mtm_scan.worktrees(main):
        plan = Path(w["path"]) / "plans/CURRENT_PLAN"
        out[Path(w["path"]).name] = {"plan": plan.read_text().strip() if plan.exists() else "",
                                     "ahead": mtm_scan.unmerged(w["path"], "main")}
    return out


def delegate_all(main: str, out: dict, dry: bool, now: dt.datetime) -> None:
    """Place this round's delegations (planned ones in a dry run), then follow up on the running servants."""
    settings = out.get("settings") or {}
    limit, values = delegation.parse_limit(settings.get("servant_limit")), delegation.servant_values(settings)
    todo = [a for a in out["planned"] if a["do"] == "delegate"] if dry else out.get("delegate", [])
    out["delegations"] = [delegation.delegate(a, main, limit, dry, now, values) for a in todo]
    out["delegations"] += delegation.follow_up(main, slot_state(main), limit, dry, now, values)


def summarize(main: str, top: str, out: dict) -> None:
    """The round's summary from the log: a file of its own when the round did something, latest.md always."""
    snap = mtm_scan.snapshot(top, 24, fetch=False)  # the round's merge-from-main fetched origin
    logged = [a for a in out["done"] if a["do"] != "ran"]
    notes = "\n".join(f"- {a['duty']} {a['kind']} {a['slot']}: {a.get('text', '')}" for a in logged) or "quiet"
    if logged or snap["findings"]:
        out["summary"] = str(mtm_scan.write_summary(main, snap, notes))
        return
    latest = mtm_scan.summary_dir(main) / "latest.md"
    latest.write_text(mtm_scan.render_summary(snap, [], [], notes))
    out["summary"] = str(latest)


def run(repo: str, dry: bool, handlers: dict, now: dt.datetime | None = None, all_due: bool = False) -> dict:
    """One round. Dry: plan only, touch nothing. Returns the round as data (also what `--json` prints)."""
    timing: dict[str, float] = {}
    out = {"dry": dry, "now": now, "wake": [], "notify": [], "done": [], "planned": [], "timing": timing}
    start = time.monotonic()
    problem = slot_problem(repo)
    if problem:
        out.update(stop=True, problem=problem)
        return out
    with timed(timing, "frame"):
        top = git(repo, "rev-parse", "--show-toplevel")
        main = mtm_scan.main_checkout(top)
        out["planned"].append(act("frame", "stay-current", "run", argv=MFM, text="merge-from-main in the farmer slot"))
        if not dry:
            stay_current(top, main, out)
            out["done"].append(out["planned"][0])
        edit, go_on = role_edit(top)
    with gh_runs.round(gh_runs.cache_dir(mtm_scan.state_dir(main))) as out["gh"]:
        rest(out, top, main, handlers, now, dry, all_due, edit, go_on)
    timing["total"] = round(time.monotonic() - start, 2)
    return out


def rest(out: dict, top: str, main: str, handlers: dict, now: dt.datetime | None, dry: bool, all_due: bool,
         edit: list[dict], go_on: bool) -> None:
    """The round after its frame: plan, execute, delegate, wake, summarize (inside one gh_runs round)."""
    timing = out["timing"]
    out["planned"] += edit
    rnd = plan_round(top, handlers, now, dry, timing, all_due) if go_on else {"due": [], "settings": {}, "actions": [],
                                                                              "stop": True}
    out["planned"] += rnd["actions"]
    out.update(due=rnd["due"], settings=rnd["settings"], stop=rnd["stop"])
    if not dry:
        for a in edit + rnd["actions"]:
            with timed(timing, a.get("item", "frame")):
                execute(a, top, main, out)
            out["done"].append(a)
    if go_on:
        with timed(timing, "delegations"):
            delegate_all(main, out, dry, now or dt.datetime.now())
    with timed(timing, "wake"):
        if dry:
            out["wake_items"] = wake.items({k: [a for a in out["planned"] if a["do"] == k] for k in wake.KINDS}
                                           | {"delegations": out.get("delegations", [])})
        else:
            out["woke"] = wake.hand_over(top, main, out, now or dt.datetime.now())
    if not dry:
        with timed(timing, "summary"):
            summarize(main, top, out)


def timing_line(timing: dict, gh: dict | None = None) -> str:
    """`timing: frame 2.1s, duty:mtm 3.4s, ..., total 9.8s; gh 2 list, 3 view, 5 cached`: where the round's time
    went (tick.log) and the gh calls it made (gh_runs)."""
    line = "timing: " + ", ".join(f"{name} {secs:.1f}s" for name, secs in timing.items())
    return line + (f"; gh {gh['list']} list, {gh['view']} view, {gh['cached']} cached" if gh else "")
