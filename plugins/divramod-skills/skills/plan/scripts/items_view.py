"""items_view.py: a plan's gaps and manual items for `plan.py current` (hal2 plan 0595, step 3).

The stores are `plans/<plan>/gaps/<NN>-<slug>.md` and `plans/<plan>/manual/<NN>-<slug>.md`, written only by
`hal2-cli-plans gaps|manual` (hal2-plans' lib has the shape, hal2-records the kinds `Gap` and `Manual`). `fields`
reads them, never writes them:

    {"gaps":   {"open": 2, "total": 5, "items": [{"n": 3, "title": ..., "state": "open|routed|closed", "route": ""}]},
     "manual": {"open": 1, "total": 1, "items": [{"n": 1, "title": ..., "state": "open|done", "from": "Q2", "waits": ""}]}}

`items` lists every item of the plan by its number with its state; `open` counts the gaps not closed (open or
routed) and the manual items not done, `total` all of them. The
answer is `hal2-cli-plans <kind> list --state all --json` (`$HAL2_CLI_PLANS`, else on PATH; masterplan_view.binary)
when the plan folder has the folder or the checkout keeps its plans in the store home (the files are not in the
tree there); when the CLI is missing, an older one without the command, or its answer is no list, the folder's
front matter is read directly (advisory: "source": "files"). `problems` appear only when a file does not parse.
"""
import json
import subprocess
from pathlib import Path

import envelope
import masterplan_view
import planhome

KINDS = {"gaps": ("open", "routed"), "manual": ("open",)}
KEYS = {"gaps": ("route",), "manual": ("from", "waits")}
TIMEOUT = 15


def empty() -> dict:
    return {"open": 0, "total": 0, "items": []}


def item_of(kind: str, data: dict) -> dict:
    """The fields `current` shows of one item, from the CLI's JSON or a file's front matter."""
    out = {"n": data.get("n"), "title": data.get("title") or "", "state": data.get("state") or ""}
    out.update({key: data.get(key) or "" for key in KEYS[kind]})
    return out


def from_cli(root: Path, slug: str, kind: str) -> dict | None:
    """The CLI's list of the plan's items of `kind`, None when it cannot answer."""
    cli = masterplan_view.binary()
    if cli is None:
        return None
    command = [str(Path(cli).expanduser()), kind, "list", "--state", "all", "--json", "--repo", str(root),
               "--plan", slug]
    try:
        out = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=TIMEOUT)
        data = json.loads(out.stdout) if out.returncode == 0 else None
    except (OSError, UnicodeDecodeError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        return None
    return {"items": [item_of(kind, i) for i in data["items"] if isinstance(i, dict)],
            "problems": [f"{p.get('file')}: {p.get('message')}" for p in data.get("problems") or []
                         if isinstance(p, dict)], "source": "cli"}


def from_files(folder: Path, kind: str) -> dict:
    """The items by their front matter; a file that does not parse is a problem line."""
    items, problems = [], []
    for path in sorted((folder / kind).glob("[0-9][0-9]-*.md")):
        try:
            front, _ = envelope.split(path.read_text(encoding="utf-8"))
            data = envelope.parse(front) if front is not None else {}
        except (OSError, UnicodeDecodeError, envelope.FormatError) as error:
            problems.append(f"{path.name}: {error}")
            continue
        if data.get("n") is None or not data.get("state"):
            problems.append(f"{path.name}: no `n` or `state`")
            continue
        items.append(item_of(kind, data))
    return {"items": items, "problems": problems, "source": "files"}


def view(kind: str, found: dict) -> dict:
    items = sorted(found["items"], key=lambda i: i["n"] if isinstance(i["n"], int) else 0)
    out = {"open": sum(1 for i in items if i["state"] in KINDS[kind]), "total": len(items), "items": items,
           "source": found["source"]}
    if found["problems"]:
        out["problems"] = found["problems"]
    return out


def fields(root: Path, path: Path) -> dict:
    """`{"gaps": ..., "manual": ...}` of the plan whose plan.md is `path`; empty views for a flat plan file."""
    if path.name != "plan.md":
        return {kind: empty() for kind in KINDS}
    store = planhome.home(root) is not None
    out = {}
    for kind in KINDS:
        found = None
        if store or (path.parent / kind).is_dir():
            found = from_cli(root, path.parent.name, kind)
        if found is None:
            found = from_files(path.parent, kind)
        out[kind] = view(kind, found)
    return out
