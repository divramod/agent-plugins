#!/usr/bin/env python3
"""`halverse.py christen|rechristen|swap|move|avatar|who`: one call of `hal2-cli-halverse names <leaf> --json` each (plan 0283, D1, D12, D25).

The CLI keeps the names (a farm's christened roles, their earlier names, their postings) in hal2's state folder and
is their one writer; this module makes the calls and words the answers, nothing here opens a store. A name is the
user's data: nothing in this file or its tests is a real one.

- `christen`, `rechristen`: with the name, the CLI's call; without it, the first 20 `names ideas` as numbered ideas and
  the call to make after the pick (the skill asks the user in the Q form, SKILL.md section 8).
- `swap`, `move`, `avatar`: the CLI's call at once; the user asked for exactly this.
- `who <name>`: `names lookup`: per hit the holder, its farm, field and folder and the line to reach it, or "not posted
  now" with the last posting. An unknown name is the CLI's exit 3.
- A refusal is the error document the CLI prints on stderr (exit 3 not found, 4 refused, 5 busy, 1 failed, 2 usage); it
  is worded by `details.reason` with the holder's name, and the CLI's exit code is passed on.

Python stdlib only.
"""
import json
import shlex
from typing import Any, Dict, List, Optional, Tuple

import cli

IDEAS = 20  # the ideas listed when no name is given
Result = Tuple[str, int]

ADVICE = {
    "BAD_NAME": "That is no name: it must not be empty, too long or hold a control character.",
    "NAME_IN_USE": "A name is given only once. Choose another name, or ask for ideas (`/hv christen`).",
    "NAME_RESERVED": "A name once given stays that one's for good. Choose another name, or ask for ideas (`/hv christen`).",
    "PLACE_HELD": "Another already holds that field. Swap with it (`/hv swap`) or move to a free field.",
    "NOT_A_FIELD": "That folder is no checkout of a repository. Name a field's folder (`--field <folder>`, `--to <folder>`).",
    "NO_NAMED": "Nobody is named so now. `/hv who <name>` finds one by a current or an earlier name, or by <farm>/<field>.",
    "SAME_NAME": "The name is the one it has already; nothing is changed.",
    "BUSY": "Another writer holds the names. Nothing was changed; call again in a moment.",
    "UNREADABLE": "The names cannot be read, so nothing was compared and nothing was changed. Tell the farmer.",
}


def holder_text(holder: Optional[Dict[str, Any]]) -> str:
    """"Mira, the foreman of barley field 07" (or "Mira, at no field now")."""
    if not holder:
        return ""
    if holder.get("role") and holder.get("farm_name"):
        return "%s, the %s of %s field %s" % (holder["name"], holder["role"], holder["farm_name"], holder.get("field"))
    return "%s, at no field now" % holder.get("name", "?")


def refusal_text(err: Dict[str, Any]) -> str:
    """The CLI's error worded for the user: what it refused, the holder's name, what to do. `err` is the contract's
    document (`details.reason`) or cli.py's normalized `{code: <reason>, message, detail, exit}`."""
    details = err.get("details") or err.get("detail") or {}
    reason = details.get("reason") or err.get("code", "?")
    holder = holder_text(details.get("holder"))
    message = err.get("message", "").rstrip(".")
    lines = ["Refused (%s): %s." % (reason, message)]
    if holder and reason != "NAME_IN_USE":  # that message is the holder's sentence already
        lines.append("The holder is %s." % holder)
    lines.append(ADVICE.get(reason, err.get("hint") or "See the message above."))
    if err.get("code") in ("refused", "busy") or err.get("exit") in (4, 5):
        lines.append("Nothing was changed.")
    return "\n".join(lines)


def _call(args: List[str]) -> Tuple[Optional[Dict[str, Any]], Optional[Result]]:
    """(the CLI's JSON, None), or (None, the worded failure and the CLI's exit code)."""
    try:
        return cli.call(["names"] + args), None
    except cli.CliError as err:
        if err.error is None:
            return None, (err.text, err.code)
        return None, (refusal_text(err.error), err.code)


def day(stamp: Optional[str]) -> str:
    return (stamp or "")[:10]


def head(named: Dict[str, Any]) -> str:
    """"Mira, foreman of barley field 07, avatar 12"."""
    open_ = open_posting(named)
    where = ("%s of %s field %s" % (open_["role"], open_["place"]["farm_name"], open_["place"]["field"])
             if open_ else "at no field")
    return "%s, %s, avatar %s" % (named["name"], where, named["avatar"])


def open_posting(named: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    last = (named.get("postings") or [None])[-1]
    return last if last and last.get("to") is None else None


def changed(verb: str, data: Dict[str, Any], as_json: bool) -> Result:
    if as_json:
        return json.dumps(data, indent=2, ensure_ascii=False), 0
    return "\n".join("%s %s" % (verb, head(named)) for named in data.get("named", [])), 0


def write(verb: str, args: List[str], as_json: bool) -> Result:
    data, failure = _call(args)
    return failure if failure else changed(verb, data, as_json)


def ideas_list(call: str, as_json: bool) -> Result:
    """The first IDEAS ideas, numbered, and the call to make once the user has picked one."""
    data, failure = _call(["ideas", "--count", str(IDEAS)])
    if failure:
        return failure
    ideas = list(data.get("ideas", []))
    if as_json:
        return json.dumps({"ideas": ideas, "then": call}, indent=2, ensure_ascii=False), 0
    rows = ["%2d. %s" % (i, idea) for i, idea in enumerate(ideas, 1)]
    return ("%d name ideas, none taken and none an earlier name of anyone:\n%s\n\nAsk the user to pick one or type "
            "their own (SKILL.md section 8, the Q form), then run:\n  %s\nThe same command again offers other ideas."
            % (len(ideas), "\n".join(rows), call)), 0


def christen(name: Optional[str], field: Optional[str], avatar: Optional[int], as_json: bool) -> Result:
    extra = (["--field", field] if field else []) + (["--avatar", str(avatar)] if avatar else [])
    if name:
        return write("christened", ["christen", name] + extra, as_json)
    return ideas_list("halverse.py christen <name>" + "".join(" " + shlex.quote(a) for a in extra), as_json)


def rechristen(name: str, new: Optional[str], as_json: bool) -> Result:
    if new:
        return write("rechristened", ["rechristen", name, new], as_json)
    return ideas_list("halverse.py rechristen %s <new name>" % shlex.quote(name), as_json)


def swap(first: str, second: str, as_json: bool) -> Result:
    return write("swapped", ["swap", first, second], as_json)


def move(name: str, to: str, as_json: bool) -> Result:
    return write("moved", ["move", name, "--to", to], as_json)


def avatar(name: str, number: int, as_json: bool) -> Result:
    return write("gave a new avatar to", ["avatar", name, str(number)], as_json)


def reach(posting: Dict[str, Any]) -> str:
    place = posting["place"]
    return ("To reach it: ListAgents shows the session of %s field %s, the one working in %s; send to it with "
            "SendMessage." % (place["farm_name"], place["field"], place["folder"]))


def plans(posting: Dict[str, Any]) -> str:
    labels = [p["label"] for p in posting.get("plans") or []]
    return ", plans " + ", ".join(labels) if labels else ""


def hit_lines(named: Dict[str, Any]) -> List[str]:
    how = {"earlier-name": " (found by an earlier name)", "holds": " (holds the field now)",
           "held": " (was at the field)"}.get(named.get("by"), "")
    now = open_posting(named)
    lines = ["%s%s" % (head(named), how)]
    if now:
        place = now["place"]
        lines += ["Posted now: the %s of %s field %s since %s%s." % (
            now["role"], place["farm_name"], place["field"], day(now["from"]), plans(now)),
                  "Farm: %s. Field: %s. Folder: %s" % (place["farm_name"], place["field"], place["folder"]),
                  reach(now)]
    elif named.get("postings"):
        last = named["postings"][-1]
        place = last["place"]
        lines.append("Not posted now. Last posting: the %s of %s field %s, %s to %s%s." % (
            last["role"], place["farm_name"], place["field"], day(last["from"]), day(last["to"]), plans(last)))
    else:
        lines.append("Not posted now. It has never been posted.")
    lines += ["Earlier name %s: %s to %s." % (e["name"], day(e["from"]), day(e["to"])) for e in named.get("earlier") or []]
    return lines


def who(query: str, as_json: bool) -> Result:
    data, failure = _call(["lookup", query])
    if failure:
        return failure
    if as_json:
        return json.dumps(data, indent=2, ensure_ascii=False), 0
    return "\n\n".join("\n".join(hit_lines(named)) for named in data.get("named", [])), 0
