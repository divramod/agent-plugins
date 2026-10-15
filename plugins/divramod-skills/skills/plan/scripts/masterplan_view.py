"""masterplan_view.py: `plan.py masterplan [--plan <ref>] [--json]`, a masterplan's rows and its roll-up (hal2 plan
0275's D3, D13).

The roll-up (the plans brought in of all, the steps done of all, the `+` while a row is `draft`, each row's plan with
its steps and the fields working on it) has one home, hal2-plans: this module prints what `hal2-cli-plans masterplan
<slug> --repo <root> --json` answers and never adds up a step table itself. The binary is `$HAL2_CLI_PLANS` (a hal2
worktree ahead of the installed binary, and the tests, set it), else `hal2-cli-plans` on PATH. Without it, with one
that knows no `masterplan` (an older one: exit 2), on any other failure and on the answer `null`, the command prints
the masterplan's own rows and one line saying what the roll-up needs, and exits 0: the skill works without hal2.

`after_landing` is the skill's own, read from this checkout's copies and no sum: the masterplan's plans whose open
steps are all checked after the landing (masterplan_keep.finishable), which the mtm skill finishes after a bring in.
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

import masterplan
import masterplan_keep
import parallel

ENV = "HAL2_CLI_PLANS"
NAME = "hal2-cli-plans"
TIMEOUT = 30
NEEDS = f"the roll-up (plans and steps done of all) needs {NAME}"


def binary() -> str | None:
    """The CLI to ask: `$HAL2_CLI_PLANS` when it names a file, else the one on PATH; None when neither."""
    named = os.environ.get(ENV, "").strip()
    if named:
        return named if Path(named).expanduser().is_file() else None
    return shutil.which(NAME)


def rollup(root: Path, slug: str) -> tuple[dict | None, str]:
    """(the CLI's roll-up of masterplan `slug`, "") or (None, the one line that says why there is none)."""
    cli = binary()
    if cli is None:
        return None, f"{NEEDS}: it is not installed"
    try:
        out = subprocess.run([str(Path(cli).expanduser()), "masterplan", slug, "--repo", str(root), "--json"],
                             capture_output=True, text=True, encoding="utf-8", timeout=TIMEOUT)
    except (OSError, UnicodeDecodeError, subprocess.TimeoutExpired) as error:
        return None, f"{NEEDS}: it did not answer ({type(error).__name__})"
    if out.returncode != 0:
        return None, f"{NEEDS} with the command `masterplan`: the installed one gave none (exit {out.returncode})"
    try:
        data = json.loads(out.stdout)
    except json.JSONDecodeError:
        data = None
    if not isinstance(data, dict):
        return None, f"{NEEDS}: it knows no masterplan {slug} in this repository"
    return data, ""


def listed(values: list) -> str:
    return ",".join(str(v) for v in values) or "-"


def view(out: dict) -> str:
    """The text view: with the roll-up a line with the crop's glyph, the plans brought in of all and the steps done
    of all, a row per plan (row, plan, the fields working on it, steps, status, Needs) and a line per problem, as
    `hal2-cli-plans masterplan` prints it; without it the masterplan's own rows and the line `note`."""
    roll, lines = out["rollup"], []
    if roll:
        glyph = (roll.get("crop") or {}).get("glyph") or "-"
        plus = "+" if roll.get("plus") else ""
        lines.append(f"{glyph} {roll.get('slug', out['slug'])}  {roll.get('plans_done')}/{roll.get('plans_total')} "
                     f"plans  {roll.get('steps_done')}/{roll.get('steps_total')}{plus} steps")
        for row in roll.get("rows", []):
            steps, fields = f"{row.get('done')}/{row.get('total')}", listed(row.get("current_in", []))
            lines.append(f"{row.get('row', ''):>3}  {row.get('slug') or '-':<40} {fields:<8} {steps:>7}  "
                         f"{row.get('status', ''):<12} needs {listed(row.get('needs', []))}")
        for problem in roll.get("problems", []):
            same = f" (as row {problem['same_as']})" if problem.get("same_as") else ""
            lines.append(f"problem: row {problem.get('row')} {problem.get('slug') or '-'} {problem.get('kind')}{same}")
    else:
        lines.append(f"{out['crop'] or '-'} {out['slug']}")
        for row in out["rows"]:
            lines.append(f"{row['number']:>3}  {row['plan'] or '-':<40} {row['status'] or '-':<12} "
                         f"needs {listed(row['needs'])}")
        lines.append(out["note"])
    for plan in out.get("after_landing", []):
        lines.append(f"after the landing: row {plan['row']} {plan['plan']} step(s) {listed(plan['steps'])}")
    if lead := out.get("lead"):
        mine = next((r["plan"] for r in out["rows"] if r["number"] == lead["step"]), None)
        own = f": row {lead['step']}, plan {mine}" if lead["plan"] == out["slug"] and mine else ""
        lines.append(f"this field is a servant of the foreman in field {lead['slot']}{own}")
    return "\n".join(lines)


def show(root: Path, path: Path, as_json: bool, steps_of=None) -> int:
    """`plan.py masterplan`: the masterplan the plan at `path` is, or is a plan of. It only reads, so it works in a
    servant's field too (`lead` in the JSON: its plans/LEAD). `steps_of(plan.md)`: plan.py's reader of a plan's
    steps, for `after_landing`."""
    master = masterplan.master_of(path)
    text, slug = masterplan.read(master), masterplan.slug_of(master)
    roll, note = rollup(root, slug)
    out = {"slug": slug, "title": str(masterplan.key(text, "title") or ""),
           "crop": str(masterplan.key(text, "crop") or ""), "rows": masterplan.rows(text), "rollup": roll, "note": note,
           "after_landing": masterplan_keep.finishable(master, steps_of) if steps_of else []}
    if marker := parallel.read_marker(root):
        out["lead"] = marker
    print(json.dumps(out, indent=2, ensure_ascii=False) if as_json else view(out))
    return 0
