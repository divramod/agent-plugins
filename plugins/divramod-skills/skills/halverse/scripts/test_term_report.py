"""How the halverse skill words the writing calls' answers (plan 0276 step 11): a dry run's lines per file, a write's
report, VoiceInk's state, every error code, and `voiceink prompt` and `export` on fake programs."""
import json
import os
import re
import unittest

import cli
import fake_cli
import term_errors
import term_report
import voiceink
from fake_cli import REFUSED, TERM, InFolder, fixture

RUST = os.path.join(fake_cli.HERE, *[os.pardir] * 6, "rust")
STATES = ("no-store", "unknown-schema", "store-unavailable", "write-failed")


def error(code, message="the CLI's own words", detail=None):
    return {"error": {"code": code, "message": message, "detail": detail or {}}}


class Proposal(InFolder):
    def test_every_file_has_its_lines(self):
        out = term_report.proposal(fixture(TERM, "term-add-dry"), "n-1", "halverse.py add write --from t.json --confirmed n-1")
        self.assertTrue(out.startswith("halverse proposal (a dry run, nothing is written): 9 files, 9 changes\n"))
        for line in ["GLOSSARY.md (the glossary)\n  insert before line 69:\n    + \n    + **lashing**, **tie-up**:\n",
                     "GLOSSARY.de.md (the glossary, German)", "GLOSSARY.nl.md (the glossary, Dutch)\n",
                     "    + _pt-PT_: amarração\n", "HALVERSE-ONTOLOGY.pt-PT.md (the ontology, Portuguese)\n  insert before line 55:\n",
                     "    + | tie-up | ein Festmachen | in Kraft (Synonym) |", "DICTATION.md (DICTATION.md)\n",
                     "    + | lashing | lash in, lasching | the history: 3 |",
                     "check of the files as they would be: 3 errors, 16 notes",
                     "proposal number: n-1\n", "Only on the user's yes: halverse.py add write --from t.json --confirmed n-1"]:
            self.assertIn(line, out)
        self.assertNotIn("VoiceInk", out)

    def test_the_lines_that_give_way_are_shown_from_the_file(self):
        with open("GLOSSARY.md", "w", encoding="utf-8") as handle:
            handle.write("".join("old line %d\n" % n for n in range(1, 80)))
        out = term_report.proposal(fixture(TERM, "term-change-dry"), "n", "w")
        self.assertIn("GLOSSARY.md (the glossary)\n  replace line 71:\n    - old line 71\n"
                      "    + A ship made fast at its berth, bow and stern.\n", out)
        # A file that cannot be read says so and still shows the new line.
        self.assertIn("GLOSSARY.de.md (the glossary, German)\n  replace line 53:\n    (the old lines could not be read)\n    + Ein", out)

    def test_a_removal_and_a_range(self):
        with open("G.md", "w", encoding="utf-8") as handle:
            handle.write("one\ntwo\nthree\nfour\n")
        files = [{"file": "glossary", "lang": None, "path": "G.md", "changes": [
            {"line": 2, "last": 3, "lines": []}, {"line": 4, "last": 4, "lines": ["vier", "fünf"]}, {"line": 9, "last": 12, "lines": ["x"]}]}]
        self.assertEqual(term_report.files_lines(files, True), [
            "G.md (the glossary)", "  remove lines 2-3:", "    - two", "    - three", "  replace line 4:", "    - four",
            "    + vier", "    + fünf", "  replace lines 9-12:", "    (the old lines could not be read)", "    + x"])
        self.assertEqual(term_report.files_lines(files, False)[:2], ["G.md (the glossary)", "  remove lines 2-3"])

    def test_nothing_to_write_asks_nothing(self):
        data = dict(fixture(TERM, "term-change-dry"), files=[])
        out = term_report.proposal(data, "n", "w")
        self.assertIn("nothing to write, the files say this already", out)
        self.assertNotIn("proposal number", out)

    def test_a_retires_remark_and_an_unfinished_write_are_said(self):
        data = fixture(TERM, "term-retire-dry")
        data["remarks"].append("an earlier write did not end: 2 files as it left them")
        out = term_report.proposal(data, "n", "w")
        self.assertIn("note: VoiceInk keeps the word shipmaster", out)
        self.assertIn("note: an earlier write did not end: 2 files as it left them", out)


class Report(unittest.TestCase):
    def test_a_write_names_every_file_the_backup_the_check_and_voiceink(self):
        out = term_report.written(fixture(TERM, "term-add"))
        for line in ["halverse write: written, 9 files\n", "GLOSSARY.pt-PT.md (the glossary, Portuguese)\n  insert before line 61:\n",
                     "backup of the nine files as they were: state/backups/", "check of the files now: 3 errors, 16 notes",
                     "VoiceInk: synced, 60 vocabulary words and 9 replacements added, 0 extended",
                     "  vocabulary: pilot, Lotse,", " and 35 more", "  + lashing <- lash in, lasching",
                     "  backup of VoiceInk's store: voiceink-backups/dictionary-", "(undo: /hv voiceink restore)"]:
            self.assertIn(line, out)
        self.assertEqual(out.splitlines()[-1], term_report.SESSIONS)
        self.assertIn("after a clear", term_report.SESSIONS)

    def test_nothing_written_has_no_backup_and_no_line_on_sessions(self):
        data = dict(fixture(TERM, "term-change"), written=False, files=[], backup=None)
        out = term_report.written(data)
        self.assertIn("nothing written, the files said this already", out)
        self.assertIn("backup of the nine files as they were: none (nothing was written)", out)
        self.assertNotIn(term_report.SESSIONS, out)

    def test_what_an_interrupted_write_left_was_put_back_first(self):
        data = dict(fixture(TERM, "term-change"), recovered=["/h/GLOSSARY.md", "/h/DICTATION.md"])
        self.assertIn("An earlier write that did not end was undone first; put back: /h/GLOSSARY.md, /h/DICTATION.md",
                      term_report.written(data))

    def test_each_state_of_the_sync(self):
        said = term_report.voiceink_lines
        self.assertEqual(said({"state": "nothing-to-add", "report": {}, "message": None}),
                         ["VoiceInk: nothing to add, it has the words already"])
        self.assertEqual(said({"state": "skipped", "report": None, "message": None}), ["VoiceInk: not synced"])
        self.assertEqual(said({"state": "skipped", "report": None, "message": "the files cannot be read again"}),
                         ["VoiceInk: not synced: the files cannot be read again"])
        extended = {"state": "synced", "report": {"plan": {"vocabulary": {"added": []}, "replacements": {
            "added": [], "extended": [{"word": "knot", "heard": ["not", "kn"], "heard_added": ["kn"]}]}}, "backup": None}}
        self.assertEqual(said(extended), ["VoiceInk: synced, 0 vocabulary words and 0 replacements added, 1 extended",
                                          "  ~ knot <- kn (forms added)"])

    def test_a_failed_sync_has_the_codes_advice_and_says_the_files_stand(self):
        wanted = {"no-store": "VoiceInk's store was not found", "unknown-schema": "`/hv voiceink export`",
                  "store-unavailable": "could not be read or written now", "write-failed": "`/hv voiceink restore`"}
        for state in STATES:
            lines = term_report.voiceink_lines({"state": state, "report": None, "message": "the library's words"})
            self.assertEqual(lines[0], "VoiceInk: NOT synced (%s)" % state)
            self.assertIn(wanted[state], lines[1], state)
            self.assertEqual(lines[-2], "  CLI message: the library's words")
            self.assertEqual(lines[-1], "  The halverse files are written whatever VoiceInk says; `/hv voiceink` repeats the sync.")
        out = term_report.written(dict(fixture(TERM, "term-add"), voiceink={"state": "no-store", "report": None, "message": "m"}))
        self.assertIn("halverse write: written, 9 files", out)
        self.assertIn("VoiceInk: NOT synced (no-store)", out)

    def test_a_clash_in_a_companion_or_a_repository_names_that_file(self):
        data = fixture(TERM, "term-check")
        data["repositories"] = ["quay.md"]
        none = {"word_lang": None, "lang": None, "repository": None, "section": None}
        data["fit"][0] = {"word": "plank", "free": False, "clashes": [
            dict(none, kind="word", word="Planke", word_lang="de", file="glossary", lang="de", line=4),
            dict(none, kind="repository-avoid", word="plank", file="glossary", repository="quay.md", line=7),
            dict(none, kind="ontology-mention", word="plank", file="ontology", section="Todo", line=90),
            dict(none, kind="newer-kind", word="plank", file="dictation", line=2)]}
        out = term_report.fit(data)
        self.assertIn("and the repository glossary quay.md", out)
        self.assertIn('    - "Planke" (German) is an entry\'s word of another language: GLOSSARY.de.md:4', out)
        self.assertIn('    - "plank" is an `_Avoid_` word of a repository\'s own glossary: quay.md:7', out)
        self.assertIn('HALVERSE-ONTOLOGY.md:90, section "Todo"', out)
        self.assertIn('    - "plank" is held as newer-kind: DICTATION.md:2', out)


class Errors(InFolder):
    def said(self, payload, exit_code, *argv):
        self.answer(payload, exit_code)
        code, out, err = self.main(*(argv or ("short", "rm", "zz")))
        self.assertEqual((code, out), (exit_code, ""))
        return err

    def test_every_code_has_its_advice_and_the_clis_message(self):
        for code, advice in term_errors.ADVICE.items():
            exit_code = {"usage": 2, "unreadable": 2, "changed-meanwhile": 4, "locked": 4, "failed": 5}.get(code, 3)
            err = self.said(error(code), exit_code)
            self.assertEqual(err.splitlines()[:3], ["halverse term: %s (exit %d)" % (code, exit_code), advice,
                                                    "CLI message: the CLI's own words"], code)
        self.assertEqual(len(set(term_errors.ADVICE.values())), len(term_errors.ADVICE))

    def test_every_code_of_the_clis_source_has_an_advice(self):
        sources = [os.path.join(RUST, "libs", "hal2-halverse", "src", name) for name in ("edit.rs", os.path.join("write", "error.rs"))]
        if not all(os.path.isfile(path) for path in sources):
            return  # a checkout without the Rust sources (the published plugin)
        codes = {"usage", "unreadable"}
        for path in sources:
            with open(path, encoding="utf-8") as handle:
                body = handle.read().split("pub fn code(&self)")[1].split("\n    }\n")[0]
            codes |= set(re.findall(r'=> "([a-z0-9-]+)"', body))
        self.assertGreater(len(codes), 20)
        self.assertEqual(sorted(codes - set(term_errors.ADVICE)), [])
        self.assertEqual(sorted(set(term_errors.ADVICE) - codes), [])

    def test_a_code_without_an_advice_still_says_the_message(self):
        err = self.said(error("newer-code", "what the CLI says"), 3)
        self.assertIn("no advice for", err)
        self.assertIn("CLI message: what the CLI says", err)

    def test_the_documents_faults_are_named_by_field(self):
        self.use(REFUSED)
        code, _, err = self.main("change", "propose", "--from", os.path.join(fake_cli.DOCUMENTS, "invalid.json"))
        self.assertEqual(code, 3)
        self.assertIn("  - `terms` names no term\n  - `definition` line 2 reads as a heading", err)

    def test_a_planners_refusal_names_its_place(self):
        err = self.said(error("shared-row", detail={"file": "ontology", "lang": "de", "line": 30}), 3)
        self.assertIn("  at the ontology (German), line 30", err)
        err = self.said(error("draft-unfit", detail={"field": "ontology.languages.de.cells", "why": "is one part of two"}), 3)
        self.assertIn("  field `ontology.languages.de.cells`: is one part of two", err)
        err = self.said(error("spoken-form-refused", detail={"form": "k", "rule": "one-letter-form"}), 3)
        self.assertIn('  form "k", rule "one-letter-form"', err)
        self.use(REFUSED)
        self.assertIn('  term "berth", short form "bt"\n  at line 161', self.main("retire", "propose", "berth")[2])

    def test_a_change_beside_the_request_is_named_as_the_writers_fault(self):
        problem = {"file": "glossary", "lang": "nl", "line": 12, "severity": "error", "rule": "changed-unnamed",
                   "message": "the entry **knot** would read differently"}
        err = self.said(error("refused", detail={"problems": [problem]}), 3)
        self.assertIn("  - the glossary (Dutch), line 12: the entry **knot** would read differently (changed-unnamed; the change "
                      "would alter something the request does not name", err)

    def test_a_file_saved_meanwhile_names_it_and_the_undo(self):
        detail = {"file": "glossary", "lang": "de", "path": "/h/GLOSSARY.de.md",
                  "undone": {"put_back": ["/h/GLOSSARY.md"], "left": [], "failed": [], "journal": None}}
        err = self.said(error("changed-meanwhile", detail=detail), 4)
        self.assertIn("  at /h/GLOSSARY.de.md\nthe undo:\n  put back, as before the write: /h/GLOSSARY.md", err)
        err = self.said(error("locked", detail={"path": "/s/halverse/lock", "waited_ms": 5000}), 4)
        self.assertIn("  at /s/halverse/lock\n  waited 5000 ms for the lock", err)

    def test_a_failed_write_says_what_was_put_back_left_and_recovered(self):
        undone = {"put_back": ["/h/GLOSSARY.md"], "left": ["/h/GLOSSARY.nl.md"], "failed": ["/h/DICTATION.md"], "journal": "busy"}
        err = self.said(error("failed", detail={"undone": undone, "recovered": ["/h/HALVERSE-ONTOLOGY.md"]}), 5)
        for line in ["  put back, as before the write: /h/GLOSSARY.md", "  LEFT as they are: someone saved them since, and they "
                     "still hold a part of the write: /h/GLOSSARY.nl.md", "  could NOT be put back: the next call tries again "
                     "before anything else: /h/DICTATION.md", "  the writer's journal could not be removed (busy)",
                     "Before this error an earlier write that did not end was undone; put back: /h/HALVERSE-ONTOLOGY.md"]:
            self.assertIn(line, err)
        clean = self.said(error("failed", detail={"undone": {"put_back": [], "left": [], "failed": [], "journal": None}}), 5)
        self.assertIn("  no file had been replaced: the files are as they were", clean)

    def test_a_dry_run_names_what_an_earlier_write_left(self):
        err = self.said(error("no-entry", detail={"unrecovered": ["/h/GLOSSARY.md"]}), 3, "retire", "propose", "windlass")
        self.assertIn("An earlier write did not end; these files still hold its text, and the next write puts them back "
                      "first: /h/GLOSSARY.md", err)

    def test_a_missing_cli_names_the_install(self):
        os.remove(self.path)
        code, _, err = self.main("short")
        self.assertEqual(code, 2)
        self.assertIn("cargo install --path apps/hal2-cli-halverse", err)
        self.assertEqual(term_errors.text(cli.CliError("no answer", 1)), "no answer")


class Dictation(InFolder):
    """`voiceink prompt` asks hal2-cli-halverse, `voiceink export` hal2-cli-voiceink."""

    def setUp(self):
        super().setUp()
        self.use(TERM)
        self.voiceink = os.path.join(self.tmp.name, "hal2-cli-voiceink")
        self.voiceink_log = os.path.join(self.tmp.name, "voiceink-args.txt")
        self.saved_voiceink = os.environ.get(voiceink.CLI_ENV)
        os.environ[voiceink.CLI_ENV] = self.voiceink
        fake_cli.program(self.voiceink, self.voiceink_log, fixture(TERM, "export"))

    def tearDown(self):
        if self.saved_voiceink is None:
            os.environ.pop(voiceink.CLI_ENV, None)
        else:
            os.environ[voiceink.CLI_ENV] = self.saved_voiceink
        super().tearDown()

    def voiceink_args(self):
        if not os.path.isfile(self.voiceink_log):
            return []
        with open(self.voiceink_log) as handle:
            return handle.read().splitlines()

    def test_the_prompt_is_the_halverse_clis_between_two_lines(self):
        code, out, _ = self.main("voiceink", "prompt")
        self.assertEqual((code, self.args(), self.voiceink_args()), (0, ["prompt --json"], []))
        lines = out.splitlines()
        self.assertTrue(lines[0].startswith("halverse correction prompt: 40 terms, 9 of them with heard forms"))
        first, last = [n for n, line in enumerate(lines) if line == "-----"]
        self.assertEqual("\n".join(lines[first + 1:last]), fixture(TERM, "prompt")["prompt"])
        self.assertEqual(lines[last + 1:], ["the source files have 3 errors (their rows are left out) and 16 notes: `/hv check` lists them"])
        self.assertEqual(json.loads(self.main("voiceink", "prompt", "--json")[1])["terms"][0]["word"], "seaverse")

    def test_the_export_is_the_voiceink_clis_and_names_the_file(self):
        code, out, _ = self.main("voiceink", "export")
        self.assertEqual((code, self.args(), self.voiceink_args()), (0, [], ["export --json"]))
        self.assertIn("VoiceInk's import file is written: voiceink-import.json", out)
        self.assertIn("59 vocabulary words and 9 replacements; VoiceInk's store was not opened", out)
        self.assertIn("\"Import Dictionary\"", out)
        self.main("voiceink", "export", "--out", "words.json")
        self.assertEqual(self.voiceink_args()[1], "export --out words.json --json")

    def test_an_export_that_cannot_be_written_is_exit_2_with_its_advice(self):
        fake_cli.program(self.voiceink, self.voiceink_log, error("unwritable", "cannot write /x/w.json", {"path": "/x/w.json"}), 2)
        code, _, err = self.main("voiceink", "export", "--out", "/x/w.json")
        self.assertEqual(code, 2)
        self.assertIn("`/hv voiceink export --out <file>`", err)
        self.assertIn("CLI message: cannot write /x/w.json", err)

    def test_an_unknown_schema_names_the_export(self):
        self.assertIn("`/hv voiceink export`", voiceink.ADVICE["unknown-schema"])
        fake_cli.program(self.voiceink, self.voiceink_log, error("unknown-schema", "hashes differ"), 4)
        code, _, err = self.main("voiceink")
        self.assertEqual(code, 4)
        self.assertIn("`/hv voiceink export` writes the words as a file", err)


if __name__ == "__main__":
    unittest.main()
