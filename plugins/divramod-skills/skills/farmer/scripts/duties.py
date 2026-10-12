"""The development lead's, ci's, prs', watch's and autoclear's rules as code (plan 0007 step 3).

Each `<duty>(item, ctx)` scans read-only and plans actions (see tick.py). Templated help is typed into idle
sessions; what needs judgment (a question, a permission prompt, a real CI failure, an unclear stop) becomes a
`wake` item with its evidence. Keys keep a round from repeating what an earlier one did.
"""

import datetime as dt
import re
import sys
from pathlib import Path

import ci_scan
import delegation
import lead_scan
import pr_scan
from tick import act

HERE = Path(__file__).resolve().parent
SKILLS = HERE.parents[1]
sys.path.insert(0, str(SKILLS / "sanity-watch" / "scripts"))
sys.path.insert(0, str(SKILLS / "fix-autoclear" / "scripts"))
import evidence  # noqa: E402  (fix-autoclear)
import scan as watch_scan  # noqa: E402  (sanity-watch)

LEAD = "farmer (development lead)"
# The relayed go (plan 0137): a farmer message whose first line has this form carries the user's own decision, quoted
# from the farmer's session or the log's `decision` entries; the plan and mtm skills accept it for exactly those words.
USER_DECIDED = 'farmer [<id>]: the user decided: "<the user\'s words>"'


def user_decided(ack_id: str, words: str) -> str:
    """The first line of a relayed go."""
    return USER_DECIDED.replace("<id>", ack_id).replace("<the user's words>", words.replace('"', "'"))
TEXT = {
    "no-plan": LEAD + ": write your task into plans/CURRENT_PLAN now: the plan's <NNNN>-<slug>, the shot's "
                      "<shotfile>/<n>/<title-slug>, or a short kebab-case task name (global CLAUDE.md).",
    "context-high": LEAD + ": your context is at {percent}%. Run /handoff now; hal2's autoclear continues you.",
    "continue": LEAD + ": you stopped mid-plan ({plan}). Continue the plan to its end.",
    # A former subservant (a stale plans/LEAD, skills plan 0013) never lands; since skills plan 0016 a plan's steps
    # run in subagents and `plan.py report` is gone: the lead takes the work over, or plans/LEAD is deleted.
    "continue-step": LEAD + ": you stopped mid-step {step} of plan {plan} and hold a stale plans/LEAD of the lead in "
                            "slot {slot}: never land and never edit plan.md; commit your work on your branch, then "
                            "the lead in slot {slot} takes the work over, or delete plans/LEAD.",
    "failed": "Your last turn failed ({why}). Check git status and your last tool result, then continue.",
    "resume": "Your last response was cut off ({error}). Check git status and the result of your last tool call, "
              "then continue where you stopped.",
    "slot-red": "farmer (ci): your branch's CI is red: {workflow} ({jobs}) {url}. Fix it in your plan.",
}
# A last message that just announces the next step: the session stopped by accident, not to wait.
GOING_ON = re.compile(r"\b(next,? I'?ll|now I'?ll|I'?ll now|moving on to|continuing with)\b", re.I)
WAITS = re.compile(r"\b(wait|waiting|once|when it|until|your go|you decide|\?)", re.I)
# CI failures that a rerun fixes: the network, a registry, a lost runner, a cancelled job.
TRANSIENT = re.compile(r"ECONNRESET|ETIMEDOUT|EAI_AGAIN|Could not resolve host|TLS handshake timeout|"
                       r"connection (reset|refused|timed out)|50[234] (Bad Gateway|Service Unavailable|Gateway)|"
                       r"rate limit|The runner has received a shutdown signal|lost communication with the server|"
                       r"The operation was canceled|toomanyrequests", re.I)
DAY = dt.timedelta(days=1)
# A session idle in its plan or waiting for an answer: the wake comes back every hour while it stays (plan 0137).
REWAKE = {"asks", "idle-in-plan"}


def plan_lead(item: dict, ctx: dict, scan: dict | None = None) -> list[dict]:
    scan = scan if scan is not None else lead_scan.scan(ctx["top"], False)
    out = []
    for n in scan.get("needs_help", []):
        kind, slot, pane = n["kind"], n.get("slot") or "-", n.get("pane")
        if slot in ctx.get("told", set()):
            continue
        key, done = f"lead:{n['session']}:{n['since']}", [sys.executable, str(HERE / "lead_scan.py"), "record",
                                                           n["session"], str(n["since"])]
        said = (n.get("said") or "").strip().split("\n\n")[-1]
        text = None
        if kind == "no-plan":
            text = TEXT["no-plan"]
        elif kind == "context-high":
            text = TEXT["context-high"].format(percent=n.get("context_percent"))
        elif kind == "idle-in-plan" and GOING_ON.search(said) and not WAITS.search(said):
            lead = n.get("lead")  # a subservant continues its one step, never the plan to its landing
            if not lead:
                text = TEXT["continue"].format(plan=n.get("plan") or "your plan")
            elif not lead.get("bad"):  # a broken marker names no step: the farmer judges it (a wake)
                text = TEXT["continue-step"].format(**lead)
        elif kind == "failed" and "watch" not in ctx.get("duties", ()):
            text = TEXT["failed"].format(why=n.get("why", "failed"))
        if text is None:
            out.append(act("lead", kind, "wake", slot, key=key, text=f"{kind}: {n.get('why', '')}", evidence=n,
                           **({"window": lead_scan.REWAKE} if kind in REWAKE else {})))
            continue
        out.append(act("lead", kind, "send", slot, pane=pane, text=text, key=key,
                       **({"window": lead_scan.REWAKE} if kind in REWAKE else {})))
        out.append(act("lead", "handled", "run", slot, argv=done + [kind, "--repo", ctx["top"]], text=f"{kind} handled",
                       after=key))
    return out


def plan_ci(item: dict, ctx: dict, scan: dict | None = None, log_failed=None) -> list[dict]:
    scan = scan if scan is not None else ci_scan.scan(ctx["top"], False)
    log_failed = log_failed or (lambda run: ci_scan.run(["gh", "run", "view", str(run), "--log-failed"], ctx["main"]))
    out, slots = [], set(ctx.get("panes", {}))
    for f in scan.get("findings", []):
        kind, run, key = f["kind"], f["run"], f"ci:{f['run']}"
        record = [sys.executable, str(HERE / "ci_scan.py"), "record", str(run)]
        if kind == "queued-wake":
            # Deterministic: the wake tool is a no-op for a running runner; again after 10 min while still queued.
            out.append(act("ci", kind, "run", "-", key=f"ci-wake:{run}", window=600,
                           argv=["bash", f["tool"], "start"], text=f["why"]))
        elif kind == "main-red":
            tail = (log_failed(run) or "")[-20000:]
            transient = TRANSIENT.search(tail)
            if transient:
                out.append(act("ci", "rerun", "run", "-", key=key, argv=["gh", "run", "rerun", str(run), "--failed"],
                               text=f"reran {f['workflow']} (transient: {transient.group(0)})"))
                out.append(act("ci", "handled", "run", "-", argv=record + ["rerun --failed", "--repo", ctx["top"]],
                               after=key))
            else:
                out.append(act("ci", "main-red", "delegate", "-", key=key, text=f"main is red: {f['why']}",
                               brief={"finding": f, "log_tail": tail[-4000:]}))
        elif kind == "slot-red" and f["branch"] in slots:
            text = TEXT["slot-red"].format(workflow=f["workflow"], jobs=", ".join(f.get("failed_jobs", [])), url=f["url"])
            out.append(act("ci", kind, "send", f["branch"], pane=ctx["panes"][f["branch"]], text=text, key=key))
            out.append(act("ci", "handled", "run", f["branch"], argv=record + ["told the slot", "--repo", ctx["top"]],
                           after=key))
        else:
            out.append(act("ci", kind, "wake", f.get("branch") or "-", key=key, text=f["why"], evidence=f))
    return out


def plan_watch(item: dict, ctx: dict, incidents: list[dict] | None = None) -> list[dict]:
    if incidents is None:
        state, at = watch_scan.load_state(), watch_scan.now_ms()
        agents = watch_scan.run_json("hal2-cli-agents", "list", "--json", default=[]) or []
        orphans = watch_scan.run_json("hal2-cli-agents", "terminal", "orphans", "--json", default=[]) or []
        events = watch_scan.chronicle_events(at - 24 * 3600 * 1000)
        found = watch_scan.find_incidents(ctx["main"], agents, events, orphans, state, at)
        incidents = [i for i in found if i["id"] not in state.get("handled", {})]
    out = []
    for i in incidents:
        slot, action = i.get("slot") or "-", i["action"]
        record = [sys.executable, str(SKILLS / "sanity-watch/scripts/scan.py"), "record", i["id"]]
        landing = slot in ctx.get("landing", set())
        if action == "resume" and i.get("pane") and not landing:
            error = (i["evidence"].get("api_error") or {}).get("text") or i["name"]
            out.append(act("watch", "resume", "send", slot, pane=i["pane"], states=["failed"], key=f"watch:{i['id']}",
                           text=TEXT["resume"].format(error=error[:160])))
            out.append(act("watch", "handled", "run", slot, argv=record + ["resume", "--session", i["session"]],
                           after=f"watch:{i['id']}"))
        elif action == "count":
            out.append(act("watch", "handled", "run", slot, argv=record + ["count", "--note", i.get("reason", "")]))
        elif action in ("escalate", "handover"):
            out.append(act("watch", action, "notify", slot, key=f"watch:{i['id']}",
                           text=f"sanity-watch: {slot} {i['name']}: {i.get('reason') or action}"))
            out.append(act("watch", "handled", "run", slot, argv=record + [action], after=f"watch:{i['id']}"))
        elif action != "wait":
            out.append(act("watch", action, "wake", slot, key=f"watch:{i['id']}", text=f"{i['class']} {i['name']}",
                           evidence=i))
    return out


def plan_autoclear(item: dict, ctx: dict, problems: list[dict] | None = None, off: set[str] | None = None
                   ) -> list[dict]:
    """fix-autoclear's doctor as code: a resting session's failed autoclear continued, each failure class delegated
    once. A session whose autoclear the user switched off (`off`, evidence.autoclear_off) is never touched (plan 0011)."""
    problems = problems if problems is not None else evidence.doctor_items(1.5)
    off = off if off is not None else set(evidence.off_sessions())
    out, agents = [], ctx.get("agents_by_pane", {})
    for p in problems:
        if p.get("what") == "blocked":
            continue  # a person's draft blocks the job (hal2 plan 0139): sanity-watch's F13 wakes the farmer
        a = agents.get(p.get("pane")) or {}
        if p.get("session") in off or (a.get("session_id") == p.get("session") and evidence.autoclear_off(agent=a)):
            continue  # the user's own switch, not a failure
        slot = a.get("slot") or "-"
        if p.get("session") and a.get("session_id") == p["session"] and a.get("state") in ("idle", "done", "sleeping"):
            out.append(act("autoclear", "continue", "run", slot, key=f"autoclear:{p['session']}",
                           argv=["hal2-cli-agents", "clear-and-continue", "--pane", p["pane"], "--session",
                                 p["session"], "--await-handoff", "--detach"],
                           text=f"clear-and-continue for {p['who']} (autoclear {p.get('reason') or 'gave up'})"))
        reason = p.get("reason") or "attempts"
        out.append(act("autoclear", "fix", "delegate", slot, key=f"autoclear-fix:{reason}",
                       text=f"/fix-autoclear {slot}: {p.get('message') or reason}", brief={"problem": p}))
    return out


DEPENDABOT_TASK = (
    "Apply these Dependabot updates in your slot and land them together as one plan:\n\n"
    "- Merge each PR's branch into your slot branch as it is, oldest first (`git fetch origin <head>` then "
    "`git merge --no-ff origin/<head>`), resolving conflicts in the merge. Never rewrite Dependabot's commits: GitHub "
    "marks a PR merged once its head commit reaches main.\n"
    "- Fix what each update breaks (build, tests, lint, a major version's migration) in commits of your own, and "
    "regenerate what the repository derives from its dependencies (its CLAUDE.md names it, e.g. `cargo hakari`).\n"
    "- An update that cannot be done now (it needs a product decision or an upstream fix): leave its branch out, close "
    "its PR with `gh pr close <n> --comment \"<why>\"` and record why in the plan.\n"
    "- Never merge a PR on GitHub and never push to a `dependabot/` branch: main moves only by your landing.")
DEPENDABOT_DONE = ("Every PR listed is merged by your landing (GitHub shows it merged, or Dependabot closes it as up to "
                   "date) or closed by you with its reason, and the landing's gates were green.")
CLOSE = {"superseded": "Closed by the farmer: main already holds this update.",
         "land-stale": "Closed by the farmer: this landing's slot has no ticket in the merge queue and nothing beyond "
                       "main; a new landing opens its own PR."}


def plan_prs(item: dict, ctx: dict, scan: dict | None = None, held: dict | None = None) -> list[dict]:
    """The open PRs kept clean: Dependabot's applied by one servant per batch, PRs main holds closed, a leftover
    landing PR closed (its slot holds nothing) or judged, any other PR the user's."""
    scan = scan if scan is not None else pr_scan.scan(ctx["top"])
    held = held if held is not None else delegation.ledger(ctx["main"])
    busy = any(k.startswith("prs:dependabot") and e.get("state") in ("running", "waiting") for k, e in held.items())
    out = []
    for f in scan.get("findings", []):
        kind = f["kind"]
        if kind == "dependabot" and not busy:
            nums = f["numbers"]
            out.append(act("prs", kind, "delegate", "-", key="prs:dependabot:" + "-".join(map(str, nums)),
                           text="Apply the open Dependabot PRs " + ", ".join(f"#{n}" for n in nums),
                           task=DEPENDABOT_TASK, done=DEPENDABOT_DONE, brief={"prs": f["prs"]}))
        elif kind == "superseded" or (kind == "land-stale" and not f.get("ahead")):
            out.append(act("prs", kind, "run", f.get("slot") or "-", key=f"prs:close:{f['number']}", text=f["why"],
                           argv=["gh", "pr", "close", str(f["number"]), "--comment", CLOSE[kind]]))
        elif kind == "land-stale":
            out.append(act("prs", kind, "wake", f["slot"], key=f"prs:{kind}:{f['number']}", text=f["why"], evidence=f))
        elif kind == "other":
            out.append(act("prs", kind, "notify", "-", key=f"prs:other:{f['number']}",
                           text=f"open PR {f['why']}: {f['url']}"))
    return out
