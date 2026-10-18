"""The store commands of `lookout.py` (plan 0311 step 2): add, set, end, list, log, finds, run, tick.

Each handler takes the parsed args and returns the exit code; a refused change prints `lookout.py: <why>` to stderr
and returns 2. They are joined into `lookout.COMMANDS` (name -> (help, add_arguments, run)). Stdlib only.
"""

import json
import sys

import lookout_frame  # noqa: F401  (puts the daybook's watchfile on the import path)
import find
import lookout_tick
import paths
import runner
import store
import watchfile

KEYS = ("title", "cron", "check") + store.OPTIONAL
HELP = {"title": "what is watched", "cron": "5-field cron, the tick's 5-minute grid", "check": "the check command line",
        "every": "the cron in words", "until": "when the watch ends", "prompt": "a daybook prompt-only watch's text",
        "judge": "judge prompt: text or @path in the farm", "apply": "the farm's command per find",
        "budget": "USD per judge run (default 0.05, at most 0.50)", "model": "judge model (default sonnet)",
        "notify": "default, none or desktop,telegram", "timeout": "check timeout in seconds (default 60, max 300)"}


def guarded(handler):
    def run(args):
        try:
            return handler(args)
        except (store.StoreError, watchfile.YamlError) as exc:
            print(f"lookout.py: {exc}", file=sys.stderr)
            return 2
    return run


def _name(farm):
    """The farm name of a `--farm DIR` option (default: the current folder's farm)."""
    return store.farm_of(farm or ".")[0]


def _fields(args, keys):
    return {k: getattr(args, k) for k in keys if getattr(args, k, None) is not None}


def _add_args(p):
    p.add_argument("id")
    p.add_argument("--farm", default=".", help="the farm's folder (default: here)")
    for key in KEYS:
        p.add_argument(f"--{key}", help=HELP[key])
    p.add_argument("--by", help="who adds it (default $LOOKOUT_BY, else user@host)")


@guarded
def cmd_add(args):
    name, path = store.farm_of(args.farm)
    store.add(name, path, args.id, _fields(args, KEYS), args.by)
    print(f"added {name}/{args.id}")
    return 0


def _set_args(p):
    p.add_argument("id")
    p.add_argument("--farm", help="the farm's folder (needed when the id is in several farms)")
    for key in KEYS + ("active",):
        p.add_argument(f"--{key}", help=HELP.get(key, "true or false"))
    p.add_argument("--by")


@guarded
def cmd_set(args):
    name = store.find_watch(args.id, _name(args.farm) if args.farm else None)
    changes = store.set_keys(name, args.id, _fields(args, KEYS + ("active",)), args.by)
    print("\n".join(f"{name}/{args.id}: {k} {old!r} -> {new!r}" for k, (old, new) in changes.items())
          or f"{name}/{args.id}: nothing changed")
    return 0


def _end_args(p):
    p.add_argument("id")
    p.add_argument("--farm")
    p.add_argument("--reason", default="")
    p.add_argument("--by")


@guarded
def cmd_end(args):
    name = store.find_watch(args.id, _name(args.farm) if args.farm else None)
    changed = store.end(name, args.id, args.by, reason=args.reason)
    print(f"ended {name}/{args.id}" if changed else f"{name}/{args.id} had ended already")
    return 0


def _list_args(p):
    p.add_argument("--farm", help="the farm's folder (default: here)")
    p.add_argument("--all", action="store_true", help="every farm")
    p.add_argument("--json", action="store_true")


@guarded
def cmd_list(args):
    names = [n for n, _ in store.farm_files()] if args.all else [_name(args.farm)]
    rows = [dict(w, farm_name=n) for n in names for w in store.load(n)[1]]
    if args.json:
        print(json.dumps({"watches": rows}, ensure_ascii=False, default=str))
        return 0
    for w in rows:
        print("\t".join([f"{w['farm_name']}/{w['id']}", "active" if w.get("active", True) is not False else "ended",
                         str(w.get("state") or "-"), str(w.get("last_run") or "-"), str(w.get("cron", "")),
                         str(w.get("title", ""))]))
    return 0


def _log_args(p):
    p.add_argument("id", nargs="?")
    p.add_argument("--farm", help="the farm's folder (default: every farm)")
    p.add_argument("--since", help="ISO date or time")
    p.add_argument("--json", action="store_true")


@guarded
def cmd_log(args):
    lines = store.read_changes(_name(args.farm) if args.farm else None, args.id, args.since)
    for line in lines:
        if args.json:
            print(json.dumps(line, ensure_ascii=False))
            continue
        what = "; ".join(f"{k}: {old!r} -> {new!r}" for k, (old, new) in line.get("changes", {}).items())
        print(f"{line.get('at')}\t{line.get('by')}\t{line.get('farm')}/{line.get('watch')}\t{line.get('op')}\t{what}"
              + (f"\t({line['reason']})" if line.get("reason") else ""))
    return 0


@guarded
def cmd_finds(args):
    for line in find.read_finds(_name(args.farm), args.since):
        print(json.dumps(line, ensure_ascii=False) if args.json else
              f"{line.get('at')}\t{line.get('watch')}\t{line.get('event')}\t{line.get('title')}")
    return 0


def _finds_args(p):
    p.add_argument("--farm", help="the farm's folder (default: here)")
    p.add_argument("--since", help="ISO date or time")
    p.add_argument("--json", action="store_true")


def _run_args(p):
    p.add_argument("id")
    p.add_argument("--farm")
    p.add_argument("--dry-run", action="store_true", help="judge and record nothing (LOOKOUT_DRY_RUN=1)")


@guarded
def cmd_run(args):
    name = store.find_watch(args.id, _name(args.farm) if args.farm else None)
    record = next(w for w in store.load(name)[1] if w.get("id") == args.id)
    if args.dry_run:
        out = runner.run_watch(record, name, dry_run=True)
        print(json.dumps({"outcome": out["outcome"], "new": out["new"], "record": out["record"],
                          "finds": [f["title"] for f in out["finds"]]}, ensure_ascii=False))
        return 0
    report = lookout_tick.handle(lookout_tick.Ctx(now=paths.now()), name, record, True)
    print(json.dumps(report, ensure_ascii=False))
    return 0


def _tick_args(p):
    p.add_argument("--repo", help="ignored: the timer types it, lookout is global")
    p.add_argument("--dry-run", action="store_true", help="print the watches a tick would run, run nothing")


COMMANDS = {
    "add": ("add a watch to a farm's file", _add_args, cmd_add),
    "set": ("change keys of a watch", _set_args, cmd_set),
    "end": ("end a watch (kept as history)", _end_args, cmd_end),
    "list": ("the watches with their state", _list_args, cmd_list),
    "log": ("the change log (who changed what)", _log_args, cmd_log),
    "finds": ("a farm's find record", _finds_args, cmd_finds),
    "run": ("run one watch now", _run_args, cmd_run),
    "tick": ("one round over every due watch", _tick_args, lookout_tick.cmd_tick),
}
