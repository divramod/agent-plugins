#!/usr/bin/env python3
"""Messenger of the important-interrupt skill: list the live local agent sessions and tell them something, as code.

Usage: messenger.py <command> [args]
  list [--json]                         the live sessions but the calling one: pid, name, pane, state, cwd
  send <name> <text> [--dry-run]
                                        deliver <text> to the session named by its name, pane, pid or worktree

Delivery speaks Claude Code's own cross-session inbox, what ListAgents/SendMessage use: every session registers
in <claude config>/sessions/<pid>.json (name, cwd, status, messagingSocketPath) and listens on a unix socket
(/tmp/cc-socks/<pid>.sock) for newline-delimited JSON: an optional auth line {"type":"auth","token":<peerToken of
sessions/<pid>.<hash>.key>}, then {"type":"user","message":{"role":"user","content":<wrapped text>},
"priority":"next","msgV":1,"msg_id":<uuid>}. The text is wrapped in <cross-session-message from-name=...
from-mode=...>; a session in bypass mode holds a peer message for its user unless from-mode says bypass too, so
from-mode is always the calling session's own mode, read from its command line, never a flag (no laundering).
A session without an inbox gets `hal2-cli-agents send <pane> <text> --submit`. No reply comes back on the
socket; whether a session paused is read from its pause record and its state (paused_since).

<claude config> is $CLAUDE_CONFIG_DIR or ~/.claude; pause records live in $PAUSE_ROOT or ~/skills/pause.
"""
import argparse
import json
import os
import re
import socket
import subprocess
import sys
import uuid
from pathlib import Path

TAG = "cross-session-message"
FROM_NAME = "important-interrupt"
MODES = ("bypass", "prompting")
IDLE_STATES = ("idle", "done", "sleeping")


def run_cmd(cmd: list, timeout: float = 20) -> tuple:
    """The one runner of external commands: (exit code, stdout, stderr); a missing tool is exit 127."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError as e:
        return 127, "", str(e)
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {timeout}s"


def connect_unix(path: str, timeout: float = 2.0):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(path)
    except OSError:
        s.close()
        raise
    return s


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def sessions_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "sessions"


def pause_root() -> Path:
    return Path(os.environ.get("PAUSE_ROOT") or Path.home() / "skills" / "pause")


def proc_table(run=run_cmd) -> dict:
    """{pid: (ppid, comm, args)} from ps."""
    code, out, _ = run(["ps", "-axo", "pid=,ppid=,comm=,args="])
    table = {}
    for line in out.splitlines() if code == 0 else []:
        parts = line.split(None, 3)
        if len(parts) >= 3 and parts[0].isdigit() and parts[1].isdigit():
            table[int(parts[0])] = (int(parts[1]), parts[2], parts[3] if len(parts) > 3 else parts[2])
    return table


def self_pid(run=run_cmd, environ=None, start=None) -> int | None:
    """The calling Claude session's pid: its inbox socket's name, else the first `claude` up the ppid chain."""
    environ = os.environ if environ is None else environ
    sock = environ.get("CLAUDE_CODE_MESSAGING_SOCKET", "")
    m = re.search(r"(\d+)(?:-[0-9a-f]+)?\.sock$", sock)
    if m:
        return int(m.group(1))
    table, pid, seen = proc_table(run), start or os.getpid(), set()
    while pid in table and pid not in seen and pid > 1:
        seen.add(pid)
        ppid, comm, _ = table[pid]
        if os.path.basename(comm) == "claude":
            return pid
        pid = ppid
    return None


def caller_mode(pid: int | None, run=run_cmd) -> str:
    """The permission mode a session runs in, read from its command line: bypass or prompting."""
    args = proc_table(run).get(pid, (0, "", ""))[2] if pid else ""
    if "--dangerously-skip-permissions" in args or re.search(r"--permission-mode[ =]bypassPermissions", args):
        return "bypass"
    return "prompting"


def registry(directory: Path, alive=pid_alive) -> dict:
    """{pid: entry} of the live sessions Claude Code registered."""
    found = {}
    for f in sorted(directory.glob("*.json")) if directory.is_dir() else []:
        try:
            entry = json.loads(f.read_text())
            pid = int(entry["pid"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if alive(pid):
            found[pid] = entry
    return found


def hal2_agents(run=run_cmd) -> list:
    code, out, _ = run(["hal2-cli-agents", "list", "--json"])
    if code != 0:
        return []
    try:
        data = json.loads(out)
    except ValueError:
        return []
    return [a for a in data if isinstance(a, dict)] if isinstance(data, list) else []


def merge(reg: dict, agents: list) -> list:
    """One row per session: the registry's facts, the hal2 list's pane and state joined by pid."""
    by_pid = {a.get("pid"): a for a in agents if a.get("pid") is not None}
    rows = []
    for pid, e in reg.items():
        a = by_pid.pop(pid, {})
        rows.append({"pid": pid, "name": e.get("name") or a.get("slot") or str(pid), "cwd": e.get("cwd"),
                     "checkout": a.get("checkout") or e.get("cwd"), "pane": a.get("pane_id"), "slot": a.get("slot"),
                     "kind": a.get("kind", "claude"), "state": a.get("state") or e.get("status"),
                     "status": e.get("status"), "since": a.get("since") or e.get("statusUpdatedAt"),
                     "socket": e.get("messagingSocketPath"), "session_id": e.get("sessionId")})
    for a in by_pid.values():
        if a.get("state") == "ended":
            continue
        rows.append({"pid": a.get("pid"), "name": a.get("slot") or a.get("pane_id"), "cwd": a.get("cwd"),
                     "checkout": a.get("checkout") or a.get("cwd"), "pane": a.get("pane_id"), "slot": a.get("slot"),
                     "kind": a.get("kind"), "state": a.get("state"), "status": None, "since": a.get("since"),
                     "socket": None, "session_id": a.get("session_id")})
    return sorted(rows, key=lambda r: str(r["name"]))


def sessions(exclude_pid=None, run=run_cmd, alive=pid_alive, directory=None) -> list:
    """The live local agent sessions, the calling one (exclude_pid, by default self_pid()) left out."""
    exclude = self_pid(run) if exclude_pid is None else exclude_pid
    rows = merge(registry(directory or sessions_dir(), alive), hal2_agents(run))
    return [r for r in rows if r["pid"] != exclude]


def wrap(text: str, from_name: str = FROM_NAME, from_mode: str | None = None) -> str:
    """The text as Claude Code's own SendMessage wraps it, so the receiver parses the sender's name and mode."""
    name = re.sub(r'["<>\x00-\x1f\x7f]', "", from_name).strip()[:64]
    attrs = [f'from-name="{name}"'] if name else []
    if from_mode in MODES:
        attrs.append(f'from-mode="{from_mode}"')
    body = re.sub(f"</(?={TAG})", "<\\\\", text, flags=re.IGNORECASE)
    head = (" " + " ".join(attrs)) if attrs else ""
    return f"<{TAG}{head}>\n{body}\n</{TAG}>"


def frame(text: str, from_name: str = FROM_NAME, from_mode: str | None = None, msg_id: str | None = None) -> dict:
    return {"msgV": 1, "msg_id": msg_id or str(uuid.uuid4()), "type": "user",
            "message": {"role": "user", "content": wrap(text, from_name, from_mode)}, "priority": "next"}


def peer_token(pid: int, directory: Path) -> str | None:
    """The inbox's auth token from sessions/<pid>.<hash>.key; never printed."""
    keys = sorted(directory.glob(f"{pid}.*.key")) if directory.is_dir() else []
    for key in keys:
        try:
            token = json.loads(key.read_text()).get("peerToken")
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(token, str) and token:
            return token
    return None


def send_socket(session: dict, payload: dict, connect=connect_unix, directory=None) -> None:
    """Write the auth line (when a key is published) and the frame to the session's inbox; raises OSError."""
    lines = []
    token = peer_token(session["pid"], directory or sessions_dir()) if session.get("pid") else None
    if token:
        lines.append(json.dumps({"type": "auth", "token": token}))
    lines.append(json.dumps(payload))
    conn = connect(session["socket"])
    try:
        conn.sendall(("\n".join(lines) + "\n").encode())
    finally:
        conn.close()


def send(session: dict, text: str, from_name: str = FROM_NAME, from_mode: str | None = None, dry_run=False,
         run=run_cmd, connect=connect_unix, directory=None) -> dict:
    """Deliver text to one session: its inbox socket, else hal2-cli-agents send to its pane."""
    out = {"name": session.get("name"), "pid": session.get("pid"), "via": None, "status": "failed", "reason": ""}
    reasons = []
    if session.get("socket"):
        out["via"] = "socket"
        if dry_run:
            return {**out, "status": "dry-run", "reason": f"would write to {session['socket']}"}
        try:
            send_socket(session, frame(text, from_name, from_mode), connect, directory)
            return {**out, "status": "delivered"}
        except OSError as e:
            reasons.append(f"socket: {e}")
    if session.get("pane"):
        out["via"] = "hal2-cli-agents"
        cmd = ["hal2-cli-agents", "send", session["pane"], text, "--submit"]
        if dry_run:
            return {**out, "status": "dry-run", "reason": "would run " + " ".join(cmd[:3]) + " <text> --submit"}
        code, _, err = run(cmd)
        if code == 0:
            return {**out, "status": "delivered", "reason": "; ".join(reasons)}
        reasons.append(f"hal2-cli-agents send exit {code}: {err.strip()[:200]}")
    out["reason"] = "; ".join(reasons) or "no inbox socket and no pane"
    return out


def pause_record(session: dict, root: Path | None = None) -> Path:
    where = session.get("checkout") or session.get("cwd") or ""
    return (root or pause_root()) / (re.sub(r"[^A-Za-z0-9]", "-", where) + ".md")


def paused_since(session: dict, t: float, root: Path | None = None, directory=None) -> tuple:
    """(True, why) when the session paused after t (epoch seconds): a pause record newer than t, or idle since t."""
    rec = pause_record(session, root)
    try:
        if rec.stat().st_mtime > t:
            return True, f"pause record {rec}"
    except OSError:
        pass
    state, since = session.get("state"), session.get("since")
    if session.get("pid"):
        try:
            entry = json.loads(((directory or sessions_dir()) / f"{session['pid']}.json").read_text())
            state, since = entry.get("status", state), entry.get("statusUpdatedAt", since)
        except (OSError, ValueError):
            pass
    if state in IDLE_STATES and since is not None and float(since) / 1000 >= t:
        return True, f"{state} since {float(since) / 1000:.0f}"
    return False, f"{state or 'unknown'}"


def find(rows: list, name: str) -> dict | None:
    for key in ("name", "pane", "pid", "slot"):
        for r in rows:
            if str(r.get(key)) == name:
                return r
    return None


def main(argv=None, run=run_cmd, connect=connect_unix, alive=pid_alive) -> int:
    ap = argparse.ArgumentParser(prog="messenger.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ls = sub.add_parser("list")
    ls.add_argument("--json", action="store_true")
    sd = sub.add_parser("send")
    sd.add_argument("name")
    sd.add_argument("text")
    sd.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    me = self_pid(run)
    rows = sessions(me if me is not None else -1, run=run, alive=alive)
    if a.cmd == "list":
        if a.json:
            print(json.dumps(rows, indent=1))
        for r in [] if a.json else rows:
            print(f"{r['pid']!s:>7} {str(r['name'])[:24]:24} {str(r['pane'] or '-'):16} {str(r['state']):8} {r['cwd']}")
        return 0
    target = find(rows, a.name)
    if target is None:
        print(f"messenger.py: no live session named {a.name}", file=sys.stderr)
        return 1
    res = send(target, a.text, from_mode=caller_mode(me, run), dry_run=a.dry_run, run=run,
               connect=connect)
    print(json.dumps(res))
    return 0 if res["status"] in ("delivered", "dry-run") else 1


if __name__ == "__main__":
    sys.exit(main())
