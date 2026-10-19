"""One rollout: a candidate SKILL.md run on one eval by a lean headless `claude -p` (plan 0390 step 1). Stdlib only.

    claude -p "<eval prompt>" --output-format stream-json --verbose --model <model> --setting-sources project
      --no-session-persistence --strict-mcp-config --max-turns <n> --max-budget-usd <usd>
      --tools Skill,Bash,Read,Glob,Grep --allowedTools Skill,Read,Glob,Grep --permission-prompts none
      --settings '{"sandbox": {"enabled": true, "failIfUnavailable": true, "allowUnsandboxedCommands": false, ...}}'

The cwd is a workspace folder rebuilt for every rollout: `.claude/skills/<name>/` holds a copy of the skill's folder
(without its `evals/`, so the model never sees a task or its checks) with the candidate as SKILL.md, the eval's files
at the root, the caller's `support` (e.g. the plugin's shared `scripts/`). Bash runs only in Claude Code's sandbox
(Seatbelt on macOS, bubblewrap on Linux): it writes only the workspace and the sandbox's temp folder (never the
skill's folder, the repository or ~/.claude), reaches no network host, cannot retry unsandboxed, and claude exits
when the sandbox cannot start (`failIfUnavailable`; native Windows has none). Bash is not in `--allowedTools`: the
sandbox auto-allows it, anything that would prompt is denied (`--permission-prompts none`). `--setting-sources project` keeps the
user's plugins, CLAUDE.md and hooks out (no plugin skill of the same name shadows the candidate);
`--disable-slash-commands` must not be used (it disables every skill). A fixed workspace path per run keeps the
prompt cache warm across rollouts. The env drops `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `CLAUDECODE` and every
`CLAUDE_CODE_*` but `CLAUDE_CODE_OAUTH_TOKEN`: the run pays with the login (research 0100 L10). The binary is
`$OPTIMIZE_SKILL_CLAUDE`, else `claude`. The skill's own folder is only ever read.

`run(...)` returns the rollout result, the interface of judge.py, gate.py, reflect.py and optimize.py:

    {"eval_id": str, "ok": bool,            # ok: a `result` event with subtype success, no timeout
     "final_text": str,                     # the run's last answer (the result event's `result`)
     "tool_calls": [{"id", "name", "input"}],  # every tool_use in order; input as the model gave it
     "skills": [str],                       # the `skill` of every Skill tool call (the candidate's name if invoked)
     "transcript": [{"type": "text", "text"} | {"type": "tool_use", "name", "input"}
                    | {"type": "tool_result", "is_error", "text"}],   # texts cut to 2000 chars
     "usage": {"input", "output", "cache_read", "cache_creation", "total"},   # exact tokens; total = the sum
     "cost_usd": float,                     # list-price equivalent (no bill on the subscription)
     "num_turns": int, "subtype": str or None,   # e.g. success, error_max_turns, error_max_budget_usd
     "error": str or None,                  # None when ok; "timeout", "no result event", "<subtype>; <errors>", ...
     "truncated": bool,                     # the child ran but gave no result event (a timeout, a crash): usage
                                            # under-counts, the loop charges at least its estimate (budget.floored)
     "duration_s": float}
"""

import json
import os
import re
import shutil
import tempfile
from pathlib import Path

import proc
import stream

DEFAULT_MODEL = "haiku"
DEFAULT_TURNS = 8
DEFAULT_TIMEOUT = 120
DEFAULT_BUDGET_USD = "0.50"
DEFAULT_TOOLS = ("Skill", "Bash", "Read", "Glob", "Grep")
ALLOWED = ("Skill", "Read", "Glob", "Grep")  # Bash only through the sandbox's auto-allow
SANDBOX = {"sandbox": {"enabled": True, "failIfUnavailable": True, "allowUnsandboxedCommands": False,
                       "autoAllowBashIfSandboxed": True, "network": {"strictAllowlist": True, "allowedDomains": []}}}
SCRUBBED = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDECODE")
KEPT = ("CLAUDE_CODE_OAUTH_TOKEN",)
MARKER = ".claude/.optimize-skill-workspace"
EVAL_FILES = "evals/files/"
SKIPPED = ("evals", "__pycache__", ".git", ".pytest_cache")
NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class WorkspaceError(Exception):
    """The workspace cannot be built (a bad name or path, a folder that is not ours)."""


def claude_binary(claude=None):
    return claude or os.environ.get("OPTIMIZE_SKILL_CLAUDE") or "claude"


def scrub_env(env):
    """The env without the API keys (they win over the login) and the session-coupling variables."""
    return {k: v for k, v in env.items()
            if k not in SCRUBBED and (not k.startswith("CLAUDE_CODE_") or k in KEPT)}


def command(claude, prompt, *, model=DEFAULT_MODEL, max_turns=DEFAULT_TURNS, budget_usd=DEFAULT_BUDGET_USD,
            tools=DEFAULT_TOOLS):
    allowed = [tool for tool in tools if tool in ALLOWED]
    return [claude, "-p", prompt, "--output-format", "stream-json", "--verbose", "--model", model,
            "--setting-sources", "project", "--no-session-persistence", "--strict-mcp-config",
            "--max-turns", str(max_turns), "--max-budget-usd", str(budget_usd), "--tools", ",".join(tools),
            "--allowedTools", ",".join(allowed), "--permission-prompts", "none",
            "--settings", json.dumps(SANDBOX, separators=(",", ":"))]


def default_workspace(skill_name):
    return Path(tempfile.gettempdir()) / "optimize-skill" / f"ws-{skill_name}-{os.getpid()}"


def _inside(root, rel):
    target = (root / rel).resolve()
    if rel in ("", ".") or Path(rel).is_absolute() or not target.is_relative_to(root.resolve()):
        raise WorkspaceError(f"path leaves the workspace: {rel!r}")
    return target


def _clear(workspace):
    """Empty the workspace; refuse a non-empty folder this module did not make."""
    if workspace.exists():
        if any(workspace.iterdir()) and not (workspace / MARKER).is_file():
            raise WorkspaceError(f"not an optimize-skill workspace: {workspace}")
        shutil.rmtree(workspace)
    (workspace / MARKER).parent.mkdir(parents=True)
    (workspace / MARKER).write_text("rebuilt by optimize-skill before every rollout\n", encoding="utf-8")


def _copy(src, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dest, dirs_exist_ok=True, ignore=shutil.ignore_patterns(*SKIPPED[1:]))
    else:
        shutil.copy2(src, dest)


def _eval_file(entry, skill_dir):
    """(source path or None, text or None, destination) of one entry of an eval's `files`."""
    if isinstance(entry, dict):
        dest = str(entry.get("dest") or entry.get("path") or "")
        if "text" in entry:
            return None, str(entry["text"]), dest
        return Path(str(entry.get("src") or entry.get("path"))), None, dest
    rel = str(entry)
    dest = rel[len(EVAL_FILES):] if rel.startswith(EVAL_FILES) else rel
    src = Path(rel) if Path(rel).is_absolute() or skill_dir is None else Path(skill_dir) / rel
    return src, None, Path(rel).name if Path(rel).is_absolute() else dest


def build_workspace(workspace, skill_name, skill_md, *, skill_dir=None, files=(), support=None):
    """Rebuild the workspace for one rollout and return the candidate's folder in it.

    `files`: an eval's entries: a path relative to the skill's folder (`evals/files/x` lands at `x`), an absolute
    path (lands at its name), or {"src" or "path", "dest"} / {"dest", "text"}. `support`: {destination in the
    workspace: source file or folder, or None for an empty folder}."""
    if not NAME.match(skill_name or ""):
        raise WorkspaceError(f"bad skill name: {skill_name!r}")
    workspace = Path(workspace)
    _clear(workspace)
    skill = workspace / ".claude" / "skills" / skill_name
    if skill_dir is not None:
        shutil.copytree(skill_dir, skill, ignore=shutil.ignore_patterns(*SKIPPED))
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(skill_md, encoding="utf-8")
    for dest, src in (support or {}).items():
        target = _inside(workspace, dest)
        if src is None:
            target.mkdir(parents=True, exist_ok=True)
        else:
            _copy(Path(src), target)
    for entry in files or ():
        src, text, dest = _eval_file(entry, skill_dir)
        target = _inside(workspace, dest)
        if text is not None:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        else:
            _copy(src, target)
    return skill


def _failed(eval_id, error, seconds):
    return dict(stream.parse(""), eval_id=eval_id, ok=False, error=error, truncated=False,
                duration_s=round(seconds, 3))


def run(skill_name, skill_md, eval_case, *, skill_dir=None, workspace=None, support=None, model=DEFAULT_MODEL,
        max_turns=DEFAULT_TURNS, timeout=DEFAULT_TIMEOUT, budget_usd=DEFAULT_BUDGET_USD, tools=DEFAULT_TOOLS,
        claude=None, env=None):
    """Run one eval ({id, prompt, files}) against a candidate SKILL.md; the rollout result (module doc)."""
    eval_id = str(eval_case.get("id"))
    workspace = Path(workspace) if workspace else default_workspace(skill_name)
    try:
        build_workspace(workspace, skill_name, skill_md, skill_dir=skill_dir, files=eval_case.get("files") or (),
                        support=support)
    except (OSError, WorkspaceError) as exc:
        return _failed(eval_id, f"workspace: {exc}", 0.0)
    argv = command(claude_binary(claude), str(eval_case.get("prompt") or ""), model=model, max_turns=max_turns,
                   budget_usd=budget_usd, tools=tools)
    child = proc.run(argv, cwd=str(workspace), env=scrub_env(dict(os.environ) if env is None else env),
                     stdin=b"", timeout=timeout)
    seconds = child["ms"] / 1000
    if child["error"]:
        return _failed(eval_id, f"start: {child['error']}", seconds)
    facts = stream.parse(child["out"].decode("utf-8", errors="replace"))
    if child["timed_out"]:
        facts["error"] = "timeout"
    elif facts["error"] == "no result event":
        facts["error"] = f"no result event (exit {child['code']}): {proc.tail(child['err'], 300).strip()}"
    truncated = bool(child["timed_out"] or (facts["error"] or "").startswith("no result event"))
    return dict(facts, eval_id=eval_id, ok=facts["error"] is None, truncated=truncated,
                duration_s=round(seconds, 3))

