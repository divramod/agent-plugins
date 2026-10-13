#!/usr/bin/env python3
"""halverse: `ontology [<term>]` shows the user's ontology and glossary; `learn [--days n] [--json]` counts the user's old words against their farm words (plan 0270); `voiceink [status|restore]` syncs the words into VoiceInk through hal2-cli-voiceink (plan 0273).

Reads the user's typed prompts of the last n days (transcripts.py) and the two source files (sources.py); prints a
table, the ambiguous forms and the three words to practise. Stores nothing, sends nothing. Python stdlib only.
"""
import argparse
import json
import sys
from typing import List, Optional

import learn
import ontology
import sources
import transcripts
import voiceink


def run_learn(days: float, as_json: bool) -> str:
    pairset = learn.load_pairs()
    messages = list(transcripts.user_messages(days))
    stats = learn.count(messages, pairset.pairs)
    words = sources.farm_words(sources.read_text(sources.ontology_path()))
    headings = sources.glossary_pairs(sources.read_text(sources.glossary_path()))
    warnings = learn.coverage_warnings(pairset, words, headings)
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


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="halverse.py", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    cmd = sub.add_parser("learn", help="count old words against farm words in the user's own prompts")
    cmd.add_argument("--days", type=float, default=7, help="how many days back (default 7)")
    cmd.add_argument("--json", action="store_true", help="print data instead of the table")
    onto = sub.add_parser("ontology", help="the user's ontology and glossary, or one term of them")
    onto.add_argument("term", nargs="?", help="a term: its glossary entry, ontology lines, old word and command")
    onto.add_argument("--json", action="store_true", help="print data instead of text")
    vi = sub.add_parser("voiceink", help="sync the words into VoiceInk (hal2-cli-voiceink), or show the difference, or restore a backup")
    vi.add_argument("action", nargs="?", choices=["sync", "status", "restore"], default="sync", help="sync (default), status or restore")
    vi.add_argument("backup", nargs="?", help="restore: the backup to put back (default the newest)")
    vi.add_argument("--dry-run", action="store_true", help="sync: show what it would write, write nothing")
    vi.add_argument("--list", action="store_true", help="restore: list the backups")
    vi.add_argument("--json", action="store_true", help="print the CLI's data instead of the report")
    args = parser.parse_args(argv)
    if args.command == "voiceink":
        text, code = voiceink.run(args.action, args.json, args.dry_run, args.backup, args.list)
        print(text, file=sys.stderr if code else sys.stdout)
        return code
    if args.command == "ontology":
        text, code = ontology.run(args.term, args.json)
        print(text, file=sys.stderr if code else sys.stdout)
        return code
    print(run_learn(args.days, args.json))
    return 0


if __name__ == "__main__":
    sys.exit(main())
