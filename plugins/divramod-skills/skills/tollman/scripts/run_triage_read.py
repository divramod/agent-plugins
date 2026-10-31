"""The reading half of a finished land run's triage (hal2 plan 0490 step 1, D3, D11): pure parsers over the run's
data, no IO. run_triage.py places what these find; run_triage_gather.py fetches the data.

- `counted`: the red jobs the triage takes: mtm_ci.red_jobs (the gate's reds) and the ship jobs that failed (a red
  hub-deploy is a red job of the run too); a cancelled ship job only stopped
- `needs_graph`: the workflow's `jobs:` ids and their `needs` (inline forms only, as hal2's workflows write them),
  keyed by the stage prefix a job's display name starts with (`e4-hz01-host-c` -> `e4`, `e4-01-hub-deploy`)
- `units`: a red job's units: one per failed `gate <job> <part>` step (`stack-test/hub-e2e`), else one for the job
  (`runner-image-linux`); each with its log lines, found by the log's step column, else by the task log's
  `[NN] 🎬` .. `[NN] 💥` markers
- `facts`: what a unit's lines say: the error lines, the failing specs (Playwright's `✘ ... › <spec>:<line>`) and
  tests (mtm_scan.failing_tests), a build-phase timeout (docker compose's limit, exit 124), a transient fault
  (transient.TRANSIENT), the runner, a budget-only failure (`budget_only`, L13) and a job no runner served
  (`unserved`, L64)
"""

import re

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import job_error
import mtm_ci
import mtm_scan
import stack_red
import transient

SHIP_RED = {"failure", "timed_out", "startup_failure"}
GATE_STEP = re.compile(r"^(?:\[\d+\]\s*)?gate (?P<job>\S+) (?P<part>\S+)$")
NUMBER = re.compile(r"^\[(\d+)\]")
MARK = re.compile(r"^\[(\d+)\] (🎬|💥|🏁)")
ERRORS = re.compile(r"##\[error\]|^!! |✘|^failed now|phase (?:build|up): failed|^Error: |gate: unit .* failed|"
                    r"error\[|panicked|FAILED|timed out", re.I)
NOISE = re.compile(r"^##\[error\]Process completed with exit code \d+\.$")
SPEC = re.compile(r"✘\s+\d+\s+\[[^\]]+\]\s+›\s+(?P<file>\S+\.(?:spec|test)\.[tj]sx?):(?P<line>\d+)")
SPEC_PATH = re.compile(r"failed now \(attempt \d+\): \S+ › (?P<path>\S+\.(?:spec|test)\.[tj]sx?) ›")
TIMEOUT = re.compile(r"phase (?:build|up): failed after \d+s \(exit 124\)")
RUNNER = re.compile(r"Runner name: '([^']+)'")
# L13: a latency budget missed (hal2-core's budgets.rs `FAIL <call>: ... (budget N ms`, its tests' `over budget:`,
# hal9k-e2e's `p95=... ms, budget N ms`) or a test's own time limit: load on the shared host, never a build phase's
BUDGET = re.compile(r"over budget:|^\s*FAIL\s+\S+: p50 .*\(budget \d|p95=\S+ ms, budget \d|Test timeout of \d+ms "
                    r"exceeded|^\s*TIMEOUT \[", re.M)
# what only frames a failure (a step's exit, a spec's header, the gate's summary): never its own cause
FRAME = re.compile(r"##\[error\]Process completed|✘|^failed now|gate: unit .* failed|^\s*FAILED|FAIL \[|panicked at|"
                   r"exit code \d+")
LINES = 12  # a unit's error lines kept as evidence


def counted(jobs: list[dict]) -> list[dict]:
    """The run's red jobs the triage takes, in the run's order."""
    names = set(mtm_ci.red_jobs(jobs))
    return [j for j in jobs if j.get("name") in names
            or (mtm_ci.is_ship(j.get("name", "")) and j.get("conclusion") in SHIP_RED)]


def prefix(name: str) -> str:
    """The stage prefix of a job id or display name (`d1-az02-host-a`, `d1-01-stack-test` -> `d1`), else ''."""
    m = re.match(r"^([a-z][1-9])-", name or "")
    return m[1] if m else ""


def needs_graph(workflow: str) -> dict[str, list[str]]:
    """{job prefix: the prefixes it needs} from a workflow's text."""
    graph, inside, job = {}, False, ""
    for line in (workflow or "").splitlines():
        if re.match(r"^jobs:\s*$", line):
            inside = True
        elif inside and re.match(r"^\S", line):
            break
        elif inside and (m := re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)):
            job = prefix(m[1])
            graph.setdefault(job, [])
        elif inside and job and (m := re.match(r"^    needs:\s*(.+?)\s*$", line)):
            items = m[1].strip("[]").split(",")
            graph[job] = [p for p in (prefix(i.strip()) for i in items) if p]
    return graph


def needs_red(job: str, graph: dict, red: list[str]) -> list[str]:
    """The red jobs (display names) a job needs directly by the workflow's graph."""
    wanted = set(graph.get(prefix(job)) or [])
    return [r for r in red if r != job and prefix(r) in wanted]


def job_lines(log: str, job: str) -> list[tuple[str, str]]:
    """[(step column, text)] of a job's lines in a `--log-failed` text (job, step, line by tabs)."""
    out = []
    for raw in (log or "").splitlines():
        cols = raw.split("\t", 2)
        if len(cols) == 3 and cols[0] == job:
            out.append((cols[1], job_error.clean(raw)))
    return out


def step_lines(lines: list[tuple[str, str]], step: dict) -> list[str]:
    """A step's lines: by the log's step column, else between its `[NN] 🎬` and its end marker."""
    named = [t for s, t in lines if s == step.get("name")]
    if named:
        return named
    num = (NUMBER.match(step.get("name") or "") or [None, None])[1]
    out, inside = [], False
    for _, text in lines:
        m = MARK.match(text)
        if m and m[1] == num:
            inside = m[2] == "🎬"
            out += [] if inside else [text]
            continue
        if inside:
            out.append(text)
    return out


def part_of(job: dict, step: dict) -> str:
    """A unit's name: `<bare job>/<part>` for a `gate <job> <part>` step, else the bare job."""
    bare = stack_red.bare(job.get("name"))
    m = GATE_STEP.match(step.get("name") or "")
    return f"{bare}/{m['part']}" if m and m["job"] == bare else bare


def failed_steps(job: dict) -> list[dict]:
    return [s for s in job.get("steps") or [] if s.get("conclusion") in ("failure", "timed_out")
            and (NUMBER.sub("", s.get("name") or "").strip() not in (mtm_ci.STOP_STEP, "fail fast"))]


def units(jobs: list[dict], log: str) -> list[dict]:
    """[{unit, job, bare, steps, lines}] of the run's counted red jobs (see the module doc)."""
    out: dict[str, dict] = {}
    for job in counted(jobs):
        lines, steps = job_lines(log, job["name"]), failed_steps(job)
        for step in steps or [{}]:
            name = part_of(job, step)
            got = step_lines(lines, step) if step else [t for _, t in lines]
            runner = RUNNER.search("\n".join(t for _, t in lines))
            u = out.setdefault(name, {"unit": name, "job": job["name"], "bare": stack_red.bare(job["name"]),
                                      "conclusion": job.get("conclusion"), "steps": [], "lines": [],
                                      "runner": runner[1] if runner else "", "unserved": unserved(job)})
            u["steps"] += [step["name"]] if step else []
            u["lines"] += got or ([t for _, t in lines] if len(steps) <= 1 else [])
    return list(out.values())


def unserved(job: dict) -> bool:
    """A red job that never got a runner (L64: hz01 parked, the job cancelled after 11 min with no log): gh gives it
    no step at all. A runner fault, never a car's (a job read without its steps is not judged)."""
    return "steps" in job and not job["steps"] and job.get("conclusion") in mtm_ci.RED


def budget_only(lines: list[str]) -> bool:
    """The lines fail only on a latency budget or a test's time limit (L13): a budget line, and every other error
    line only frames a failure."""
    errors = [t for t in lines if ERRORS.search(t) and not NOISE.match(t)]
    return any(BUDGET.search(t) for t in lines) and all(BUDGET.search(t) or FRAME.search(t) for t in errors)


def green_units(jobs: list[dict]) -> set[str]:
    """The units a run had green: each green `gate` step's unit, and each green job's bare name (a flake's proof)."""
    out = set()
    for job in jobs or []:
        if job.get("conclusion") == "success":
            out.add(stack_red.bare(job.get("name")))
        out |= {part_of(job, s) for s in job.get("steps") or [] if s.get("conclusion") == "success"
                and GATE_STEP.match(s.get("name") or "")}
    return out


def specs(lines: list[str]) -> list[dict]:
    """[{file, tests: [<file>:<line>]}] of the failing specs, a file once; `path` its longer form when given."""
    found: dict[str, dict] = {}
    for text in lines:
        if m := SPEC.search(text):
            s = found.setdefault(m["file"], {"file": m["file"], "path": "", "tests": []})
            s["tests"] += [f"{m['file']}:{m['line']}"]
        elif (m := SPEC_PATH.search(text)) and (s := next((v for k, v in found.items() if m["path"].endswith(k)), None)):
            s["path"] = s["path"] or m["path"]
    return list(found.values())


def facts(lines: list[str]) -> dict:
    """What a unit's lines say (see the module doc); `errors` all its error lines, the transient one included."""
    text = "\n".join(lines)
    hit = transient.TRANSIENT.search(text)
    errors = [t for t in lines if (ERRORS.search(t) and not NOISE.match(t)) or (hit and hit[0] in t)
              or BUDGET.search(t)]
    runner, timeout = RUNNER.search(text), bool(TIMEOUT.search(text))
    return {"errors": errors, "specs": specs(lines), "tests": mtm_scan.failing_tests(text),
            "timeout": timeout, "transient": hit[0] if hit else "", "runner": runner[1] if runner else "",
            "budget": not timeout and budget_only(lines)}


def evidence_lines(errors: list[str], spec: dict | None, others: list[dict]) -> list[str]:
    """A verdict's lines: its spec's lines first, then the unit's lines naming no other spec, at most LINES."""
    mine = [t for t in errors if spec and spec["file"] in t]
    rest = [t for t in errors if t not in mine and not any(o["file"] in t for o in others)]
    return (mine + rest)[:LINES]


def signatures(jobs: list[dict], log: str) -> dict[str, dict]:
    """{unit: {tests, timeout}} of a run's red units: what a later run's red is compared with (a repeat, L131)."""
    out = {}
    for u in units(jobs, log):
        f = facts(u["lines"])
        out[u["unit"]] = {"tests": [t for s in f["specs"] for t in s["tests"]] + f["tests"], "timeout": f["timeout"],
                          "lines": f["errors"][:LINES]}
    return out
