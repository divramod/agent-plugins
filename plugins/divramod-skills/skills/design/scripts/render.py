"""Render a plan's designs into its one `design.html` (hal2 plan 0364, D3-D5): the page's data (plan, feats, kinds,
versions and their files) goes into the page as JSON; `review.js` and `page.js` (inlined) draw the fixed layout
from it in the browser.
DBML files are drawn here as ERD cards (erd.py); every other file goes in as text, an image as a data URL.

The output is deterministic (no timestamp of its own), so a re-render without a change leaves git clean.
"""

import base64
import json
import os
import tempfile
from html import escape
from pathlib import Path

import erd
import review
import store

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "page_template.html"
IMAGES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
          ".webp": "image/webp"}
SERVE = "design.py serve"


def _file_entry(path: Path) -> dict:
    entry = {"name": path.name, "ext": path.suffix.lower(), "role": path.stem if path.stem in ("current", "new") else ""}
    if entry["ext"] in IMAGES:
        data = base64.b64encode(path.read_bytes()).decode()
        entry["data"] = f"data:{IMAGES[entry['ext']]};base64,{data}"
    else:
        entry["text"] = path.read_text(errors="replace")
    return entry


def _with_erd(entries: list[dict]) -> list[dict]:
    """DBML files get their cards; `new.dbml` beside a `current.dbml` gets the diff."""
    dbmls = {e["role"]: e for e in entries if e["ext"] == ".dbml"}
    for entry in entries:
        if entry["ext"] != ".dbml":
            continue
        if entry["role"] == "new" and "current" in dbmls:
            entry["html"] = erd.diff_html(dbmls["current"]["text"], entry["text"])
        else:
            entry["html"] = erd.plain_html(entry["text"])
    return entries


def _review(state: dict, design: str) -> dict:
    """The review state of one version (step 2 writes it): accepted and the comments, read-only here."""
    raw = state.get(design) if isinstance(state.get(design), dict) else {}
    comments = [c for c in raw.get("comments", []) if isinstance(c, dict)]
    return {"accepted": bool(raw.get("accepted")), "comments": comments}


def _version(folder: Path, feat: str, kind: str, n: int, state: dict) -> dict:
    path = store.version_dir(folder, feat, kind, n)
    meta = store.read_meta(path)
    design = store.design_id(feat, kind, n)
    return {"id": design, "v": n, "title": meta.get("title") or f"{feat} {kind}", "created": meta.get("created", ""),
            "from": meta.get("from") or "", "base": meta.get("base") or "",
            "files": _with_erd([_file_entry(f) for f in store.files(path)]), "review": _review(state, design)}


def model(folder: Path) -> dict:
    """The page's data: the plan and every feat -> kind -> version with its files."""
    info = store.plan_info(folder)
    state = store.read_state(folder)
    feats = []
    for feat in store.feats(folder):
        kinds = [{"id": kind, "versions": [_version(folder, feat, kind, n, state)
                                           for n in store.versions(folder, feat, kind)]}
                 for kind in store.kinds(folder, feat)]
        feats.append({"id": feat, "kinds": [k for k in kinds if k["versions"]]})
    label = f"plan {info['number']} {info['name']}" if info["number"] else f"plan {info['name']}"
    return {"plan": info, "title": f"{label} - design", "feats": [f for f in feats if f["kinds"]],
            "serve": f"{SERVE} --plan {info['slug']}"}


def _json_for_script(data: dict) -> str:
    """JSON safe inside a <script> element: no `<` can close it."""
    return json.dumps(data, ensure_ascii=False, indent=None).replace("<", "\\u003c")


def page(data: dict) -> str:
    html = TEMPLATE.read_text()
    html = html.replace("/*{{CSS}}*/", (HERE / "page.css").read_text())
    script = (HERE / "review.js").read_text() + "\n" + (HERE / "page.js").read_text()
    html = html.replace("/*{{JS}}*/", script)
    html = html.replace("{{TITLE}}", escape(data["title"]))
    return html.replace("{{DATA}}", _json_for_script(data))


def render(folder: Path, out: Path | None = None) -> Path:
    """Write `plans/<plan>/design.html` (or `out`) and return its path. Under the review lock, so a render never reads a
    state half-way through a write, and atomic (temp file + rename), so a reader never sees half a page."""
    target = out or folder / "design.html"
    with review.LOCK:
        html = page(model(folder))
        fd, temp = tempfile.mkstemp(prefix=".design-", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(fd, "w") as handle:
                handle.write(html)
            os.chmod(temp, 0o644)
            os.replace(temp, target)
        except BaseException:
            Path(temp).unlink(missing_ok=True)
            raise
    return target
