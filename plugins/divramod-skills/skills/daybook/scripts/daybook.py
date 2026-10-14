#!/usr/bin/env python3
"""The daybook: a farm's daily list of chores, one file per day, open chores carried into the next day.

  daybook.py [--farm DIR] [--date YYYY-MM-DD] [--json] <command>
    show                       make/refresh today, print the open items numbered, the plans, the watches
    today                      the same, print only the file's path
    jot <text> [--later]       a chore under Today (Later)
    tick <n | text>            tick one open item off (a watch item ends its watch)
    move <n | text> today|later
    plans                      only the plan lines (no write)
    watch list                 the watches with due (no write)
    watch add <id> --title T --cron C --prompt P [--every E] [--until U]
    watch rm <id>              active: false, its open item ticked
    watch ran <id> [--result R]
    where                      the farm root, the folder, today's path (no write)

Exit codes: 0 ok; 2 usage or a ref matching no or several items; 3 farm not found or folder not writable;
4 an unparsable watches.yaml or day file; 5 the lock not taken in 5 s. The format: the skill's README.md.
"""
import argparse
import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import dayfile  # noqa: E402
import farm  # noqa: E402
import watchfile  # noqa: E402

DAY_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.md$")


class Usage(Exception):
    pass


class Book:
    """One farm's daybook for one day: paths, language, the watches."""

    def __init__(self, start, date):
        self.root, self.trees = farm.farm_root(start)
        self.folder, jobsearch = farm.folder_of(self.root)
        self.date = date
        self.path = os.path.join(self.folder, f"{date.isoformat()}.md")
        self.jobsearch = jobsearch
        self.watch_path = os.path.join(self.folder, "watches.yaml")

    def read(self, path):
        try:
            return farm.read_text(path)
        except UnicodeDecodeError as err:
            raise watchfile.YamlError(f"{path}: not UTF-8 ({err})") from err

    def earlier(self):
        days = sorted(m.group(1) for name in (os.listdir(self.folder) if os.path.isdir(self.folder) else [])
                      for m in [DAY_RE.match(name)] if m and m.group(1) < self.date.isoformat())
        return os.path.join(self.folder, days[-1] + ".md") if days else None

    def watches(self):
        if not os.path.exists(self.watch_path):
            return [], []
        try:
            return watchfile.parse(self.read(self.watch_path))
        except watchfile.YamlError as err:
            raise watchfile.YamlError(f"{self.watch_path}: {err}") from err

    def save_watches(self, comments, watches):
        farm.write_atomic(self.watch_path, watchfile.dump(comments, watches))

    def load(self):
        """Today's day (made by carry-over when missing, D5) and its language; nothing written."""
        if os.path.exists(self.path):
            text = self.read(self.path)
            return dayfile.complete(dayfile.parse(text), self.lang(text)), self.lang(text), text
        prev_path = self.earlier()
        prev_text = self.read(prev_path) if prev_path else ""
        lang = self.lang(prev_text)
        previous = dayfile.parse(prev_text) if prev_path else None
        return dayfile.carry_over(previous, self.date, lang), lang, None

    def lang(self, text):
        return "de" if self.jobsearch else dayfile.language(text)

    def refresh_plans(self, day, plans):
        sec = dayfile.first(day, "plans")
        if sec["marker"] == dayfile.MARKER:
            sec["items"] = [[p["line"]] for p in plans]

    def save(self, day, old_text):
        text = dayfile.render(day)
        if text != old_text:
            farm.write_atomic(self.path, text)


def now():
    return dt.datetime.now().astimezone()


def watch_rows(watches, at):
    keys = ("id", "title", "cron", "every", "until", "prompt", "active", "last_run", "last_result")
    return [dict({k: w.get(k) for k in keys}, active=w.get("active", True) is not False, due=watchfile.due(w, at))
            for w in watches]


def report(book, day, plans, watches):
    open_ = [dayfile.item_info(n, sec, item, book.date) for n, sec, _, item in dayfile.open_items(day)]
    done = [dayfile.item_info(None, sec, item, book.date) for sec in day["sections"] if sec["role"] == "done"
            for item in sec["items"]]
    return {"farm": book.root, "folder": book.folder, "date": book.date.isoformat(), "path": book.path,
            "open": open_, "done": done, "plans": [{k: v for k, v in p.items() if k != "line"} for p in plans or []],
            "watches": watch_rows(watches, now())}


def text_report(data, plans):
    names = {"today": "Today", "later": "Later", "watches": "Watch"}
    lines = [data["path"]]
    for item in data["open"]:
        old = f"  [{item['age_days']} days old]" if (item["age_days"] or 0) > 3 else ""
        lines.append(f"{item['n']:>2}. [{names[item['section']]}] {item['text']}{old}")
    if plans is not None:
        lines += ["", "Plans:"] + [p["line"] for p in plans] if plans else ["", "Plans: none open"]
    if data["watches"]:
        lines += ["", "Watches:"]
        for w in data["watches"]:
            if w["active"]:
                state = {True: "due", False: "not due", None: "bad cron"}[w["due"]]
                lines.append(f"- {w['id']}: {state} ({w['every'] or w['cron']}; last run {w['last_run'] or 'never'})")
    lines += ["", f"{len(data['open'])} open, {len(data['done'])} done today"]
    return "\n".join(lines)


def watch_command(args, book, day, lang, comments, watches):
    """watch add|rm|ran on the parsed watches and day; returns the message to print."""
    by_id = {w.get("id"): w for w in watches}
    if args.action != "add" and args.id not in by_id:
        raise Usage(f"no watch {args.id!r}")
    if args.action == "add":
        if not re.fullmatch(r"[a-z0-9-]+", args.id) or args.id in by_id:
            raise Usage(f"watch id {args.id!r} is not kebab case or exists already")
        if not (args.title and args.cron and args.prompt):
            raise Usage("watch add needs --title, --cron and --prompt")
        try:
            watchfile.parse_cron(args.cron)
        except ValueError as err:
            raise Usage(str(err)) from err
        entry = {"id": args.id, "title": args.title, "cron": args.cron, "prompt": args.prompt, "active": True}
        entry.update({k: getattr(args, k) for k in ("every", "until") if getattr(args, k)})
        watches.append(entry)
        dayfile.add_watch_items(day, [entry], book.date, lang)
        return f"watch added: {args.id} (create its cron job)"
    watch = by_id[args.id]
    if args.action == "rm":
        watch["active"] = False
        dayfile.tick_watch(day, args.id, now(), lang)
        return f"watch ended: {args.id} (delete its cron job)"
    watch["last_run"] = now().isoformat(timespec="seconds")
    if args.result:
        watch["last_result"] = " ".join(args.result.split())
    return f"watch ran: {args.id}"


def write_command(args, book):
    """Every command that may write: carry-over first, then the edit, under the lock."""
    farm.make_folder(book.root, book.folder)
    with farm.Lock(book.folder):
        day, lang, old_text = book.load()
        comments, watches = book.watches()
        watches_before = watchfile.dump(comments, watches)
        dayfile.add_watch_items(day, watches, book.date, lang)
        plans, message = None, None
        if args.cmd in ("show", "today") or old_text is None:
            plans = farm.scan_plans(book.root, book.trees)
            book.refresh_plans(day, plans)
        if args.cmd == "jot":
            dayfile.jot(day, " ".join(args.text), "later" if args.later else "today", book.date, lang)
        elif args.cmd == "tick":
            item, ended = dayfile.tick(day, args.ref, now(), lang)
            message = f"ticked: {item[0][6:]}"
            for w in watches:
                if ended and w.get("id") == ended:
                    w["active"] = False
                    message += f"\nwatch ended: {ended} (delete its cron job)"
        elif args.cmd == "move":
            dayfile.move(day, args.ref, args.to)
        elif args.cmd == "watch":
            message = watch_command(args, book, day, lang, comments, watches)
        if watchfile.dump(comments, watches) != watches_before:
            book.save_watches(comments, watches)
        book.save(day, old_text)
    return day, (plans if args.cmd in ("show", "today") else None), watches, message


def parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--farm", default=".")
    ap.add_argument("--date", help="YYYY-MM-DD instead of today (local time)")
    ap.add_argument("--json", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("show", "today", "plans", "where"):
        sub.add_parser(name)
    p = sub.add_parser("jot")
    p.add_argument("text", nargs="+")
    p.add_argument("--later", action="store_true")
    sub.add_parser("tick").add_argument("ref")
    p = sub.add_parser("move")
    p.add_argument("ref")
    p.add_argument("to", choices=dayfile.MOVABLE)
    p = sub.add_parser("watch")
    p.add_argument("action", choices=("list", "add", "rm", "ran"))
    p.add_argument("id", nargs="?")
    for opt in ("--title", "--cron", "--prompt", "--every", "--until", "--result"):
        p.add_argument(opt)
    return ap


def run(args):
    try:
        date = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    except ValueError as err:
        raise Usage(f"bad --date: {err}") from err
    book = Book(args.farm, date)
    if args.cmd == "where":
        data = {"farm": book.root, "folder": book.folder, "date": date.isoformat(), "path": book.path}
        return json.dumps(data) if args.json else "\n".join(data.values())
    if args.cmd == "plans":
        plans = farm.scan_plans(book.root, book.trees)
        return json.dumps({"plans": [{k: v for k, v in p.items() if k != "line"} for p in plans]}, ensure_ascii=False) \
            if args.json else "\n".join(p["line"] for p in plans)
    if args.cmd == "watch" and args.action == "list":
        rows = watch_rows(book.watches()[1], now())
        return json.dumps({"watches": rows}, ensure_ascii=False) if args.json else \
            "\n".join(f"{r['id']}\t{'active' if r['active'] else 'ended'}\t{'due' if r['due'] else '-'}\t{r['title']}"
                      for r in rows)
    if args.cmd == "watch" and not args.id:
        raise Usage(f"watch {args.action} needs an id")
    day, plans, watches, message = write_command(args, book)
    data = report(book, day, plans, watches)
    if args.json:
        return json.dumps(dict(data, message=message), ensure_ascii=False)
    if args.cmd == "today":
        return book.path
    return "\n".join(filter(None, [message, text_report(data, plans)]))


def fail(args, code, error, candidates=()):
    if args.json:
        print(json.dumps({"error": error, "candidates": list(candidates)}, ensure_ascii=False), file=sys.stderr)
    else:
        print("error: " + "\n  ".join([error, *candidates]), file=sys.stderr)
    return code


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        print(run(args))
    except dayfile.RefError as err:
        return fail(args, 2, str(err), err.candidates)
    except Usage as err:
        return fail(args, 2, str(err))
    except farm.FarmError as err:
        return fail(args, 3, str(err))
    except PermissionError as err:
        return fail(args, 3, f"folder not writable: {err}")
    except watchfile.YamlError as err:
        return fail(args, 4, str(err))
    except farm.LockError as err:
        return fail(args, 5, str(err))
    return 0


if __name__ == "__main__":
    sys.exit(main())
