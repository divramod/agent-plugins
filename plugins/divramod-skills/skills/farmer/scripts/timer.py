"""The farmer's external timer (plan 0007 step 7): `farmer.py tick` at the loop's cron, no Claude cron job.

macOS: a launchd agent `local.farmer.<repo>` (~/Library/LaunchAgents), one StartCalendarInterval entry per minute of
the loop's cron. Linux: a systemd user timer + service of the same name. Installing writes the mode `timer`,
removing it `claude`, so a tick and the Claude loop never both run. `timer.json` in the state folder keeps the
installed cron; a tick reinstalls when roles/farmer/ROLE.md changed the loop's cron.

The tick's output goes to `tick.log` in the state folder (rotated at 1 MB to `tick.log.1`).

Another role's timer (hal2 plan 0294) is the same with its `roles.Wiring`: the label `local.<role>.<repo>`, its
own CLI's `tick` and its own state folder; without one every function is the farmer's.
"""

import json
import os
import platform
import subprocess
import sys
from pathlib import Path

import due
import roles

FARMER = roles.FARMER.cli
LOG_MAX = 1 << 20


def label(repo_name: str, wiring: roles.Wiring = roles.FARMER) -> str:
    return f"local.{wiring.role}.{repo_name}"


def minutes(cron: str) -> list[int]:
    """The minutes of an hourly loop cron (`7-59/15 * * * *`, `4 * * * *`, what due.loop_cron writes)."""
    fields = cron.split()
    if len(fields) != 5 or fields[1:] != ["*"] * 4:
        raise ValueError(f"not an hourly loop cron: {cron!r}")
    return sorted(due.parse_field(fields[0], 0, 59))


def argv(top: str, wiring: roles.Wiring = roles.FARMER) -> list[str]:
    return [sys.executable, str(wiring.cli), "tick", "--repo", top]


def env(wiring: roles.Wiring = roles.FARMER) -> dict[str, str]:
    """What the tick needs from this shell: PATH (hal2's CLIs), the wiring's variables (FARMER_DIR) when set."""
    return {k: os.environ[k] for k in ("PATH", *wiring.env) if k in os.environ}


def plist(name: str, top: str, state: Path, cron: str, wiring: roles.Wiring = roles.FARMER) -> str:
    def s(x):
        return f"<string>{x}</string>"
    times = "".join(f"<dict><key>Minute</key><integer>{m}</integer></dict>" for m in minutes(cron))
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            f'<plist version="1.0"><dict><key>Label</key>{s(label(name, wiring))}'
            f'<key>ProgramArguments</key><array>{"".join(s(a) for a in argv(top, wiring))}</array>'
            f'<key>WorkingDirectory</key>{s(top)}'
            f'<key>EnvironmentVariables</key><dict>{"".join(f"<key>{k}</key>{s(v)}" for k, v in env(wiring).items())}</dict>'
            f'<key>StartCalendarInterval</key><array>{times}</array>'
            f'<key>StandardOutPath</key>{s(state / "tick.log")}<key>StandardErrorPath</key>{s(state / "tick.log")}'
            '</dict></plist>\n')


def systemd(name: str, top: str, state: Path, cron: str, wiring: roles.Wiring = roles.FARMER) -> tuple[str, str]:
    mins, what = ",".join(f"{m:02d}" for m in minutes(cron)), f"{wiring.role} tick for {name}"
    # A role whose tick leaves a process behind (the tollman's detached landing, plan 0294 D24) must not lose
    # it to systemd's default, which kills the unit's whole control group when the tick ends.
    keep = "KillMode=process\n" if wiring.carries else ""
    service = (f"[Unit]\nDescription={what}\n\n[Service]\nType=oneshot\n{keep}WorkingDirectory={top}\n"
               + "".join(f"Environment={k}={v}\n" for k, v in env(wiring).items())
               + f"ExecStart={' '.join(argv(top, wiring))}\n"
               f"StandardOutput=append:{state / 'tick.log'}\nStandardError=append:{state / 'tick.log'}\n")
    timer = (f"[Unit]\nDescription={what}\n\n[Timer]\nOnCalendar=*-*-* *:{mins}:00\n"
             "Persistent=false\n\n[Install]\nWantedBy=timers.target\n")
    return service, timer


def files(name: str, wiring: roles.Wiring = roles.FARMER) -> list[Path]:
    unit = label(name, wiring)
    if platform.system() == "Darwin":
        return [Path.home() / "Library/LaunchAgents" / f"{unit}.plist"]
    d = Path.home() / ".config/systemd/user"
    return [d / f"{unit}.service", d / f"{unit}.timer"]


def run(cmd: list[str]) -> tuple[int, str]:
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr).strip()


def install(name: str, top: str, state: Path, cron: str, dry: bool = False,
            wiring: roles.Wiring = roles.FARMER) -> list[list[str]]:
    """Write the timer for `cron` and load it; returns the commands (only planned when `dry`)."""
    paths, unit = files(name, wiring), label(name, wiring)
    if platform.system() == "Darwin":
        domain = f"gui/{os.getuid()}"
        contents = [plist(name, top, state, cron, wiring)]
        cmds = [["launchctl", "bootout", f"{domain}/{unit}"], ["launchctl", "bootstrap", domain, str(paths[0])]]
    else:
        contents = list(systemd(name, top, state, cron, wiring))
        cmds = [["systemctl", "--user", "daemon-reload"], ["systemctl", "--user", "enable", "--now", f"{unit}.timer"]]
    if dry:
        return cmds
    for path, text in zip(paths, contents):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    for i, cmd in enumerate(cmds):
        code, out = run(cmd)
        if code and not (i == 0 and platform.system() == "Darwin"):  # bootout of a timer not loaded fails: fine
            raise RuntimeError(f"{' '.join(cmd)}: {out}")
    (state / "timer.json").write_text(json.dumps({"cron": cron, "label": unit}) + "\n")
    (state / "mode").write_text("timer\n")
    return cmds


def remove(name: str, state: Path, dry: bool = False, wiring: roles.Wiring = roles.FARMER) -> list[list[str]]:
    if platform.system() == "Darwin":
        cmds = [["launchctl", "bootout", f"gui/{os.getuid()}/{label(name, wiring)}"]]
    else:
        cmds = [["systemctl", "--user", "disable", "--now", f"{label(name, wiring)}.timer"]]
    if dry:
        return cmds
    for cmd in cmds:
        run(cmd)  # not loaded: nothing to stop
    for path in files(name, wiring):
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


def status(name: str, state: Path, wiring: roles.Wiring = roles.FARMER) -> dict:
    unit = label(name, wiring)
    if platform.system() == "Darwin":
        code, _ = run(["launchctl", "print", f"gui/{os.getuid()}/{unit}"])
    else:
        code, _ = run(["systemctl", "--user", "is-active", "--quiet", f"{unit}.timer"])
    return {"label": unit, "loaded": code == 0, **installed(state),
            "files": [str(p) for p in files(name, wiring) if p.exists()]}


def rotate(state: Path) -> None:
    log = state / "tick.log"
    if log.exists() and log.stat().st_size > LOG_MAX:
        log.replace(state / "tick.log.1")
