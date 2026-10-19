"""The eval set of a skill (plan 0390 step 2): skill-creator's `evals/evals.json` plus a `split` and `checks` per eval.

    {"skill_name": "get-open-questions",
     "evals": [{"id": 1, "prompt": "...", "expected_output": "...", "files": [], "expectations": ["..."],
                "split": "train" | "val",
                "checks": [{"op": "contains", "value": "Q1"}, ...]}]}

A `files` entry is a path (skill-creator's form) or rollout.py's object `{"dest", "text"}` (a fixture inline in
evals.json) or `{"src", "dest"}`. `id`, `prompt`, `expected_output`, `files`, `expectations` are skill-creator's keys (plain-English `expectations` are
kept for the reader, never scored); `split` and `checks` are ours: the checks are deterministic (deterministic-first),
judge.py scores them. The ops:

    contains / not_contains   {"op", "value": str}      substring of the final answer
    regex                     {"op", "value": str}      `re.search` in the final answer (compiled here)
    max_chars                 {"op", "value": int > 0}  the final answer is at most that long
    tool_called               {"op", "name": str, "input": str (optional)}   a tool call with that name, whose input
                                                        (JSON text) holds the substring

`load` refuses a bad set with every problem at once (`EvalSetError.errors`): an eval without checks, an unknown op,
a set lacking a train or a val eval, duplicate ids. Stdlib only.
"""

import json
import re
from pathlib import Path

SPLITS = ("train", "val")
TEXT_OPS = ("contains", "not_contains", "regex")
OPS = TEXT_OPS + ("max_chars", "tool_called")


class EvalSetError(Exception):
    """The eval set is invalid; `errors` lists every problem."""

    def __init__(self, errors):
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


def _check_errors(where, check):
    if not isinstance(check, dict):
        return [f"{where}: a check must be an object"]
    op = check.get("op")
    if op not in OPS:
        return [f"{where}: unknown op {op!r} (known: {', '.join(OPS)})"]
    if op == "max_chars":
        value = check.get("value")
        ok = isinstance(value, int) and not isinstance(value, bool) and value > 0
        return [] if ok else [f"{where}: max_chars needs an integer value above 0"]
    if op == "tool_called":
        errors = [] if isinstance(check.get("name"), str) and check["name"] else [f"{where}: tool_called needs a name"]
        if "input" in check and not isinstance(check["input"], str):
            errors.append(f"{where}: tool_called's input must be a string")
        return errors
    value = check.get("value")
    if not isinstance(value, str) or (op != "not_contains" and not value):
        return [f"{where}: {op} needs a string value"]
    if op == "regex":
        try:
            re.compile(value)
        except re.error as exc:
            return [f"{where}: regex {value!r} does not compile ({exc})"]
    return []


def _file_ok(entry):
    """A `files` entry rollout.py can place: a path, or an object with a `dest` and either `text` or `src`."""
    if isinstance(entry, str):
        return bool(entry)
    if not isinstance(entry, dict) or not isinstance(entry.get("dest"), str) or not entry["dest"]:
        return False
    return isinstance(entry.get("text"), str) or isinstance(entry.get("src"), str)


def _eval_errors(where, item):
    if not isinstance(item, dict):
        return [f"{where}: an eval must be an object"]
    errors = []
    if not isinstance(item.get("prompt"), str) or not item["prompt"].strip():
        errors.append(f"{where}: needs a prompt")
    if item.get("split") not in SPLITS:
        errors.append(f"{where}: split must be one of {', '.join(SPLITS)}")
    if "expectations" in item and not (isinstance(item["expectations"], list)
                                       and all(isinstance(v, str) for v in item["expectations"])):
        errors.append(f"{where}: expectations must be a list of strings")
    if "files" in item and not (isinstance(item["files"], list) and all(_file_ok(v) for v in item["files"])):
        errors.append(f"{where}: files must be a list of paths or {{dest, text}} / {{src, dest}} objects")
    checks = item.get("checks")
    if not isinstance(checks, list) or not checks:
        errors.append(f"{where}: needs checks (a non-empty list)")
    else:
        for i, check in enumerate(checks):
            errors += _check_errors(f"{where} check {i + 1}", check)
    return errors


def validate(data):
    """Every problem of an evals.json object, as a list of messages (empty when valid)."""
    if not isinstance(data, dict):
        return ["the file must hold an object"]
    errors = []
    if not isinstance(data.get("skill_name"), str) or not data["skill_name"]:
        errors.append("needs a skill_name")
    items = data.get("evals")
    if not isinstance(items, list) or not items:
        return errors + ["needs evals (a non-empty list)"]
    seen = set()
    for i, item in enumerate(items):
        ident = item.get("id") if isinstance(item, dict) else None
        where = f"eval {ident if ident is not None else i + 1}"
        if isinstance(item, dict) and ident is None:
            errors.append(f"{where}: needs an id")
        elif ident is not None:
            if isinstance(ident, bool) or not isinstance(ident, (int, str)):
                errors.append(f"{where}: id must be an integer or a string")
            elif str(ident) in seen:
                errors.append(f"{where}: duplicate id")
            seen.add(str(ident))
        errors += _eval_errors(where, item)
    splits = {item.get("split") for item in items if isinstance(item, dict)}
    errors += [f"the set has no {name} eval" for name in SPLITS if name not in splits]
    return errors


class EvalSet:
    """A validated eval set: `train()` and `val()` give the evals of a split, in file order."""

    def __init__(self, data):
        errors = validate(data)
        if errors:
            raise EvalSetError(errors)
        self.skill_name = data["skill_name"]
        self.evals = list(data["evals"])

    def train(self):
        return [e for e in self.evals if e["split"] == "train"]

    def val(self):
        return [e for e in self.evals if e["split"] == "val"]

    def get(self, eval_id):
        for item in self.evals:
            if str(item["id"]) == str(eval_id):
                return item
        raise KeyError(eval_id)


def evals_path(path):
    """`<skill>/evals/evals.json` for a skill folder, else the path itself."""
    path = Path(path)
    return path / "evals" / "evals.json" if path.is_dir() else path


def load(path):
    """Load and validate the eval set of a skill folder or an evals.json file."""
    file = evals_path(path)
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise EvalSetError([f"{file} does not exist"]) from None
    except (OSError, ValueError) as exc:
        raise EvalSetError([f"{file} cannot be read as JSON ({exc})"]) from None
    return EvalSet(data)


def skeleton(skill_name):
    """A starting evals.json (D2): one train and one val eval with a placeholder prompt and check to be drafted.

    It passes `validate`, but its prompts still say TODO, so `is_skeleton` tells a run to draft the evals first.
    """
    def item(ident, split):
        return {"id": ident, "prompt": "TODO: a realistic task for this skill", "expected_output": "TODO",
                "files": [], "expectations": ["TODO: what a good answer does"], "split": split,
                "checks": [{"op": "contains", "value": "TODO"}]}
    return {"skill_name": skill_name, "evals": [item(1, "train"), item(2, "val")]}


def is_skeleton(data):
    """True while any prompt of the set still holds the skeleton's TODO."""
    return any(str(e.get("prompt", "")).startswith("TODO") for e in data.get("evals", []))
