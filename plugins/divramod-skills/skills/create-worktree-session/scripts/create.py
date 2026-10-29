#!/usr/bin/env python3
"""Start an agent session in the repository's first free and clean worktree.

  create.py [--repo DIR] [--agent claude|codex|opencode] [--model ID] [--effort LEVEL] [--tmux] [--prompt TEXT] [--exact]
            [--role foreman|servant] [--from NN] [--to NN] [--min-free-gb 50] [--lead "<field> <plan> <step|NN-slug>"]

The worktree, counting from 01: no agent session runs in it (no live agent of the repository, no live terminal host
of its worktree, no window of tmux session hal-<repo>), and its worktree is clean or missing and not paused (`hal2-cli-git worktree paused`, plan 0458: a paused field is
skipped, and refused when `--from` and `--to` name only it): the CURRENT_PLAN pointer
names nothing, no uncommitted changes, no commits not on main, no landing in the merge queue (behind main is
fine: the first prompt runs /merge-from-main). The agent starts detached through `hal2-cli-git worktree run <NN> --detach`, in
a hal2 terminal host (`--tmux`: a window of hal-<repo>), with a new session whose first prompt runs /merge-from-main, then the
given prompt (`--exact`: the prompt as given, without /merge-from-main). `--model` and `--effort` go to the agent's process
(saved nowhere). Prints JSON: slot, pane, worktree, the attach command, the model and effort asked for (null: the
agent's default) and the worktrees skipped for their work. Exit 2 when a hal2 CLI is missing, 3 when no free and clean
worktree is left in the range, 1 for any other failure.

`--role foreman|servant` (hal2 plan 0383, D15): the session loads its role skill first, `/foreman` or `/servant` (its duties
and the repository's roles/<role>/ROLE.md), before the given prompt, also with `--exact`: pass it for every session that
runs a plan (a foreman) or a foreman's step (a servant, in a field holding `plans/LEAD`).

`--from NN` starts the search at worktree NN, 00 to 99 (the farmer's foremen: 00; a foreman's servants: 30), `--to NN`
ends it there (default 99, also the farmer's foremen: a foreman works in any field, its role comes from `plans/LEAD`,
not the number, D16). A field holding `plans/LEAD` is a servant's and is skipped unless `--role servant`. A missing worktree is
created by hal2's `worktree run` from main; it needs `--min-free-gb` free disk (default 50).

`--lead "<foreman's field> <plan> <step|NN-slug>"` (plan 0376 D6; only with `--from 30` or more) makes the session a
servant: `plans/LEAD` and the `CURRENT_PLAN` pointer (the plan) are written into its worktree (before the start when the
worktree exists, else right after hal2 created it) and the first prompt merges the foreman's pushed branch
(`git merge origin/<field>`) and runs `/servant`. The third word is a legacy step or row (digits) or a sub-plan
`NN-slug`, as `plan.py ready` prints the line. It is a servant start (`--role servant` implied: it may take a field
holding `plans/LEAD`; `--role foreman` is refused).
"""
import json
import os
import shlex
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

sys.path.insert(0, next(str(_p / "scripts") for _p in Path(__file__).resolve().parents if (_p / ".claude-plugin").is_dir()))
from skillpath import pointers  # noqa: E402  (the skills unit's scripts/, plan 0360 D20)

GONE = {"ended", "failed"}
# What hal2-agents' spawn drops, so the agent is no child of this tmux pane, terminal host or Claude session.
DROPPED_ENV = ("TMUX", "TMUX_PANE", "HAL2_TERMINAL", "CLAUDECODE", "CLAUDE_CODE_CHILD_SESSION",
               "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_BRIDGE_SESSION_ID", "CLAUDE_CODE_MESSAGING_SOCKET",
               "CLAUDE_CODE_MESSAGING_TOKEN", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_EXECPATH",
               "CLAUDE_CODE_SESSION_ATTENDED", "CLAUDE_PID", "CLAUDE_EFFORT")


def die(message: str, code: int = 1) -> NoReturn:
    print(f"create.py: {message}", file=sys.stderr)
    sys.exit(code)


def need(tool: str) -> None:
    if not shutil.which(tool):
        die(f"{tool} is missing: run scripts/install-prerequisites.sh (needs hal2)", 2)


def run(*args: str, cwd: Path | None = None, check: bool = True) -> str:
    need(args[0])
    r = subprocess.run(list(args), cwd=cwd, capture_output=True, text=True)
    if check and r.returncode != 0:
        die(f"{' '.join(args[:3])} failed: {(r.stderr or r.stdout).strip()}")
    return r.stdout if r.returncode == 0 else ""


def main_checkout(repo: Path) -> Path:
    out = run("git", "worktree", "list", "--porcelain", cwd=repo)
    first = out.splitlines()[0] if out else ""
    return Path(first.split(" ", 1)[1]) if first.startswith("worktree ") else repo


def slot_of(name: str) -> str | None:
    return name if len(name) == 2 and name.isdigit() else None


def taken(repo: Path) -> set[str]:
    """Worktrees a session holds: a live agent, a live terminal host of the worktree, a window of hal-<repo>."""
    agents = json.loads(run("hal2-cli-agents", "list", "--json"))
    agents = agents if isinstance(agents, list) else agents.get("agents", [])
    slots = {a.get("slot") for a in agents if a.get("state") not in GONE and a.get("project")
             and Path(a["project"]).resolve() == repo.resolve()}
    hosts = json.loads(run("hal2-cli-agents", "terminal", "list", "--json") or "[]")
    for host in hosts if isinstance(hosts, list) else hosts.get("terminals", []):
        worktree = Path(host.get("worktree") or "/")
        if host.get("alive") and worktree.parent.name == repo.name:
            slots.add(worktree.name)
    if shutil.which("tmux"):
        windows = run("tmux", "list-windows", "-t", f"hal-{repo.name}", "-F", "#W", check=False)
        slots |= set(windows.split())
    return {s for s in slots if s and slot_of(s)}


def paused_fields(repo: Path) -> dict[str, str]:
    """{field: "paused by <by>: <why>"} from `hal2-cli-git worktree paused --json` (hal2 plan 0458, D2: never the file).
    An older CLI without the command, or an answer that cannot be read, is nothing paused."""
    if not shutil.which("hal2-cli-git"):
        return {}
    r = subprocess.run(["hal2-cli-git", "worktree", "paused", "--json"], cwd=repo, capture_output=True, text=True)
    try:
        rows = json.loads(r.stdout).get("fields", []) if r.returncode == 0 else []
    except (ValueError, AttributeError):
        return {}
    return {str(p["field"]): f"paused by {p.get('by') or '?'}: {p.get('why') or 'no reason given'}"
            for p in rows if isinstance(p, dict) and p.get("field")}


def work(entry: dict, landing: str | None, servant: bool = False) -> str | None:
    """Why a worktree holds work, or None when it is clean. A field holding `plans/LEAD` is a servant's (hal2 plan 0383,
    D16: the marker says it, not the field's number): only a servant start (`--role servant`) takes it."""
    if not servant and entry.get("path") and pointers(__file__).exists(entry["path"], "LEAD"):
        return "a servant's field (plans/LEAD)"
    if entry.get("plan"):
        return f"works on {entry['plan']}"
    if entry.get("dirty"):
        return "uncommitted changes"
    if entry.get("main_ahead"):
        return f"{entry['main_ahead']} commit{'s' if entry['main_ahead'] != 1 else ''} not on main"
    return f"its landing is {landing} in the merge queue" if landing else None


def choose(repo: Path, first: int = 1, last: int = 99, servant: bool = False) -> tuple[str, list[dict], dict | None]:
    listed = json.loads(run("hal2-cli-git", "worktree", "list", "--json", cwd=repo)).get("worktrees", [])
    worktrees = {w["name"]: w for w in listed if not w.get("main")}
    queue = json.loads(run("hal2-cli-git", "worktree", "queue", "--json", cwd=repo)).get("queue", [])
    landings = {t.get("slot"): t.get("state") or "queued" for t in queue if t.get("repo") == repo.name}
    busy, skipped, paused = taken(repo), [], paused_fields(repo)
    if first == last and f"{first:02d}" in paused:
        die(f"field {first:02d} is {paused[f'{first:02d}']} (`hal2-cli-git worktree resume {first:02d}` first)")
    for n in range(first, last + 1):
        slot = f"{n:02d}"
        if slot in busy:
            continue
        why = paused.get(slot) or (work(worktrees[slot], landings.get(slot), servant) if slot in worktrees else None)
        if why is None:
            return slot, skipped, worktrees.get(slot)
        skipped.append({"slot": slot, "why": why})
    die(f"no free and clean worktree from {first:02d} to {last:02d}", 3)


def free_gb(repo: Path) -> float:
    """Free disk where the worktrees live (hal2: ~/.hal/git/worktree)."""
    folder = Path.home() / ".hal" / "git" / "worktree"
    return shutil.disk_usage(folder if folder.exists() else repo).free / 2**30


def prepare(repo: Path, entry: dict | None, min_gb: float) -> None:
    """Before the start: free disk for a new worktree (hal2's `worktree run` creates it)."""
    if entry is None and free_gb(repo) < min_gb:
        needed = ("%f" % min_gb).rstrip("0").rstrip(".")
        die(f"only {free_gb(repo):.0f} GB free, a new worktree needs {needed} (--min-free-gb): prune a worktree first")


def start(repo: Path, slot: str, argv: list[str], prompt: str) -> dict:
    need("hal2-cli-git")
    command = ["hal2-cli-git", "worktree", "run", slot, "--agent", arg(argv, "--agent") or "claude",
               "--detach", "--json"]
    if "--tmux" in argv:
        command.append("--tmux")
    if arg(argv, "--model"):
        command += ["--model", arg(argv, "--model")]
    if arg(argv, "--effort"):
        command += ["--effort", arg(argv, "--effort")]
    command += ["--prompt", prompt]
    env = {k: v for k, v in os.environ.items() if k not in DROPPED_ENV}
    shell = os.environ.get("SHELL") or "/bin/zsh"
    r = subprocess.run([shell, "-lc", "exec " + shlex.join(command)], cwd=repo, env=env, stdin=subprocess.DEVNULL,
                       capture_output=True, text=True)
    if r.returncode != 0:
        die(f"hal2-cli-git worktree run {slot} failed: {(r.stderr + r.stdout).strip()}")
    for line in reversed(r.stdout.splitlines()):
        try:
            return json.loads(line)
        except ValueError:
            continue
    die(f"hal2-cli-git worktree run {slot} printed no report: {r.stdout.strip()}")


ROLES = ("foreman", "servant")


def role_load(role: str) -> str:
    return f"/{role} (it prints your duties, the skill's and the repository's roles/{role}/ROLE.md; work by them)"


def first_prompt(prompt: str | None, exact: bool, role: str | None = None) -> str:
    """The session's first prompt: /merge-from-main (unless `exact` with a prompt), then the role skill (`role`), then
    `prompt`. Without a role: as before."""
    if not role:
        if exact and prompt:
            return prompt
        return f"Run /merge-from-main first, then:\n\n{prompt}" if prompt else "/merge-from-main"
    steps = ([] if exact else ["/merge-from-main"]) + [role_load(role)]
    head = f"Run {steps[0]} first" + "".join(f", then {step}" for step in steps[1:])
    return f"{head}, then:\n\n{prompt}" if prompt else f"{head}."


def arg(argv: list[str], flag: str) -> str | None:
    return argv[argv.index(flag) + 1] if flag in argv and argv.index(flag) + 1 < len(argv) else None


LEAD = re.compile(r"^(\d{2}) (\d{4}-[a-z0-9-]+) (\d+|\d{2}-[a-z0-9-]+)$")


def lead_of(argv: list[str], first: int) -> str | None:
    """The `--lead` line as `plans/LEAD` holds it, None without the flag; dies when it is malformed or `--from` < 30
    (a servant works only in a worktree from 30 to 99)."""
    if "--lead" not in argv:
        return None
    line = " ".join((arg(argv, "--lead") or "").split())
    if first < 30:
        die("--lead needs --from 30 or more: a servant works only in a worktree from 30 to 99")
    if not LEAD.match(line):
        die(f"--lead needs \"<field> <plan> <step or NN-slug>\" (07 0376-one-plan-shape 02-readers), not '{line}'")
    return line


def write_lead(folder: Path, line: str) -> None:
    """The servant's marker and current plan (neither committed): in the git dir's hal/ in a store-home farm, else
    plans/LEAD and the CURRENT_PLAN pointer (hal2 plan 0409 step 12)."""
    pointers(__file__).write(folder, "LEAD", line)
    pointers(__file__).write(folder, "CURRENT_PLAN", line.split()[1])


def lead_prompt(line: str, prompt: str | None) -> str:
    field, plan, part = line.split()
    task = (f"You are the servant of field {field} for sub-plan or step {part} of plan {plan} (plans/LEAD and "
            f"the CURRENT_PLAN pointer are written). Merge the foreman's pushed branch first (`git fetch origin && git "
            f"merge origin/{field}`), then run /servant.")
    return f"{task}\n\n{prompt}" if prompt else task


def main(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    repo = main_checkout(Path(arg(argv, "--repo") or ".").expanduser().resolve())
    first = arg(argv, "--from") or "1"
    if not first.isdigit() or not 0 <= int(first) <= 99:
        die(f"--from needs a worktree from 00 to 99, not '{first}'")
    last = arg(argv, "--to") or "99"
    if not last.isdigit() or not int(first) <= int(last) <= 99:
        die(f"--to needs a worktree from {first} to 99, not '{last}'")
    if "--base" in argv:
        die("--base is gone (skills plan 0016): a plan's steps run in subagents, never in servant worktrees")
    lead = lead_of(argv, int(first))
    role = arg(argv, "--role")
    if role and role not in ROLES:
        die(f"--role needs foreman or servant, not '{role}'")
    if lead and role == "foreman":
        die("--lead starts a servant: drop --role foreman")
    slot, skipped, entry = choose(repo, int(first), int(last), role == "servant" or bool(lead))
    prepare(repo, entry, float(arg(argv, "--min-free-gb") or 50))
    prompt = lead_prompt(lead, arg(argv, "--prompt")) if lead else arg(argv, "--prompt")
    if lead and entry and entry.get("path"):
        write_lead(Path(entry["path"]), lead)
    report = start(repo, slot, argv, first_prompt(prompt, "--exact" in argv and not lead, None if lead else role))
    if lead and not (entry and entry.get("path")) and report.get("worktree"):
        write_lead(Path(report["worktree"]), lead)
    result = {
        "repo": repo.name,
        "slot": report.get("slot") or slot,
        "pane": report.get("pane"),
        "mode": report.get("mode"),
        "worktree": report.get("worktree"),
        "attach": f"hal2-cli-agents attach {repo.name}/{slot}",
        "model": arg(argv, "--model"),
        "effort": arg(argv, "--effort"),
        "skipped": skipped,
        **({"lead": lead} if lead else {}),
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
