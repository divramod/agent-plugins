"""The farmer's questions as data (hal2 plan 0268, D9 and D11): its own store and the one list of everyone's.

  farmer.py question add --slot <slot|farmer> --text <the question in the Q form> [--waits <what waits for it>]
  farmer.py question answer <n> --text <answer>      farmer.py question drop <n> [--text <why>]
  farmer.py question list [--open|--answered|--all] [--json]       the farmer's own store only
  farmer.py questions [a|answered|l|list] [--json]    the call `/farmer questions` (and `/q` in the farmer's worktree): the
      farmer's own entries, the log's open `ask` entries and unacked instructions, and every worktree's store (the
      `q` skill's script), sorted by worktree then number, each in the Q form under a head line. No model call.

The store is `questions.jsonl` in the farmer's role folder, a keyed log (hal2 .adr/role-folder-formats.md): key `n`, the
last line per number is the state, so add, answer and drop each append one whole line. A line: `schema` 1, `at` (UTC),
`n`, `slot`, `text`, `waits`, `state` (open, answered, dropped), `asked`, `answer`, `closed`. A number is the highest ever
written plus one: never reused. Reading never creates the folder; a write needs it (the farmer's worktree, or FARMER_DIR).
"""

import argparse
import datetime as dt
import fcntl
import importlib.util
import json
import re
import sys
from pathlib import Path

import mtm_scan
import roles

sys.path.insert(0, next(str(_p / "scripts") for _p in Path(__file__).resolve().parents if (_p / ".claude-plugin").is_dir()))
from skillpath import sibling  # noqa: E402  (the skills unit's scripts/, plan 0360 D20)
S_SCRIPTS, Q_SCRIPTS = sibling("get-state") / "scripts", sibling("get-open-questions") / "scripts"
FILE, SCHEMA = "questions.jsonl", 1
STATES = ("open", "answered", "dropped")
MODES = {"open": "open", "a": "answered", "answered": "answered", "l": "all", "list": "all"}
NONE = {"open": "no open questions", "answered": "no answered questions", "all": "no questions"}
PREFIX = re.compile(r"^\s*Q\d+\s*:\s*")
SOURCE_LABEL = {"farmer": "the farmer's list", "ask": "open ask in the farmer's log", "unacked": "instruction not acked"}


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sibling(name: str, folder: Path, file: str, on_path: bool = False):
    """A module of a sibling skill loaded by path under `name` (a plain import would clash with the farmer's own
    `questions`), None when the skill or the module is missing or fails to import."""
    if name in sys.modules:
        return sys.modules[name]
    path = folder / file
    if not path.is_file():
        return None
    if on_path and str(folder) not in sys.path:
        sys.path.append(str(folder))
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    except Exception:  # noqa: BLE001  (a broken sibling skill leaves its part out, never fails the call)
        sys.modules.pop(name, None)
        return None
    return mod


def read_dir(main: str) -> Path:
    """The farmer's state folder as `roles.state_dir` finds it, without creating it."""
    if mtm_scan.DATA:
        return mtm_scan.DATA / Path(main).name
    return roles.slot_dir(main) / "roles" / roles.ROLE


def parse(text: str) -> dict[int, dict]:
    """The store's lines tolerantly (a torn or foreign line is skipped): the last line per number."""
    last: dict[int, dict] = {}
    for line in text.splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict) and isinstance(e.get("n"), int) and e.get("state") in STATES:
            last[e["n"]] = {"slot": "", "text": "", "waits": "", "asked": e.get("at", ""), "answer": "", "closed": "",
                            **e}
    return last


def load(folder: Path) -> list[dict]:
    path = folder / FILE
    return sorted(parse(path.read_text()).values(), key=lambda e: e["n"]) if path.is_file() else []


def append(folder: Path, make) -> dict:
    """Appends the line `make(entries by number)` returns, under an exclusive lock, so two writers never share a number."""
    if not folder.is_dir():
        raise ValueError(f"no farmer state folder at {folder}: start the farmer's worktree first")
    with (folder / FILE).open("a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        line = make(parse(f.read()))
        f.write(json.dumps(line, ensure_ascii=False) + "\n")
        f.flush()
    return line


def add(folder: Path, slot: str, text: str, waits: str = "") -> dict:
    if not slot.strip() or not text.strip():
        raise ValueError("question add needs --slot and --text")

    def make(entries: dict) -> dict:
        n, at = max(entries, default=0) + 1, now_utc()
        return {"schema": SCHEMA, "at": at, "n": n, "slot": slot.strip(), "text": f"Q{n}: {PREFIX.sub('', text.strip())}",
                "waits": waits.strip(), "state": "open", "asked": at, "answer": "", "closed": ""}
    return append(folder, make)


def close(folder: Path, n: int, state: str, answer: str = "") -> dict:
    if not (folder / FILE).is_file():
        raise ValueError(f"no question {n} in the farmer's list")

    def make(entries: dict) -> dict:
        e = entries.get(n)
        if e is None:
            raise ValueError(f"no question {n} in the farmer's list")
        if e["state"] != "open":
            raise ValueError(f"question {n} is already {e['state']}")
        return {**e, "schema": SCHEMA, "at": (at := now_utc()), "state": state, "answer": answer.strip(), "closed": at}
    return append(folder, make)


def entry(slot: str, source: str, state: str, text: str, n: int | None = None, waits: str = "", at: str = "",
          store: str = "") -> dict:
    return {"slot": slot, "source": source, "n": n, "state": state, "text": text, "waits": waits, "at": at, "store": store}


def own_text(e: dict) -> str:
    """A farmer-store entry as it prints: the Q form as stored, its answer or drop line, what waits for it."""
    lines = [e["text"]]
    if e["state"] == "answered":
        lines.append(f"Answer ({e['closed'][:10]}): {e['answer']}")
    elif e["state"] == "dropped":
        lines.append(f"Dropped ({e['closed'][:10]})" + (f": {e['answer']}" if e["answer"] else ""))
    if e["waits"]:
        lines.append(f"Waits for: {e['waits']}")
    return "\n".join(lines)


def own_entries(folder: Path) -> list[dict]:
    return [entry(e["slot"], "farmer", e["state"], own_text(e), e["n"], e["waits"], e["asked"]) for e in load(folder)]


def relayed(folder: Path) -> list[dict]:
    """The log's open `ask` entries (a worktree's last `ask` or answer is an `ask`) and the farmer's instructions nobody
    acked (state_sources.unacked, the call `state` uses)."""
    log = mtm_scan.entries(folder / "log.jsonl")
    if not log:
        return []
    answers = ("answered", "answer", "decision")
    last: dict[str, dict] = {}
    for e in log:
        if e.get("kind") == "ask" or e.get("kind") in answers:
            for slot in str(e.get("slot", "")).split(","):
                last[slot.strip()] = e
    out = [entry(slot, "ask", "open", "\n".join(x for x in (e["what"], e["note"]) if x), at=e["at"])
           for slot, e in last.items() if slot and e["kind"] == "ask"]
    return out + unacked_entries(log)


def unacked_entries(log: list[dict]) -> list[dict]:
    ss = sibling("state_sources", S_SCRIPTS, "state_sources.py", on_path=True)
    if ss is None:
        return []
    try:
        import acks
        texts = {i: (v["text"].splitlines() or [""])[0] for i, v in acks.instructions(log).items()}
        found = ss.unacked(log)
    except (ImportError, KeyError, ValueError, TypeError):
        return []
    return [entry(slot, "unacked", "open", f"{i}: {texts.get(i, '')}".rstrip(": ")) for slot, ids in found.items() for i in ids]


def slot_entries(main: str, mode: str) -> tuple[list[dict], list[str]]:
    """Every worktree's store (and the main checkout's) through the `q` skill's script; a store that cannot be read
    is named in the problems; without the `q` skill nothing is added."""
    qm = sibling("q_skill", Q_SCRIPTS, "q.py")
    if qm is None or getattr(qm, "questions", None) is None:
        return [], []
    slots = [(Path(w["path"]).name, Path(w["path"])) for w in mtm_scan.worktrees(main) if not Path(w["path"]).name.startswith(".")]
    out, problems = [], []
    for name, root in slots + [("main", Path(main))]:
        path = qm.store_of(root)
        rel = str(path.relative_to(root))
        try:
            found = qm.load(path)
        except ValueError as err:
            problems.append(f"{name}: {rel}: {err}")
            continue
        out += [entry(name, "store", e["state"], qm.render_entry(e), e["n"], at=e["asked"], store=rel) for e in qm.pick(found, mode)]
    return out, problems


def slot_key(slot: str) -> tuple:
    return (0, int(slot), "") if slot.isdigit() else (2, 0, "") if slot == "main" else (1, 0, slot)


def gather(main: str, mode: str) -> tuple[list[dict], list[str]]:
    """Everything that matches `mode`, sorted by worktree then number (a relayed ask has none)."""
    folder = read_dir(main)
    own = [e for e in own_entries(folder) if mode == "all" or e["state"] == mode]
    shown = relayed(folder) if mode in ("open", "all") else []
    slots, problems = slot_entries(main, mode)
    every = own + shown + slots
    return sorted(every, key=lambda e: (slot_key(e["slot"]), e["n"] or 0, e["source"])), problems


def head(entries: list[dict], mode: str) -> str:
    n, k = len(entries), len({e["slot"] for e in entries})
    where = f"in {k} worktree{'s' * (k != 1)}"
    if mode == "all":
        return f"{n} question{'s' * (n != 1)} {where}, {sum(e['state'] == 'open' for e in entries)} open"
    return f"{n} {mode} question{'s' * (n != 1)} {where}"


def block(e: dict) -> str:
    label = SOURCE_LABEL.get(e["source"]) or e["store"]
    return f"**{e['slot']}** ({label})\n{e['text']}"


def render(entries: list[dict], problems: list[str], mode: str) -> str:
    """The head line, then each entry under its worktree and source; one line when none. Problems close the list."""
    tail = [f"(not read: {p})" for p in problems]
    if not entries:
        return "\n".join([NONE[mode], *tail])
    return "\n\n".join([head(entries, mode), *(block(e) for e in entries), *tail])


def joined(mode_key: str, as_json: bool, repo: str) -> int:
    """`/farmer questions` (and `/q` in the farmer's worktree): print the one list."""
    mode, main = MODES[mode_key], mtm_scan.main_checkout(repo)
    entries, problems = gather(main, mode)
    if as_json:
        print(json.dumps({"mode": mode, "open": sum(e["state"] == "open" for e in entries),
                          "slots": len({e["slot"] for e in entries}), "entries": entries, "problems": problems}))
    else:
        print(render(entries, problems, mode))
    return 0


def run_question(args) -> int:
    main = mtm_scan.main_checkout(args.repo)
    try:
        if args.action == "add":
            e = add(mtm_scan.state_dir(main), args.slot or "", args.text or "", args.waits)
            print(f"Q{e['n']} added for {e['slot']}")
        elif args.action in ("answer", "drop"):
            if args.n is None or (args.action == "answer" and not (args.text or "").strip()):
                raise ValueError(f"question {args.action} needs <n>" + (" and --text" if args.action == "answer" else ""))
            e = close(mtm_scan.state_dir(main), args.n, "answered" if args.action == "answer" else "dropped", args.text or "")
            print(f"Q{e['n']} {e['state']}")
        else:
            mode = "answered" if args.answered else "all" if args.all else "open"
            own = [e for e in own_entries(read_dir(main)) if mode == "all" or e["state"] == mode]
            print(json.dumps({"mode": mode, "entries": own}) if args.json else render(own, [], mode))
    except ValueError as err:
        print(f"farmer.py question {args.action}: {err}", file=sys.stderr)
        return 1
    return 0


def add_parsers(sub) -> None:
    """The subcommands `question` and `questions` of farmer.py."""
    qs = sub.add_parser("question", help="the farmer's own question store")
    qs.add_argument("action", choices=("add", "answer", "drop", "list"))
    qs.add_argument("n", nargs="?", type=int)
    qs.add_argument("--slot")
    qs.add_argument("--text")
    qs.add_argument("--waits", default="")
    qs.add_argument("--open", action="store_true")
    qs.add_argument("--answered", action="store_true")
    qs.add_argument("--all", action="store_true")
    ql = sub.add_parser("questions", help="the one list of everyone's questions")
    ql.add_argument("mode", nargs="?", default="open", choices=sorted(MODES))
    for x in (qs, ql):
        x.add_argument("--json", action="store_true")
        x.add_argument("--repo", default=str(Path.cwd()))


def run(args) -> int:
    return run_question(args) if args.cmd == "question" else joined(args.mode, args.json, args.repo)
