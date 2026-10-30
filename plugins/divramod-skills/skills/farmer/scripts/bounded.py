#!/usr/bin/env python3
"""A time limit and one retry for every git and gh call a tick starts (hal2 plan 0480 step 06.01, tollman learning L63).

A farmer tick hung 9 minutes in merge-from-main on a stalled `git fetch`, so a train's run went unwatched. Every git,
gh and hal2-cli-git call of a tick (the farmer's round and the tollman's pass through it) runs through `run`, which
takes the place of `subprocess.run` (same result, same `subprocess.TimeoutExpired` and `OSError` for the callers'
handlers):

  limit      the caller's `timeout=`, else by the command: LOCAL_GIT for a local git, NETWORK_GIT for a git that talks
             to the remote (fetch, push, pull, ls-remote, clone), GH for `gh`, LONG for the calls meant to be long
             (`hal2-cli-git worktree merge-from-main` and `merge-to-main`), HAL for the other hal2-cli-git calls
  network    a git that talks to the remote, and hal2-cli-git (which starts one), also get GIT_HTTP_LOW_SPEED_LIMIT/TIME
             (a transfer under 1 KB/s for 60 s aborts), GIT_TERMINAL_PROMPT=0 and, only when the caller set neither
             GIT_SSH_COMMAND nor GIT_SSH, ssh keepalives (ServerAliveInterval/CountMax, ConnectTimeout): a dead link
             ends in about 45 s instead of hanging
  timeout    the child's whole process group gets SIGTERM (git removes its lock files), then SIGKILL, never a kill by
             name; the call is retried once, unless it changes the checkout (merge, commit, rebase ...: `retry=False`
             is also the caller's way to ask for none)
  transient  a non-zero exit whose output names a network fault (TRANSIENT) is retried once, a real error exit never
  happy path no sleep, no extra process: a retry starts only after a fault

stdin is /dev/null (no prompt can wait for a tty). The child runs in its own session, so a Ctrl-C reaches `run`, which
then takes the group down. Tests give a tiny `timeout=`.
"""

import os
import re
import signal
import subprocess

LOCAL_GIT = 60  # seconds: rev-parse, status, log, diff, ls-tree ... on a loaded Mac
NETWORK_GIT = 180  # fetch, push, pull, ls-remote, clone: the low-speed settings end a stall sooner
GH = 90
HAL = 300  # the other hal2-cli-git calls (queue reads, order, the tollman's land and train calls)
LONG = 900  # hal2-cli-git worktree merge-from-main / merge-to-main: meant to be long
OTHER = 300  # any other command routed here without a timeout
GRACE = 2  # seconds between SIGTERM and SIGKILL of the group

NETWORK_SUBS = {"fetch", "pull", "push", "ls-remote", "clone"}
LONG_VERBS = {"merge-from-main", "merge-to-main"}
CHANGES_CHECKOUT = {"merge", "commit", "rebase", "cherry-pick", "reset", "checkout", "switch", "am", "revert", "stash"}
GLOBAL_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--super-prefix"}
SSH = "ssh -o ServerAliveInterval=15 -o ServerAliveCountMax=3 -o ConnectTimeout=30"
LOW_SPEED = {"GIT_HTTP_LOW_SPEED_LIMIT": "1000", "GIT_HTTP_LOW_SPEED_TIME": "60", "GIT_TERMINAL_PROMPT": "0"}
TRANSIENT = re.compile(
    r"could not resolve host|temporary failure in name resolution|connection (?:timed out|reset|refused|closed)"
    r"|operation timed out|network is unreachable|early eof|rpc failed|the remote end hung up"
    r"|tls handshake|i/o timeout|error connecting to|kex_exchange_identification|http (?:429|50[0234])"
    r"|bad gateway|service unavailable|gateway timeout|failed to connect|connect to host", re.I)


def subcommand(argv) -> str:
    """git's subcommand: the first word that is no global option (or its value)."""
    skip = False
    for a in argv[1:]:
        if skip:
            skip = False
        elif a in GLOBAL_WITH_VALUE:
            skip = True
        elif not a.startswith("-"):
            return a
    return ""


def kind(argv) -> str:
    """"git", "gh", "hal" (hal2-cli-git) or "other"."""
    name = os.path.basename(str(argv[0])) if argv else ""
    return {"git": "git", "gh": "gh", "hal2-cli-git": "hal"}.get(name, "other")


def networked(argv) -> bool:
    """A git that talks to the remote, or hal2-cli-git, which starts one."""
    k = kind(argv)
    sub = subcommand(argv) if k == "git" else ""
    return k == "hal" or sub in NETWORK_SUBS or (sub == "remote" and "update" in argv)


def limit_for(argv, other: int | None = None, local: int | None = None) -> int:
    """The default limit of a command, in seconds (`other`: a command that is no git, gh or hal2-cli-git; `local`: a git
    that stays on this machine)."""
    k = kind(argv)
    if k == "hal":
        return LONG if LONG_VERBS & set(argv) else HAL
    if k == "gh":
        return GH
    if k == "git":
        return NETWORK_GIT if networked(argv) else (LOCAL_GIT if local is None else local)
    return OTHER if other is None else other


def environment(argv, env=None):
    """`env` (None: the process's) with the network limits of a git that talks to the remote; unchanged otherwise."""
    if not networked(argv):
        return env
    e = dict(os.environ if env is None else env)
    for k, v in LOW_SPEED.items():
        e.setdefault(k, v)
    if "GIT_SSH_COMMAND" not in e and "GIT_SSH" not in e:
        e["GIT_SSH_COMMAND"] = SSH
    return e


def transient(p, argv) -> bool:
    """A failed git, gh or hal2-cli-git call whose output names a network fault."""
    return p.returncode != 0 and kind(argv) != "other" and bool(TRANSIENT.search(f"{p.stderr}\n{p.stdout}"))


def retry_on_timeout(argv) -> bool:
    return not (kind(argv) == "git" and subcommand(argv) in CHANGES_CHECKOUT)


def stop(proc) -> None:
    """The child's process group: SIGTERM, a grace, SIGKILL for what is left; not by name (the child is its group's
    leader: start_new_session)."""
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (AttributeError, ProcessLookupError, PermissionError):
        proc.terminate()
    try:
        proc.wait(GRACE)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(proc.pid, signal.SIGKILL)  # stragglers of the group, also when the leader already went
    except (AttributeError, ProcessLookupError, PermissionError):
        proc.kill()
    proc.wait()


def once(argv, cwd, limit, env, text, data, coding=None):
    proc = subprocess.Popen(argv, cwd=cwd, env=env, text=text or coding is not None, start_new_session=True,
                            **(coding or {}), stdin=subprocess.PIPE if data is not None else subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        out, err = proc.communicate(data, timeout=limit)
    except subprocess.TimeoutExpired:
        stop(proc)
        try:
            proc.communicate(timeout=GRACE)  # drain: the group is gone, the pipes closed
        except subprocess.TimeoutExpired:
            pass
        raise subprocess.TimeoutExpired(argv, limit) from None
    except BaseException:
        stop(proc)
        raise
    return subprocess.CompletedProcess(argv, proc.returncode, out, err)


def run(argv, *, cwd=None, timeout=None, env=None, input=None, text=True, retry=True, other: int | None = None,
        local: int | None = None, coding=None) -> subprocess.CompletedProcess:
    """`subprocess.run(argv, capture_output=True)` with a limit and one retry (see the module); raises
    `subprocess.TimeoutExpired` when the retry also ran out, `OSError` when the program cannot start. `other` and
    `local` set the default limit of a non-git command and of a local git; `coding` is Popen's `encoding`/`errors`."""
    limit = limit_for(argv, other, local) if timeout is None else timeout
    env = environment(argv, env)
    tries = 2 if retry else 1
    for attempt in range(tries):
        last = attempt == tries - 1
        try:
            p = once(argv, cwd, limit, env, text, input, coding)
        except subprocess.TimeoutExpired:
            if last or not retry_on_timeout(argv):
                raise
            continue
        if last or not transient(p, argv):
            return p
    raise AssertionError("unreachable")  # pragma: no cover
