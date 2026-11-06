"""The land branch's name is asked of hal2-git, never built here (plan 0607 step 6, D4, D6, D10, D13; the user,
2026-11-04: "the name of a train should also be checked by the pre checks ... this also needs to be deterministic
now"; train 51's run went out as `land/tollman-train-big-0514-0581-28`: started by hand, unmarked, hal2-git fell back
to `land/<carrier>`).

`ask` is the one place the scripts call `hal2-cli-git worktree land-ref [--slot <slot>] --json` and read its JSON
(`schema` 1, `slot`, `kind`, `current`, `next`; a schema it does not know is refused). `current` is the branch a
landing runs or ran on, `next` the one the next new candidate is pushed to. A carrier without its numbered train mark,
a field without a numbered plan and `main` make the CLI exit 1 with a one-line message: that is the answer, never a
guessed name.

`engine.land` asks `refuses` twice: before the pretest (no pretest for a landing that may not push) and right before
the landing (after the wait for the run before, the last point before every push). It refuses when the CLI cannot
name the carrier's branch, when the carrier is no train (`kind`), when `--land-ref` names another branch than the CLI
and when the name is not the standing train's (`land/train-<number>-`): one line `tollman: refused: ...` and the
landing's result as a JSON line (`status` `refused`, as head_guard's), exit 1; never a push under a wrong name.
"""

import json

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import mtm_scan
import train_state

SCHEMA = 1
KEYS = ("slot", "kind", "current", "next")
LINE = "tollman: refused: the landing would push {branch}: {why}"


def cli(args: list[str], cwd: str) -> tuple[int, str]:
    from engine import cli as run  # lazily: engine imports this module
    return run(args, cwd)


def ask(top: str, slot: str | None = None, run=None) -> tuple[dict | None, str]:
    """(the CLI's report for `slot`, else the field of `top`; ``) or (None, why): the CLI's own one-line message
    when it exits 1, or what is wrong with its answer (not JSON, a schema other than SCHEMA, a missing key)."""
    code, out = (run or cli)(["worktree", "land-ref", *(["--slot", slot] if slot else []), "--json"], top)
    try:
        data = json.loads(out)
    except ValueError:
        return None, (out.splitlines() or [f"exit {code}"])[-1][-300:] if code else "land-ref printed no JSON"
    if code:
        error = data.get("error") if isinstance(data, dict) else None
        return None, str((error or {}).get("message") or f"exit {code}")[-300:]
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        return None, f"land-ref's schema {data.get('schema') if isinstance(data, dict) else '?'} is not {SCHEMA}"
    if lacking := [k for k in KEYS if k not in data]:
        return None, f"land-ref's answer lacks {', '.join(lacking)}"
    return data, ""


def next_ref(top: str, slot: str | None = None, run=None) -> tuple[str | None, str]:
    """(the `--land-ref` form of the branch the next candidate of `slot` is pushed to, ``): `train-7-2` for
    `land/train-7-2`; (None, why) when the CLI names none."""
    report, why = ask(top, slot, run)
    return (report["next"].removeprefix("land/"), "") if report else (None, why)


def current(top: str, slot: str | None = None, run=None) -> str | None:
    """The branch the landing of `slot` runs or ran last on (`current`), None before any or when the CLI cannot say."""
    report, _ = ask(top, slot, run)
    return report["current"] if report else None


def why_bad(report: dict | None, why: str, ref: str | None, number) -> str | None:
    """Why the report (or the CLI's failure `why`) is no good answer for the standing train numbered `number`."""
    if report is None:
        return why
    if report["kind"] != "train":
        return "the carrier has no numbered train mark (`--train <n> --attempt <a>`)"
    if ref and f"land/{ref}" != report["next"]:
        return f"--land-ref names land/{ref}, hal2-git names {report['next']}"
    if number and not report["next"].startswith(f"land/train-{number}-"):
        return f"the standing train is {number}"
    return None


def refuses(top: str, ref: str | None = None, read=ask) -> int:
    """1 (printed) when the landing of the carrier `top` would push a branch hal2-git does not name for the standing
    train, else 0."""
    main = mtm_scan.main_checkout(top)
    train = train_state.standing(train_state.lines(main)) or {}
    report, why = read(top)
    why = why_bad(report, why, ref, train.get("number"))
    if not why:
        return 0
    line = LINE.format(branch=(report or {}).get("next") or "a branch", why=why)
    print(line, flush=True)
    print(json.dumps({"status": "refused", "run": None, "message": line}), flush=True)
    return 1
