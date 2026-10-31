"""The words of the triage's actions (hal2 plan 0490 step 2; D11, D12): every order, note and wake carries each red's
evidence (job, first error line, failing tests, the commit and run) and its "reproduce first" command: the tollman
never reproduces a red itself, the receiving field does (run_triage.REPRODUCED). Pure text over verdicts."""

from orders import PROOF  # the whole red job before the answer, the gate's bats (L113, L85): one source

LINE = 160  # an error line kept in a text
WHY = 700  # the longest `--why` of an order
ORDER = ("tollman (wagon train, triage of land run {rid}): train {train} is {where}, and {n} red unit(s) of its run "
         "are yours. Fix {them} in your next harvest (the fix rides the next train; nothing waits for it). Reproduce "
         "each first with the command named; the tollman did not." + PROOF + "\n{items}\nRun: {url}.")
ITEM = "- {unit} ({how}): {error}{tests}\n  reproduce first: {reproduce}"
WAKE = ("tollman (triage of land run {rid}): train {train}'s run {url} has {n} red unit(s) the code could not place. "
        "Judge each (a second look at the evidence, not a rerun), then order its owner by `tollman.py order <field> "
        "--post <train> --why ...` or post a board note:\n{items}")


def first(v: dict) -> str:
    """The verdict's first evidence line, cut."""
    lines = (v.get("evidence") or {}).get("lines") or []
    return (lines[0].strip() if lines else "no error line in the job's failed log")[:LINE]


def unit(v: dict) -> str:
    e = v.get("evidence") or {}
    return e.get("unit", "?") + (f" ({e['spec']})" if e.get("spec") else "")


def how(v: dict) -> str:
    """What the verdict is, in words: the kind and what it was placed by."""
    e, kind = v.get("evidence") or {}, v["kind"]
    if kind == "repeat":
        return f"repeat of run {e.get('repeat_of')}, never a car's; cause {v.get('cause')}"
    by = ((e.get("owner") or {}).get("from") or {}).get("by")
    return kind + (f", by the {by} of its newest commit" if kind == "file" and by else "")


def head(v: dict) -> str:
    return f"{v['key'].split(':', 2)[-1]} red ({v['kind']})"


def names(reds: list[dict]) -> str:
    return ", ".join(dict.fromkeys(unit(v) for v in reds))


def item(v: dict) -> str:
    e = v.get("evidence") or {}
    tests = f"; failing: {', '.join((e.get('tests') or [])[:4])}" if e.get("tests") else ""
    return ITEM.format(unit=unit(v), how=how(v), error=first(v), tests=tests, reproduce=v["reproduce"])


def why(reds: list[dict]) -> str:
    """`--why` of an order: each red's unit, first error line and reproduce command, cut at WHY."""
    text = " | ".join(f"{unit(v)}: {first(v)[:100]}; reproduce first: {v['reproduce']}" for v in reds)
    return text if len(text) <= WHY else text[:WHY - 3] + "..."


def order_text(reds: list[dict], train: dict, url: str, where: str = "in the barn") -> str:
    return ORDER.format(rid=url.rsplit("/", 1)[-1], train=train["train"], where=where, n=len(reds),
                        them="it" if len(reds) == 1 else "them", url=url, items="\n".join(item(v) for v in reds))


def note(v: dict, url: str, who: str | None = None) -> str:
    """A board note: nobody can be sent (no owner, its owner has no live session, or `who` says why)."""
    owner = v.get("owner")
    who = who or (f"owner {owner} has no live session" if owner else "no owner found")
    return f"{unit(v)} red ({how(v)}) of {url}: {who}. {first(v)}. Reproduce first: {v['reproduce']}"


def wake_text(waked: list[dict], train: dict, url: str) -> str:
    items = "\n".join(f"{item(v)}\n  {v['kind']}: {v.get('missing') or 'no owner found by the rules'}" for v in waked)
    return WAKE.format(rid=url.rsplit("/", 1)[-1], train=train["train"], url=url, n=len(waked), items=items)
