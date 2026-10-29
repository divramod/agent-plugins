#!/usr/bin/env python3
"""`/gp`: group the uncommitted files into Conventional Commits and push (hal2 plan 0364, D12).

  gp.py scan [--json]                                   what is uncommitted: unit, scope, class, groups
  gp.py commit --group <unit> --subject "<type>(<NNNN>|<step>): <text>" [--body <text>] [--step n/m] [--trailer <line>]...
               [--also <ignore-candidate path>]...      stage and commit exactly that group's files
  gp.py ignore <pattern>...                             append to .gitignore
  gp.py push [--remote <name>]                          push the current branch, never force

`--repo <dir>` works on another checkout. Exit 0 ok, 1 refused (the reason on stderr), 2 usage. The subject is the model's
(judgment); this script only checks its form, never writes one. A secret is never committed, not even with --also.
"""
import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gp_neutral  # noqa: E402
import gp_scan  # noqa: E402

sys.path.insert(0, next(str(p / "scripts") for p in Path(__file__).resolve().parents if (p / ".claude-plugin").is_dir()))
import landing_workflow  # noqa: E402  (the skills unit's scripts/)

TYPES = ("feat", "fix", "docs", "test", "ci", "perf", "style", "refactor", "build", "chore")
HEAD = re.compile(r"^(" + "|".join(TYPES) + r")(\([A-Za-z0-9._/,@|-]+\))?!?: \S.*$")
STEP = re.compile(r"^\d+/\d+$")
WORKFLOWS = landing_workflow.NAMES  # plan 0423 D4: local, cloud, then the older names


class Refused(Exception):
    pass


def check_subject(subject: str) -> None:
    if "\n" in subject:
        raise Refused("the subject is one line")
    if not HEAD.match(subject):
        raise Refused(f"subject {subject!r} is no Conventional Commit: `<type>(<scope>): <text>`, type one of {', '.join(TYPES)}")
    if len(subject) > 72:
        raise Refused(f"subject is {len(subject)} characters, at most 72")
    if subject.endswith("."):
        raise Refused("subject must not end with a period")
    if re.search(r"\bwip\b", subject, re.IGNORECASE):
        raise Refused("subject must not say wip")


current_plan = gp_scan.current_plan


def worktree_name(root: str) -> str:
    """The folder name when the checkout is a linked worktree (a field), else an empty string."""
    git_dir = gp_scan.run(["git", "rev-parse", "--absolute-git-dir"], root).stdout.strip()
    common = gp_scan.run(["git", "rev-parse", "--git-common-dir"], root).stdout.strip()
    common = os.path.realpath(os.path.join(root, common))
    return Path(root).resolve().name if os.path.realpath(git_dir) != common else ""


def trailers(root: str, step: str, extra: list[str], origin: bool) -> list[str]:
    lines = []
    if origin:
        wt, plan = worktree_name(root), current_plan(root)
        if wt:
            lines.append(f"Worktree: {wt}")
        if plan:
            lines.append(f"Plan: {plan}")
            if step:
                lines.append(f"Step: {step}")
    return lines + [t for t in extra if t.strip()]


def message(subject: str, body: str, trailer_lines: list[str]) -> str:
    parts = [subject]
    if body.strip():
        parts.append(body.strip())
    if trailer_lines:
        parts.append("\n".join(trailer_lines))
    return "\n\n".join(parts) + "\n"


def cmd_scan(args) -> int:
    result = gp_scan.scan(args.repo)
    print(json.dumps(result, indent=2) if args.json else gp_scan.render(result))
    return 0


def cmd_commit(args) -> int:
    check_subject(args.subject)
    if args.step and not STEP.match(args.step):
        raise Refused(f"--step is <n>/<total>, not {args.step!r}")
    result = gp_scan.scan(args.repo)
    root = result["root"]
    if result["conflicts"]:
        raise Refused("unresolved merge conflicts: " + ", ".join(result["conflicts"]))
    group = next((g for g in result["groups"] if g["unit"] == args.group), None)
    if group is None:
        names = ", ".join(g["unit"] for g in result["groups"]) or "no group"
        raise Refused(f"no group {args.group!r} to commit; groups: {names}")
    paths = list(group["files"])
    for also in args.also:
        item = next((f for f in result["files"] if f["path"] == also), None)
        if item is None:
            raise Refused(f"--also {also}: not an uncommitted file")
        if item["class"] == "secret":
            raise Refused(f"--also {also}: a secret is never committed ({item['reason']})")
        if item["class"] != "ignore-candidate":
            raise Refused(f"--also {also}: only an ignore-candidate needs --also; it is in a group already")
        paths.append(also)
    subject, origin = args.subject, not args.no_origin
    if gp_neutral.neutral(root):  # neutral commits (plan 0409 D15): no plan scope, no origin trailers, the link in the store
        subject, origin = gp_neutral.head(subject), False
        gp_neutral.link(root, current_plan(root), args.step)
    lines = trailers(root, args.step, args.trailer, origin)
    text = message(subject, args.body, lines)
    # literal: a path like app/[id]/page.tsx is a file name here, never a glob
    gp_scan.run(["git", "--literal-pathspecs", "add", "-A", "--"] + paths, root)
    with tempfile.NamedTemporaryFile("w", suffix=".msg", delete=False) as handle:
        handle.write(text)
    try:
        done = gp_scan.run(["git", "--literal-pathspecs", "commit", "-F", handle.name, "--"] + paths, root, check=False)
    finally:
        os.unlink(handle.name)
    if done.returncode != 0:
        raise Refused("git commit failed (a hook?): " + (done.stderr or done.stdout).strip())
    short = gp_scan.run(["git", "rev-parse", "--short", "HEAD"], root).stdout.strip()
    out = {"commit": short, "subject": subject, "files": paths, "trailers": lines}
    print(json.dumps(out) if args.json else f"committed {short} {subject} ({len(paths)} files)")
    return 0


def cmd_ignore(args) -> int:
    root = gp_scan.toplevel(args.repo)
    target = Path(root, ".gitignore")
    text = target.read_text() if target.is_file() else ""
    have = {line.strip() for line in text.splitlines()}
    new = [p for p in dict.fromkeys(args.patterns) if p.strip() and p not in have]
    if new:
        target.write_text(text + ("" if not text or text.endswith("\n") else "\n") + "\n".join(new) + "\n")
    for pattern in args.patterns:
        tracked = gp_scan.run(["git", "ls-files", "--", pattern], root, check=False).stdout.split()
        if tracked:
            print(f"warning: {pattern} has tracked files ({tracked[0]}...): .gitignore does not untrack them", file=sys.stderr)
    print(f"added {len(new)} of {len(args.patterns)} to .gitignore" + (": " + ", ".join(new) if new else ""))
    return 0


def default_branch(root: str) -> str:
    ref = gp_scan.run(["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"], root, check=False).stdout.strip()
    return ref.split("/", 1)[1] if "/" in ref else ""


def cmd_push(args) -> int:
    root = gp_scan.toplevel(args.repo)
    branch = gp_scan.run(["git", "branch", "--show-current"], root).stdout.strip()
    if not branch:
        raise Refused("detached HEAD: no branch to push")
    on_default = branch in ("main", "master", default_branch(root))
    queue = [w for w in WORKFLOWS if Path(root, ".github", "workflows", w).is_file()]
    if on_default and queue:
        raise Refused(f"{branch} is the default branch and lands through the merge queue ({queue[0]}): use /mtm, never a push")
    upstream = gp_scan.run(["git", "rev-parse", "--abbrev-ref", "@{u}"], root, check=False)
    remote = args.remote
    if upstream.returncode == 0:
        tracked = gp_scan.run(["git", "config", f"branch.{branch}.remote"], root, check=False).stdout.strip()
        remote = tracked or args.remote
        merge = gp_scan.run(["git", "config", f"branch.{branch}.merge"], root, check=False).stdout.strip()
        target = merge.removeprefix("refs/heads/")
        if queue and target in ("main", "master", default_branch(root)):
            raise Refused(f"{branch} tracks the default branch {target}, which lands through the merge queue "
                          f"({queue[0]}): use /mtm, never a push")
    # explicit, whatever push.default or the upstream says: the branch goes to the branch of its own name
    cmd = ["git", "push"] + ([] if upstream.returncode == 0 else ["-u"]) + [remote, f"HEAD:refs/heads/{branch}"]
    done = gp_scan.run(cmd, root, check=False)
    sys.stdout.write(done.stdout)
    if done.returncode != 0:
        sys.stderr.write(done.stderr)
        raise Refused("push failed; never force: `git pull --rebase`, then /gp push again")
    left = len(gp_scan.scan(root)["files"])
    print(f"pushed {branch}" + (f" ({left} uncommitted files left)" if left else ""))
    return 0


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(prog="gp.py", description=__doc__.split("\n")[0])
    top.add_argument("--repo", default=".", help="the checkout (default: the current folder)")
    sub = top.add_subparsers(dest="cmd", required=True)
    scan = sub.add_parser("scan")
    scan.add_argument("--json", action="store_true")
    scan.set_defaults(fn=cmd_scan)
    commit = sub.add_parser("commit")
    commit.add_argument("--group", required=True)
    commit.add_argument("--subject", required=True)
    commit.add_argument("--body", default="")
    commit.add_argument("--step", default="", help="<n>/<total>, with the plan in CURRENT_PLAN")
    commit.add_argument("--trailer", action="append", default=[], help="a trailer line after the origin ones (attribution)")
    commit.add_argument("--also", action="append", default=[], help="an ignore-candidate the user chose to commit")
    commit.add_argument("--no-origin", action="store_true", help="no Worktree/Plan/Step trailers")
    commit.add_argument("--json", action="store_true")
    commit.set_defaults(fn=cmd_commit)
    ignore = sub.add_parser("ignore")
    ignore.add_argument("patterns", nargs="+")
    ignore.set_defaults(fn=cmd_ignore)
    push = sub.add_parser("push")
    push.add_argument("--remote", default="origin")
    push.set_defaults(fn=cmd_push)
    return top


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return args.fn(args)
    except Refused as error:
        print(f"gp: {error}", file=sys.stderr)
        return 1
    except Exception as error:  # a git failure: say it, exit 1
        detail = getattr(error, "stderr", "") or str(error)
        print(f"gp: {detail.strip()}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
