#!/usr/bin/env python3
"""The arguments of `halverse.py` (plans 0270, 0273, 0276): one parser, a command per call of the skill.

`add` and `change` take an action each: `check <word>...` (the fit), `show <term>` (the term as the files have it),
`propose --from <file>` (the dry run) and `write --from <file> --confirmed <number>` (the one writing call). `retire`
takes `show`, `propose` and `write` with the term and `--by`; `short` lists, `short set` and `short rm` write at once.
Plan 0283 adds `christen`, `rechristen`, `swap`, `move`, `avatar` (names.py) and `who`.
Python stdlib only.
"""
import argparse

JSON_HELP = "print the CLI's data instead of the report"


def _document_actions(cmd: argparse.ArgumentParser, kind: str) -> None:
    actions = cmd.add_subparsers(dest="action", required=True)
    chk = actions.add_parser("check", help="the fit: each word free, or what holds it (file and line)")
    chk.add_argument("words", nargs="+", help="the term, its synonyms and its words of the other languages")
    chk.add_argument("--repo-glossary", action="append", help="a repository's GLOSSARY.md to compare with too "
                     "(default: the current repository's)")
    show = actions.add_parser("show", help="a term as the files have it, as data")
    show.add_argument("term")
    for name, text in (("propose", "the dry run: the lines per file and the proposal number, nothing written"),
                       ("write", "the writing call: only with the proposal number, after the user's yes")):
        act = actions.add_parser(name, help=text)
        act.add_argument("--from", dest="source", required=True, help="the term's JSON document: a file, or - for stdin")
        if name == "write":
            act.add_argument("--confirmed", help="the number the proposal of this document printed")
    for act in actions.choices.values():
        act.add_argument("--json", action="store_true", help=JSON_HELP)
        act.set_defaults(kind=kind)


def _retire_actions(cmd: argparse.ArgumentParser) -> None:
    actions = cmd.add_subparsers(dest="action", required=True)
    actions.add_parser("show", help="a term as the files have it, as data").add_argument("term")
    for name, text in (("propose", "the dry run: the lines per file and the proposal number, nothing written"),
                       ("write", "the writing call: only with the proposal number, after the user's yes")):
        act = actions.add_parser(name, help=text)
        act.add_argument("term", help="the term to retire")
        act.add_argument("--by", help="the term that replaces it: the retired word joins its _Avoid_ line")
        if name == "write":
            act.add_argument("--confirmed", help="the number the proposal of this retire printed")
    for act in actions.choices.values():
        act.add_argument("--json", action="store_true", help=JSON_HELP)


def _short_actions(cmd: argparse.ArgumentParser) -> None:
    cmd.add_argument("--json", action="store_true", help=JSON_HELP)
    actions = cmd.add_subparsers(dest="action")
    put = actions.add_parser("set", help="set a short form; written at once")
    put.add_argument("short")
    put.add_argument("word", help="the term it stands for; with --farm the project folder's name")
    put.add_argument("--farm", action="store_true", help="a farm's short form")
    put.add_argument("--spoken", action="store_true", help="also a heard form for VoiceInk (never one letter)")
    actions.add_parser("rm", help="remove a short form; written at once").add_argument("short")
    for act in actions.choices.values():
        act.add_argument("--json", action="store_true", help=JSON_HELP)


def _voiceink(cmd: argparse.ArgumentParser) -> None:
    cmd.add_argument("action", nargs="?", choices=["sync", "status", "restore", "prompt", "export"], default="sync",
                     help="sync (default), status, restore, prompt (the correction prompt) or export (the import file)")
    cmd.add_argument("backup", nargs="?", help="restore: the backup to put back (default the newest)")
    cmd.add_argument("--dry-run", action="store_true", help="sync: show what it would write, write nothing")
    cmd.add_argument("--list", action="store_true", help="restore: list the backups")
    cmd.add_argument("--out", help="export: the file to write (default: in hal2's state folder)")
    cmd.add_argument("--json", action="store_true", help=JSON_HELP)


def _names(sub) -> None:
    """The commands of plan 0283: christen, rechristen, swap, move, avatar and the lookup `who`."""
    cmds = {}
    for name, text in (("christen", "christen the field's role: with a name the CLI's call, without one name ideas"),
                       ("rechristen", "give a named one a new name; without it name ideas"),
                       ("swap", "two named ones swap their names"),
                       ("move", "move a named one to another field, also of another farm"),
                       ("avatar", "give a named one another of the 50 avatars"),
                       ("who", "find a named one by a current or earlier name, or <farm>/<field>: its farm and field")):
        cmds[name] = sub.add_parser(name, help=text)
        cmds[name].add_argument("--json", action="store_true", help=JSON_HELP)
    cmds["christen"].add_argument("name", nargs="?", help="the name; without it the ideas are listed")
    cmds["christen"].add_argument("--field", help="the field's folder (default: the working directory's checkout)")
    cmds["christen"].add_argument("--avatar", type=int, help="the avatar's number, 1 to 50 (default: the field's own)")
    cmds["rechristen"].add_argument("name", help="the current name, or <farm>/<field>")
    cmds["rechristen"].add_argument("new", nargs="?", help="the new name; without it the ideas are listed")
    cmds["swap"].add_argument("first", help="a current name or <farm>/<field>")
    cmds["swap"].add_argument("second", help="a current name or <farm>/<field>")
    cmds["move"].add_argument("name", help="the current name, or <farm>/<field>")
    cmds["move"].add_argument("--to", required=True, help="the other field's folder")
    cmds["avatar"].add_argument("name", help="the current name, or <farm>/<field>")
    cmds["avatar"].add_argument("number", type=int, help="the avatar's number, 1 to 50")
    cmds["who"].add_argument("name", help="a current or earlier name, or <farm>/<field>")


def parser(description: str) -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(prog="halverse.py", description=description)
    sub = top.add_subparsers(dest="command", required=True)
    cmd = sub.add_parser("learn", help="count old words against farm words in the user's own prompts")
    cmd.add_argument("--days", type=float, default=7, help="how many days back (default 7)")
    cmd.add_argument("--json", action="store_true", help="print data instead of the table")
    onto = sub.add_parser("ontology", help="the user's ontology and glossary, or one term of them")
    onto.add_argument("term", nargs="?", help="a term: its glossary entry, ontology lines, old word and command")
    onto.add_argument("--json", action="store_true", help="print data instead of text")
    chk = sub.add_parser("check", help="the check of the halverse files: errors, notes and what is untranslated")
    chk.add_argument("--json", action="store_true", help=JSON_HELP)
    _voiceink(sub.add_parser("voiceink", help="sync the words into VoiceInk, show the difference, restore a backup, "
                                              "print the correction prompt or write the import file"))
    _document_actions(sub.add_parser("add", help="add a term to the nine halverse files and VoiceInk"), "add")
    _document_actions(sub.add_parser("change", help="change a term in the nine halverse files"), "change")
    _retire_actions(sub.add_parser("retire", help="retire a term: it leaves the files and joins its successor's _Avoid_"))
    _short_actions(sub.add_parser("short", help="the short forms: list them, set one, remove one"))
    _names(sub)
    return top
