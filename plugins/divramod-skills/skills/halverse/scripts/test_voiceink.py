import contextlib
import io
import json
import os
import stat
import sys
import tempfile
import unittest

import halverse
import fake_cli
import voiceink

SYNC = {"dry_run": False, "changed": True, "backup": "/state/backups/20261013T120000.store",
        "vocabulary": {"added": ["toll gate", "Wagon Train"], "present": 340},
        "replacements": {"added": [{"word": "Claude Code", "heard": ["clawed code", "cloud code"]}],
                         "extended": [{"word": "farmer", "heard_added": ["farma"]}], "present": 52,
                         "refused": [{"word": "Claude", "heard": "clawed", "reason": "overlap", "detail": "inside \"clawed code\""},
                                     {"word": "mtm", "heard": "m t m", "reason": "other-word"}]},
        "problems": ["DICTATION.md line 9: no Word"]}
STATUS = {"store": {"path": "/s/default.store", "found": True, "schema_ok": True, "versions_verified": ["2.22"]},
          "vocabulary": {"wanted": 342, "present": 340, "missing": ["toll gate", "wagon train"]},
          "replacements": {"wanted": 54, "present": 52, "missing": [{"word": "Claude Code", "heard": ["clawed code"]}],
                           "refused": []}, "problems": []}


def error(code, message, detail=None):
    return {"error": {"code": code, "message": message, "detail": detail or {}}}


class Fake(unittest.TestCase):
    """A fake hal2-cli-voiceink: a script printing fixture JSON and exiting with D15's codes. The real CLI and store are never touched."""

    def setUp(self):
        fake_cli.in_process(self)
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "hal2-cli-voiceink")
        self.log = os.path.join(self.tmp.name, "args.txt")
        self.saved = os.environ.get(voiceink.CLI_ENV)
        os.environ[voiceink.CLI_ENV] = self.path

    def tearDown(self):
        if self.saved is None:
            os.environ.pop(voiceink.CLI_ENV, None)
        else:
            os.environ[voiceink.CLI_ENV] = self.saved
        self.tmp.cleanup()

    def cli(self, payload, code=0, raw=None):
        body = raw if raw is not None else json.dumps(payload)
        with open(self.path, "w") as handle:
            handle.write("#!%s\nimport sys\nopen(%r, 'a').write(' '.join(sys.argv[1:]) + '\\n')\nprint(%r)\nsys.exit(%d)\n"
                         % (sys.executable, self.log, body, code))
        os.chmod(self.path, os.stat(self.path).st_mode | stat.S_IXUSR)

    def args(self):
        with open(self.log) as handle:
            return handle.read().splitlines()


class Sync(Fake):
    def test_report_lines(self):
        self.cli(SYNC)
        text, code = voiceink.run("sync")
        self.assertEqual(code, 0)
        self.assertEqual(self.args(), ["sync --json"])
        for line in ["VoiceInk sync: written", "vocabulary: 2 added, 340 there already", "added: toll gate, Wagon Train",
                     "replacements: 1 added, 1 extended, 52 there already", "+ Claude Code <- clawed code, cloud code",
                     "~ farmer <- farma (forms added)", "refused (2), not written:",
                     "\"clawed\" for \"Claude\": it overlaps another entry", "inside \"clawed code\"",
                     "\"m t m\" for \"mtm\": the wrong form already points to another word",
                     "problems in the source files (1)", "DICTATION.md line 9: no Word",
                     "backup: /state/backups/20261013T120000.store", "undo: /hv voiceink restore"]:
            self.assertIn(line, text)

    def test_nothing_to_add_writes_no_backup(self):
        quiet = {"dry_run": False, "changed": False, "backup": None, "vocabulary": {"added": [], "present": 5},
                 "replacements": {"added": [], "extended": [], "present": 2, "refused": []}, "problems": []}
        self.cli(quiet)
        text, code = voiceink.run("sync")
        self.assertEqual(code, 0)
        self.assertIn("nothing to add, nothing written", text)
        self.assertIn("no backup made", text)
        self.assertNotIn("refused", text)

    def test_dry_run_passes_the_flag_and_says_so(self):
        self.cli(dict(SYNC, dry_run=True, backup=None))
        text, code = voiceink.run("sync", dry_run=True)
        self.assertEqual(self.args(), ["sync --dry-run --json"])
        self.assertIn("dry run: nothing written", text)
        self.assertNotIn("backup:", text)

    def test_long_lists_are_cut(self):
        big = dict(SYNC, vocabulary={"added": ["w%d" % i for i in range(40)], "present": 0})
        self.cli(big)
        text, _ = voiceink.run("sync")
        self.assertIn("w24 and 15 more", text)
        self.assertNotIn("w25,", text)

    def test_json_is_the_cli_data(self):
        self.cli(SYNC)
        text, code = voiceink.run("sync", as_json=True)
        self.assertEqual(json.loads(text), SYNC)


class Status(Fake):
    def test_report_and_no_write_flag(self):
        self.cli(STATUS)
        text, code = voiceink.run("status")
        self.assertEqual((code, self.args()), (0, ["status --json"]))
        for line in ["VoiceInk status (nothing written)", "store: /s/default.store (found)", "schema: known; verified versions: 2.22",
                     "vocabulary: 342 wanted, 340 there, 2 missing", "missing: toll gate, wagon train",
                     "replacements: 54 wanted, 52 there, 1 missing", "+ Claude Code <- clawed code", "/hv voiceink adds the missing ones."]:
            self.assertIn(line, text)

    def test_notes_are_no_problems_and_every_reason_has_words(self):
        note = {"file": "ontology", "line": 62, "message": "the in-force term zorb has no glossary entry",
                "rule": "no-glossary-entry", "severity": "note"}
        bad = {"file": "dictation", "line": 9, "message": "the row has no word", "rule": "no-word", "severity": "error"}
        refused = [{"word": "Zorb", "heard": form, "reason": reason, "detail": ""}
                   for form, reason in (("a$b", "unsafe-character"), ("", "empty"), ("a, b", "comma"), ("zorb", "in-replacement"))]
        self.cli(dict(STATUS, problems=[note, bad],
                      vocabulary={"wanted": 2, "present": 1, "missing": [], "refused": [{"word": "a, b", "reason": "comma"}]},
                      replacements={"wanted": 1, "present": 0, "missing": [], "refused": refused}))
        text, _ = voiceink.run("status")
        for line in ["problems in the source files (1), their rows were left out:", "  - dictation line 9: the row has no word",
                     "notes on the source files (1), nothing to do for the sync:",
                     "  - ontology line 62: the in-force term zorb has no glossary entry",
                     "  left out: \"a, b\" (it holds a comma", "a $ or a backslash", "\"\" for \"Zorb\": it is empty",
                     "also its own word, differing only by case"]:
            self.assertIn(line, text)
        self.assertNotIn("{", text)  # no raw JSON in a report

    def test_nothing_missing(self):
        done = dict(STATUS, vocabulary={"wanted": 1, "present": 1, "missing": []},
                    replacements={"wanted": 1, "present": 1, "missing": [], "refused": []})
        self.cli(done)
        text, _ = voiceink.run("status")
        self.assertIn("Nothing to add", text)


class Restore(Fake):
    def test_restore_newest(self):
        self.cli({"restored": "/b/1.store", "store": "/s/default.store"})
        text, code = voiceink.run("restore")
        self.assertEqual((code, self.args()), (0, ["restore --json"]))
        self.assertIn("restored /b/1.store", text)
        self.assertIn("into /s/default.store", text)
        self.assertNotIn("as it was", text)

    def test_restore_names_the_copy_of_the_store_as_it_was(self):
        self.cli({"restored": "/b/1.store", "store": "/s/default.store", "before": "/b/before-restore-1.store"})
        text, _ = voiceink.run("restore")
        self.assertIn("the store as it was before the restore is kept: /b/before-restore-1.store", text)
        self.assertIn("Open VoiceInk again.", text)  # a restore runs only while VoiceInk is quit

    def test_restore_a_named_backup_and_list(self):
        self.cli({"restored": "/b/2.store", "store": "/s"})
        voiceink.run("restore", backup="/b/2.store")
        self.assertEqual(self.args(), ["restore /b/2.store --json"])
        self.cli({"backups": [{"path": "/b/2.store", "created": "2026-10-13T12:00:00Z", "bytes": 4096}]})
        text, _ = voiceink.run("restore", list_backups=True)
        self.assertIn("/b/2.store", text)
        self.assertIn("4096 bytes", text)

    def test_empty_list(self):
        self.cli({"backups": []})
        self.assertIn("no backups yet", voiceink.run("restore", list_backups=True)[0])


class Errors(Fake):
    def check(self, code, kind, expect, detail=None, action="sync"):
        self.cli(error(kind, "cli says " + kind, detail), code=code)
        text, got = voiceink.run(action)
        self.assertEqual(got, code)
        self.assertIn(expect, text)
        self.assertIn("CLI message: cli says " + kind, text)
        return text

    def contract(self, exit_code, code, reason, message, details=None):
        """The CLI's answer since plan 0318: the contract's error on stderr, the old code in `details.reason`."""
        body = {"error": {"code": code, "exit": exit_code, "message": message, "hint": None,
                          "details": dict(details or {}, reason=reason)}}
        with open(self.path, "w") as handle:
            handle.write("#!%s\nimport sys\nprint(%r, file=sys.stderr)\nsys.exit(%d)\n"
                         % (sys.executable, json.dumps(body), exit_code))
        os.chmod(self.path, os.stat(self.path).st_mode | stat.S_IXUSR)

    def test_the_contracts_errors_are_read_and_told_in_the_scripts_codes(self):
        for exit_code, code, reason, told, expect, details in [
            (3, "not_found", "no-store", 3, "VoiceInk is not installed", {"path": "/x"}),
            (4, "refused", "unknown-schema", 4, "Verified VoiceInk versions: 2.11", {"versions_verified": ["2.11"]}),
            (5, "busy", "store-unavailable", 5, "Quit VoiceInk", {"why": "app-running"}),
            (1, "failed", "write-failed", 6, "rolled back", {"written": False}),
            (3, "not_found", "no-backup", 7, "no backup to restore", {}),
            (2, "usage", "unreadable", 2, "dictation file /h/DICTATION.md cannot be read",
             {"file": "dictation", "path": "/h/DICTATION.md"}),
            (1, "failed", "unwritable", 2, "import file could not be written", {"path": "/x/words.json"}),
        ]:
            self.contract(exit_code, code, reason, "cli says " + reason, details)
            text, got = voiceink.run("sync")
            self.assertEqual(got, told, reason)
            self.assertIn(expect, text, reason)
            self.assertIn("CLI message: cli says " + reason, text)

    def test_no_store(self):
        self.check(3, "no-store", "VoiceInk is not installed, was never opened, or this is not a Mac")

    def test_unknown_schema_names_verified_versions(self):
        text = self.check(4, "unknown-schema", "VoiceInk was probably updated", {"versions_verified": ["2.22", "2.23"]})
        self.assertIn("Verified VoiceInk versions: 2.22, 2.23.", text)

    def test_store_unavailable_advice_goes_by_the_reason(self):
        busy = self.check(5, "store-unavailable", "/hv voiceink again in a moment", {"reason": "busy"})
        self.assertIn("does not have to be quit", busy)  # a sync never needs VoiceInk quit (D17)
        self.assertNotIn("Quit VoiceInk", busy)
        running = self.check(5, "store-unavailable", "Quit VoiceInk (Cmd+Q in VoiceInk)", {"reason": "app-running"}, "restore")
        self.assertIn("/hv voiceink restore again", running)
        for detail in ({"reason": "failed"}, {}):
            other = self.check(5, "store-unavailable", "could not be read or written", detail)
            self.assertNotIn("Quit VoiceInk", other)

    def test_write_failed_after_a_rollback_says_nothing_was_written(self):
        text = self.check(6, "write-failed", "nothing was written", {"written": False})
        self.assertNotIn("put back", text)

    def test_write_failed_says_the_backup_was_put_back_only_when_it_was(self):
        text = self.check(6, "write-failed", "the backup was put back, so VoiceInk's store is as it was",
                          {"written": True, "backup": "/b/1.store", "restored": True})
        self.assertNotIn("/hv voiceink restore", text)

    def test_write_failed_with_the_backup_not_put_back_names_it_and_restore(self):
        text = self.check(6, "write-failed", "the backup was NOT put back",
                          {"written": True, "backup": "/b/1.store", "restored": False})
        self.assertIn("/b/1.store", text)
        self.assertIn("/hv voiceink restore", text)
        self.assertIn("Quit VoiceInk", text)

    def test_write_failed_without_detail_does_not_claim_a_restore(self):
        text = self.check(6, "write-failed", "NOT put back")
        self.assertNotIn("so VoiceInk's store is as it was", text)

    def test_no_backup(self):
        self.check(7, "no-backup", "There is no backup to restore", action="restore")

    def test_usage(self):
        self.check(2, "usage", "hal2-cli-voiceink --help")

    def test_a_source_file_that_cannot_be_read_is_named_and_is_no_wrong_call(self):
        text = self.check(2, "usage", "The dictation file /h/.claude/DICTATION.md cannot be read",
                          {"file": "dictation", "path": "/h/.claude/DICTATION.md"}, "status")
        self.assertIn("nothing was written", text)
        self.assertNotIn("The call was wrong", text)

    def test_unreadable_output(self):
        self.cli(None, code=0, raw="not json at all")
        text, code = voiceink.run("status")
        self.assertEqual(code, 1)
        self.assertIn("without JSON", text)
        self.cli(None, code=9, raw="boom")
        text, code = voiceink.run("status")
        self.assertEqual(code, 9)
        self.assertIn("exit code 9", text)

    def test_cli_not_installed_says_how_to_install(self):
        os.environ[voiceink.CLI_ENV] = os.path.join(self.tmp.name, "missing")
        text, code = voiceink.run("sync")
        self.assertEqual(code, 2)
        self.assertIn("not installed", text)
        self.assertIn("cargo install --path apps/hal2-cli-voiceink", text)
        self.assertIn("code/rust", text)


class Main(Fake):
    def run_main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = halverse.main(["voiceink"] + list(args))
        return code, out.getvalue(), err.getvalue()

    def test_default_is_sync(self):
        self.cli(SYNC)
        code, out, err = self.run_main()
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.args(), ["sync --json"])
        self.assertIn("VoiceInk sync: written", out)

    def test_status_restore_and_dry_run_routes(self):
        self.cli(STATUS)
        self.assertEqual(self.run_main("status")[0], 0)
        self.cli(SYNC)
        self.run_main("--dry-run")
        self.cli({"restored": "x", "store": "y"})
        self.run_main("restore")
        self.assertEqual(self.args(), ["status --json", "sync --dry-run --json", "restore --json"])

    def test_error_goes_to_stderr_with_the_cli_code(self):
        self.cli(error("store-unavailable", "m"), code=5)
        code, out, err = self.run_main()
        self.assertEqual((code, out), (5, ""))
        self.assertIn("could not be read or written", err)


if __name__ == "__main__":
    unittest.main()
