"""`farmer.py stop <fields> --soft|--hard --why <the user's words>`: a stop on the user's word, as code (hal2 plan 0695
step 58, D45, D46). Every stop on the user's word leaves a pause mark, so the tick's `paused-skip` keeps every duty away
from the field: this command writes the mark first (`hal2-cli-git worktree pause <NN> --by user --why ...`, the one
writer) and only then sends the stop, so a model that forgets a step cannot leave a stopped field unmarked.

soft: the field's session is typed the stop order (stop now, commit, write the handoff) with `hal2-cli-agents send
--force` (the field is paused by then, a paused field refuses a plain send). hard: `hal2-cli-agents stop --force`
(it marks the field too, an earlier pause stays). A field without a session is marked and reported, no failure.
Exit 0 every field marked and stopped, 1 a mark or a stop failed (the stop is not sent after a failed mark), 2 usage.
"""

import json
import subprocess
import sys

import reach
import tick

ORDER = ("hal2 soft stop, relayed by the farmer: the user decided: \"{why}\". Stop your work now, commit what is "
         "done and write the handoff (/handoff); hal2 then stops this session.")


def run_cmd(argv: list[str], cwd: str) -> tuple[int, str]:
    """One command: (exit code, stdout or the error text). The seam the tests replace."""
    try:
        done = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, str(e)
    return done.returncode, done.stdout if done.returncode == 0 else (done.stderr or done.stdout).strip()


def pane_of(field: str, main: str) -> str | None:
    """The pane of the agent working in `field` of the repository `main` (hal2-cli-agents list --json), else None."""
    code, out = run_cmd(["hal2-cli-agents", "list", "--json"], main)
    try:
        agents = json.loads(out).get("agents", []) if code == 0 else []
    except (ValueError, AttributeError):
        return None
    return reach.pane_in(agents, field, main)


def stop_field(field: str, main: str, hard: bool, why: str, dry: bool) -> tuple[bool, str]:
    """Mark `field` paused by the user, then stop it. (ok, the line to print)."""
    mark = ["hal2-cli-git", "worktree", "pause", field, "--by", "user", "--why", why]
    if dry:
        return True, f"{field}: would run {' '.join(mark)}, then a {'hard' if hard else 'soft'} stop"
    code, out = run_cmd(mark, main)
    if code != 0:
        return False, f"{field}: NOT stopped, the pause mark failed: {out}"
    pane = pane_of(field, main)
    if pane is None:
        return True, f"{field}: marked paused, no session runs"
    if hard:
        argv = ["hal2-cli-agents", "stop", pane, "--force", "--by", "user", "--why", why]
    else:
        argv = ["hal2-cli-agents", "send", pane, ORDER.format(why=why), "--submit", "--force"]
    code, out = run_cmd(argv, main)
    kind = "hard" if hard else "soft"
    if code != 0:
        return False, f"{field}: marked paused, the {kind} stop failed: {out}"
    return True, f"{field}: marked paused, {kind} stop sent to {pane}"


def add_parser(sub) -> None:
    sp = sub.add_parser("stop", help="a stop on the user's word: the pause mark first, then the stop")
    sp.add_argument("fields", nargs="+", help="field names: 07, 49")
    how = sp.add_mutually_exclusive_group(required=True)
    how.add_argument("--soft", action="store_true", help="type the stop order (commit, handoff) into the session")
    how.add_argument("--hard", action="store_true", help="stop the session by signal at once")
    sp.add_argument("--why", required=True, help="the user's words, quoted")
    sp.add_argument("--repo", default=".")
    sp.add_argument("--dry-run", action="store_true")


def run(args) -> int:
    main = tick.mtm_scan.main_checkout(args.repo)
    failed = 0
    for field in args.fields:
        ok, line = stop_field(field.zfill(2) if field.isdigit() else field, main, args.hard, args.why, args.dry_run)
        print(line)
        failed += not ok
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(2)
