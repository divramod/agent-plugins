import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import unittest

import check
import fake_cli
import halverse
from fake_cli import FakeCli

NINE = {"glossary": "GLOSSARY.md", "ontology": "HALVERSE-ONTOLOGY.md", "dictation": "DICTATION.md",
        "companions": {"de": {"glossary": "GLOSSARY.de.md", "ontology": "HALVERSE-ONTOLOGY.de.md"},
                       "nl": {"glossary": "GLOSSARY.nl.md", "ontology": "HALVERSE-ONTOLOGY.nl.md"},
                       "pt-PT": {"glossary": "GLOSSARY.pt-PT.md", "ontology": "HALVERSE-ONTOLOGY.pt-PT.md"}}}


def problem(rule, severity="note", file="glossary", lang=None, line=3, message="m"):
    return {"file": file, "lang": lang, "line": line, "severity": severity, "rule": rule, "message": message}


class Folder(FakeCli):
    """A folder of the test's own JSON files: the CLI's contract copies, one file replaced."""

    def folder(self, **files):
        path = os.path.join(self.tmp.name, "data")
        os.makedirs(path, exist_ok=True)
        for name in ("terms", "ontology"):
            shutil.copy(os.path.join(fake_cli.CONTRACT, name + ".json"), path)
        for name, data in files.items():
            with open(os.path.join(path, name.replace("_", "-") + ".json"), "w") as handle:
                json.dump(data, handle)
        self.use(path)

    def nine(self, problems):
        errors = [p for p in problems if p["severity"] == "error"]
        self.folder(check={"files": NINE, "ok": not errors, "errors": len(errors), "notes": len(problems) - len(errors),
                           "problems": problems})
        shutil.copy(os.path.join(fake_cli.CONTRACT, "terms-de.json"), os.path.join(self.tmp.name, "data", "terms.json"))

    def call(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = halverse.main(["check", *args])
        return code, out.getvalue(), err.getvalue()


class Report(Folder):
    def test_three_files_only_ok_notes_and_everything_untranslated(self):
        self.use(fake_cli.CONTRACT)
        code, out, _ = self.call()
        self.assertEqual(code, 0)
        self.assertIn("halverse check: ok, 0 errors, 13 notes", out)
        self.assertIn("notes (13):", out)
        self.assertNotIn("errors (", out)
        self.assertIn("  - glossary.de.md: the glossary has no German companion", out)  # the companion's path, no line
        self.assertIn("  German: 45, ", out)
        self.assertIn("of 45 terms", out)

    def test_nine_files_errors_make_exit_1_and_name_the_companion_file(self):
        self.nine([problem("orphan-entry", "error", "glossary", "de", 65, "the entry has a head line no entry has"),
                   problem("untranslated", "note", "glossary", None, 43, "the term logbook is untranslated in German"),
                   problem("orphan-row", "note", "ontology", "nl", 67, "the row stands for none")])
        code, out, _ = self.call()
        self.assertEqual(code, 1)
        self.assertIn("halverse check: 1 errors, 2 notes", out)
        self.assertIn("  - GLOSSARY.de.md:65: the entry has a head line no entry has (orphan-entry)", out)
        self.assertIn("  - GLOSSARY.md:43: the term logbook is untranslated in German (untranslated)", out)
        self.assertIn("  - HALVERSE-ONTOLOGY.nl.md:67: the row stands for none (orphan-row)", out)

    def test_untranslated_per_language(self):
        self.nine([])
        _, out, _ = self.call()
        lines = {line.split(":")[0].strip(): line for line in out.splitlines() if line.startswith("  ") and ":" in line}
        self.assertTrue(lines["German"].startswith("  German: 6, hail all ships, logbook, "))
        self.assertTrue(lines["Dutch"].startswith("  Dutch: 5, "))
        self.assertNotIn("logbook", lines["Dutch"])
        self.assertTrue(lines["Portuguese"].startswith("  Portuguese: 5, "))

    def test_a_language_with_nothing_untranslated_says_none(self):
        terms = {"terms": [{"term": "a", "languages": {lang: {"untranslated": False} for lang in ("de", "nl", "pt-PT")}}]}
        self.assertEqual(check.untranslated(terms), {"de": [], "nl": [], "pt-PT": []})
        self.assertIn("German: none", check.report({"ok": True, "problems": []}, terms))

    def test_a_part_is_cut_at_25_lines_and_the_rest_counted(self):
        self.nine([problem("untranslated", "note", "glossary", None, n + 1, "n%d" % n) for n in range(40)]
                  + [problem("duplicate-term", "error", "glossary", None, n + 1, "e%d" % n) for n in range(30)])
        _, out, _ = self.call()
        self.assertIn("errors (30):", out)
        self.assertIn("notes (40):", out)
        self.assertEqual(sum(line.startswith("  - ") for line in out.splitlines()), 50)
        self.assertEqual(out.count("  ... and 5 more"), 1)
        self.assertEqual(out.count("  ... and 15 more"), 1)

    def test_the_names_of_untranslated_terms_are_cut_at_25(self):
        terms = {"terms": [{"term": "t%d" % n, "languages": {"de": {"untranslated": True}}} for n in range(30)]}
        report = check.report({"ok": True, "problems": []}, terms)
        self.assertIn("German: 30, t0,", report)
        self.assertIn("t24 and 5 more", report)
        self.assertNotIn("t25", report)

    def test_json_is_the_clis_data_with_the_untranslated_terms(self):
        self.nine([problem("orphan-entry", "error", "glossary", "de", 65)])
        code, out, _ = self.call("--json")
        data = json.loads(out)
        self.assertEqual(code, 1)
        self.assertEqual(data["errors"], 1)
        self.assertEqual(len(data["untranslated"]["de"]), 6)
        self.assertEqual(self.args(), ["check --json", "terms --json"])


class Failures(Folder):
    def test_without_the_program_exit_2_and_the_install(self):
        os.remove(self.path)
        code, _, err = self.call()
        self.assertEqual(code, 2)
        self.assertIn("cargo install --path apps/hal2-cli-halverse", err)

    def test_a_file_the_cli_cannot_read_exit_2_naming_it(self):
        self.script("#!%s\nimport sys\nprint(%r)\nsys.exit(2)\n" % (sys.executable, json.dumps(
            {"error": {"code": "unreadable", "message": "x", "detail": {"file": "dictation", "path": "/x/DICTATION.md"}}})))
        code, _, err = self.call()
        self.assertEqual(code, 2)
        self.assertIn("/x/DICTATION.md", err)

    def test_the_script_runs_as_a_program_and_prints_the_report(self):
        result = subprocess.run([sys.executable, os.path.join(fake_cli.HERE, "halverse.py"), "check"], capture_output=True,
                                text=True, cwd=self.tmp.name)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("halverse check: ok, 0 errors, 13 notes", result.stdout)


if __name__ == "__main__":
    unittest.main()
