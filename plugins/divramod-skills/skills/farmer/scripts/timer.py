"""The farmer's external timer (plan 0007 step 7): `farmer.py tick` at the loop's cron, no Claude cron job.

macOS: a launchd agent `local.farmer.<repo>` (~/Library/LaunchAgents), one StartCalendarInterval entry per minute of
the loop's cron. Linux: a systemd user timer + service of the same name. Installing writes the mode `timer`,
removing it `claude`, so a tick and the Claude loop never both run. `timer.json` in the state folder keeps the
installed cron; a tick reinstalls when roles/farmer/ROLE.md changed the loop's cron.

The tick's output goes to `tick.log` in the state folder (rotated at 1 MB to `tick.log.1`).
"""

import json
import os
import platform
import subprocess
import sys
from pathlib import Path

import due

FARMER = Path(__file__).resolve().parent / "farmer.py"
LOG_MAX = 1 << 20


def label(repo_name: str) -> str:
    return f"local.farmer.{repo_name}"


def minutes(cron: str) -> list[int]:
    """The minutes of an hourly loop cron (`7-59/15 * * * *`, `4 * * * *`, what due.loop_cron writes)."""
    fields = cron.split()
    if len(fields) != 5 or fields[1:] != ["*"] * 4:
        raise ValueError(f"not an hourly loop cron: {cron!r}")
    return sorted(due.parse_field(fields[0], 0, 59))


def argv(top: str) -> list[str]:
    return [sys.executable, str(FARMER), "tick", "--repo", top]


def env() -> dict[str, str]:
    """What the tick needs from this shell: PATH (hal2's CLIs), FARMER_DIR when set."""
    return {k: os.environ[k] for k in ("PATH", "FARMER_DIR") if k in os.environ}


def plist(name: str, top: str, state: Path, cron: str) -> str:
    def s(x):
        return f"<string>{x}</string>"
    times = "".join(f"<dict><key>Minute</key><integer>{m}</integer></dict>" for m in minutes(cron))
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            f'<plist version="1.0"><dict><key>Label</key>{s(label(name))}'
            f'<key>ProgramArguments</key><array>{"".join(s(a) for a in argv(top))}</array>'
            f'<key>WorkingDirectory</key>{s(top)}'
            f'<key>EnvironmentVariables</key><dict>{"".join(f"<key>{k}</key>{s(v)}" for k, v in env().items())}</dict>'
            f'<key>StartCalendarInterval</key><array>{times}</array>'
            f'<key>StandardOutPath</key>{s(state / "tick.log")}<key>StandardErrorPath</key>{s(state / "tick.log")}'
            '</dict></plist>\n')


def systemd(name: str, top: str, state: Path, cron: str) -> tuple[str, str]:
    mins = ",".join(f"{m:02d}" for m in minutes(cron))
    service = (f"[Unit]\nDescription=farmer tick for {name}\n\n[Service]\nType=oneshot\nWorkingDirectory={top}\n"
               + "".join(f"Environment={k}={v}\n" for k, v in env().items()) + f"ExecStart={' '.join(argv(top))}\n"
               f"StandardOutput=append:{state / 'tick.log'}\nStandardError=append:{state / 'tick.log'}\n")
    timer = (f"[Unit]\nDescription=farmer tick for {name}\n\n[Timer]\nOnCalendar=*-*-* *:{mins}:00\n"
             "Persistent=false\n\n[Install]\nWantedBy=timers.target\n")
    return service, timer


def files(name: str) -> list[Path]:
    if platform.system() == "Darwin":
        return [Path.home() / "Library/LaunchAgents" / f"{label(name)}.plist"]
    d = Path.home() / ".config/systemd/user"
    return [d / f"{label(name)}.service", d / f"{label(name)}.timer"]


def run(cmd: list[str]) -> tuple[int, str]:
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr).strip()


def install(name: str, top: str, state: Path, cron: str, dry: bool = False) -> list[list[str]]:
    """Write the timer for `cron` and load it; returns the commands (only planned when `dry`)."""
    paths = files(name)
    if platform.system() == "Darwin":
        domain = f"gui/{os.getuid()}"
        contents = [plist(name, top, state, cron)]
        cmds = [["launchctl", "bootout", f"{domain}/{label(name)}"], ["launchctl", "bootstrap", domain, str(paths[0])]]
    else:
        contents = list(systemd(name, top, state, cron))
        cmds = [["systemctl", "--user", "daemon-reload"],
                ["systemctl", "--user", "enable", "--now", f"{label(name)}.timer"]]
    if dry:
        return cmds
    for path, text in zip(paths, contents):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    for i, cmd in enumerate(cmds):
        code, out = run(cmd)
        if code and not (i == 0 and platform.system() == "Darwin"):  # bootout of a timer not loaded fails: fine
            raise RuntimeError(f"{' '.join(cmd)}: {out}")
    (state / "timer.json").write_text(json.dumps({"cron": cron, "label": label(name)}) + "\n")
    (state / "mode").write_text("timer\n")
    return cmds


def remove(name: str, state: Path, dry: bool = False) -> list[list[str]]:
    if platform.system() == "Darwin":
        cmds = [["launchctl", "bootout", f"gui/{os.getuid()}/{label(name)}"]]
    else:
        cmds = [["systemctl", "--user", "disable", "--now", f"{label(name)}.timer"]]
    if dry:
        return cmds
    for cmd in cmds:
        run(cmd)  # not loaded: nothing to stop
    for path in files(name):
        path.unlink(missing_ok=True)
    (state / "timer.json").unlink(missing_ok=True)
    (state / "mode").write_text("claude\n")
    return cmds


def installed(state: Path) -> dict:
    f = state / "timer.json"
    try:
        return json.loads(f.read_text()) if f.exists() else {}
    except json.JSONDecodeError:
        return {}


def status(name: str, state: Path) -> dict:
    if platform.system() == "Darwin":
        code, _ = run(["launchctl", "print", f"gui/{os.getuid()}/{label(name)}"])
    else:
        code, _ = run(["systemctl", "--user", "is-active", "--quiet", f"{label(name)}.timer"])
    return {"label": label(name), "loaded": code == 0, **installed(state),
            "files": [str(p) for p in files(name) if p.exists()]}


def rotate(state: Path) -> None:
    log = state / "tick.log"
    if log.exists() and log.stat().st_size > LOG_MAX:
        log.replace(state / "tick.log.1")
