"""A desktop notice for a role's round (hal2 plan 0530 D5): the one channel a tick has when it cannot wake its own
session, e.g. "farmer tick failing: TypeError: ...". Modelled on the lookout skill's notify.py desktop backend
(terminal-notifier, else osascript on macOS; notify-send on Linux; a PowerShell WinRT toast on Windows), without
importing it (its `paths` would clash with the frame's modules on sys.path).

    send(title, body, runner=None, system=None, which=shutil.which) -> {"ok": bool, "error": str | None}

Never raises, never retries; `body` is cut to 200 characters, `title` to 100. Tests inject `runner(argv) -> (code,
error text)` so no real notice is shown. Stdlib only.
"""

import shutil
import subprocess
import sys

BODY_LIMIT = 200
TITLE_LIMIT = 100
TIMEOUT = 15
GROUP = "hal2-roles"


def one_line(text, limit: int) -> str:
    """`text` on one line, cut to `limit` characters with an ellipsis."""
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def run(argv: list[str]) -> tuple[int | None, str]:
    """Run a notifier tool to its end, at most TIMEOUT seconds: (exit code, error text). The default runner."""
    try:
        done = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, timeout=TIMEOUT, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"{type(exc).__name__}: {exc}"
    return done.returncode, done.stderr.decode("utf-8", errors="replace")[-300:]


def _applescript(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _toast_script(title: str, body: str) -> str:
    def quoted(text: str) -> str:
        text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return "'" + text.replace("'", "''") + "'"
    return ("$null = [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = "
            "WindowsRuntime]; $x = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
            "[Windows.UI.Notifications.ToastTemplateType]::ToastText02); $t = $x.GetElementsByTagName('text'); "
            f"$t.Item(0).AppendChild($x.CreateTextNode({quoted(title)})) | Out-Null; "
            f"$t.Item(1).AppendChild($x.CreateTextNode({quoted(body)})) | Out-Null; "
            f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{GROUP}').Show("
            "[Windows.UI.Notifications.ToastNotification]::new($x))")


def command(title: str, body: str, system: str, which=shutil.which) -> list[str] | None:
    """The argv of the desktop notice on `system` (`darwin`, `linux`, `win32`), or None when no tool exists."""
    if system == "darwin":
        if which("terminal-notifier"):
            return ["terminal-notifier", "-title", title, "-message", body, "-group", GROUP]
        if which("osascript"):
            script = f'display notification "{_applescript(body)}" with title "{_applescript(title)}"'
            return ["osascript", "-e", script]
        return None
    if system == "win32":
        shell = which("powershell") or which("pwsh")
        return [shell, "-NoProfile", "-NonInteractive", "-Command", _toast_script(title, body)] if shell else None
    return ["notify-send", f"--app-name={GROUP}", title, body] if which("notify-send") else None


def send(title: str, body: str, runner=None, system: str | None = None, which=shutil.which) -> dict:
    """Show one desktop notice; {"ok": True, "error": None} or {"ok": False, "error": <one line>}, never raising."""
    try:
        argv = command(one_line(title, TITLE_LIMIT) or "hal2", one_line(body, BODY_LIMIT), system or sys.platform,
                       which)
        if argv is None:
            return {"ok": False, "error": "no desktop notification tool found"}
        code, err = (runner or run)(argv)
        if code != 0:
            return {"ok": False, "error": one_line(f"{argv[0]} exit {code}: {err}", 300)}
        return {"ok": True, "error": None}
    except Exception as exc:  # a notice must never take the round down with it
        return {"ok": False, "error": one_line(f"{type(exc).__name__}: {exc}", 300)}
