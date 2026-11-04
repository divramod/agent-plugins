"""One question store (hal2 plan 0595, D8-D10): a question about a plan lives only in that plan's questions.md.

  farmer.py question add --slot <NN> ...       refused (exit 2) when field <NN> has a plan: the message names the
      `hal2-cli-plans questions add` line; `--slot farmer` and a field without a plan keep working (`refusal`).
  farmer.py question twins [--pair <slot>:<farmerQ>=<planQ> ...] [--drop] [--json] [--repo <dir>]
      the farmer-list questions (open or answered) that a field's plan also asks: the same stem (the text before the options,
      its `Q<n>:` dropped, whitespace collapsed, case folded) or a given pair. `--drop` closes each farmer twin `dropped` with
      `twin of <plan> Q<n>`; one answered only on the farmer side first answers the plan's Q through `hal2-cli-plans`
      (`$HAL2_CLI_PLANS`, else on PATH); without it the twin stays and a problem line says so.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import lead_marker
import mtm_scan
import questions

PLAN_NAME = re.compile(r"^(?:plans/)?(\d{4}-[\w.-]+?)/?(?:plan\.md)?$")
PAIR = re.compile(r"^([\w.-]+):(\d+)=(\d+)$")
OPTIONS = re.compile(r"(?:^|\s)a\)\s")
PREFIX = re.compile(r"^\s*Q\d+\s*:\s*")
TIMEOUT = 60


def plan_of(field: str | Path) -> str:
    """The `<NNNN>-<slug>` the field's CURRENT_PLAN names; "" when it names a shot, a task or nothing."""
    m = PLAN_NAME.match(lead_marker.current_plan(field).strip())
    return m.group(1) if m else ""


def field_path(main: str, slot: str) -> Path | None:
    for w in mtm_scan.field_worktrees(main):
        if Path(w["path"]).name == slot:
            return Path(w["path"])
    return None


def refusal(main: str, slot: str) -> str:
    """The message when `question add --slot <slot>` must go to the plan's store instead, else ""."""
    field = field_path(main, slot) if slot.strip() and slot.strip() != "farmer" else None
    plan = plan_of(field) if field else ""
    if not plan:
        return ""
    return (f"field {slot} runs plan {plan}: its question lives only in the plan's questions.md; ask it with\n"
            f"  hal2-cli-plans questions add \"<the question in the Q form>\" --option \"<a>\" --option \"<b>\" --option \"<c>\" "
            f"--repo {field} --plan {plan}")


def stem(text: str) -> str:
    """The question without its number and options, normalized (D8)."""
    body = OPTIONS.split(PREFIX.sub("", text.strip()), maxsplit=1)[0]
    return " ".join(body.casefold().split())


def plan_questions(field: Path) -> tuple[str, dict[int, dict]]:
    """The plan a field runs and its questions by number (open and answered); ("", {}) without a readable plan store."""
    qm = questions.sibling("q_skill", questions.Q_SCRIPTS, "q.py")
    if qm is None or getattr(qm, "questions", None) is None:
        return "", {}
    store = qm.store_of(field)
    if store.name != "questions.md":
        return "", {}
    try:
        found = qm.load(store)
    except ValueError:
        return "", {}
    out = {e["n"]: {"state": e["state"], "answer": e.get("a", ""), "stem": stem(qm.render_entry(e))}
           for e in found if e["state"] in ("open", "answered")}
    return store.parent.name, out


def parse_pairs(pairs: list[str]) -> dict[tuple[str, int], int]:
    out = {}
    for p in pairs:
        m = PAIR.match(p)
        if not m:
            raise ValueError(f"--pair {p!r}: expected <slot>:<farmerQ>=<planQ>")
        out[(m.group(1), int(m.group(2)))] = int(m.group(3))
    return out


def find(main: str, pairs: dict[tuple[str, int], int]) -> list[dict]:
    """Every twin: a farmer entry (open or answered) of a field with a plan and the plan's question it repeats."""
    plans: dict[str, tuple[Path | None, str, dict]] = {}
    found = []
    for e in questions.load(questions.read_dir(main)):
        slot = e["slot"]
        if e["state"] == "dropped" or not slot or slot == "farmer":
            continue
        if slot not in plans:
            field = field_path(main, slot)
            plans[slot] = (field, *plan_questions(field)) if field else (None, "", {})
        field, plan, theirs = plans[slot]
        n = pairs.get((slot, e["n"]))
        if n is None:
            n = next((k for k, v in theirs.items() if v["stem"] and v["stem"] == stem(e["text"])), None)
        if field is None or n is None or n not in theirs:
            continue
        found.append({"slot": slot, "farmer_n": e["n"], "farmer_state": e["state"], "farmer_answer": e["answer"],
                      "plan": plan, "plan_n": n, "plan_state": theirs[n]["state"], "field": str(field),
                      "how": "pair" if (slot, e["n"]) in pairs else "stem"})
    return found


def cli() -> str | None:
    return os.environ.get("HAL2_CLI_PLANS") or shutil.which("hal2-cli-plans")


def answer_plan(t: dict) -> str:
    """Answers the plan's question with the farmer twin's answer; "" when it worked, else the problem."""
    exe = cli()
    if not exe:
        return "hal2-cli-plans is not installed"
    try:
        p = subprocess.run([exe, "questions", "answer", str(t["plan_n"]), t["farmer_answer"], "--repo", t["field"],
                            "--plan", t["plan"]], capture_output=True, text=True, timeout=TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as err:
        return f"hal2-cli-plans did not run: {err}"
    return "" if p.returncode == 0 else f"hal2-cli-plans questions answer failed: {(p.stderr or p.stdout).strip()[:200]}"


def drop(folder: Path, t: dict) -> None:
    """Closes the farmer twin `dropped` whatever its state (questions.close takes only open ones)."""
    def make(entries: dict) -> dict:
        at = questions.now_utc()
        return {**entries[t["farmer_n"]], "schema": questions.SCHEMA, "at": at, "state": "dropped",
                "answer": f"twin of {t['plan']} Q{t['plan_n']}", "closed": at}
    questions.append(folder, make)


def drop_all(main: str, twins: list[dict]) -> list[str]:
    """Drops every twin it can; the problems of the ones it could not."""
    problems = []
    for t in twins:
        if t["farmer_state"] == "answered" and t["plan_state"] == "open":
            if err := answer_plan(t):
                problems.append(f"{t['slot']} Q{t['farmer_n']}: {err}; the twin stays")
                continue
        try:
            drop(mtm_scan.state_dir(main), t)
        except ValueError as err:
            problems.append(f"{t['slot']} Q{t['farmer_n']}: {err}")
            continue
        t["dropped"] = True
    return problems


def render(twins: list[dict], dropped: bool) -> str:
    if not twins:
        return "no twins"
    verb = "dropped" if dropped else "twin"
    return "\n".join(f"{t['slot']}: farmer Q{t['farmer_n']} ({t['farmer_state']}) = plan {t['plan']} Q{t['plan_n']} "
                     f"({t['plan_state']}, by {t['how']})" + (f" -> {verb}" if t.get("dropped") else "") for t in twins)


def run_twins(args) -> int:
    main = mtm_scan.main_checkout(args.repo)
    try:
        twins = find(main, parse_pairs(args.pair))
        problems = drop_all(main, twins) if args.drop else []
    except ValueError as err:
        print(f"farmer.py question twins: {err}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({"twins": twins, "problems": problems}))
    else:
        print(render(twins, args.drop))
        for p in problems:
            print(f"(not dropped: {p})", file=sys.stderr)
    return 1 if problems else 0
