"""The passes of the important interrupt's stop, each measured (plan 0585 D7); interrupt.py's `stop` runs them.

In order: every live session told (source 5: the sessions of every farm, the other farms' farmers among them),
hal2-daemon frozen (source 3), the CI VMs stopped (source 2), the workqueue holders (source 1, sources.py), the host
runners of every repo (source 4, runners.py), quiet.py, the builds, the workqueue's quiet mode. `measured` times each
pass and samples the CPU idle after it (not in a dry run, which changes nothing): one line `-- <label>: ...` and a
`steps` entry for the stop record and the log row. `settle` re-scans until the machine is quiet: new builds, quiet.py's
rows, new `freeze serve` holders, and the host runners that were busy (retried, D8; a runner still busy does not keep
the machine from counting as quiet: its job's builds are frozen).
"""
import io
import re
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout

import freeze
import leftovers
import pollers_quiet
import runners
import sources
import wq_quiet

RESCAN = 5
FAILED = re.compile(r"  \(failed[^)]*\)$")  # quiet.py's "(failed)" and "(failed: timed out after 20s)"
LABELS = {"sessions": "source 5 sessions of every farm told", "daemon": "source 3 hal2-daemon (pollers held, else frozen)",
          "vms": "source 2 CI VMs", "workqueue holders": "source 1 workqueue holders",
          "host runners": "source 4 host runners", "quiet": "quiet.py (agents, docker, simulators, ollama)",
          "builds": "builds and tests", "wq-quiet": "workqueue quiet mode", "rescan": "rescan to quiet",
          "leftovers": "leftover report (what still runs)"}
VERBS = {"leftovers": "reported"}  # read-only in a dry run too


def classify(text: str) -> str:
    """The kind of a recorded or printed action, from its text (quiet.py's actions carry no kind)."""
    text = text.removeprefix("would ")
    for prefix, kind in (("freeze build", "build"), ("freeze hal2-daemon", "daemon"), ("hold hal2 pollers", "pollers"),
                         ("stop tart VM", "vm"),
                         ("freeze ", "session"), ("set workqueue quiet", "quiet"), ("terminate orphan", "orphan"),
                         ("terminate Ollama", "ollama"), ("shut down", "simulator"), ("pause container", "docker"),
                         ("unload LaunchAgent actions.runner.", "runner"), ("unload ", "agent")):
        if text.startswith(prefix):
            return kind
    return "other"


def measured(d, steps: list, name: str, dry: bool, fn) -> list:
    """Run one pass, time it, sample the CPU idle after it; print one line, append its `steps` entry."""
    t = d.clock()
    kinds = fn()
    secs = round(d.clock() - t, 1)
    idle = None if dry else d.idle()
    steps.append({"step": name, "seconds": secs, "idle": idle, "count": len(kinds)})
    after = "" if dry else f", CPU idle {'?' if idle is None else f'{idle:.0f}'}% after"
    verb = VERBS.get(name) or ("planned" if dry else "done")
    d.out(f"-- {LABELS.get(name, name)}: {len(kinds)} {verb} in {secs:.1f}s{after}")
    return kinds


def farmers(rows: list) -> list:
    return sorted(str(r["name"]) for r in rows if str(r.get("name", "")).startswith("farmer-"))


def tell_all(d, rows: list, text: str, mode: str, dry: bool) -> list:
    with ThreadPoolExecutor(max_workers=16) as pool:
        res = list(pool.map(lambda r: d.msg.send(r, text, from_mode=mode, dry_run=dry), rows))
    ok = sum(r["status"] in ("delivered", "dry-run") for r in res)
    d.out(f"{'would tell' if dry else 'told'} {len(rows)} sessions to pause ({ok} {'planned' if dry else 'delivered'})")
    found = farmers(rows)
    d.out(f"  farmers among them: {', '.join(found)}" if found else "  no farmer session is live")
    for r in res:
        if r["status"] == "failed":
            d.out(f"  not delivered to {r['name']}: {r['reason']}")
    return res


def quiet_pass(d, keep: list, runner: bool, dry: bool, first: bool) -> list:
    """quiet.py apply (--runner unless hal2-cli-ci stops the host runners) with every CONFIRM row confirmed."""
    table = d.quiet.procs()  # one scan: the rows, the confirmations and the apply share it (D12)
    rows = d.quiet.scan(keep, runner, table)
    yes = [d.quiet.key(r) for r in rows if r.get("confirm")]
    buf = io.StringIO()
    with redirect_stdout(buf):
        d.quiet.apply(keep, runner, dry, yes, rows, table)
    kinds = []
    for line in buf.getvalue().splitlines():
        if line.startswith(("left alone", "CONFIRM")):
            if first:
                d.out(line)
        elif not FAILED.search(line):
            kinds.append(classify(line))
            d.out(line)
        elif first:
            d.out(line)
    return kinds


def freeze_pass(d, rows: list, dry: bool) -> list:
    done = freeze.apply(rows, d.sys, dry, d.out)
    if done:
        d.rec.add_actions(done)
    return [r["kind"] for r in rows] if dry else [a["kind"] for a in done]


def builds_pass(d, keep_dirs: list, dry: bool) -> list:
    table = freeze.proc_table(d.sys)
    return freeze_pass(d, freeze.builds(table, freeze.caller_tree(table, d.getpid()), keep_dirs, d.sys), dry)


class Run:
    """One stop's passes: what they share (keep, dry, the steps) and what the rescan needs (busy runners)."""

    def __init__(self, d, keep: list, dry: bool, why: str = "important interrupt"):
        self.d, self.keep, self.dry, self.why = d, keep, dry, why
        self.steps, self.notes, self.busy, self.left = [], {}, [], []
        self.runner = runners.find_cli() is None

    def step(self, name: str, fn) -> list:
        return measured(self.d, self.steps, name, self.dry, fn)

    def source(self, name: str, fn) -> list:
        def go():
            res = fn(self.d, self.dry)
            self.notes[name] = res["note"]
            return res["kinds"]
        return self.step(name, go)

    def machine(self) -> list:
        """Every pass after the sessions are told, in order; the kinds of what was (or would be) done."""
        d, dry = self.d, self.dry
        kinds = self.step("daemon", self.daemon)
        kinds += self.step("vms", lambda: freeze_pass(d, freeze.vms(d.sys, d.out), dry))
        for name, fn in sources.SOURCES + runners.SOURCES:
            kinds += self.source(name, fn)
        self.busy = list(self.notes.get("host runners", {}).get("busy", []))
        if not self.runner:
            d.out("host runner LaunchAgents are left to hal2-cli-ci (source 4): quiet.py runs without --runner")
        kinds += self.step("quiet", lambda: quiet_pass(d, self.keep, self.runner, dry, True))
        kinds += self.step("builds", lambda: builds_pass(d, self.keep, dry))
        return kinds + self.step("wq-quiet", self.wq_quiet)

    def daemon(self) -> list:
        """Source 3: hal2-daemon's pollers held (plan 0584 D11); frozen as before when that is not possible."""
        d = self.d
        kinds, note, pollers = pollers_quiet.turn_on(d, self.dry, self.why)
        if note:
            self.notes["pollers quiet"] = note
        if pollers:
            return kinds
        return kinds + freeze_pass(d, freeze.daemon(freeze.proc_table(d.sys)), self.dry)

    def leftovers(self) -> list:
        """The report of what still runs (after the settle; also in a dry run: it only reads), kept in `left`."""
        self.step("leftovers", lambda: self.left.extend(leftovers.report(self.d)) or self.left)
        return self.left

    def wq_quiet(self) -> list:
        kinds, note = wq_quiet.turn_on(self.d, self.dry)
        if note:
            self.notes["workqueue quiet"] = note
        return kinds

    def rescan(self) -> list:
        """One rescan round: quiet.py, builds, new holders, the runners that were busy."""
        d = self.d
        found = quiet_pass(d, self.keep, self.runner, False, False) + builds_pass(d, self.keep, False)
        found += sources.serves(d, False)
        if self.busy:
            stopped, self.busy = runners.retry(d)
            found += stopped
        return found

    def settle(self, a, t0: float, kinds: list) -> tuple:
        """Re-scan every 5 s until idle >= a.idle with nothing new, or the timeout: (quiet_at or None, idle)."""
        d, new, rounds, t = self.d, len(kinds), 0, self.d.clock()
        while True:
            idle = freeze.cpu_idle(d.sys)
            done = (not new and idle is not None and idle >= a.idle) or d.clock() - t0 >= a.timeout
            if done:
                self.steps.append({"step": "rescan", "seconds": round(d.clock() - t, 1), "idle": idle,
                                   "count": rounds})
                d.out(f"-- {LABELS['rescan']}: {rounds} rounds in {d.clock() - t:.1f}s, CPU idle {idle}% after")
                if self.busy:
                    d.out(f"host runners still busy with a job (not stopped, their builds frozen): "
                          f"{', '.join(self.busy)}")
                return (d.clock() if not new and idle is not None and idle >= a.idle else None), idle
            d.sleep(RESCAN)
            rounds += 1
            found = self.rescan()
            kinds.extend(found)
            new = len(found)


def replies(d, results: list, rows: list, t0: float, wait: float) -> dict:
    """{name: why} of the told sessions that paused since t0, polled until t0 + wait (at least once)."""
    told = [r for r, res in zip(rows, results) if res["status"] == "delivered"]
    paused = {}
    while True:
        for r in told:
            if r["name"] not in paused:
                ok, why = d.msg.paused_since(r, t0)
                if ok:
                    paused[r["name"]] = why
        if len(paused) == len(told) or d.clock() >= t0 + wait:
            return paused
        d.sleep(RESCAN)
