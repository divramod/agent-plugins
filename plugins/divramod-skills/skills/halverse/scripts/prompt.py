#!/usr/bin/env python3
"""`halverse.py voiceink prompt`: the correction prompt for dictation, from `hal2-cli-halverse prompt --json` (plan 0276, D19, D38).

The CLI builds the prompt (research 0076's measured wording, then each term with what the speech model writes for it);
this module prints it between two lines, so it is copied whole and unchanged. Nothing is written. Python stdlib only.
"""
import json
from typing import Tuple

import cli
import voiceink

RULE = "-" * 5


def run(as_json: bool = False) -> Tuple[str, int]:
    """(the prompt with its head line, the exit code): 2 the CLI missing or a file it cannot read (named)."""
    try:
        data = cli.call(["prompt"])
    except cli.CliError as err:
        return err.text, err.code
    if as_json:
        return json.dumps(data, indent=2, ensure_ascii=False), 0
    terms = data.get("terms") or []
    heard = sum(1 for term in terms if term.get("heard_as"))
    out = ["halverse correction prompt: %d terms, %d of them with heard forms; the prompt is the text between the two "
           "lines of dashes, to be copied whole" % (len(terms), heard), RULE, data.get("prompt", ""), RULE]
    return "\n".join(out + voiceink.problem_counts(data.get("problems") or [])), 0
