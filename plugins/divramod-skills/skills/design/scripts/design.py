#!/usr/bin/env python3
"""The design skill's engine (hal2 plan 0364): a plan's designs as versioned files and its one `design.html`.

  design.py new <feat> <kind> [--title T] [--base NOTE]   the next version plans/<plan>/design/<feat>/<kind>/v<n>/,
                                                          started from a copy of v<n-1>'s files (never changes it)
  design.py render [--out PATH]                           write plans/<plan>/design.html from design/
  design.py list [--json]                                 every design version with its files and review state
  design.py serve [--port 0] [--open]                     the review server on 127.0.0.1: accept toggle and comments
                                                          are saved into design/state.json (open the printed URL)
  design.py status [--json]                               per feat and kind: versions, the accepted one, comments
  design.py accepted --json                               only the accepted versions with their file paths

Every command takes `--plan <n|slug>` (else plans/CURRENT_PLAN) and `--repo <path>` (else the repository around the
working directory). A version's files are named by what they show: `screen.html`, `flow.mmd`, `schema.dbml`,
`drawing.excalidraw`, `scenarios.md`, or `current.<ext>` beside `new.<ext>` for old and new side by side.
Exit 0 on success, 1 on a usage or store error.
"""

import argparse
import json
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import render  # noqa: E402
import review  # noqa: E402
import serve  # noqa: E402
import store  # noqa: E402


def parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--plan", help="the plan's number or folder name (default: plans/CURRENT_PLAN)")
    common.add_argument("--repo", help="the repository (default: the one around the working directory)")
    top = argparse.ArgumentParser(prog="design.py", description=__doc__.split("\n\n")[0],
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = top.add_subparsers(dest="command", required=True)
    new = sub.add_parser("new", parents=[common], help="create the next version of a feat's design kind")
    new.add_argument("feat", help="the feat, kebab-case (e.g. login)")
    new.add_argument("kind", help="the design kind, kebab-case (gui, flow, erd, scenarios, states, sequence, ...)")
    new.add_argument("--title", default="", help="the version's title (default: the previous version's)")
    new.add_argument("--base", default="", help="what the design is based on (the current look, schema, ...)")
    new.add_argument("--json", action="store_true", help="print the new version as JSON")
    out = sub.add_parser("render", parents=[common], help="write plans/<plan>/design.html")
    out.add_argument("--out", help="another output path")
    listing = sub.add_parser("list", parents=[common], help="list every design version")
    listing.add_argument("--json", action="store_true", help="print JSON")
    host = sub.add_parser("serve", parents=[common], help="serve design.html on 127.0.0.1 and save the review state")
    host.add_argument("--port", type=int, default=0, help="the port (default 0: a free one)")
    host.add_argument("--host", default=serve.LOOPBACK, help="127.0.0.1 only (anything else is refused)")
    host.add_argument("--open", action="store_true", help="open the page in the default browser")
    state = sub.add_parser("status", parents=[common], help="the review state: accepted versions and comments")
    state.add_argument("--json", action="store_true", help="print JSON")
    ok = sub.add_parser("accepted", parents=[common], help="the accepted versions with their file paths")
    ok.add_argument("--json", action="store_true", help="print JSON")
    return top


def folder_of(args) -> Path:
    root = Path(args.repo).resolve() if args.repo else store.repo_root(Path.cwd())
    return store.plan_dir(root, args.plan)


def cmd_new(args) -> int:
    folder = folder_of(args)
    path = store.new_version(folder, args.feat, args.kind, title=args.title, base=args.base)
    meta = store.read_meta(path)
    files = [f.name for f in store.files(path)]
    if args.json:
        print(json.dumps({**meta, "path": str(path), "files": files}, indent=2))
    else:
        start = f" (started from {meta['from']}: {', '.join(files)})" if meta.get("from") else ""
        print(f"{meta['id']}: {path}{start}")
    return 0


def cmd_render(args) -> int:
    folder = folder_of(args)
    target = render.render(folder, Path(args.out).resolve() if args.out else None)
    print(target)
    return 0


def listing(folder: Path) -> dict:
    """The plan and every version: id, title, created, files, accepted, comments (agents read this)."""
    data = render.model(folder)
    designs = [{"id": v["id"], "feat": f["id"], "kind": k["id"], "version": v["v"], "title": v["title"],
                "created": v["created"], "from": v["from"], "base": v["base"],
                "files": [x["name"] for x in v["files"]], "latest": v is k["versions"][-1],
                "accepted": v["review"]["accepted"], "comments": len(v["review"]["comments"])}
               for f in data["feats"] for k in f["kinds"] for v in k["versions"]]
    return {"plan": data["plan"], "folder": str(folder), "html": str(folder / "design.html"), "designs": designs}


def cmd_list(args) -> int:
    data = listing(folder_of(args))
    if args.json:
        print(json.dumps(data, indent=2))
        return 0
    if not data["designs"]:
        print(f"no designs in {data['folder']}/design")
    for d in data["designs"]:
        mark = "accepted" if d["accepted"] else "open"
        print(f"{d['id']:<32} {mark:<8} {d['title']}  [{', '.join(d['files'])}]")
    return 0


def cmd_serve(args) -> int:
    folder = folder_of(args)
    server = serve.make_server(folder, args.host, args.port)
    render.render(folder)
    url = serve.url_of(server)
    print(f"design review at {url}  (Ctrl+C stops it; state: {review.state_path(folder)})", flush=True)
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("stopped", flush=True)
    finally:
        server.server_close()
    return 0


def cmd_status(args) -> int:
    data = review.status(folder_of(args))
    if args.json:
        print(json.dumps(data, indent=2))
        return 0
    counts = data["counts"]
    print(f"plan {data['plan']['number']} {data['plan']['name']}: {counts['designs']} designs, "
          f"{counts['accepted']} accepted, {counts['comments']} comments")
    for feat in data["feats"]:
        for kind in feat["kinds"]:
            print(f"{feat['id']}/{kind['id']}: accepted {kind['accepted'] or 'none'} (latest {kind['latest']})")
            for row in kind["versions"]:
                for c in row["comments"]:
                    where = f" [{c['anchor']}]" if c.get("anchor") else ""
                    print(f"  {row['id']}{where} {c.get('at', '')} {c.get('by', '')}: {c.get('text', '')}")
    return 0


def cmd_accepted(args) -> int:
    data = review.accepted(folder_of(args))
    if args.json:
        print(json.dumps(data, indent=2))
        return 0
    if not data["accepted"]:
        print("no accepted design")
    for row in data["accepted"]:
        print(f"{row['id']}{' (superseded)' if row['superseded'] else ''}: {row['path']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    commands = {"new": cmd_new, "render": cmd_render, "list": cmd_list, "serve": cmd_serve, "status": cmd_status,
                "accepted": cmd_accepted}
    try:
        return commands[args.command](args)
    except (store.StoreError, OSError, json.JSONDecodeError) as err:
        print(f"design.py: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
