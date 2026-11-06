"""The notifier (plan 0311 design.md, Notifier; D13): one function `send` over the backends `desktop` and `telegram`.

    send(title, body, farm, watch, backends) -> [{"backend": name, "ok": bool, "error": str or None}]

It never raises and never retries: a failing backend is one `ok: false` result (the tick logs it), the find is
already recorded. `body` is cut to 200 characters. The desktop backend is terminal-notifier or `osascript` on
macOS, `notify-send` on Linux, a PowerShell WinRT toast on Windows. Telegram uses the Bot API over urllib; the token
and chat id are secret names in settings.json (`telegram: {token, chat, repo}`, read with `hal2-cli-secrets show`),
else `LOOKOUT_TELEGRAM_TOKEN`/`LOOKOUT_TELEGRAM_CHAT`. No secret is printed, logged or put in an error. Tests inject
`impls` ({backend: fn(title, body, farm, watch)}), `runner`, `urlopen` and `record`. Stdlib only.

After the sends, `send` records ONE notification (plan 0606 D9, D10): `hal2-cli-ring notifications add --from
lookout --role lookout --farm <farm> --case lookout --channel desktop:<sent|failed> [--channel telegram:...] --
<title>: <body>`, so the hal9k Ring view lists it. A missing `hal2-cli-ring` or a failed `add` is never raised and
never an `ok: false` result.
"""

import json
import os
import shutil
import subprocess
import sys
import urllib.request

import paths

BODY_LIMIT = 200
DEFAULT_BACKENDS = ["desktop"]
TIMEOUT = 15


def one_line(text, limit):
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def backends_for(record, settings):
    """The backends to run: the record's `notify` (`none`, `default`, or a comma list), else settings.json's."""
    value = str((record or {}).get("notify") or "default").strip()
    if value == "none":
        return []
    if value != "default":
        return [name.strip() for name in value.split(",") if name.strip()]
    chosen = (settings or {}).get("notify", DEFAULT_BACKENDS)
    if isinstance(chosen, str):
        chosen = [chosen]
    return [str(name) for name in chosen] if isinstance(chosen, list) else list(DEFAULT_BACKENDS)


def _run(argv):
    """Run a notifier tool to its end: returns (code, error text). The default `runner`."""
    try:
        done = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, timeout=TIMEOUT, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"{type(exc).__name__}: {exc}"
    return done.returncode, done.stderr.decode("utf-8", errors="replace")[-300:]


def _applescript(text):
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _toast_script(title, body):
    def quoted(text):
        text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return "'" + text.replace("'", "''") + "'"
    return ("$null = [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = "
            "WindowsRuntime]; $x = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
            "[Windows.UI.Notifications.ToastTemplateType]::ToastText02); $t = $x.GetElementsByTagName('text'); "
            f"$t.Item(0).AppendChild($x.CreateTextNode({quoted(title)})) | Out-Null; "
            f"$t.Item(1).AppendChild($x.CreateTextNode({quoted(body)})) | Out-Null; "
            "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('lookout').Show("
            "[Windows.UI.Notifications.ToastNotification]::new($x))")


def desktop_command(title, body, system, which=shutil.which):
    """The argv of the desktop notification on `system` (`darwin`, `linux`, `win32`), or None when no tool exists."""
    if system == "darwin":
        if which("terminal-notifier"):
            return ["terminal-notifier", "-title", title, "-message", body, "-group", "lookout"]
        if which("osascript"):
            return ["osascript", "-e", f'display notification "{_applescript(body)}" with title "{_applescript(title)}"']
        return None
    if system == "win32":
        shell = which("powershell") or which("pwsh")
        return [shell, "-NoProfile", "-NonInteractive", "-Command", _toast_script(title, body)] if shell else None
    return ["notify-send", "--app-name=lookout", title, body] if which("notify-send") else None


def _desktop(title, body, farm, watch, *, runner=_run, system=None, which=shutil.which):
    argv = desktop_command(title, body, system or sys.platform, which)
    if argv is None:
        raise RuntimeError("no desktop notification tool found")
    code, err = runner(argv)
    if code != 0:
        raise RuntimeError(f"{argv[0]} exit {code}: {err}".strip())


def read_secret(name, repo=None, runner=None):
    """A secret by name through `hal2-cli-secrets show` (stdout is the value); never printed. Raises RuntimeError."""
    argv = ["hal2-cli-secrets", "show", name] + (["--repo", str(repo)] if repo else [])
    try:
        done = (runner or subprocess.run)(argv, stdin=subprocess.DEVNULL, capture_output=True, timeout=TIMEOUT,
                                          check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"hal2-cli-secrets: {type(exc).__name__}") from None
    if done.returncode != 0:
        raise RuntimeError(f"hal2-cli-secrets show {name}: exit {done.returncode}")
    return done.stdout.decode("utf-8", errors="replace").strip()


def telegram_credentials(settings, env=None, secrets=read_secret):
    """(token, chat) from settings.json's secret names, else the environment; ("", "") when not configured."""
    env = os.environ if env is None else env
    conf = (settings or {}).get("telegram")
    conf = conf if isinstance(conf, dict) else {}
    token, chat = conf.get("token"), conf.get("chat")
    if token and chat:
        return secrets(token, conf.get("repo")), secrets(chat, conf.get("repo"))
    return env.get("LOOKOUT_TELEGRAM_TOKEN", ""), env.get("LOOKOUT_TELEGRAM_CHAT", "")


def _telegram(title, body, farm, watch, *, settings=None, env=None, secrets=read_secret, urlopen=None):
    token, chat = telegram_credentials(settings, env, secrets)
    if not token or not chat:
        raise RuntimeError("telegram is not configured")
    text = title if body in ("", title) else f"{title}\n{body}"
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage", method="POST",
        data=json.dumps({"chat_id": chat, "text": text, "disable_web_page_preview": True}).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    try:
        with (urlopen or urllib.request.urlopen)(request, timeout=TIMEOUT) as reply:
            status = getattr(reply, "status", 200)
    except Exception as exc:  # the token sits in the URL: never let it reach an error text
        raise RuntimeError(str(exc).replace(token, "<token>")) from None
    if status != 200:
        raise RuntimeError(f"telegram answered {status}")


RING = "hal2-cli-ring"
KNOWN = ("desktop", "telegram")  # the backends the notifications store has a channel for


def record_argv(binary, farm, results, text):
    """`notifications add` for one notify call: a channel per known backend that ran (`sent` or `failed`)."""
    argv = [binary, "notifications", "add", "--from", "lookout", "--role", "lookout", "--farm",
            str(farm or "unknown"), "--case", "lookout"]
    for item in results:
        if item["backend"] in KNOWN:
            argv += ["--channel", f"{item['backend']}:{'sent' if item['ok'] else 'failed'}"]
    return argv + ["--", text]


def record_notification(farm, text, results, *, which=shutil.which, runner=_run):
    """Record the call's one notification; (recorded, error text). Never raises; no known backend, nothing to record."""
    try:
        if not any(item["backend"] in KNOWN for item in results):
            return False, None
        binary = which(RING)
        if not binary:
            return False, f"{RING} is not installed"
        code, err = runner(record_argv(binary, farm, results, text))
        return (True, None) if code == 0 else (False, one_line(f"{RING} notifications add exit {code}: {err}", 300))
    except Exception as exc:
        return False, one_line(f"{type(exc).__name__}: {exc}", 300)


def send(title, body, farm, watch, backends, *, settings=None, impls=None, runner=_run, urlopen=None, record=None):
    """Notify through each named backend; one result per backend, never raising. Then one `notifications add`."""
    title = one_line(title, 100) or "lookout"
    body = one_line(body, BODY_LIMIT)
    settings = paths.load_settings() if settings is None else settings
    table = {"desktop": lambda t, b, f, w: _desktop(t, b, f, w, runner=runner),
             "telegram": lambda t, b, f, w: _telegram(t, b, f, w, settings=settings, urlopen=urlopen)}
    table.update(impls or {})
    results = []
    for name in backends or []:
        try:
            if name not in table:
                raise RuntimeError(f"unknown backend {name}")
            table[name](title, body, farm, watch)
            results.append({"backend": name, "ok": True, "error": None})
        except Exception as exc:
            results.append({"backend": name, "ok": False, "error": one_line(f"{exc}", 300)})
    text = title if body in ("", title) else f"{title}: {body}"
    (record or record_notification)(farm, text, results)
    return results
