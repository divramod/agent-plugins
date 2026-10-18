"""Where lookout keeps its files (plan 0311 design.md, Store), and its run log.

The config root holds the records, `changes.jsonl` and `settings.json`; the state root holds `log.jsonl`, the tick's
files and each watch's state folder `state/<farm>/<id>/` (its `state.json` and the check's own `check/`).
`XDG_CONFIG_HOME`/`XDG_STATE_HOME` move the roots on every system; `LOOKOUT_DIR` and `LOOKOUT_STATE_DIR` override
them (tests). Stdlib only.
"""

import datetime as dt
import json
import os
from pathlib import Path


def _xdg(name, default):
    value = os.environ.get(name)
    return Path(value) if value else Path.home() / default


def config_root():
    """`~/.config/hal2/lookout`: the records, the change log, settings.json."""
    if os.environ.get("LOOKOUT_DIR"):
        return Path(os.environ["LOOKOUT_DIR"])
    return _xdg("XDG_CONFIG_HOME", ".config") / "hal2" / "lookout"


def state_root():
    """`~/.local/state/hal2/lookout`: log.jsonl, the tick's files, the watches' state folders."""
    if os.environ.get("LOOKOUT_STATE_DIR"):
        return Path(os.environ["LOOKOUT_STATE_DIR"])
    return _xdg("XDG_STATE_HOME", ".local/state") / "hal2" / "lookout"


def watch_dir(farm, watch):
    """The state folder of one watch: `state/<farm>/<id>/`."""
    return state_root() / "state" / farm / watch


def log_path():
    return state_root() / "log.jsonl"


def now():
    """The local time, aware, to the second (the format of every `at`)."""
    return dt.datetime.now().astimezone().replace(microsecond=0)


def append_log(line, path=None):
    """Append one JSON line to log.jsonl (run results: checks and judge runs, D10)."""
    path = Path(path) if path else log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n")


def read_log(path=None):
    """Every parseable line of log.jsonl (a broken line is skipped)."""
    path = Path(path) if path else log_path()
    if not path.exists():
        return []
    lines = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(raw)
        except ValueError:
            continue
        if isinstance(item, dict):
            lines.append(item)
    return lines


def load_settings(path=None):
    """settings.json (written by the user, names only, no secret); {} when missing or broken."""
    path = Path(path) if path else config_root() / "settings.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}
