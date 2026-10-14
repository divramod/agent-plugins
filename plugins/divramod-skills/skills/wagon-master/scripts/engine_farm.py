"""The train engine's test farm (hal2 plan 0294 step 6; test_engine.py runs on it): test_wagon_master's temporary
repository (the yard `hal2`, its origin, the wagon master's field) in timer mode with the duty `trains` alone, the
foremen's fields hitched by `crop`, and `Gate`, a fake `hal2-cli-git` that holds the merge queue as data. No
landing is ever started: `engine.spawn` only counts, a test writes what the landing would have printed (`ends`)."""

import contextlib
import io
import json
import subprocess
import sys
from pathlib import Path
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import engine
import mtm_scan
import tick
import train_state
import trains
import wagon_master
from test_farmer import git
from test_wagon_master import Field

ROLE = """---
duties:
  trains: "*/15 * * * *"
notify: every-round
---

# the wagon master
"""
OWN = "wagon-master-hal2"


def out(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class Gate:
    """A fake `hal2-cli-git`: the merge queue's tickets as data, with the calls that changed it."""

    def __init__(self):
        self.tickets, self.calls, self.refuse, self.seq = [], [], "", 0

    def ticket(self, field, worktree, **kw):
        self.seq += 1
        t = {"slot": field, "seq": self.seq, "pid": 0, "repo": "hal2", "branch": field, "worktree": str(worktree),
             "enqueued": "2026-10-13T10:00:00Z", "landing": None, "state": "waiting", "hold": None, "ready": None,
             "train": None, **kw}
        self.tickets.append(t)
        return t

    def hitch(self, field, worktree):
        mark = {"at": f"2026-10-13T10:00:{self.seq:02}Z", "head": out(worktree, "rev-parse", "HEAD"), "by": f"hal2/{field}"}
        return self.ticket(field, worktree, ready=mark)

    def of(self, field):
        return next((t for t in self.tickets if t["slot"] == field), None)

    def queue(self):
        riding = {c["field"]: t["slot"] for t in self.tickets for c in (t["train"] or {}).get("cars", [])}
        return {"queue": [{**t, "position": n, "rides_with": riding.get(t["slot"])}
                          for n, t in enumerate(self.tickets)]}

    def cli(self, args, cwd):
        if args[:2] == ["worktree", "queue"] and args[2:] == ["--json"]:
            return 0, json.dumps(self.queue())
        self.calls.append([a for a in args if a != "--json"])
        if self.refuse and self.refuse in args:
            return 1, f"refused: {self.refuse}"
        verb, fields = args[1:3] if args[1] == "queue" else (args[1], args[1]), [a for a in args[3:] if a[0] != "-"]
        if verb == ["queue", "ready"]:  # --clear
            self.tickets = [t for t in self.tickets if t["slot"] != fields[0] or not t["ready"]]
        elif verb == ["queue", "train"] and "--clear" in args:
            self.tickets = [t for t in self.tickets if t["slot"] != fields[0] or t["state"] == "held"]
            for t in self.tickets:
                t["train"] = None if t["slot"] == fields[0] else t["train"]
        elif verb == ["queue", "train"]:
            mine = self.of(fields[0]) or self.ticket(fields[0], cwd)
            mine["train"] = {"carrier": fields[0], "at": "2026-10-13T10:01:00Z", "by": "hal2/" + fields[0], "cars": [
                {"field": f, "branch": f, "head": ((self.of(f) or {}).get("ready") or {}).get("head")} for f in fields[1:]]}
        elif args[1] == "release":
            self.tickets = [t for t in self.tickets if t["slot"] != args[2]]
        return 0, json.dumps({"status": "ok"})


class Farm(Field):
    """The wagon master in timer mode with the duty `trains` alone; every round is due."""

    def setUp(self):
        super().setUp()
        self.commit(self.main, wagon_master.WIRING.role_file, ROLE, push=True)
        git(self.wm, "merge", "-q", "--ff-only", "main")
        self.gate, self.spawned, self.alive, self.typed, self.panes = Gate(), [], set(), [], {}
        self.fields = {}
        real = tick.sh

        def sh(argv, cwd, timeout=900):
            if argv[0] == "hal2-cli-git":  # the frame's merge-from-main
                return 0, json.dumps({"status": "ok"})
            if argv[:2] != [sys.executable, str(trains.ENGINE)]:
                return real(argv, cwd, timeout)
            text = io.StringIO()
            with contextlib.redirect_stdout(text):
                code = engine.main(argv[2:])
            return code, text.getvalue().strip()

        def spawn(top, log):
            log.write_text("")
            self.spawned.append(Path(top).name)
            return 40000 + len(self.spawned)

        def agents(*args, **kw):
            rows = [{"pane_id": p, "slot": f, "checkout": str(self.fields[f]), "state": "idle"} for f, p in self.panes.items()]
            return 0, json.dumps(rows)

        for p in (mock.patch.object(tick, "sh", sh), mock.patch.object(engine, "cli", self.gate.cli),
                  mock.patch.object(engine, "spawn", spawn), mock.patch.object(tick.deliver, "cli", agents),
                  mock.patch.object(mtm_scan, "run_json", lambda args, cwd=None: self.gate.queue()
                                    if args[:3] == ["hal2-cli-git", "worktree", "queue"] else None),
                  mock.patch.object(mtm_scan, "pid_alive", lambda pid: pid in self.alive),
                  mock.patch.object(tick.deliver, "send", lambda pane, text, s=None: self.typed.append((pane, text))),
                  mock.patch.object(tick.due, "is_due", return_value=True)):
            p.start()
            self.addCleanup(p.stop)
        self.assertEqual(self.call("mode", "timer")[0], 0)

    def crop(self, name, files, plan=""):
        """A foreman's field with one commit the barn lacks, hitched: its ready ticket."""
        path = self.fields[name] = self.field(name)
        for f, text in files.items():
            self.commit(path, f, text)
        if plan:
            (path / "plans").mkdir(exist_ok=True)
            (path / "plans/CURRENT_PLAN").write_text(plan + "\n")
        return self.gate.hitch(name, path)

    def round(self):
        code, text = self.call("tick", "--json")
        self.assertEqual(code, 0, text)
        r = json.loads(text)
        self.last = [(a["kind"], a["do"], a["slot"]) for a in r["planned"] if a["duty"] == "trains" and a["do"] != "ran"]
        return r

    def state(self):
        return [(e["kind"], e["slot"]) for e in train_state.lines(str(self.main))]

    def train(self):
        return train_state.standing(train_state.lines(str(self.main)))

    def ends(self, result, land=False):
        """The landing's process is gone; `result` is what it printed last. `land`: the barn has the candidate, the
        landing's end took the mark and the cars' ready tickets (hal2-git, plan 0294 step 3)."""
        self.alive.clear()
        (self.wm_state / train_state.LOG).write_text("hal2: waiting\n" + (json.dumps(result) + "\n" if result else ""))
        if land:
            git(self.wm, "push", "-q", "origin", "HEAD:main")
            self.gate.tickets = []

    def subjects(self, rev="HEAD"):
        return out(self.wm, "log", "--format=%s", f"origin/main..{rev}").splitlines()
