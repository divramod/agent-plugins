#!/usr/bin/env python3
"""halverse: `ontology [<term>]` shows the user's ontology and glossary; `check` words the check of the halverse files; `learn [--days n] [--json]` counts the user's old words against their farm words (plan 0270); `voiceink [status|restore|prompt|export]` syncs the words into VoiceInk through hal2-cli-voiceink (plan 0273); `add`, `change`, `retire` and `short` write a term or a short form through hal2-cli-halverse (plan 0276).

Reads the user's typed prompts of the last n days (transcripts.py) and, through hal2-cli-halverse (sources.py), the
halverse files; prints a table, the ambiguous forms and the three words to practise. `check` words the CLI's
check of the files. The writing calls (term.py) go through the CLI's writer: a proposal is a dry run, a write needs the
proposal's number. This script stores nothing and sends nothing. Python stdlib only.
"""
import argparse
import json
import shlex
import sys
from typing import List, Optional, Tuple

import check
import cli
import halverse_args
import learn
import ontology
import prompt
import sources
import term
import transcripts
import voiceink


def coverage(pairset: learn.PairSet) -> List[str]:
    """The pairs checked against the files; without the CLI or with a file it cannot read, one line says they were not."""
    try:
        data = sources.load()
    except cli.CliError as err:
        return ["the pairs were not checked against the files: " + err.text.splitlines()[0]]
    return learn.coverage_warnings(pairset, sources.farm_words(data), sources.glossary_pairs(data))


def run_learn(days: float, as_json: bool) -> str:
    pairset = learn.load_pairs()
    messages = list(transcripts.user_messages(days))
    stats = learn.count(messages, pairset.pairs)
    warnings = coverage(pairset)
    top = learn.practise(stats)
    if as_json:
        return json.dumps({
            "days": days, "messages": len(messages),
            "rows": [{"old": s.pair.old_label, "new": s.pair.new, "command": s.pair.command, "since": s.pair.since,
                      "old_uses": s.old, "new_uses": s.new, "share": s.share, "ambiguous_uses": s.ambiguous_count,
                      "ambiguous": s.ambiguous, "practise": s.pair.practise, "example": s.example[1] if s.example else None}
                     for s in learn.ranked(stats)],
            "ambiguous": learn.ambiguous_lines(stats),
            "practise": [{"new": s.pair.new, "old": s.pair.old_label, "old_uses": s.old, "share": s.share} for s in top],
            "warnings": warnings}, indent=2, ensure_ascii=False)
    out = ["halverse learn: %d typed prompts of the last %g days" % (len(messages), days), "", learn.table(stats)]
    amb = learn.ambiguous_lines(stats)
    out += [""] + [learn.wrap(line) for line in amb] if amb else []
    out += ["", learn.wrap("practise: " + (", ".join("%s (for %s, %d old use%s)" % (s.pair.new, s.pair.old_label, s.old, "" if s.old == 1 else "s") for s in top)
                                or "nothing: no old word used"))]
    out += [""] + [learn.wrap("warning: " + w) for w in warnings] if warnings else []
    return "\n".join(out)


def run_term(args: argparse.Namespace) -> Tuple[str, int]:
    """`add`, `change` and `retire`: the fit, the term as it is, the proposal (a dry run) or the one writing call."""
    if args.action == "check":
        return term.check(args.words, args.repo_glossary, args.json)
    if args.action == "show":
        return term.show(args.term)
    try:
        if args.command == "retire":
            request = term.retire_request(args.term, args.by)
            call = "halverse.py retire write %s" % " ".join(shlex.quote(part) for part in request[0][2:])
        else:
            request = term.document_request(args.kind, args.source)
            call = "halverse.py %s write --from %s" % (args.kind, shlex.quote(args.source))
    except cli.CliError as err:
        return err.text, err.code
    if args.action == "propose":
        return term.propose(request, call, args.json)
    return term.write(request, args.confirmed, args.json)


def run_short(args: argparse.Namespace) -> Tuple[str, int]:
    if args.action == "set":
        return term.short_set(args.short, args.word, args.farm, args.spoken, args.json)
    if args.action == "rm":
        return term.short_rm(args.short, args.json)
    return term.short_list(args.json)


def run_voiceink(args: argparse.Namespace) -> Tuple[str, int]:
    if args.action == "prompt":
        return prompt.run(args.json)
    return voiceink.run(args.action, args.json, args.dry_run, args.backup, args.list, args.out)


def main(argv: Optional[List[str]] = None) -> int:
    args = halverse_args.parser(__doc__).parse_args(argv)
    if args.command == "learn":
        print(run_learn(args.days, args.json))
        return 0
    if args.command == "check":
        text, code = check.run(args.json)
        print(text, file=sys.stderr if code > 1 else sys.stdout)
        return code
    if args.command == "ontology":
        text, code = ontology.run(args.term, args.json)
    elif args.command == "voiceink":
        text, code = run_voiceink(args)
    elif args.command == "short":
        text, code = run_short(args)
    else:
        text, code = run_term(args)
    print(text, file=sys.stderr if code else sys.stdout)
    return code


if __name__ == "__main__":
    sys.exit(main())
