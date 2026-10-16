#!/usr/bin/env python3
"""Collect what hal2's Mac VM (Tart) runner left behind, for the fix-tart skill.

  evidence.py show [--hours 2]
      the VM's `hal2-daemon vms list --json` row (state, runner_enabled, job), `tart list`, the last runner
      task logs, the daemon log's hal2_vm_node / hal2_ci_supervisor lines, the CI supervisor's journal,
      pmset's sleeps and wakes, the GitHub jobs wanting the VM's labels (skipped with a note when gh
      fails) and the known cases found (the doctor)
  evidence.py doctor [--hours 2] [--json]
      the known cases' signatures (cases.md) in the window; "no case" and exit 0 when none
  evidence.py capture --out <dir> [--hours 2]
      the same as files, to turn into hal2 test fixtures, with a README.md naming each
  evidence.py selfcheck [--repo ~/a/hal2]
      whether SKILL.md's paths, log strings and config keys still match hal2's code

Every source is overridable (sources.py: --daemon-log, --tasks-dir, --journal, --pmset-log-file,
--vms-json, --tart-list, --gh-jobs; --now for a fixed clock). Exit 0 on success, 1 when selfcheck finds
drift, 2 when a required tool (hal2-daemon) is missing.
"""

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import signatures  # noqa: E402
import sources  # noqa: E402

SKILL_MD = Path(__file__).resolve().parent.parent / "SKILL.md"
RUST = ["code/rust/libs/hal2-vm/src", "code/rust/libs/hal2-vm-node/src",
        "code/rust/libs/hal2-ci-supervisor/src", "code/rust/apps/hal2-daemon/src"]
CONFIG_RS = "code/rust/libs/hal2-ci-supervisor/src/config.rs"
SHOW_LINES = 60  # daemon lines `show` prints (capture keeps all)
SHOW_TASKS = 3


def window(args):
    now = sources.utc(args.now) if args.now else datetime.now(timezone.utc)
    return now - timedelta(hours=args.hours), now


def context(args, with_extras=False):
    """Everything read once: the doctor's context, and for show/capture the rest."""
    since, now = window(args)
    ctx = {
        "now": now, "since": since,
        "daemon": sources.daemon_lines(args.daemon_log, since, now),
        "journal": sources.journal_lines(args.journal, since, now),
        "tasks": sources.runner_tasks(args.tasks_dir, since, now),
        "pmset": sources.pmset_events(args.pmset_log_file, since, now),
        "vm": sources.vm_row(args.vms_json, args.vm),
    }
    ctx["missing_daemon_log"] = ctx["daemon"] is None
    ctx["daemon_all"] = ctx["daemon"] or []
    ctx["daemon"] = [(t, l) for t, l in ctx["daemon_all"] if sources.is_vm(l)]
    if with_extras:
        ctx["tart"] = sources.tart_list(args.tart_list)
        ctx["labels"] = sources.labels()
        ctx["gh"] = sources.gh_jobs(args.gh_jobs, ctx["labels"])
    return ctx


def doctor_text(ctx, hours):
    found = signatures.find(ctx)
    lines = [f"case {f['case']} {f['slug']} ({sources.fmt(f['at'])}): {f['detail']}" for f in found]
    lines.append(f"{len(found)} finding(s) in the last {hours:g} h" if found else f"no case in the last {hours:g} h")
    if ctx["missing_daemon_log"]:
        lines.append("note: no daemon log (--daemon-log)")
    return found, "\n".join(lines)


def task_text(task, cut=False):
    lines = task["lines"]
    if cut and len(lines) > 30:
        lines = lines[:12] + [f"... ({len(lines) - 24} lines)"] + lines[-12:]
    head = f"-- task {task['name']}: started {sources.fmt(task['start'])}, last write {sources.fmt(task['end'])}"
    return "\n".join([head] + lines)


def sections(ctx, args, short):
    """(file name, title, text) of every source; `short` cuts long ones for the screen."""
    vm = ctx["vm"]
    row = json.dumps(vm, indent=1) if vm else f"(no row {args.vm} in `hal2-daemon vms list --json`)"
    tasks = ctx["tasks"][-SHOW_TASKS:] if short else ctx["tasks"]
    daemon = [l for _, l in ctx["daemon"]]
    auth = sum(1 for _, l in ctx["daemon_all"] if signatures.AUTH.search(l))
    gh = ctx["gh"]
    gh_text = gh if isinstance(gh, str) else (
        "\n".join(f"run {r} job {j} {s} [{','.join(n)}]" for r, j, s, n in gh) or "(none)")
    out = [
        ("vms.json", f"vms list: {args.vm}", row),
        ("tart-list.txt", "tart list", ctx["tart"].rstrip()),
        ("tasks.txt", f"runner task logs ({len(ctx['tasks'])} in the window)",
         "\n\n".join(task_text(t, short) for t in tasks) or "(none)"),
        ("daemon.log", f"daemon log: hal2_vm, hal2_vm_node, hal2_ci_supervisor ({len(daemon)} lines, "
                       f"{auth} gh 401/404 in all its lines)",
         "\n".join(daemon[-SHOW_LINES:] if short else daemon) or "(none)"),
        ("journal.log", f"supervisor journal {args.journal}",
         "(no journal yet)" if ctx["journal"] is None else "\n".join(l for _, l in ctx["journal"]) or "(none)"),
        ("pmset.txt", "pmset sleep/wake (UTC)",
         "(pmset not readable)" if ctx["pmset"] is None else
         "\n".join(f"{sources.fmt(t)} {k} {x}" for t, k, x in ctx["pmset"]) or "(none)"),
        ("gh-jobs.txt", f"GitHub jobs wanting {','.join(ctx['labels'])}", gh_text),
        ("doctor.txt", "known cases (doctor)", doctor_text(ctx, args.hours)[1]),
    ]
    return out


def show(args):
    ctx = context(args, with_extras=True)
    print(f"window {sources.fmt(ctx['since'])} to {sources.fmt(ctx['now'])}")
    for _, title, text in sections(ctx, args, short=True):
        print(f"\n== {title}\n{text}")


def capture(args):
    ctx = context(args, with_extras=True)
    out = Path(args.out).expanduser()
    (out / "tasks").mkdir(parents=True, exist_ok=True)
    readme = [f"# fix-tart capture, {sources.fmt(ctx['since'])} to {sources.fmt(ctx['now'])}", ""]
    for name, title, text in sections(ctx, args, short=False):
        (out / name).write_text(text + "\n")
        readme.append(f"- `{name}`: {title}")
    for task in ctx["tasks"]:
        (out / "tasks" / f"{task['name']}.log").write_text("\n".join(task["lines"]) + "\n")
    readme.append("- `tasks/<id>.log`: each runner task log as it is (its start is the UUIDv7 id's time)")
    (out / "README.md").write_text("\n".join(readme) + "\n")
    print(out)
    return 0


def doctor(args):
    ctx = context(args)
    found, text = doctor_text(ctx, args.hours)
    if args.json:
        print(json.dumps({"hours": args.hours, "findings": found}, default=str, indent=1))
    else:
        print(text)
    return 0


def rust_source(repo):
    return "\n".join(p.read_text(errors="replace") for d in RUST for p in (repo / d).rglob("*.rs"))


def block(skill, name):
    """The backticked items between the lines `<!-- name -->` and `<!-- /name -->` (markers on their own lines)."""
    m = re.search(rf"^<!-- {name} -->$(.*?)^<!-- /{name} -->$", skill, re.M | re.S)
    return re.findall(r"`([^`]+)`", m.group(1)) if m else []


def selfcheck(args):
    """SKILL.md's paths exist, its log strings and evidence's needles are in hal2's code, its keys in config.rs."""
    repo = Path(args.repo).expanduser()
    skill = SKILL_MD.read_text()
    drift = []
    for rel in sorted(set(re.findall(r"`((?:code|utils)/[^`\s]+?)`", skill))):
        if "<" in rel:
            continue
        if not (list(repo.glob(rel)) if "*" in rel else (repo / rel).exists()):
            drift.append(f"missing path {rel}")
    source = rust_source(repo)
    for text in dict.fromkeys(block(skill, "strings") + signatures.FRAGMENTS):
        if text not in source:
            drift.append(f"log string `{text}` no longer in {', '.join(RUST)}")
    config = (repo / CONFIG_RS).read_text() if (repo / CONFIG_RS).exists() else ""
    for key in block(skill, "keys"):
        if not re.search(rf"pub {re.escape(key)}:", config):
            drift.append(f"config key `{key}` not in {CONFIG_RS}")
    for line in drift:
        print("DRIFT", line)
    print("ok" if not drift else f"{len(drift)} drift(s): update SKILL.md (Insider knowledge) or the code")
    return 1 if drift else 0


def add_sources(p):
    d = sources.defaults()
    p.add_argument("--hours", type=float, default=2)
    p.add_argument("--now", help="the clock, a UTC ISO time (tests)")
    p.add_argument("--vm", default=sources.VM)
    for key, value in d.items():
        p.add_argument("--" + key.replace("_", "-"), dest=key, default=value)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    add_sources(sub.add_parser("show"))
    k = sub.add_parser("capture")
    add_sources(k)
    k.add_argument("--out", required=True)
    d = sub.add_parser("doctor")
    add_sources(d)
    d.add_argument("--json", action="store_true")
    sub.add_parser("selfcheck").add_argument("--repo", default="~/a/hal2")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "show":
            show(args)
            return 0
        return {"capture": capture, "doctor": doctor, "selfcheck": selfcheck}[args.cmd](args)
    except sources.Missing as e:
        print(f"evidence.py: missing {e}; run scripts/install-prerequisites.sh", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
