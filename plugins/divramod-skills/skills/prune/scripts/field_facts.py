"""The per-field facts prune's plan decides on besides the proof (hal2 plan 0377 step 4; facts.collect gathers them).

`pointer` (plans/CURRENT_PLAN and its plan's state, D5), `unsaved` (work off main behind a stale pointer), `lead` (a
servant's foreman and what the foreman's branch lacks, D6), `hold` (queue ticket, landing, boss pause, open question),
`building` (cleanup's `busy`) and the last landed train's cars. Reading only; every outside call is injectable.
"""

import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import lead_marker
import mtm_scan
import prune_proof
import sizes

POINTER = Path("plans/CURRENT_PLAN")
TOLLMAN, TRAINS = "tollman", "train.jsonl"
FINISHED, MISSING, OPEN, UNKNOWN = "finished", "missing", "open", "unknown"


def pointer_name(path: str) -> str | None:
    """The plan `plans/CURRENT_PLAN` names (its first line), None when the file is missing or empty."""
    try:
        text = (Path(path) / POINTER).read_text().strip()
    except OSError:
        return None
    return text.splitlines()[0].strip() if text else None


def show(plan: str, repo: str) -> tuple[int, str, str]:
    """`hal2-cli-plans show <plan> --repo <repo> --json` as (exit code, stdout, stderr); (-1, "", why) when it cannot run."""
    try:
        p = subprocess.run(["hal2-cli-plans", "show", plan, "--repo", repo, "--json"], capture_output=True, text=True,
                           timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        return -1, "", str(e)
    return p.returncode, p.stdout, p.stderr


def plan_state(plan: str, repos: list[str], run=show) -> str:
    """finished, missing, open or unknown for a plan name, looked up in each repo (the field, then the main checkout):
    a plan is `missing` only when none knows it, `finished` when its state is done or it has a finish date. The one
    place that reads the plan's shape (plan 0376 rebuilds it); anything it does not understand is `unknown`, never stale."""
    unknown_plan = 0
    for repo in repos:
        code, out, err = run(plan, repo)
        if code == 0:
            try:
                data = json.loads(out)
            except ValueError:
                return UNKNOWN
            if not isinstance(data, dict):
                return UNKNOWN
            return FINISHED if data.get("state") == "done" or data.get("finished") else OPEN
        if code == 1 and "no plan matches" in err:
            unknown_plan += 1
        else:
            return UNKNOWN
    return MISSING if unknown_plan == len(repos) else UNKNOWN


def pointer(field: dict, main: str, lookup=plan_state) -> dict | None:
    """`{plan, state}` for a field with a CURRENT_PLAN, None without; a servant's pointer is its foreman's plan and
    not part of its proof, so it is not looked at."""
    name = pointer_name(field["path"])
    if name is None or lead_marker.marker(field["path"]) is not None:
        return None
    return {"plan": name, "state": lookup(name, [field["path"], main])}


def unsaved(field: dict) -> list[str]:
    """What the field holds that origin's default branch lacks, the pointer aside: commits (HEAD, side branches), changes.
    The pointer file itself is no change (a farm that does not ignore it would never have a stale one)."""
    path = field["path"]
    why = [w for w in prune_proof.unsaved(path, field["slot"], prune_proof.tick.default_ref(path))
           if not w.startswith("plans/CURRENT_PLAN")]
    if "uncommitted changes" in why and not prune_proof.git(path, "status", "--porcelain", "--", ".", ":!plans/CURRENT_PLAN"):
        why.remove("uncommitted changes")
    return why


def lead(field: dict) -> dict | None:
    """A servant's marker `{slot, at, missing}`: its foreman, when plans/LEAD was written (epoch seconds) and what the
    foreman's branch `origin/<foreman>` lacks of the field (a broken marker or branch gives `bad` instead)."""
    m = prune_proof.marker(field["path"])
    if m is None:
        return None
    if m.get("bad"):
        return {"bad": m["error"]}
    base = f"origin/{m['slot']}"
    if not prune_proof.ref_exists(field["path"], base):
        return {"slot": m["slot"], "at": m["at"], "bad": f"its foreman's branch {base} does not exist"}
    return {"slot": m["slot"], "at": m["at"], "missing": prune_proof.unsaved_for_lead(field["path"], field["slot"], base)}


def last_cars(main: str) -> list[str]:
    """The fields that rode in the tollman's newest `landed` train (a read of its state file `train.jsonl`)."""
    f = mtm_scan.state_dir(main, TOLLMAN) / TRAINS
    cars: list[str] = []
    try:
        lines = f.read_text().splitlines()
    except OSError:
        return cars
    for text in lines:
        try:
            row = json.loads(text)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("kind") == "landed":
            cars = [str(c) for c in row.get("cars", []) if prune_proof.NUMBERED.fullmatch(str(c))]
    return cars


def building(fields: list[dict], build=prune_proof.build_running) -> dict[str, bool]:
    """cleanup's `busy` per field, in parallel (read-only; the actions stay serial, D14)."""
    if not fields:
        return {}
    with ThreadPoolExecutor(max_workers=sizes.workers()) as ex:
        return dict(zip((f["slot"] for f in fields), ex.map(lambda f: bool(build(f["path"])), fields)))


def extra(fields: list[dict], ctx: dict, main: str, free: dict[str, bool], lookup=plan_state,
          build=prune_proof.build_running) -> dict[str, dict]:
    """{slot: {pointer, unsaved, lead, hold, building}} for the fields given (`free`: the proof's verdict per field; names-ok: the keys
    a free field cannot be building, so it is not asked). `unsaved` only behind a finished or missing pointer."""
    out = {}
    for f in fields:
        ptr = pointer(f, main, lookup)
        stale = ptr is not None and ptr["state"] in (FINISHED, MISSING)
        out[f["slot"]] = {"pointer": ptr, "unsaved": unsaved(f) if stale else None, "lead": lead(f),
                          "hold": prune_proof.held(f["slot"], ctx)}
    busy = building([f for f in fields if not free[f["slot"]]], build)
    for f in fields:
        out[f["slot"]]["building"] = busy.get(f["slot"], False)
    return out
