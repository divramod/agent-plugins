#!/usr/bin/env python3
"""The live check of every agent kind's ack (hal2 plan 0731 D15): one throwaway session per kind in a free field 90-99,
one stamped instruction by `acks.py instruct <NN> <text> --send`, its `ack` awaited in the farmer's `log.jsonl`.

  acks_live.py [--kinds grok,codex,claude,opencode,antigravity] [--bin <dir>] [--out <live.md>] [--repo <dir>]

One session at a time (the Mac's load): start it (`hal2-cli-git worktree new <NN>`, then `worktree run <NN> --agent
<kind> --fresh --detach`),
wait for its row to rest (a known start dialog answered by its key), send, wait at most ACK_WAIT for the ack, read
whether the send was verified (the pane's sent log, `confirmed`), then stop and remove the field (`worktree remove
<NN> --remote --stop`, never forced; a refusal is reported). `--bin` (this branch's `code/rust/target/debug`) goes
first on PATH for the subprocesses only. The caller's own host record (`terminals/$HAL2_TERMINAL.json`) is hashed
before and after: a run must never rewrite it (D16). Exit 0 when every required kind (grok, codex, claude) acked.
Claude Code's own reply line is SendMessage to the farmer session, which code cannot see: its instruction asks for
the shell ack too, so the live farmer is not woken by a test.
"""

import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import acks_live_field as af  # noqa: E402
from acks_live_field import POLL, free_field, kill, remove, until  # noqa: E402,F401
import deliver  # noqa: E402
import mtm_scan  # noqa: E402
import reply_line  # noqa: E402

KINDS = ("grok", "codex", "claude", "opencode", "antigravity")
REQUIRED = ("grok", "codex", "claude")
ACK_WAIT = 300  # seconds per ack (the step's bound)
START_WAIT = 180
NEW_WAIT = 600  # `worktree new` sets the field up as merge-from-main does
SETTLE = 3  # probes a non-Claude `starting` row must hold without a dialog
TEXT = "plan 0731 live check: reply with the ack line, nothing else."
CLAUDE_EXTRA = (" This is a test: instead of SendMessage, run `python3 {acks} ack <the id in brackets above> done "
                "\"live check\" --role farmer --repo {main}` in your shell.")
# A start dialog seen in step 1 (fixtures/screens): its text on the screen and the key that passes it.
DIALOGS = (("Do you trust the contents of this project?", ("Enter",)),  # agy
           ("Update now (runs", ("2", "Enter")),  # codex's update offer: 2. Skip (the send is refused `dialog`)
           ("Switch to gpt-6-luna", ("Escape",)))  # codex's model switch offer: keep the model


@dataclass
class Live:
    """What the check reaches; every part injectable, so the test drives it on a fake CLI in a scratch root."""
    repo: str
    main: str
    log: Path
    sent: Path
    terminals: Path
    env: dict
    run: object = None  # (argv, timeout) -> (code, stdout, stderr)
    sleep: object = time.sleep
    clock: object = time.monotonic
    now: object = dt.datetime.now
    kill: object = kill  # (pid, sig) -> alive
    lines: list = field(default_factory=list)

    def call(self, *argv: str, timeout: int = 60) -> tuple[int, str, str]:
        if self.run:
            return self.run(list(argv), timeout)
        try:
            p = subprocess.run(list(argv), capture_output=True, text=True, timeout=timeout, cwd=self.repo, env=self.env)
            return p.returncode, p.stdout, p.stderr
        except (OSError, subprocess.TimeoutExpired) as e:
            return 127, "", str(e)


def agents(lv: Live) -> list[dict]:
    code, out, _ = lv.call("hal2-cli-agents", "list", "--json")
    try:
        data = json.loads(out) if code == 0 else {}
    except ValueError:
        return []
    rows = data.get("agents", []) if isinstance(data, dict) else data
    return rows if isinstance(rows, list) else []


def row_of(lv: Live, nn: str) -> dict | None:
    return next((a for a in agents(lv) if a.get("slot") == nn
                 and str(a.get("project") or "").rstrip("/") == lv.main.rstrip("/")), None)


def host_hash(lv: Live) -> str:
    tid = lv.env.get("HAL2_TERMINAL", "")
    path = lv.terminals / f"{tid}.json"
    return hashlib.sha256(path.read_bytes()).hexdigest() if tid and path.is_file() else "none"


def resting(lv: Live, nn: str, seen: list) -> dict | None:
    """The field's row once it rests; a known start dialog on its screen is answered by its key first. A non-Claude
    row may stay listed `starting` (grok, plan 0726): the send reads its box by kind (rest::kind_allows), so such a
    row counts once it was seen SETTLE probes in a row without a dialog."""
    row = row_of(lv, nn)
    if not row:
        return None
    code, screen, _ = lv.call("hal2-cli-agents", "capture", row["pane_id"])  # a dialog first: codex's is listed idle
    for text, keys in DIALOGS:
        if code == 0 and text in screen:
            for key in keys:
                lv.call("hal2-cli-agents", "send", row["pane_id"], key, "--key")
            seen.clear()
            return None
    if row.get("state") in deliver.READY:
        return row
    if row.get("kind") != reply_line.CLAUDE and row.get("state") == "starting":
        seen.append(1)
        return row if len(seen) >= SETTLE else None
    return None


def ack_of(lv: Live, ack_id: str) -> dict | None:
    return next((e for e in mtm_scan.entries(lv.log) if e.get("kind") == "ack" and e.get("id") == ack_id), None)


def verified(lv: Live, pane: str, typed: str) -> str:
    """The sent log's `confirmed` of the last entry carrying `typed` into `pane` (`%<n>` -> sent/<n>.jsonl, a host's
    `t:<id>` -> sent/<id>.jsonl)."""
    path = lv.sent / f"{pane.removeprefix('%').removeprefix('t:')}.jsonl"
    found = "?"
    for line in path.read_text().splitlines() if path.is_file() else []:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if typed and typed in str(e.get("text", "")) and "confirmed" in e:
            found = "y" if e["confirmed"] else "n"
    return found


def check(lv: Live, kind: str) -> dict:
    res = {"kind": kind, "field": "", "id": "", "ack": "n", "at": "", "verified": "", "note": "", "removed": ""}
    nn = free_field(lv)
    if not nn:
        return dict(res, note="no free field 90-99")
    res["field"] = nn
    code, out, err = lv.call("hal2-cli-git", "worktree", "new", nn, timeout=NEW_WAIT)
    if code:
        res["removed"] = remove(lv, nn) if nn in af.fields(lv) else "never made"
        return dict(res, note=f"worktree new failed ({code}): {(err or out).strip()[-200:]}")
    try:
        code, out, err = lv.call("hal2-cli-git", "worktree", "run", nn, "--agent", kind, "--fresh", "--detach",
                                 "--json", timeout=120)
        if code:
            return dict(res, note=f"start failed ({code}): {err.strip()[-200:]}")
        try:
            res["pane"] = json.loads(out).get("pane") or ""
        except (ValueError, AttributeError):
            pass
        seen: list = []
        row = until(lv, START_WAIT, lambda: resting(lv, nn, seen))
        if not row:
            last = row_of(lv, nn)
            return dict(res, note=f"never rested in {START_WAIT}s (state {last and last.get('state')})")
        text = TEXT + (CLAUDE_EXTRA.format(acks=reply_line.acks_path(), main=lv.main) if kind == "claude" else "")
        acks = str(HERE / "acks.py")
        code, out, err = lv.call(sys.executable, acks, "instruct", nn, text, "--send", "--json", "--repo", lv.repo,
                                 timeout=120)
        try:
            res["id"] = json.loads(out)["id"]
        except (ValueError, KeyError, TypeError):
            return dict(res, note=f"instruct failed ({code}): {err.strip()[-200:]}")
        if "not sent" in err:
            return dict(res, note=err.strip()[-200:])
        sent_at = lv.now()
        got = until(lv, ACK_WAIT, lambda: ack_of(lv, res["id"]))
        res["verified"] = verified(lv, row["pane_id"], f"[{res['id']}]")
        if got:
            secs = (lv.now() - sent_at).total_seconds()
            res.update(ack="y", at=f"{lv.now():%H:%M:%S} ({secs:.0f}s, {got.get('what')})")
        else:
            res["note"] = f"no ack in {ACK_WAIT}s"
        return res
    finally:
        res["removed"] = remove(lv, nn, res.get("pane", ""))


def report(rows: list[dict], before: str, after: str, started: str) -> str:
    out = ["# Plan 0731: live ack check", "",
           f"Run {started} by `acks_live.py` (step 8, D15): one throwaway session per kind, one instruction by "
           "`acks.py instruct <NN> ... --send`, its ack awaited in the farmer's `roles/farmer/log.jsonl` (at most "
           f"{ACK_WAIT}s).", "",
           "| Kind | Field | Sent id | Ack seen | Verified send | Field removed | Note |",
           "|---|---|---|---|---|---|---|"]
    for r in rows:
        ack = f"y {r['at']}" if r["ack"] == "y" else "n"
        out.append(f"| {r['kind']} | {r['field']} | {r['id']} | {ack} | {r['verified']} | {r['removed']} | "
                   f"{r['note'].replace('|', '/')} |")
    same = "unchanged" if before == after else "CHANGED"
    out += ["", f"Field host record (`terminals/$HAL2_TERMINAL.json`) sha256 before `{before[:16]}`, after "
            f"`{after[:16]}`: {same}.", ""]
    return "\n".join(out)


def with_bin(env, bin_dir: str) -> dict:
    """A copy of `env` with `bin_dir` first on PATH (the subprocesses' only; this process's PATH is untouched)."""
    env = dict(env)
    if bin_dir:
        env["PATH"] = f"{Path(bin_dir).resolve()}{os.pathsep}{env.get('PATH', '')}"
    return env


def live(args) -> Live:
    env = with_bin(os.environ, args.bin)
    import autopilot_duty  # hal2-core's state root (HAL2_STATE_DIR, XDG_STATE_HOME, the home)
    state = autopilot_duty.records_dir().parent
    main = mtm_scan.main_checkout(args.repo)
    return Live(repo=args.repo, main=main, log=mtm_scan.state_dir(main) / "log.jsonl", sent=state / "agents/sent",
                terminals=state / "terminals", env=env)


def run_all(lv: Live, kinds: list[str], out: Path) -> int:
    started = f"{lv.now():%Y-%m-%d %H:%M}"
    before = host_hash(lv)
    rows = []
    for kind in kinds:
        rows.append(check(lv, kind))
        r = rows[-1]
        print(f"acks_live: {kind} field {r['field']} id {r['id']} ack {r['ack']} {r['note']}", file=sys.stderr)
    after = host_hash(lv)
    out.write_text(report(rows, before, after, started))
    print(out.read_text())
    acked = {r["kind"] for r in rows if r["ack"] == "y"}
    return 0 if all(k in acked for k in REQUIRED if k in kinds) and before == after else 1


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--kinds", default=",".join(KINDS))
    p.add_argument("--bin", default="", help="put first on PATH for the subprocesses (the branch's target/debug)")
    p.add_argument("--repo", default=os.getcwd())
    p.add_argument("--out", default="")
    args = p.parse_args(argv)
    lv = live(args)
    out = Path(args.out or Path(args.repo) / "plans/0731-agent-acks/live.md")
    return run_all(lv, [k for k in args.kinds.split(",") if k], out)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
