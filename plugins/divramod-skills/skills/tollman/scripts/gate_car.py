#!/usr/bin/env python3
"""Which car rides alone (hal2 plan 0333 step 10, D12; .adr/wagon-master.md rule 5).

A crop touching the landing workflow, a gate job list or the runner setup (`.github/workflows/`, `.github/hal2-*.toml`,
`code/bash/scripts/gate/`; until this step the ALONE rule) rides with the other cars when its trial merge is clean:
the landing runs the candidate's own `merge-to-main.yml` (`on: push` to `land/**`), so the train's run tests a
changed job, lane, job list or runner, and a red train is split as any other. What that run cannot test is a change
to what starts it and lets hal2-cli-git find it: the landing workflow added, removed or renamed, or its `on:`,
`name:` or `run-name:` changed. Such a car (`alone_why` names the file and the change) rides alone, the only car of
its train. On 2026-10-14 09, 08, 21 and 22 changed gate files, none of them that part: they ride together.
"""

import re

import trial as trial_merge

LANDING = re.compile(r"^\.github/workflows/(merge-to-main|dev-merge-to-main|land)\.ya?ml$")  # the mtm skill's names
TRIGGER = ("on", "name", "run-name")  # the top-level keys that start the run and name it
KINDS = {"A": "adds", "D": "removes", "R": "renames"}


def trigger(text: str) -> dict[str, str]:
    """The top-level `on:`, `name:` and `run-name:` of a workflow, each with its block, comments left out."""
    keys, key = {}, None
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        top = re.match(r"^([A-Za-z_-]+|'on'|\"on\"):", line)
        if top:
            key = top.group(1).strip("'\"")
        if key in TRIGGER:
            keys[key] = keys.get(key, "") + line.split(" #")[0].rstrip() + "\n"
    return keys


def alone_why(main: str, default: str, head: str) -> str | None:
    """Why the crop at `head` rides alone, or None: it adds, removes or renames the landing workflow, or changes
    what starts and names its run."""
    base = trial_merge.git(main, "merge-base", default, head)[1] or default
    status = trial_merge.git(main, "diff", "--name-status", "-M", base, head, "--", ".github/workflows/")[1]
    for line in status.splitlines():
        kind, *paths = line.split("\t")
        landing = next((p for p in paths if LANDING.match(p)), None)
        if landing and kind[:1] in KINDS:
            return f"it {KINDS[kind[:1]]} the landing workflow {landing}"
        if landing and trigger(show(main, base, landing)) != trigger(show(main, head, landing)):
            return f"it changes what starts the landing's run ({landing}: on, name or run-name)"
    return None


def show(main: str, rev: str, path: str) -> str:
    code, text = trial_merge.git(main, "show", f"{rev}:{path}")
    return text if code == 0 else ""
