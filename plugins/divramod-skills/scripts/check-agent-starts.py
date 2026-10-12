#!/usr/bin/env python3
"""No skill script starts an agent session itself (hal2 plan 0212, hal2's .adr/every-session-reachable-by-remote-control.md).

  check-agent-starts.py [--root <dir>]

An agent session (claude, codex, opencode) starts only through hal2: `hal2-cli-git worktree run`, or what calls it
(`hal2-cli-agents spawn`, create-worktree-session's create.py), so it is named <repo>-<slot> and reachable by Remote
Control; it stops through `hal2-cli-agents stop`, never a typed `/exit`. Exit 1 naming every line of a tracked script
(`*.py`, `*.sh`, `*.bash`; not tests) that starts an agent itself: a command line (`claude --...`, `codex` with `exec`), an
argv with the agent first and a flag or subcommand next, or that types `/exit`. The patterns are hal2's
`code/python/scripts/agent-starts`; ALLOWED names the exceptions with their reason.
"""
import re
import subprocess
import sys
from pathlib import Path

SOURCES = (".py", ".sh", ".bash")
AGENT = r"(?:claude|codex|opencode)"
LINE = re.compile(rf"(?<![\w./<>@-])(?<!--agent )(?<!--kind )({AGENT})\s+(?:-{{1,2}}[a-z]|exec\b|resume\b|run\b)")
ARGV = re.compile(rf"""(?:(?:[\[{{(])\s*["']({AGENT})["']\s*,\s*["'](?:-|(?:exec|resume|run)["'])|"""
                  rf"""\(\s*["']({AGENT})["']\s*,\s*\[)""")
EXIT = re.compile(r"""["']/exit["']""")
COMMENT = ("#",)
TESTS = re.compile(r"(^|/)(tests?|fixtures)/|(^|/)test_[^/]*\.py$")
ALLOWED = {
    "scripts/check-agent-starts.py": "this check's own patterns",
}


def tracked(root: Path) -> list[str]:
    out = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, text=True, check=True).stdout
    return [name for name in out.split("\0") if name.endswith(SOURCES)]


def starts(name: str, text: str) -> list[str]:
    found = []
    for number, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith(COMMENT):
            continue
        match = LINE.search(line) or ARGV.search(line)
        if match:
            agent = next(group for group in match.groups() if group)
            found.append(f"{name}:{number}: starts {agent} directly: `{line.strip()[:100]}` (only hal2's worktree run)")
        elif EXIT.search(line):
            found.append(f"{name}:{number}: types /exit: `{line.strip()[:100]}` (stop by hal2-cli-agents stop)")
    return found


def check(root: Path) -> list[str]:
    problems = []
    for name in tracked(root):
        if name in ALLOWED or TESTS.search(name):
            continue
        try:
            text = (root / name).read_text()
        except (UnicodeDecodeError, OSError):
            continue
        problems += starts(name, text)
    return problems


def main(argv: list[str]) -> int:
    root = Path(argv[argv.index("--root") + 1]) if "--root" in argv else Path(__file__).resolve().parents[1]
    problems = check(root)
    for problem in problems:
        print(f"check-agent-starts: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
