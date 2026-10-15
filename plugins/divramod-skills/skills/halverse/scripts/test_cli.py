import json
import os
import unittest
from unittest import mock

import cli
import fake_cli
from fake_cli import FakeCli

EXPECTED = os.path.join(fake_cli.HERE, *[os.pardir] * 6, "rust", "apps", "hal2-cli-halverse", "tests", "fixtures", "expected")


def error(code, message, detail=None):
    return json.dumps({"error": {"code": code, "message": message, "detail": detail or {}}})


class Found(FakeCli):
    def test_the_override_is_run_with_json_added(self):
        data = cli.call(["terms"])
        self.assertEqual(self.args(), ["terms --json"])
        self.assertEqual(len(data["terms"]), 14)

    def test_lang_goes_on(self):
        self.use(fake_cli.CONTRACT)
        self.assertEqual(cli.call(["terms", "--lang", "de"])["lang"], "de")
        self.assertEqual(self.args(), ["terms --lang de --json"])

    def test_without_the_override_the_program_is_found_on_the_path(self):
        os.environ.pop(cli.CLI_ENV)
        path = os.environ.get("PATH")
        os.environ["PATH"] = self.tmp.name
        try:
            self.assertEqual(cli.find_cli(), self.path)
            self.assertIn("files", cli.call(["ontology"]))
        finally:
            os.environ["PATH"] = path

    def test_the_environment_goes_on_to_the_cli(self):
        self.script("#!%s\nimport os\nprint('{\"glossary\": \"%%s\"}' %% os.environ.get('HALVERSE_GLOSSARY'))\n"
                    % fake_cli.sys.executable)
        with mock.patch.dict(os.environ, {"HALVERSE_GLOSSARY": "/somewhere/G.md"}):
            self.assertEqual(cli.call(["terms"])["glossary"], "/somewhere/G.md")


class Document(FakeCli):
    """A term's document goes to the CLI on its stdin (plan 0276 step 11); a call without one gets no stdin at all."""

    def echo(self):
        self.script("#!%s\nimport json, sys\nprint(json.dumps({\"stdin\": sys.stdin.buffer.read().decode(\"utf-8\")}))\n"
                    % fake_cli.sys.executable)

    def test_the_document_reaches_the_cli_as_utf8(self):
        self.echo()
        document = '{"terms": ["amarração"]}'
        self.assertEqual(cli.call(["term", "add", "--from", "-"], stdin=document)["stdin"], document)

    def test_without_a_document_the_cli_reads_nothing_of_the_callers(self):
        self.echo()
        with open(os.devnull) as nothing, mock.patch("sys.stdin", nothing):
            self.assertEqual(cli.call(["terms"])["stdin"], "")


class Missing(FakeCli):
    def test_no_program_is_exit_2_and_names_the_install(self):
        os.remove(self.path)
        with self.assertRaises(cli.CliError) as caught:
            cli.call(["terms"])
        self.assertEqual(caught.exception.code, 2)
        self.assertIn("cargo install --path apps/hal2-cli-halverse", caught.exception.text)

    def test_a_file_that_is_no_program_counts_as_missing(self):
        os.chmod(self.path, 0o644)
        self.assertIsNone(cli.find_cli())

    def test_not_on_the_path_either(self):
        os.environ.pop(cli.CLI_ENV)
        with mock.patch.dict(os.environ, {"PATH": os.path.join(self.tmp.name, "empty")}):
            self.assertIsNone(cli.find_cli())


class Failures(FakeCli):
    def fail(self, body, code):
        self.script("#!%s\nimport sys\nprint(%r)\nsys.exit(%d)\n" % (fake_cli.sys.executable, body, code))

    def test_a_timeout_is_named(self):
        self.script("#!%s\nimport time\ntime.sleep(10)\n" % fake_cli.sys.executable)
        with mock.patch.object(cli, "TIMEOUT", 0.5), self.assertRaises(cli.CliError) as caught:
            cli.call(["terms"])
        self.assertIn("no answer within", caught.exception.text)
        self.assertEqual(caught.exception.code, 1)

    def test_the_clis_exit_2_is_relayed_and_an_unreadable_file_is_named(self):
        self.fail(error("unreadable", "cannot read", {"file": "dictation", "path": "/x/DICTATION.md"}), 2)
        with self.assertRaises(cli.CliError) as caught:
            cli.call(["terms"])
        self.assertEqual(caught.exception.code, 2)
        self.assertIn("dictation file /x/DICTATION.md cannot be read", caught.exception.text)

    def test_the_clis_error_object_and_exit_code_go_on_to_the_caller(self):
        detail = {"term": "berth", "line": 12}
        self.fail(error("term-exists", "heads an entry already", detail), 3)
        with self.assertRaises(cli.CliError) as caught:
            cli.call(["term", "add", "--from", "-"], stdin="{}")
        self.assertEqual((caught.exception.code, caught.exception.error["code"]), (3, "term-exists"))
        self.assertEqual(caught.exception.error["detail"], detail)
        os.remove(self.path)
        with self.assertRaises(cli.CliError) as caught:
            cli.call(["terms"])
        self.assertIsNone(caught.exception.error)

    def test_another_error_carries_its_code_and_message(self):
        self.fail(error("usage", "unknown flag"), 2)
        with self.assertRaises(cli.CliError) as caught:
            cli.call(["terms"])
        self.assertIn('"usage": unknown flag', caught.exception.text)

    def test_exit_1_is_an_error_unless_the_caller_allows_it(self):
        self.use(os.path.join(self.tmp.name, "none"))
        self.fail(json.dumps({"ok": False, "problems": []}), 1)
        with self.assertRaises(cli.CliError) as caught:
            cli.call(["check"])
        self.assertEqual(caught.exception.code, 1)
        self.assertFalse(cli.call(["check"], ok=(0, 1))["ok"])

    def test_an_answer_that_is_no_json_is_not_parsed(self):
        self.fail("not json at all", 0)
        with self.assertRaises(cli.CliError) as caught:
            cli.call(["terms"])
        self.assertIn("not json at all", caught.exception.text)


class Contract(unittest.TestCase):
    """The copies in fixtures/cli/contract are the CLI's expected files; where both are in the checkout they are the same."""

    def test_the_copies_equal_the_clis_expected_files(self):
        if not os.path.isdir(EXPECTED):
            self.skipTest("the CLI's expected files are not in this checkout")
        for name in ("terms.json", "terms-de.json", "ontology.json", "check.json"):
            with open(os.path.join(EXPECTED, name), "rb") as theirs, open(os.path.join(fake_cli.CONTRACT, name), "rb") as ours:
                self.assertEqual(ours.read(), theirs.read(), name)

    def test_the_copies_are_what_the_skill_reads(self):
        for name, key in (("terms", "terms"), ("terms-de", "terms"), ("ontology", "sections"), ("check", "problems")):
            with open(os.path.join(fake_cli.CONTRACT, name + ".json")) as handle:
                self.assertTrue(json.load(handle)[key], name)


if __name__ == "__main__":
    unittest.main()
