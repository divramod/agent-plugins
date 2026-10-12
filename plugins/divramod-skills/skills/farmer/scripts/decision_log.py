"""The user's decisions in the farmer's log, and which a later one replaced (skills plan 0009).

  farmer.py decision list [--slot <slot>] [--all] [--repo <dir>]
      the current `decision` entries (with --all also the superseded ones, marked), one line each
  farmer.py decision supersede <at>... --by <at> [--why <text>] [--dry-run] [--repo <dir>]
      mark decisions replaced by a later one: appends a `supersede` entry; `<at>` is a prefix of a decision's id

The log is append-only (the tick writes it too), so a mark is a new entry, never an edit of the old one: any entry's
`supersedes` key (an id or a list of them) marks those decisions as replaced, and a decision check never reports
them. A decision's id is its `at`; decisions sharing an `at` (the farmer logs several at once) are `<at>#1`, `<at>#2`
in log order, which an append-only log keeps stable.

Links (skills plan 0010): `links(log)` gives each decision the ids of the farmer instructions (`acks.py instruct`,
`12-6`) that relayed it, so a servant naming a decision by that id has it. Sources: the decision's own `ack`/`acks`,
`decision-link` entries (`acks.py instruct --decision <id>`), and a back-fill computed from the log's `ask-ack` entries
(read-only, so past relays count without rewriting the log).
"""

import datetime as dt
import re

import mtm_scan

QUOTED = re.compile(r'"([^"]+)"|“([^”]+)”')
STOP = {"with", "that", "this", "from", "into", "have", "after", "before", "when", "then", "than", "them", "they",
        "their", "there", "what", "which", "where", "every", "each", "also", "only", "should", "would", "could", "must",
        "will", "were", "been", "being", "does", "done", "make", "made", "user", "slot", "plan", "step", "steps",
        "decided", "decision", "decisions", "farmer", "servant", "skill"}
REPO_WIDE = ("", "-", "*", "all")
IDS = re.compile(r"(?<![\w-])\d{1,2}[a-z](?![\w-])")  # option ids: 1a, 2b
ACKS = re.compile(r"(?<![\w:-])\d{2}-\d{1,3}(?![\w:-])")  # farmer instruction ids: 12-33
HOUR, RELAY_AFTER = dt.timedelta(hours=1), dt.timedelta(hours=12)


def words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) >= 4 and w not in STOP}


def flat(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", (text or "").lower()))


def quotes(entry: dict) -> list[str]:
    for field in ("note", "what"):
        found = [(a or b).strip() for a, b in QUOTED.findall(entry.get(field) or "")]
        if found:
            return found
    return []


def shares_wording(source: str, text: str) -> bool:
    """4 consecutive words of `source` (the whole of a 3-word one) occur in `text`."""
    w, listed = flat(source).split(), f" {flat(text)} "
    n = min(4, len(w))
    return n >= 3 and any(f" {' '.join(w[i:i + n])} " in listed for i in range(len(w) - n + 1))


def names(text: str, slot: str) -> bool:
    """`slot` as a standalone token: not part of a date (2026-10-04), a time (10:04), a path or a longer word."""
    return re.search(r"(?<![\w./:-])" + re.escape(slot) + r"(?![\w/:-])", text or "") is not None


ASIDE = re.compile(r"\([^()\"“”]*\)")


def subject(text: str) -> str:
    """The text without its asides: a parenthetical holding no quote mark (an example list "(06 ..., 04 plan 0094 step
    7)", "(slot 04)") names slots the decision is not about (skills plan 0012); the user's quoted words stay."""
    while True:
        bare = ASIDE.sub(" ", text or "")
        if bare == text:
            return bare
        text = bare


def slots(entry: dict) -> list[str]:
    return [s.strip() for s in str(entry.get("slot", "")).split(",")]


def concerns(entry: dict, slot: str, repo: str) -> bool:
    """Is this `decision` entry for the slot (`<slot>` of the farmer's repo `repo`, or `<other repo>/<slot>`)? Its `slot`
    names it, or it is repo-wide and its `what` names it: a slot of the farmer's repo outside asides (`subject`), a
    slot of another repo together with that repo's name."""
    own, _, bare = slot.rpartition("/")
    if slot in slots(entry) or (not own or own == repo) and bare in slots(entry):
        return True
    if not all(s in REPO_WIDE for s in slots(entry)):
        return False
    text = entry.get("what", "")  # the decision itself; a note naming a slot is bookkeeping ("relayed to 12")
    if not own or own == repo:  # the slot must be the subject, not an aside (skills plan 0012)
        return names(subject(text), bare)
    return names(text, bare) and re.search(rf"\b{re.escape(own)}\b", text) is not None


def when(entry: dict) -> dt.datetime:
    return dt.datetime.fromisoformat(entry["at"][:19])


def relayed(d: dict, ask: dict, repo: str) -> bool:
    """Did the instruction `ask` relay decision `d`? It goes to a slot `d` concerns, and holds 3+ words of the user's
    quote (sent from an hour before to 12 hours after `d`) or, for a decision without a quote, all its 2+ key words
    (sent within an hour either way)."""
    if not concerns(d, ask.get("slot", ""), repo):
        return False
    gap, text = when(ask) - when(d), ask.get("text") or ask.get("what", "")
    said = quotes(d)
    if said:
        return -HOUR <= gap <= RELAY_AFTER and any(shares_wording(q, text) for q in said)
    want = words(d.get("what", ""))
    return len(want) >= 2 and abs(gap) <= HOUR and want <= words(text)


def options(entry: dict) -> set[str]:
    return set(IDS.findall(f"{entry.get('what', '')} {entry.get('note', '')}".lower()))


def links(log: list[dict], repo: str = "") -> dict[str, set[str]]:
    """{decision id: the ack ids of the instructions that relayed it}. A decision whose option ids are a strict subset
    of an earlier one's of the same slot within an hour (`3a done` after `1a, 2a, 3a`) inherits that one's links."""
    asks = [e for e in log if e.get("kind") == "ask-ack" and e.get("id")]
    explicit = [e for e in log if e.get("kind") == "decision-link" and e.get("decision") and e.get("ack")]
    ds = ident(log)
    out: dict[str, set[str]] = {}
    for i, d in ds:
        own = d.get("acks") if isinstance(d.get("acks"), list) else []
        out[i] = {*own, *([d["ack"]] if d.get("ack") else []), *(e["ack"] for e in explicit if e["decision"] == i),
                  *(a["id"] for a in asks if relayed(d, a, repo))}
    direct = {i: set(v) for i, v in out.items()}
    for n, (i, d) in enumerate(ds):
        mine, here = options(d), set(slots(d)) - set(REPO_WIDE)
        for j, earlier in ds[:n]:
            if mine and mine < options(earlier) and here & set(slots(earlier)) and \
                    dt.timedelta(0) <= when(d) - when(earlier) <= HOUR:
                out[i] |= direct[j]
    return out


def ident(log: list[dict]) -> list[tuple[str, dict]]:
    """(id, entry) of every `decision` entry, in log order."""
    ds = [e for e in log if e.get("kind") == "decision"]
    counts: dict[str, int] = {}
    for e in ds:
        counts[e["at"]] = counts.get(e["at"], 0) + 1
    seen: dict[str, int] = {}
    out = []
    for e in ds:
        seen[e["at"]] = seen.get(e["at"], 0) + 1
        out.append((e["at"] if counts[e["at"]] == 1 else f"{e['at']}#{seen[e['at']]}", e))
    return out


def superseded(log: list[dict]) -> set[str]:
    """The ids marked as replaced (a bare `at` marks every decision of that `at`)."""
    marks: set[str] = set()
    for e in log:
        s = e.get("supersedes")
        marks.update([s] if isinstance(s, str) else s if isinstance(s, list) else [])
    return {i for i, e in ident(log) if i in marks or e["at"] in marks}


def decisions(log: list[dict], include_superseded: bool = False, repo: str = "") -> list[dict]:
    """The decisions (id, `links` added), without the superseded ones unless asked."""
    gone, linked = superseded(log), links(log, repo)
    return [{**e, "id": i, "links": sorted(linked[i])} for i, e in ident(log) if include_superseded or i not in gone]


def find(log: list[dict], prefix: str) -> dict:
    hits = [e for e in decisions(log, True) if e["id"].startswith(prefix)]
    if len(hits) != 1:
        found = ", ".join(e["id"] for e in hits[:5])
        raise ValueError(f"{prefix}: {'no' if not hits else len(hits)} decisions match{': ' + found if hits else ''}; "
                         f"give a longer id")
    return hits[0]


def mark(log: list[dict], ats: list[str], by: str, why: str) -> dict:
    """The `supersede` entry for decisions `ats` replaced by the later decision `by`; ValueError when one is wrong."""
    new = find(log, by)
    old = [find(log, a) for a in ats]
    late = [e["id"] for e in old if e["at"] >= new["at"]]
    if late:
        raise ValueError(f"--by {new['id']} is not later than {', '.join(late)}")
    slots = ",".join(dict.fromkeys(str(e.get("slot") or "-") for e in old))
    return {"kind": "supersede", "slot": slots, "what": ", ".join(e["id"] for e in old),
            "supersedes": [e["id"] for e in old], "note": f"by {new['id']}" + (f": {why}" if why else ""),
            "by": "farmer"}


def line(e: dict, gone: set[str] | frozenset = frozenset()) -> str:
    relays = f" (relayed as {', '.join(e['links'])})" if e.get("links") else ""
    return (f"{e['id']} [{e.get('slot') or '-'}]{' (superseded)' if e['id'] in gone else ''} "
            f"{e.get('what', '').strip()[:160]}{relays}")


def run(args) -> int:
    main = mtm_scan.main_checkout(args.repo)
    log = mtm_scan.entries(mtm_scan.state_dir(main) / "log.jsonl")
    if args.action == "list":
        repo = main.rstrip("/").rsplit("/", 1)[-1]
        shown = [e for e in decisions(log, args.all, repo) if not args.slot or concerns(e, args.slot, repo)]
        gone = superseded(log)
        print("\n".join(line(e, gone) for e in shown) or "no decisions")
        return 0
    try:
        entry = mark(log, args.at, args.by, args.why)
    except ValueError as e:
        print(f"farmer.py decision supersede: {e}")
        return 1
    for a in entry["supersedes"]:
        print(("would mark " if args.dry_run else "superseded ") + line(find(log, a)))
    print(f"  by {line(find(log, args.by))}")
    if not args.dry_run:
        mtm_scan.log(main, entry)
    return 0
