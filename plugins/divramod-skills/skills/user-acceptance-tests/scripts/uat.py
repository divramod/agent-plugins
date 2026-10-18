#!/usr/bin/env python3
"""uat.py: the deterministic part of the user-acceptance-tests skill (hal2 plan 0364, step 6, D11).

A thin layer on `hal2-cli-plans uat list|set` (its verdicts already track which checks are confirmed; no second tracker):

  uat.py list  [<plan>] [--json]            every check: confirmed, open, failed, blocked, skipped
  uat.py open  [<plan>] [--json]            the checks still to walk, whole, in walk order
  uat.py show  [<plan>] <check> [--json]    one check, whole
  uat.py next  [<plan>] [--json]            the first open check, whole
  uat.py set   [<plan>] <check> pass|fail|skip|blocked [--note <t>] [--shot] [--step <n>] [--duration <s>] [--evidence <f>]
  uat.py plan  [<plan>]                     the plan the call resolves to

The plan is the argument (a number or a slug of `plans/`), else the name in `plans/CURRENT_PLAN`. A check is `U<n>`, a bare
`<n>` after the plan, or `<NNNN>/U<n>` (a regression check carried from an earlier plan). `--repo <dir>` names the checkout;
the default is git's top level of the current directory. The CLI is `$HAL2_CLI_PLANS`, else `hal2-cli-plans`.
Confirmed means `pass`; open means `untested`, `retest` or an outdated pass: only those are walked, so a walk ends.
Exit 0 ok, 1 nothing to show or the CLI failed, 2 bad arguments or no plan.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

VERDICTS = ("pass", "fail", "skip", "blocked")
CHECK = re.compile(r"^(?:\d{1,4}/)?[uU]\d+$")
LABELS = {"pass": "confirmed", "untested": "open", "retest": "open", "fail": "failed", "blocked": "blocked", "skip": "skipped"}
VALUE_FLAGS = ("--note", "--step", "--duration", "--evidence")


class UatError(Exception):
    def __init__(self, message: str, code: int = 2):
        super().__init__(message)
        self.code = code


def cli() -> str:
    return os.environ.get("HAL2_CLI_PLANS") or "hal2-cli-plans"


def repo_root(repo: str | None) -> Path:
    if repo:
        return Path(repo).resolve()
    out = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return Path(out.stdout.strip()) if out.returncode == 0 and out.stdout.strip() else Path.cwd()


def run_cli(args: list[str], root: Path) -> str:
    try:
        done = subprocess.run([cli(), *args, "--repo", str(root)], capture_output=True, text=True)
    except FileNotFoundError:
        raise UatError(f"{cli()} is not installed: run check-prerequisites.sh", 1)
    if done.returncode != 0:
        raise UatError((done.stderr or done.stdout).strip() or f"{cli()} exited {done.returncode}", 1)
    return done.stdout


def is_check(token: str) -> bool:
    return bool(CHECK.match(token))


def split_args(tokens: list[str]) -> tuple[str | None, str | None]:
    """The plan and the check of the positional tokens: `[<plan>] [<check>]`, a lone check token is the current plan's."""
    plan = check = None
    for token in tokens:
        if is_check(token):
            if check is not None:
                raise UatError(f"two checks given: {check} and {token}")
            check = token
        elif plan is None:
            plan = token
        elif check is None and token.isdigit():
            check = token  # `/uat 364 2` means U2
        else:
            raise UatError(f"unexpected argument: {token}")
    return plan, check


def norm_check(check: str) -> str:
    if check.isdigit():
        return f"U{int(check)}"
    head, _, tail = check.rpartition("/")
    return f"{head.zfill(4)}/{tail.upper()}" if head else tail.upper()


def resolve_plan(arg: str | None, root: Path) -> str:
    """The folder name of the plan: from the argument, else plans/CURRENT_PLAN."""
    plans = root / "plans"
    if arg is None:
        current = plans / "CURRENT_PLAN"
        arg = current.read_text().strip() if current.is_file() else ""
        if not arg:
            raise UatError("no plan given and plans/CURRENT_PLAN is empty")
        if not (plans / arg).is_dir():
            raise UatError(f"plans/CURRENT_PLAN names '{arg}', which is no plan folder: name the plan")
        return arg
    if (plans / arg).is_dir():
        return arg
    folders = sorted(p.name for p in plans.glob("[0-9][0-9][0-9][0-9]-*") if p.is_dir())
    if arg.isdigit():
        found = [f for f in folders if f.startswith(f"{int(arg):04d}-")]
    else:
        found = [f for f in folders if f.split("-", 1)[1] == arg] or [f for f in folders if arg in f]
    if len(found) != 1:
        raise UatError(f"{'no plan' if not found else 'several plans'} match '{arg}'" + (f": {', '.join(found)}" if found else ""))
    return found[0]


def load(plan: str, root: Path) -> dict:
    """The CLI's record of one plan: slug, before, checks (key, check, status), counts."""
    records = json.loads(run_cli(["uat", "list", "--plan", plan, "--json"], root) or "[]")
    for record in records:
        if record.get("slug") == plan:
            return record
    raise UatError(f"{plan} has no uat.md", 1)


def state_of(entry: dict) -> str:
    status = entry.get("status") or {}
    return "retest" if status.get("outdated") and status.get("state") == "pass" else status.get("state") or "untested"


def is_open(entry: dict) -> bool:
    return state_of(entry) in ("untested", "retest")


def label(entry: dict) -> str:
    return LABELS.get(state_of(entry), state_of(entry))


def render_check(plan: str, entry: dict) -> str:
    c = entry["check"]
    lines = [f"{entry['key']}  {c.get('title', '')}  ({c.get('priority') or 'p?'}, {state_of(entry)})", ""]
    if c.get("preconditions"):
        lines += ["Before: " + " ".join(c["preconditions"]), ""]
    if c.get("open"):
        lines.append(f"Open: {c['open']}")
    if c.get("run"):
        lines.append(f"Run: {c['run']}")
    if c.get("charter"):
        lines.append(f"Charter: {c['charter']}" + (f" (timebox {c['timebox']})" if c.get("timebox") else ""))
    lines += ["", "Steps:", *[f"{i}. {step}" for i, step in enumerate(c.get("steps") or [], 1)], ""]
    lines.append(f"Expected: {c.get('expected') or '(none written)'}")
    last = (entry.get("status") or {}).get("latest")
    if last:
        lines.append(f"Last verdict: {last.get('status')}" + (f", {last['note']}" if last.get("note") else ""))
    return "\n".join(lines) + f"\n\nSet: uat.py set {plan} {entry['key']} pass|fail|skip|blocked [--note <text>]\n"


def summary(record: dict) -> dict:
    checks = [{"key": e["key"], "title": e["check"].get("title", ""), "priority": e["check"].get("priority"),
               "state": state_of(e), "label": label(e), "open": is_open(e)} for e in record["checks"]]
    done = sum(1 for c in checks if c["label"] == "confirmed")
    return {"plan": record["slug"], "before": record.get("before"), "confirmed": done, "total": len(checks),
            "open": sum(1 for c in checks if c["open"]), "checks": checks}


def render_list(s: dict) -> str:
    lines = [f"{s['plan']}: {s['confirmed']} of {s['total']} confirmed, {s['open']} open"]
    lines += [f"  {c['key']:<8}  {c['priority'] or '':<3}  {c['label']:<9}  {c['title']}" for c in s["checks"]]
    other = [c["key"] for c in s["checks"] if c["label"] in ("failed", "blocked", "skipped")]
    if other:
        lines.append(f"not walked again unless you name them: {', '.join(other)}")
    return "\n".join(lines) + "\n"


def find(record: dict, check: str) -> dict:
    for entry in record["checks"]:
        if entry["key"].upper() == check.upper():
            return entry
    raise UatError(f"{record['slug']} has no check {check}: " + ", ".join(e["key"] for e in record["checks"]), 1)


def parse_options(rest: list[str]) -> tuple[list[str], dict]:
    """Split `rest` into positionals and the options of set; --json for the readers."""
    positional, opts, i = [], {"json": False, "repo": None, "passthrough": []}, 0
    while i < len(rest):
        token = rest[i]
        if token == "--json":
            opts["json"] = True
        elif token == "--shot":
            opts["passthrough"].append(token)
        elif token == "--repo" or token in VALUE_FLAGS:
            if i + 1 >= len(rest):
                raise UatError(f"{token} needs a value")
            if token == "--repo":
                opts["repo"] = rest[i + 1]
            else:
                opts["passthrough"] += [token, rest[i + 1]]
            i += 1
        elif token.startswith("--"):
            raise UatError(f"unknown option {token}")
        else:
            positional.append(token)
        i += 1
    return positional, opts


def command(verb: str, rest: list[str]) -> str:
    positional, opts = parse_options(rest)
    root = repo_root(opts["repo"])
    verdict = None
    if verb == "set":
        if not positional or positional[-1] not in VERDICTS:
            raise UatError("set needs a verdict: " + "|".join(VERDICTS))
        verdict = positional.pop()
    plan_arg, check = split_args(positional)
    plan = resolve_plan(plan_arg, root)
    if verb == "plan":
        return plan + "\n"
    if verb == "set":
        if not check:
            raise UatError("set needs a check: uat.py set [<plan>] <check> pass|fail|skip|blocked")
        record = load(plan, root)
        key = find(record, norm_check(check))["key"]
        return run_cli(["uat", "set", plan, key, verdict, *opts["passthrough"]], root)
    record = load(plan, root)
    if verb == "list":
        s = summary(record)
        return json.dumps(s, indent=2) + "\n" if opts["json"] else render_list(s)
    if verb in ("show", "next", "open"):
        if verb == "show":
            if not check:
                raise UatError("show needs a check: uat.py show [<plan>] <check>")
            entries = [find(record, norm_check(check))]
        else:
            entries = [e for e in record["checks"] if is_open(e)]
            entries = entries[:1] if verb == "next" else entries
        if not entries:
            raise UatError(f"{plan}: no open check, all are confirmed, failed, blocked or skipped (uat.py list)", 1)
        if opts["json"]:
            return json.dumps({"plan": plan, "before": record.get("before"), "checks": entries}, indent=2) + "\n"
        head = f"{plan}\nBefore you start: {record['before']}\n\n" if record.get("before") else f"{plan}\n\n"
        return head + "\n".join(render_check(plan, e) for e in entries)
    raise UatError(f"unknown command '{verb}': list, open, show, next, set, plan")


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("h", "help", "--help", "-h"):
        print(__doc__)
        return 0
    try:
        sys.stdout.write(command(argv[0], argv[1:]))
        return 0
    except UatError as error:
        print(f"uat.py: {error}", file=sys.stderr)
        return error.code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
