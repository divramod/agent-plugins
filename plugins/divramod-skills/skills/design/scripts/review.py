"""The review state of a plan's designs (hal2 plan 0364, D7): the accept toggle and the comments, saved in the
committed `design/state.json` as `{"schema": 1, "designs": {"<feat>/<kind>/v<n>": {"accepted": bool, "comments":
[{"at", "by", "text", "anchor"?}]}}}`. `serve.py` writes it for the page, `design.py status|accepted` read it for
agents. A write is atomic (temp file + rename) and serialised by one lock; an id must name a version in the store.
Accepting a version un-accepts its siblings of the same feat and kind: the plan conforms to one design per kind.
"""

import datetime as dt
import json
import os
import re
import tempfile
import threading
from pathlib import Path

import store

SCHEMA = 1
ID = re.compile(r"([a-z0-9][a-z0-9-]*)/([a-z0-9][a-z0-9-]*)/v([1-9]\d*)")  # used with fullmatch: `$` takes a trailing newline
MAX_TEXT, MAX_ANCHOR, MAX_BY, MAX_COMMENTS = 4000, 200, 40, 500
LOCK = threading.Lock()


class ReviewError(store.StoreError):
    """A refused change; `code` is the HTTP status the server answers with."""

    def __init__(self, message: str, code: int = 400):
        super().__init__(message)
        self.code = code


def state_path(folder: Path) -> Path:
    return store.design_root(folder) / "state.json"


def load(folder: Path) -> dict:
    """The whole state file; a missing one is empty, a broken one is refused (a write must not lose it)."""
    path = state_path(folder)
    if not path.is_file():
        return {"schema": SCHEMA, "designs": {}}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as err:
        raise ReviewError(f"{path} is not valid JSON ({err}); fix or remove it", 500) from err
    if not isinstance(data, dict) or not isinstance(data.get("designs", {}), dict):
        raise ReviewError(f"{path} is not a state file: expected {{\"schema\": 1, \"designs\": {{...}}}}", 500)
    data.setdefault("schema", SCHEMA)
    data.setdefault("designs", {})
    return data


def write(folder: Path, data: dict) -> None:
    """Atomic: a temp file in the same folder, then a rename over state.json."""
    path = state_path(folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".state-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as out:
            out.write(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


def check_id(folder: Path, design: object) -> tuple[str, str, int]:
    """Split `<feat>/<kind>/v<n>`; it must be a version of the store."""
    match = ID.fullmatch(design) if isinstance(design, str) else None
    if not match:
        raise ReviewError("id must look like <feat>/<kind>/v<n>")
    feat, kind, n = match.group(1), match.group(2), int(match.group(3))
    if n not in store.versions(folder, feat, kind):
        raise ReviewError(f"no design {design}", 404)
    return feat, kind, n


def _entry(designs: dict, design: str) -> dict:
    entry = designs.get(design)
    if not isinstance(entry, dict):
        entry = designs[design] = {}
    entry["accepted"] = bool(entry.get("accepted"))
    if not isinstance(entry.get("comments"), list):
        entry["comments"] = []
    return entry


def _stamp(now: dt.datetime | None) -> str:
    return (now or dt.datetime.now(dt.timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _text(value: object, what: str, limit: int, required: bool = False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ReviewError(f"{what} must be a string")
    value = value.strip()
    if required and not value:
        raise ReviewError(f"{what} must not be empty")
    if len(value) > limit:
        raise ReviewError(f"{what} is longer than {limit} characters")
    return value


def set_accepted(folder: Path, design: object, accepted: object) -> dict:
    """Set the toggle of one version; accepting it clears the others of its feat and kind. Returns the designs."""
    if not isinstance(accepted, bool):
        raise ReviewError("accepted must be true or false")
    feat, kind, _ = check_id(folder, design)
    with LOCK:
        data = load(folder)
        designs = data["designs"]
        if accepted:
            for other in store.versions(folder, feat, kind):
                sibling = store.design_id(feat, kind, other)
                if sibling != design and sibling in designs:
                    _entry(designs, sibling)["accepted"] = False
        _entry(designs, design)["accepted"] = accepted
        write(folder, data)
        return designs


def add_comment(folder: Path, design: object, text: object, anchor: object = "", by: object = "user",
                now: dt.datetime | None = None) -> dict:
    """Append a comment (optionally anchored to a file or element name); returns the designs."""
    check_id(folder, design)
    comment = {"at": _stamp(now), "by": _text(by, "by", MAX_BY) or "user", "text": _text(text, "text", MAX_TEXT, True)}
    note = _text(anchor, "anchor", MAX_ANCHOR)
    if note:
        comment["anchor"] = note
    with LOCK:
        data = load(folder)
        entry = _entry(data["designs"], design)
        if len(entry["comments"]) >= MAX_COMMENTS:
            raise ReviewError(f"{design} already has {MAX_COMMENTS} comments")
        entry["comments"].append(comment)
        write(folder, data)
        return data["designs"]


def delete_comment(folder: Path, design: object, index: object, at: object = None) -> dict:
    """Remove the comment at `index`; when `at` is given it must match that comment's time (a stale page)."""
    check_id(folder, design)
    if not isinstance(index, int) or isinstance(index, bool):
        raise ReviewError("index must be a number")
    with LOCK:
        data = load(folder)
        entry = _entry(data["designs"], design)
        if not 0 <= index < len(entry["comments"]):
            raise ReviewError(f"{design} has no comment {index}", 404)
        if at is not None and entry["comments"][index].get("at") != at:
            raise ReviewError("the comment changed: reload the page", 409)
        del entry["comments"][index]
        write(folder, data)
        return data["designs"]


def _review(state: dict, design: str) -> tuple[bool, list]:
    raw = state.get(design) if isinstance(state.get(design), dict) else {}
    return bool(raw.get("accepted")), [c for c in raw.get("comments", []) if isinstance(c, dict)]


def status(folder: Path) -> dict:
    """Per feat and kind: the versions, the accepted one, the comments (what agents and the plan skill read)."""
    state = store.read_state(folder)
    feats = []
    for feat in store.feats(folder):
        kinds = []
        for kind in store.kinds(folder, feat):
            numbers = store.versions(folder, feat, kind)
            if not numbers:
                continue
            rows = []
            for n in numbers:
                design = store.design_id(feat, kind, n)
                accepted, comments = _review(state, design)
                meta = store.read_meta(store.version_dir(folder, feat, kind, n))
                rows.append({"id": design, "version": n, "title": meta.get("title", ""), "accepted": accepted,
                             "comments": comments})
            winner = next((r["id"] for r in rows if r["accepted"]), None)
            kinds.append({"id": kind, "accepted": winner, "latest": rows[-1]["id"], "versions": rows})
        if kinds:
            feats.append({"id": feat, "kinds": kinds})
    rows = [v for f in feats for k in f["kinds"] for v in k["versions"]]
    counts = {"designs": len(rows), "accepted": sum(v["accepted"] for v in rows),
              "comments": sum(len(v["comments"]) for v in rows)}
    return {"plan": store.plan_info(folder), "folder": str(folder), "state": str(state_path(folder)),
            "counts": counts, "feats": feats}


def accepted(folder: Path) -> dict:
    """Only the accepted versions with their absolute file paths; `superseded` when a newer version exists."""
    found = []
    for feat in status(folder)["feats"]:
        for kind in feat["kinds"]:
            if not kind["accepted"]:
                continue
            row = next(v for v in kind["versions"] if v["id"] == kind["accepted"])
            path = store.version_dir(folder, feat["id"], kind["id"], row["version"])
            found.append({"id": row["id"], "feat": feat["id"], "kind": kind["id"], "version": row["version"],
                          "title": row["title"], "path": str(path), "files": [str(f) for f in store.files(path)],
                          "superseded": kind["latest"] != row["id"], "comments": len(row["comments"])})
    return {"plan": store.plan_info(folder), "folder": str(folder), "accepted": found}
