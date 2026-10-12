"""A record plan's step sizing: the values a step row and `run` take, the `plan-steps-sized` check and `migrate`'s
table rewrite (plan 0016, research 0004; plan 0015 D6-D9, plan 0016 D5, D6).

Every step runs in one subagent at its row's Model and Effort (the Agent tool's aliases), sized by Window (the step
model's context window, `1m` for the 5.x models) and Size (its estimated peak context, the subagent's start of about
85k included), at most 35% of Window. `run: <model> <effort> <window>` is the coordinator's own (the session that
runs the steps; its model may be a full id). Only the open rows of a record-format plan are checked: done rows and
legacy plans pass, a finished plan never breaks.

plan.py parses the table and passes its rows here: (line index, cells), the header's column positions by lower-case
name.
"""
import re

import session

RULE = "plan-steps-sized"
MODELS = ("haiku", "sonnet", "opus", "fable")
EFFORTS = ("low", "medium", "high", "xhigh", "max")
WINDOWS = {"200k": 200_000, "1m": 1_000_000}
STEP_SHARE = 0.35
SIZED = ("model", "effort", "window", "size")
TITLES = {"model": "Model", "effort": "Effort", "window": "Window", "size": "Size"}
UNSIZED = "?"
RUN_MODEL = re.compile(r"^(?:haiku|sonnet|opus|fable)$|^claude-(?:haiku|sonnet|opus|fable)(?:-[0-9a-z.]+)+$")
SIZE = re.compile(r"^(\d+(?:\.\d+)?)([km])$")


def clean(cell: str) -> str:
    return cell.strip().strip("`").strip().lower()


def tokens(size: str) -> int | None:
    """`120k` → 120000, `1.5m` → 1500000; None for anything else."""
    found = SIZE.match(clean(size))
    if not found:
        return None
    return int(float(found.group(1)) * (1000 if found.group(2) == "k" else 1_000_000))


def is_done(status: str) -> bool:
    return status.strip().lower().startswith("done")


def run_problem(run: str) -> str:
    """Why `run` is not `<model> <effort> <window>`, or ""."""
    words = [clean(w) for w in run.split()]
    if len(words) != 3:
        return f"run '{run}' needs three words, <model> <effort> <window> (e.g. `opus max 1m`; `plan.py run --sync`)"
    model, effort, window = words
    if not RUN_MODEL.match(model):
        return f"run's model '{model}' is none of {', '.join(MODELS)} nor a full id such as claude-opus-5-5"
    if effort not in EFFORTS:
        return f"run's effort '{effort}' is none of {', '.join(EFFORTS)}"
    if window not in WINDOWS:
        return f"run's window '{window}' is none of {', '.join(WINDOWS)}"
    return ""


def cell_problem(name: str, value: str, window: str) -> str:
    """Why one sized cell of an open row is wrong, or ""; `window` is the row's (for the size's share)."""
    value = clean(value)
    if name == "model" and value not in MODELS:
        return f"Model '{value}' is none of {', '.join(MODELS)}"
    if name == "effort" and value not in EFFORTS:
        return f"Effort '{value}' is none of {', '.join(EFFORTS)}"
    if name == "window" and value not in WINDOWS:
        return f"Window '{value}' is none of {', '.join(WINDOWS)}"
    if name == "size":
        if value in ("", UNSIZED):
            return f"Size '{value}' is not estimated: the step's peak context, e.g. 150k (the autogrill sizes it)"
        size = tokens(value)
        if size is None:
            return f"Size '{value}' is no <n>k or <n>m"
        limit = WINDOWS.get(clean(window))
        if limit and size > STEP_SHARE * limit:
            return (f"Size {value} is over {round(STEP_SHARE * 100)}% of Window {clean(window)} "
                    f"({int(STEP_SHARE * limit) // 1000}k): split the step")
    return ""


def problems(label: str, run: str, run_line: int | None, header: int, cols: dict[str, int],
             rows: list[tuple[int, list[str]]]) -> list[str]:
    """The `plan-steps-sized` lines of a record plan: `<label>:<line>: <message> (plan-steps-sized)`. Nothing when
    no row is open."""
    open_rows = [(i, cells) for i, cells in rows if not is_done(cells[cols["status"]])]
    if not open_rows:
        return []
    out = []
    at = lambda line: f"{label}:{line + 1}" if line is not None else label
    if why := run_problem(run):
        out.append(f"{at(run_line)}: {why} ({RULE})")
    missing = [TITLES[name] for name in SIZED if name not in cols]
    if missing:
        out.append(f"{at(header)}: the step table has no column {', '.join(missing)}: run `plan.py migrate` ({RULE})")
    for i, cells in open_rows:
        window = cells[cols["window"]] if "window" in cols else ""
        for name in SIZED:
            if name in cols and (why := cell_problem(name, cells[cols[name]], window)):
                out.append(f"{at(i)}: step {cells[cols['#']]}: {why} ({RULE})")
    return out


def window_of_model(model: str) -> str:
    """A step's Window from its model: `1m` for a 5.x model (an alias, `claude-<family>-5-*`, `[1m]`), else `200k`."""
    name = model.strip().lower()
    return "1m" if name.endswith("[1m]") or session.FIVE_X.match(name.removesuffix("[1m]")) else "200k"


def run_words(live: dict, fallback: list[str]) -> list[str]:
    """`run`'s three words from the session's live values (session.py), each one the session does not name, or names
    invalidly, from `fallback`: the model as its id (`claude-opus-5-5[1m]` and "Opus 5.5 (1M context)" are
    `claude-opus-5-5`), the window as `200k` or `1m` (not session.py's default for a model it does not know)."""
    words = (list(fallback) + ["", "", ""])[:3]
    model = session.model_id(live.get("model") or "")
    if model and RUN_MODEL.match(model):
        words[0] = model
    effort = clean(live.get("effort") or "")
    if effort in EFFORTS:
        words[1] = effort
    window = clean(live.get("window") or "")
    if window in WINDOWS and (live.get("sources") or {}).get("window") != session.DEFAULT:
        words[2] = window
    return words


def migrate_header(header: list[str]) -> list[str]:
    """The header with Model, Effort, Window and Size added where missing: each after the sized column before it,
    else before the sized column after it, else before Status."""
    out = list(header)
    lower = lambda: [c.lower() for c in out]
    for k, name in enumerate(SIZED):
        if name in lower():
            continue
        before = [n for n in SIZED[:k] if n in lower()]
        after = [n for n in SIZED[k + 1:] if n in lower()]
        if before:
            at = lower().index(before[-1]) + 1
        elif after:
            at = lower().index(after[0])
        else:
            at = lower().index("status")
        out.insert(at, TITLES[name])
    return out


def migrate_row(cells: list[str], old: dict[str, int], new: dict[str, int], run: list[str],
                separator: bool) -> list[str]:
    """One row in the new header's layout (`old`, `new`: column positions by lower-case name): a separator gets
    `---`, a done row empty new cells, an open row its empty Model and Effort from the old `run` (the model as its
    alias), Window from the model and Size `?`."""
    width = max(new.values()) + 1
    by_name = {name: cells[pos] for name, pos in old.items() if pos < len(cells)}
    out = [""] * width
    for name, pos in new.items():
        out[pos] = by_name.get(name, "---" if separator else "")
    if separator or is_done(by_name.get("status", "")):
        return out
    run_model = (run + ["", ""])[0]
    if not clean(out[new["model"]]) and run_model:
        out[new["model"]] = session.family(run_model)
    if not clean(out[new["effort"]]) and (run + ["", ""])[1]:
        out[new["effort"]] = (run + ["", ""])[1]
    if not clean(out[new["window"]]) and clean(out[new["model"]]):
        model = out[new["model"]]
        same = run_model and session.family(run_model) == clean(model)
        out[new["window"]] = window_of_model(run_model if same else model)
    if not clean(out[new["size"]]):
        out[new["size"]] = UNSIZED
    return out
