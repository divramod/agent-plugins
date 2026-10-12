#!/usr/bin/env python3
"""Send a written shot to an agent, as hal2-nvim's shooter sends one: a new worktree or an existing session.

  implement.py sessions --repo DIR                         the repo's live agent sessions (pane, slot, state, title)
  implement.py send --repo DIR --shotfile NAME --number N  start an agent in the next free worktree slot with the shot
                    [--pane %N|t:<id>]                       ... or type it into that existing session instead
                    [--global]                               a shot of the global shotfiles, carried out in DIR
                    [--model ID] [--effort LEVEL]            the session's model and effort (default opus medium)

The prompt is hal2-nvim's shot template (`shot-template-single.md`: the repo's `.hal/util/shooter/config/nvim/`,
then `~/.config/hal/util/shooter/nvim/`, then hal2-nvim's own `templates/`, else the copy below) filled with the
shot; it is also written as a bullet file (`~/.config/hal/util/shooter/nvim/bullets/<repo>/...`). A new session gets
it as its first prompt (create-worktree-session's create.py: the first slot without a session and without work), an existing one gets `@<bullet>` typed in
(`hal2-cli-agents send`). Then the shot is marked sent (`hal2-cli-shooter shots mark-sent --worktree <slot>`).

The session runs the shot's plan as its coordinator (the prompt says so, also when a loaded template does not) at an
explicit model and effort: a new one starts with them (create.py `--model`/`--effort`); an existing Claude session
whose model or effort, read from its transcript, differ or are unknown is restarted at them first, with the shot as
its first prompt (`hal2-cli-agents switch <pane> --model --effort --prompt --detach`), instead of typing.
Prints JSON; exit 2 when a hal2 CLI is missing.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HOME = Path.home()
BULLETS = HOME / ".config/hal/util/shooter/nvim/bullets"
TEMPLATE_NAME = "shot-template-single.md"
TEMPLATE_DIRS = (HOME / ".config/hal/util/shooter/nvim", HOME / "a/hal2/code/lua/apps/hal2-nvim/templates")
FALLBACK_TEMPLATE = """<!-- IMPORTANT: First, output the file content starting from "# shot" below (skip this instruction) in a code block so the user can see what was sent. Then proceed with the task. -->

# shot {{shot_title}} ({{file_title}})
{{shot_content}}

# context
1. This is shot {{shot_num}} of {{shot_origin}}.
2. Please read the file {{file_path}} to get more context on what was prompted before for this feature, if you need more context.
3. Before you start, run `/mfm` (merge-from-main), when you are in a worktree.
4. You should explicitly not implement the old shots.
5. You should explicitly not change the file {{file_path}}.
6. Your current task is the shot {{shot_num}}.
7. Make this shot a plan before you start: create it with the plan skill (`/plan new`), titled `{{plan_title}}`, so `plans/CURRENT_PLAN` names it (a shot that asks for research rather than implementation: `/plan new --research`, so the slug starts with `research-`); then run it as its coordinator. {{coordinator}}{{theme_context_line}}
"""
# The plan skill's coordinator sentence (skills plan 0016's D7), in every prompt that starts a plan-running session.
COORDINATOR = ("You are the plan's coordinator: you never do a step yourself; each step runs in one subagent at its "
               "row's Model and Effort, sized under 35% of its Window; you check its done-when, commit it and keep "
               "`run` current.")
DEFAULT_MODEL, DEFAULT_EFFORT = "opus", "medium"  # the user's defaults for new sessions (skills plan 0015's D15)
READY = {"idle", "done", "sleeping"}  # states an agent takes new input in without interrupting work
# A new session goes to the first slot without a session and without work (create-worktree-session's script).
CREATE = Path(__file__).resolve().parents[2] / "create-worktree-session" / "scripts" / "create.py"
# The plan skill's reader of a session's live model and effort (its transcript's main chain).
SESSION = Path(__file__).resolve().parents[2] / "plan" / "scripts"
PROJECTS = Path(os.environ.get("CLAUDE_PROJECTS_DIR", HOME / ".claude/projects"))


def die(message: str, code: int = 1) -> None:
    print(f"implement.py: {message}", file=sys.stderr)
    sys.exit(code)


def need(tool: str) -> str:
    path = shutil.which(tool)
    if not path:
        die(f"{tool} is missing: run scripts/install-prerequisites.sh (needs hal2, on the user's Mac)", 2)
    return path


def run(*args: str, input: str | None = None) -> str:
    need(args[0])
    r = subprocess.run(list(args), input=input, capture_output=True, text=True)
    if r.returncode != 0:
        die(f"{' '.join(args[:3])} failed: {(r.stderr or r.stdout).strip()}")
    return r.stdout


def shorten_home(path: Path) -> str:
    s = str(path)
    return "~" + s[len(str(HOME)):] if s == str(HOME) or s.startswith(str(HOME) + "/") else s


def repo_name(main: Path) -> str:
    r = subprocess.run(["git", "remote", "get-url", "origin"], cwd=main, capture_output=True, text=True)
    m = re.search(r"[:/]([^/:]+/[^/]+?)(?:\.git)?/?$", r.stdout.strip()) if r.returncode == 0 else None
    return m.group(1) if m else main.name


def main_checkout(repo: Path) -> Path:
    out = subprocess.run(["git", "worktree", "list", "--porcelain"], cwd=repo, capture_output=True, text=True).stdout
    first = out.splitlines()[0] if out else ""
    return Path(first.split(" ", 1)[1]) if first.startswith("worktree ") else repo


def template(main: Path) -> str:
    for folder in (main / ".hal/util/shooter/config/nvim", *TEMPLATE_DIRS):
        if (folder / TEMPLATE_NAME).is_file():
            return (folder / TEMPLATE_NAME).read_text()
    return FALLBACK_TEMPLATE


def render(tmpl: str, values: dict[str, str]) -> str:
    text = re.sub(r"\{\{(\w+)\}\}", lambda m: values.get(m.group(1), m.group(0)), tmpl).strip()
    return text if COORDINATOR in text else f"{text}\n\n{COORDINATOR}"


def prompt_values(shotfile: Path, number: str, title: str, body: str, repo: str,
                  is_global: bool = False) -> dict[str, str]:
    text = shotfile.read_text()
    heading = next((line[2:].strip() for line in text.splitlines() if line.startswith("# ")), shotfile.stem)
    return {
        "shot_num": number,
        "shot_title": f"{number} {title}".strip(),
        "shot_content": body,
        "file_title": heading,
        "file_path": shorten_home(shotfile),
        "shot_origin": (f'the global shotfile "{heading}", carried out in repo {repo}' if is_global
                        else f'the feature "{heading}" in repo {repo}'),
        "plan_title": f"{'global ' if is_global else ''}{shotfile.stem} {number} {title}".strip(),
        "theme_context_line": "",
        "coordinator": COORDINATOR,
    }


def where(main: Path, is_global: bool) -> list[str]:
    return ["--global"] if is_global else ["--repo", str(main)]


def find_shot(main: Path, shotfile: str, number: str, is_global: bool = False) -> dict:
    data = json.loads(run("hal2-cli-shooter", "shots", "list-open", shotfile, *where(main, is_global), "--json"))
    for shot in data.get("shots", []):
        if str(shot["number"]) == str(number):
            return shot
    die(f"shot {number} of {shotfile} is not an open shot (already sent?)")


def sessions(main: Path) -> list[dict]:
    agents = json.loads(run("hal2-cli-agents", "list", "--json"))
    agents = agents if isinstance(agents, list) else agents.get("agents", [])
    keep = ("pane_id", "slot", "kind", "state", "title", "plan", "checkout", "context_percent", "session_id")
    return [{k: a.get(k) for k in keep} for a in agents
            if a.get("project") and Path(a["project"]).resolve() == main.resolve()]


def session_values(session: str | None) -> dict[str, str]:
    """The model and effort a Claude session last ran at, from its transcript's main chain only ("" when unknown:
    no transcript, no turn yet, or the plan skill's session.py missing)."""
    found = {}
    path = next(iter(sorted(PROJECTS.glob(f"*/{session}.jsonl"))), None) if session else None
    if path and (SESSION / "session.py").is_file():
        sys.path.insert(0, str(SESSION))
        try:
            import session as live  # the plan skill's reader
            scanned = live.scan(path)
            model = live.later(scanned.get("requested_model"), scanned.get("model_switch"))
            effort = live.later(scanned.get("effort"), scanned.get("effort_switch"))
            found = {"model": model[0] if model else "", "effort": effort[0] if effort else ""}
        except (ImportError, OSError):
            found = {}
        finally:
            sys.path.remove(str(SESSION))
    return {"model": found.get("model", ""), "effort": found.get("effort", "")}


def family(model: str) -> str:
    """`opus`, `sonnet`, `haiku` or `fable` for any form of a model's name (`opus`, `claude-opus-5-5[1m]`), else it."""
    found = re.search(r"\b(?:claude-)?(opus|sonnet|haiku|fable)\b", model.lower())
    return found.group(1) if found else model.lower()


def needs_switch(have: dict[str, str], model: str, effort: str) -> bool:
    """Whether a session running at `have` must restart to run at `model` and `effort` (unknown counts as other)."""
    return family(have.get("model") or "?") != family(model) or (have.get("effort") or "?") != effort


def type_into(pane: str, kind: str, bullet: Path) -> None:
    """Type `@<bullet>` into an agent's prompt the way hal2-nvim does for its kind."""
    send = lambda *args: run("hal2-cli-agents", "send", pane, *args)
    send("C-u", "--key")
    time.sleep(0.1)
    send(str(bullet) if kind == "codex" else f"@{bullet}")
    time.sleep(0.1)
    if kind == "opencode":
        send("escape", "--key")
        time.sleep(0.1)
        send("enter", "--key")
    else:
        send("enter", "--key")
        time.sleep(0.1)
        send("enter", "--key")


def cmd_send(main: Path, shotfile_name: str, number: str, pane: str | None, is_global: bool = False,
             model: str = DEFAULT_MODEL, effort: str = DEFAULT_EFFORT) -> dict:
    shot = find_shot(main, shotfile_name, number, is_global)
    shotfile = Path(shot["path"])
    text = render(template(main), prompt_values(shotfile, str(shot["number"]), shot.get("title") or "",
                                                 shot.get("body") or "", repo_name(main), is_global))
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bullet = BULLETS / main.name / f"{shotfile.stem}_{stamp}_shot-{number}.md"
    bullet.parent.mkdir(parents=True, exist_ok=True)
    bullet.write_text(text + "\n")

    result = {"shotfile": shotfile_name, "number": number, "bullet": str(bullet), "model": model, "effort": effort}
    if pane:
        agent = next((a for a in sessions(main) if a["pane_id"] == pane), None)
        if agent is None:
            die(f"no live agent session {pane} in {main}")
        kind = agent.get("kind") or "claude"
        have = session_values(agent.get("session_id")) if kind == "claude" else {}
        switched = kind == "claude" and needs_switch(have, model, effort)
        if switched:  # restarted at the shot's model and effort, the shot its first prompt
            run("hal2-cli-agents", "switch", pane, "--model", model, "--effort", effort, "--prompt", text,
                "--detach", "--json")
        else:
            type_into(pane, kind, bullet)
        slot = agent.get("slot") or "main"
        result.update(mode="existing", pane=pane, slot=slot, state=agent.get("state"),
                      busy=agent.get("state") not in READY, switched=switched, was=have)
    else:
        spawned = json.loads(run(sys.executable, str(CREATE), "--repo", str(main), "--model", model,
                                 "--effort", effort, "--prompt", text, "--exact"))
        slot = spawned["slot"]
        result.update(mode="new", pane=spawned.get("pane"), slot=slot, worktree=spawned.get("worktree"),
                      remote_control=f"{main.name}-{slot}")
    mark = f"{main.name}/{slot}" if is_global else slot
    run("hal2-cli-shooter", "shots", "mark-sent", shotfile_name, number, "--worktree", mark,
        *where(main, is_global), "--json")
    return result


def arg(argv: list[str], flag: str) -> str | None:
    return argv[argv.index(flag) + 1] if flag in argv and argv.index(flag) + 1 < len(argv) else None


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    repo = Path(arg(argv, "--repo") or ".").expanduser().resolve()
    need("git")
    main_dir = main_checkout(repo)
    if argv[0] == "sessions":
        result = sessions(main_dir)
    elif argv[0] == "send":
        shotfile, number = arg(argv, "--shotfile"), arg(argv, "--number")
        if not shotfile or not number:
            die("send needs --shotfile and --number")
        effort = arg(argv, "--effort") or DEFAULT_EFFORT
        if effort not in ("low", "medium", "high", "xhigh", "max"):
            die(f"--effort is one of low, medium, high, xhigh, max, not {effort!r}")
        result = cmd_send(main_dir, shotfile.removesuffix(".md"), number, arg(argv, "--pane"), "--global" in argv,
                          arg(argv, "--model") or DEFAULT_MODEL, effort)
    else:
        die(f"unknown command {argv[0]!r} (sessions, send)")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
