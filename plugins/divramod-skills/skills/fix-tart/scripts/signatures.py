"""The known cases' signatures (cases.md), matched against what sources.py read. Pure: no IO.

A context is a dict: now, daemon [(time, line)] (the VM's and supervisor's lines; daemon_all: every line), journal [(time, line)] or None, tasks [{name, start,
end, lines}], pmset [(time, kind, text)] or None, vm (the `vms list` row) or None.
Each finding: {case, slug, at, detail}; `case` is the number of its case in cases.md.
"""

import re
from datetime import timedelta

AUTH = re.compile(r"HTTP 401|Requires authentication|Not Found \(HTTP 404\)")
BOOT = re.compile(r"^boot: ([\d.]+)s")
DEAD_AFTER = timedelta(minutes=5)  # a start's last line older than this, the VM not running: dead
SLOW_BOOT = 300.0  # seconds; hal2-vm's DEFAULT_BOOT_TIMEOUT
PARK_WAKE = timedelta(minutes=10)  # a wake this soon after a park: a lane lost its VM between jobs
PARK = "mac vm runner off (park)"
WAKE = "mac vm runner on (wake)"
RESTARTED = "mac vm runner restarted"
GAVE_UP = "mac vm: start still not online"
LABELS = "(mac_vm.labels) lacks"
HELD = "currently running a job and cannot be deleted"  # GitHub's 422 on a dead clone's busy runner
KILL_WITHIN = timedelta(seconds=20)  # a job task's last write this soon after a watchdog restart: it tore the job down
STAND_IN = "still holds a job on GitHub"  # hal2-vm registered a stand-in for it (the fix)
SECRETS_WAIT = "the secrets did not resolve within"  # a boot waited its whole bound for hal2-secrets (case 8)
KEPT = "env: kept from"  # the boot took the secrets kept from before (plan 0391 step 11's fix)
AGAIN = "again in this clone"  # a runner clone took its run's next VM job (plan 0391 step 11)
# The literal pieces of hal2's code the needles above and the task-log reading depend on (selfcheck greps
# hal2's Rust sources for each: one gone means a signature reads nothing).
FRAGMENTS = ["registering ", "booted in ", "copy in", "mac vm runner ", "off (park)", "on (wake)",
             RESTARTED, GAVE_UP, LABELS, STAND_IN, "mac kept awake", "mac may sleep again",
             SECRETS_WAIT, KEPT, AGAIN, "the clone goes", "got no job within"]


def fmt(dt):
    return dt.strftime("%H:%M:%S") if dt else "-"


def msg(line):
    """A log line without its time stamp."""
    return re.sub(r"^\S+\s+", "", line)


def gh_auth(ctx):
    hits = [(t, l) for t, l in ctx.get("daemon_all", ctx["daemon"]) if AUTH.search(l)]
    tasks = [t["name"][:8] for t in ctx["tasks"] if any(AUTH.search(l) for l in t["lines"])]
    if not hits and not tasks:
        return []
    n401 = sum(1 for _, l in hits if "401" in l or "Requires authentication" in l)
    detail = (f"gh unauthenticated: {n401} lines HTTP 401, {len(hits) - n401} lines HTTP 404 in the daemon log"
              + (f" ({fmt(hits[0][0])} to {fmt(hits[-1][0])})" if hits else "")
              + (f"; registration failed in task {', '.join(tasks)}" if tasks else ""))
    return [{"case": 1, "slug": "gh-auth", "at": hits[0][0] if hits else ctx["tasks"][0]["start"],
             "detail": detail}]


def boot_seconds(lines):
    for line in lines:
        m = BOOT.match(line)
        if m:
            return float(m.group(1))
    return None


def dead_starts(ctx):
    out = []
    running = (ctx["vm"] or {}).get("state") == "running"
    for task in ctx["tasks"]:
        last = task["lines"][-1] if task["lines"] else ""
        booted = any(l.startswith("booted in ") for l in task["lines"])
        boot = boot_seconds(task["lines"])
        hung = last.startswith("copy in:") or last.startswith("$ tart run")
        if hung and not running and ctx["now"] - task["end"] > DEAD_AFTER:
            out.append({"case": 2, "slug": "dead-start", "at": task["end"],
                        "detail": f"task {task['name'][:8]} stopped at `{last}` since {fmt(task['end'])}, "
                                  f"the VM is {(ctx['vm'] or {}).get('state', 'unknown')}"})
        if boot is not None and boot > SLOW_BOOT and not booted:
            out.append({"case": 2, "slug": "slow-boot", "at": task["start"],
                        "detail": f"task {task['name'][:8]} (started {fmt(task['start'])}): boot {boot:.0f}s, "
                                  f"never `booted in`"})
    return out


def watchdog(ctx):
    out = []
    for t, line in ctx["daemon"]:
        if RESTARTED in line:
            out.append({"case": 2, "slug": "watchdog-restart", "at": t, "detail": f"the watchdog acted: {msg(line)}"})
        elif GAVE_UP in line:
            out.append({"case": 2, "slug": "watchdog-gave-up", "at": t, "detail": f"the watchdog gave up: {msg(line)}"})
    return out


def slept(ctx):
    out = []
    for at, kind, text in ctx["pmset"] or []:
        if kind != "Sleep":
            continue
        busy = [t["name"][:8] for t in ctx["tasks"] if t["start"] <= at <= t["end"]]
        if busy:
            out.append({"case": 3, "slug": "slept", "at": at,
                        "detail": f"the Mac slept at {fmt(at)} while runner task {', '.join(busy)} ran ({text[:60]})"})
    return out


def park_wake(ctx):
    events = []
    for t, line in list(ctx["daemon"]) + list(ctx["journal"] or []):
        kind = "park" if PARK in line else "wake" if WAKE in line else None
        if kind and not any(k == kind and abs((t - e).total_seconds()) < 5 for e, k in events):
            events.append((t, kind))
    events.sort()
    out = []
    for (t1, k1), (t2, k2) in zip(events, events[1:]):
        if k1 == "park" and k2 == "wake" and t2 - t1 <= PARK_WAKE:
            out.append({"case": 4, "slug": "park-wake", "at": t1,
                        "detail": f"parked {fmt(t1)}, woken again {fmt(t2)} ({int((t2 - t1).total_seconds())} s)"})
    return out


def labels(ctx):
    hits = [(t, l) for t, l in ctx["daemon"] if LABELS in l]
    if not hits:
        return []
    return [{"case": 5, "slug": "labels", "at": hits[0][0], "detail": msg(hits[-1][1])}]


def held_runner(ctx):
    """Case 6: GitHub keeps a dead clone's fixed runner busy; the starts fail on its removal or register a stand-in."""
    out = []
    for slug, needle in (("held-runner", HELD), ("stand-in", STAND_IN)):
        hits = [t for t in ctx["tasks"] if any(needle in l for l in t["lines"])]
        if hits:
            out.append({"case": 6, "slug": slug, "at": hits[0]["start"],
                        "detail": f"{len(hits)} runner tasks: {needle} ({fmt(hits[0]['start'])} to {fmt(hits[-1]['start'])})"})
    return out


def watchdog_kill(ctx):
    """Case 7: a watchdog restart tore down a clone whose runner was running a GitHub job."""
    restarts = [t for t, line in ctx["daemon"] if RESTARTED in line]
    out = []
    for t in ctx["tasks"]:
        job = next((l for l in t["lines"] if "Running job: " in l), None)
        hit = next((r for r in restarts if t["start"] <= r <= t["end"] <= r + KILL_WITHIN), None)
        if job and hit:
            out.append({"case": 7, "slug": "watchdog-kill", "at": hit,
                        "detail": f"the restart at {fmt(hit)} tore down task {t['name'][:8]} mid-job ({job.split('Running job: ')[-1]})"})
    return out


def secrets_wait(ctx):
    """Case 8: boots that waited their whole bound for hal2-secrets (nothing kept, a slow listing or gpg)."""
    hits = [t for t in ctx["tasks"] if any(SECRETS_WAIT in line for line in t["lines"])]
    if not hits:
        return []
    return [{"case": 8, "slug": "secrets-wait", "at": hits[0]["start"],
             "detail": f"{len(hits)} runner tasks waited for their secrets ({fmt(hits[0]['start'])} to "
                       f"{fmt(hits[-1]['start'])}): {SECRETS_WAIT} ..."}]


def jobless(ctx):
    """Case 9: clones that ended with no GitHub job: before their runner ran (a restart, the secrets bound) or
    with it listening (a park, a start whose job went elsewhere)."""
    def without_job(lines):
        # A boot that never ended or took past the bound is case 2's.
        boot = boot_seconds(lines)
        booted = boot is not None and boot < SLOW_BOOT
        ran = any(line.startswith("command: ") for line in lines)
        listened = any("Listening for Jobs" in line for line in lines)
        return booted and not any("Running job: " in line for line in lines) and (not ran or listened)
    hits = [t for t in ctx["tasks"] if t.get("end") and without_job(t["lines"])]
    if not hits:
        return []
    names = ", ".join(t["name"][:8] for t in hits[:5])
    return [{"case": 9, "slug": "jobless", "at": hits[0]["start"],
             "detail": f"{len(hits)} VMs booted and ran no job ({names})"}]


def find(ctx):
    """Every known case's finding in the context, by case number then time."""
    found = []
    for check in (gh_auth, dead_starts, watchdog, slept, park_wake, labels, held_runner, watchdog_kill,
                  secrets_wait, jobless):
        found += check(ctx)
    return sorted(found, key=lambda f: (f["case"], f["at"]))
