"""prune.py run (hal2 plan 0377 step 5; contract: design/prune-run/sequence/v1/contract.md, D7, D14, D15, D19, D21-D24):
the plan carried out, one field at a time, as workflow commands `hal2-cli-runs exec` turns into the run's jobs and
steps.

Under the farm lock (D14; a second run prints "already running: ..." and exits 0): `facts` (collect, the half-removed
fields), `stale-pointers` (each cleared, the field re-collected), `phase-1` (the half-removed first, halfway.py, then
the free fields), `phase-2` and `phase-3` (only while the disk is short when they start, then on to the goal, the disk
read before each action, D15) and `report`. Before each action the field is collected again and planned alone: the
action stands only when the plan still has it (the proof again, PR21). `--dry-run` takes no lock, prints the same jobs
with "would ..." and changes nothing. Exit 0 done or locked, 1 an action failed (later jobs still run, RN7).
"""

import shutil

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import facts
import field_facts
import halfway
import plan as planner
import prune_act
import prune_proof
import responses
import busy
import sizes
import store
from executor_out import PAST, Out, summary, why_not  # noqa: F401  (re-exported)


def free_bytes(main: str) -> int:
    return shutil.disk_usage(main).free


class Run:
    def __init__(self, main: str, only: set[str] | None, dry: bool, out: Out, responses_only: bool = False):
        self.main, self.only, self.dry, self.out = main, only, dry, out
        self.responses_only = responses_only  # just the watermark's responses (the tollman's start with --responses)
        self.rows: list[dict] = []
        self.asks: list[dict] = []
        self.gone: set[str] = set()  # removed, half-removed or left: no later action on them
        self.trimming = False  # phase 2 or 3 started: they go on until the goal (D15)

    def all(self) -> int:
        self.facts_job()
        if self.responses_only:
            self.plan = planner.plan(self.found, self.only)
        else:
            self.stale_job()
            self.phase1_job()
            for name in (planner.PHASE2, planner.PHASE3):
                self.trim_job(name)
        self.responses_job()
        self.report_job()
        return 1 if any(r["status"] == "failure" for r in self.rows) else 0

    def collect(self, only: set[str] | None, sized: bool = True) -> dict:
        keep = {f["slot"]: f.get("size") for f in self.found["fields"]} if not sized else None
        measure = sizes.measure_all if keep is None else (lambda main, fs, **kw: {f["slot"]: keep.get(f["slot"]) for f in fs})
        return facts.collect(self.main, only=only, measure=measure)

    def facts_job(self) -> None:
        self.out.job("facts")
        self.found = self.collect(self.only)
        d, c = self.found["disk"], self.found["config"]
        self.before = d
        self.out.line(f"disk: {d['free_gb']:g} GB free, {d['used_pct']:g}% used")
        self.out.line(f"config: {c['source']} ({c['path']})")
        for f in self.found["fields"]:
            self.out.line(planner.field_line(f))
        self.half = halfway.detect(self.main, self.found["fields"], self.only)
        for h in self.half:
            self.out.line(f"half-removed {h['slot']}: {halfway.describe(h)}")

    def refresh(self, slot: str) -> dict | None:
        """The field collected again (sizes kept), replacing it in the facts; None when it is no field any more."""
        fresh = self.collect({slot}, sized=False)
        new = next((f for f in fresh["fields"] if f["slot"] == slot), None)
        self.found["fields"] = [f for f in self.found["fields"] if f["slot"] != slot] + ([new] if new else [])
        self.found["fields"].sort(key=lambda f: f["slot"])
        return new

    def recheck(self, a: dict, job: str) -> tuple[dict | None, str]:
        """The proof again just before the action (PR21): the field collected and planned alone, at the run's disk (a
        started phase goes on to the goal, D15); the fresh action, or None and why not."""
        try:
            fresh = self.collect({a["field"]}, sized=False)
        except facts.FactsError as e:
            return None, f"facts: {e}"
        f = next((x for x in fresh["fields"] if x["slot"] == a["field"]), None)
        if f is None:
            return None, "no longer a field of this farm"
        self.found["fields"] = [x if x["slot"] != f["slot"] else f for x in self.found["fields"]]
        p = planner.plan({**fresh, "disk": self.found["disk"]}, {a["field"]})
        b = next((x for x in p["jobs"][job]["actions"] if x["field"] == a["field"]), None)
        if b is not None and b["action"] == a["action"]:
            return b, ""
        return None, why_not(f)

    def row(self, a: dict, status: str, freed: int, why: str) -> None:
        self.rows.append({"field": a["field"], "action": a["action"], "status": status, "bytes": freed, "why": why})

    def stale_job(self) -> None:
        self.out.job(planner.STALE)
        job = planner.plan(self.found, self.only)["jobs"][planner.STALE]
        if job["skipped"]:
            self.out.line(f"skipped: {job['skipped']}")
        for a in job["actions"]:
            self.act(a, planner.STALE)

    def phase1_job(self) -> None:
        self.out.job(planner.PHASE1)
        for h in self.half:
            self.out.step(h["slot"])
            status, text, again = halfway.resume(self.main, h, self.dry)
            self.out.line(text)
            self.rows.append({"field": h["slot"], "action": "half-removed", "bytes": 0, "why": halfway.describe(h),
                              "status": status if not self.dry else "would"})
            if again:
                self.refresh(h["slot"])
            else:
                self.gone.add(h["slot"])
            self.out.end(status)
        self.plan = planner.plan(self.found, self.only)
        job = self.plan["jobs"][planner.PHASE1]
        todo = [a for a in job["actions"] if a["field"] not in self.gone]
        if not todo:
            self.out.line(f"skipped: {job['skipped'] or 'no free field'}")
        for a in todo:
            self.act(a, planner.PHASE1)

    def trim_job(self, name: str) -> None:
        self.out.job(name)
        job = self.plan["jobs"][name]
        if job["skipped"]:
            self.out.line(f"skipped: {job['skipped']}")
            return
        cfg = self.found["config"]
        if not self.open(cfg):
            return
        for a in job["actions"]:
            if a["field"] in self.gone:
                continue
            wait = None if self.dry else busy.reason(self.main)  # a hold may start between two trims
            if wait:
                self.out.line(f"stopped: {wait}")
                break
            d = facts.disk(self.main) if not self.dry else None
            if d and facts.goal_met(d, cfg):
                self.out.line(f"stopped: goal met ({d['free_gb']:g} GB free, {d['used_pct']:g}% used)")
                break
            self.act(a, name)

    def open(self, cfg: dict) -> bool:
        """May the trimming (and the responses after it) go on? A started one goes on to the goal (D15); one not
        started needs a short disk."""
        if self.dry:
            return True
        d = facts.disk(self.main)
        if self.trimming and facts.goal_met(d, cfg):
            self.out.line(f"skipped: goal met ({d['free_gb']:g} GB free, {d['used_pct']:g}% used)")
            return False
        if not self.trimming and not facts.short_of_space(d, cfg):
            self.out.line(f"skipped: disk fine ({d['free_gb']:g} GB free)")
            return False
        self.trimming = True
        return True

    def responses_job(self) -> None:
        """The watermark's responses (plan 0472 D2), only while still above the goal and no train builds; each one is
        asked again just before it runs, like a trim."""
        self.out.job(planner.RESPONSES)
        job = self.plan["jobs"][planner.RESPONSES]
        for note in job.get("notes", []):
            self.out.line(f"note: {note}")
        if job["skipped"]:
            self.out.line(f"skipped: {job['skipped']}")
            return
        if not self.open(self.found["config"]):
            return
        for a in job["actions"]:
            wait = None if self.dry else busy.reason(self.main)
            d = None if self.dry else facts.disk(self.main)
            if wait or (d and facts.goal_met(d, self.found["config"])):
                self.out.line(f"stopped: {wait or 'goal met (%g GB free, %g%% used)' % (d['free_gb'], d['used_pct'])}")
                break
            self.respond(a)

    def respond(self, a: dict) -> None:
        self.out.step(a["field"], "response")
        if self.dry:
            self.out.line(planner.describe(a, True))
            self.row(a, "would", 0, a["why"])
            return self.out.end("success")
        before = free_bytes(self.main)
        protected = [self.main] + [f["path"] for f in facts.fields(self.main)]
        status, text = responses.run_one(a, protected, prune_act.run, self.main)
        freed = max(0, free_bytes(self.main) - before)
        self.out.line(text)
        self.out.line(f"{PAST[a['action']]} {a['field']}: {sizes.human(freed)} freed" if status == "success"
                      else f"{status} {a['field']}: {text.splitlines()[-1] if text else a['why']}")
        self.row(a, status, freed, a["why"] if status == "success" else text)
        self.out.end(status)

    def act(self, a: dict, job: str) -> None:
        """One action in its step `field <NN>`: an ask is said, never done (D6); a dry run says "would ..."."""
        slot = a["field"]
        self.out.step(slot)
        if a["action"] == "ask":
            self.out.line(planner.describe(a))
            self.asks.append(a)
            return self.out.end("skipped")
        if self.dry:
            self.out.line(planner.describe(a, True))
            self.row(a, "would", a["bytes"] if a["action"] == "remove" else 0, a["why"])  # a trim's share is unknown
            return self.out.end("success")
        if a["action"] == "remove" and a.get("servant_of"):
            prune_proof.git(self.main, "fetch", "--quiet", "--prune", "origin")  # the foreman's newest branch
        b, why = self.recheck(a, job)
        if b is None:
            self.out.line(f"skipped {slot}: {why}")
            self.row(a, "skipped", 0, why)
            return self.out.end("skipped")
        before = free_bytes(self.main)
        try:
            status, text = self.do(b)
        except facts.FactsError as e:
            status, text = "failure", f"facts: {e}"
        freed = max(0, free_bytes(self.main) - before)
        said = [text, summary(b, status, freed, text)]
        for one in reversed(said) if b["action"] == "clear-pointer" else said:
            self.out.line(one)
        self.row(b, status, freed, b["why"] if status != "skipped" else text)
        if b["action"] == "remove" and status == "success":
            self.gone.add(slot)
        self.out.end(status)

    def do(self, a: dict) -> tuple[str, str]:
        f = next(x for x in self.found["fields"] if x["slot"] == a["field"])
        if a["action"] == "clear-pointer":
            prune_proof.lead_marker.pointers.remove(f["path"], field_facts.POINTER)  # both places
            new = self.refresh(f["slot"])
            return "success", f"new proof: {'free' if new and new['free'] else (new or {}).get('proof', 'gone')}"
        if a["action"] == "remove":
            halfway.begin(self.main, f, a.get("servant_of"))
            try:
                return prune_act.remove(self.main, f, a.get("servant_of"), a.get("stop_sessions") or [])
            finally:
                halfway.done(self.main, f["slot"])  # the command ended; only a killed run leaves the journal
        return prune_act.clean(f, None if a["action"] == "muck-out" else a.get("paths"))

    def report_job(self) -> None:
        self.out.job("report")
        for r in self.rows:
            self.out.line(f"{r['field']}  {r['action']}  {r['status']}  {sizes.human(r['bytes'])}  {r['why']}")
        for a in self.asks:
            self.out.line(planner.describe(a))
        after = self.before if self.dry else facts.disk(self.main)
        self.out.line(f"free before: {self.before['free_gb']:g} GB, after: {after['free_gb']:g} GB")
        done = [r for r in self.rows if r["status"] in ("success", "would") and r["action"] != "half-removed"]
        failed = [r["field"] for r in self.rows if r["status"] == "failure"]
        if failed:
            self.out.line(f"failed: {', '.join(failed)}")
        freed = sum(r["bytes"] for r in done)
        self.out.line(f"prune: {len(done)} {'planned ' if self.dry else ''}actions, {sizes.human(freed)} "
                      f"{'to free' if self.dry else 'freed'}, {len(self.asks)} asks")


def run(main: str, only: set[str] | None, dry: bool, out: Out | None = None, responses_only: bool = False) -> int:
    out = out or Out()
    if dry:
        return Run(main, only, dry, out, responses_only).all()
    try:
        with store.farm_lock(main):
            return Run(main, only, dry, out, responses_only).all()
    except store.Locked as e:
        out.line(f"already running: {e}")
        return 0
