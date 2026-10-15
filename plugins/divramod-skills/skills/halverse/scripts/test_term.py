"""The writing calls of the halverse skill on a fake CLI (plan 0276 step 11): each call's arguments and stdin, the
proposal number, and that no writing call is made without it. The real CLI, the user's files and VoiceInk's store are
never touched: the answers are the recorded ones of fixtures/cli/term and term-refused."""
import io
import json
import os
import unittest
from unittest import mock

import fake_cli
import term
from fake_cli import DOCUMENTS, REFUSED, TERM, InFolder, fixture

LASHING = os.path.join(DOCUMENTS, "lashing.json")
CHANGED = os.path.join(DOCUMENTS, "lashing-changed.json")


def text_of(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def number(kind, path, answer):
    """The proposal number of the document at `path` and the recorded dry run `answer`."""
    return term.number_of(term.document_request(kind, path), fixture(TERM, answer)["files"])


class Term(InFolder):
    def setUp(self):
        super().setUp()
        self.use(TERM)


class Check(Term):
    def test_the_words_and_the_repository_glossary_go_to_term_check(self):
        code, out, _ = self.main("add", "check", "lashing", "berth", "--repo-glossary", "quay.md")
        self.assertEqual(code, 0)
        self.assertEqual(self.args(), ["term check lashing berth --repo-glossary quay.md --json"])
        self.assertIn("  lashing: free", out)
        self.assertIn("  berth: taken, 2 clashes", out)
        self.assertIn('"berth" (English) heads a glossary entry: GLOSSARY.md:76', out)
        self.assertIn('"berth" is a word of DICTATION.md: DICTATION.md:23', out)

    def test_change_checks_the_same_way_and_json_is_the_clis_data(self):
        code, out, _ = self.main("change", "check", "berth", "--repo-glossary", "quay.md", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(self.args(), ["term check berth --repo-glossary quay.md --json"])
        self.assertEqual(json.loads(out)["fit"][1]["word"], "berth")

    def test_the_current_repositorys_glossary_is_given_by_default(self):
        root = os.path.realpath(self.tmp.name)
        os.makedirs(os.path.join(root, "repo", ".git"))
        os.makedirs(os.path.join(root, "repo", "code", "deep"))
        self.assertIsNone(term.repo_glossary(os.path.join(root, "repo", "code")))  # a repository without one
        glossary = os.path.join(root, "repo", "GLOSSARY.md")
        with open(glossary, "w") as handle:
            handle.write("# Quay\n")
        os.chdir(os.path.join(root, "repo", "code", "deep"))
        self.main("add", "check", "plank")
        self.assertEqual(self.args(), ["term check plank --repo-glossary %s --json" % glossary])

    def test_outside_a_repository_none_is_given(self):
        self.main("add", "check", "plank")
        self.assertEqual(self.args(), ["term check plank --json"])

    def test_a_worktrees_git_file_marks_a_repository_too(self):
        root = os.path.realpath(self.tmp.name)
        for name in (".git", "GLOSSARY.md"):
            with open(os.path.join(root, name), "w") as handle:
                handle.write("gitdir: elsewhere\n")
        self.assertEqual(term.repo_glossary(root), os.path.join(root, "GLOSSARY.md"))

    def test_a_file_the_cli_cannot_read_is_exit_2_and_named(self):
        self.answer({"error": {"code": "unreadable", "message": "cannot read quay.md", "detail": {"path": "quay.md"}}}, 2)
        code, _, err = self.main("add", "check", "plank", "--repo-glossary", "quay.md")
        self.assertEqual(code, 2)
        self.assertIn("at quay.md", err)
        self.assertIn("CLI message: cannot read quay.md", err)


class Show(Term):
    def test_a_term_is_found_by_its_synonym_and_printed_as_data(self):
        self.use(fake_cli.CONTRACT)
        code, out, _ = self.main("change", "show", "Slip")
        self.assertEqual((code, self.args()), (0, ["terms --json"]))
        data = json.loads(out)
        self.assertEqual((data["term"], sorted(data["languages"])), ("berth", ["de", "en", "nl", "pt-PT"]))

    def test_an_unknown_term_is_exit_1(self):
        self.use(fake_cli.CONTRACT)
        code, _, err = self.main("retire", "show", "windlass")
        self.assertEqual(code, 1)
        self.assertIn('no term "windlass"', err)


class Propose(Term):
    def test_an_add_is_a_dry_run_with_the_document_on_stdin(self):
        code, out, _ = self.main("add", "propose", "--from", LASHING)
        self.assertEqual(code, 0)
        self.assertEqual(self.args(), ["term add --from - --dry-run --json"])
        self.assertEqual(self.documents(), [text_of(LASHING)])
        want = number("add", LASHING, "term-add-dry")
        self.assertIn("proposal number: %s\n" % want, out)
        self.assertIn("halverse.py add write --from %s --confirmed %s" % (LASHING, want), out)

    def test_the_document_may_come_on_stdin(self):
        with mock.patch("sys.stdin", io.StringIO(text_of(CHANGED))):
            code, out, _ = self.main("change", "propose", "--from", "-")
        self.assertEqual((code, self.args()), (0, ["term change --from - --dry-run --json"]))
        self.assertEqual(self.documents(), [text_of(CHANGED)])
        self.assertIn("halverse.py change write --from - --confirmed", out)

    def test_a_retire_names_the_term_and_its_successor(self):
        code, out, _ = self.main("retire", "propose", "shipmaster", "--by", "pilot")
        self.assertEqual((code, self.args()), (0, ["term retire shipmaster --by pilot --dry-run --json"]))
        self.assertEqual(self.documents(), [])
        self.assertIn("halverse.py retire write shipmaster --by pilot --confirmed ", out)
        self.main("retire", "propose", "run the blockade")
        self.assertEqual(self.args()[1], "term retire run the blockade --dry-run --json")

    def test_a_phrase_is_one_argument_of_the_cli_and_quoted_in_the_writing_call(self):
        self.script("#!%s\nimport json, sys\nopen(%r, 'w').write(json.dumps(sys.argv[1:]))\nprint(%r)\n"
                    % (fake_cli.sys.executable, self.log, json.dumps(fixture(TERM, "term-retire-dry"))))
        _, out, _ = self.main("retire", "propose", "run the blockade", "--by", "lock gate")
        with open(self.log) as handle:
            self.assertEqual(json.load(handle), ["term", "retire", "run the blockade", "--by", "lock gate", "--dry-run", "--json"])
        self.assertIn("halverse.py retire write 'run the blockade' --by 'lock gate' --confirmed ", out)

    def test_the_number_is_the_requests_and_the_lines(self):
        files = fixture(TERM, "term-add-dry")["files"]
        base = term.number_of(term.document_request("add", LASHING), files)
        self.assertNotEqual(base, term.number_of(term.document_request("change", LASHING), files))
        self.assertNotEqual(base, term.number_of(term.document_request("add", CHANGED), files))
        self.assertNotEqual(base, term.number_of(term.document_request("add", LASHING), files[:8]))
        moved = json.loads(json.dumps(files))
        for change in moved[0]["changes"]:
            change["line"], change["last"] = change["line"] + 7, change["last"] + 7
        self.assertEqual(base, term.number_of(term.document_request("add", LASHING), moved))
        self.assertNotEqual(term.number_of(term.retire_request("a", "b"), []), term.number_of(term.retire_request("a", None), []))

    def test_a_document_that_cannot_be_read_makes_no_call(self):
        code, _, err = self.main("add", "propose", "--from", os.path.join(self.tmp.name, "none.json"))
        self.assertEqual((code, self.args()), (2, []))
        self.assertIn("cannot be read", err)

    def test_a_refused_dry_run_is_exit_3_with_the_lines_that_refuse(self):
        self.use(REFUSED)
        code, out, err = self.main("add", "propose", "--from", LASHING)
        self.assertEqual((code, out), (3, ""))
        self.assertIn("halverse term: refused (exit 3)", err)
        self.assertIn("the glossary, line 166: the short form dock is itself a term", err)
        self.assertIn("      + | dock | windlass |", err)
        self.assertNotIn("proposal number", err)

    def test_json_adds_the_number_to_the_clis_data(self):
        _, out, _ = self.main("add", "propose", "--from", LASHING, "--json")
        data = json.loads(out)
        self.assertEqual((data["dry_run"], data["proposal"]), (True, number("add", LASHING, "term-add-dry")))


class Write(Term):
    """No writing call without the number the skill passes after the user's yes."""

    def test_without_the_confirmation_no_call_is_made(self):
        for argv in (("add", "write", "--from", LASHING), ("change", "write", "--from", CHANGED),
                     ("retire", "write", "shipmaster", "--by", "pilot"), ("retire", "write", "shipmaster")):
            code, out, err = self.main(*argv)
            self.assertEqual((code, out), (term.UNCONFIRMED, ""), argv)
            self.assertIn("No writing call was made", err)
        self.assertEqual((self.args(), self.documents()), ([], []))

    def test_the_number_of_another_request_makes_no_call(self):
        other = number("add", LASHING, "term-add-dry")
        for argv in (("add", "write", "--from", CHANGED), ("change", "write", "--from", LASHING),
                     ("retire", "write", "shipmaster", "--by", "pilot")):
            code, _, err = self.main(*argv, "--confirmed", other)
            self.assertEqual(code, term.UNCONFIRMED, argv)
            self.assertIn("is not this request's", err)
        code, _, _ = self.main("add", "write", "--from", LASHING, "--confirmed", "yes")
        self.assertEqual(code, term.UNCONFIRMED)
        self.assertEqual(self.args(), [])

    def test_a_document_changed_after_the_proposal_makes_no_call(self):
        path = os.path.join(self.tmp.name, "term.json")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text_of(LASHING))
        confirmed = number("add", path, "term-add-dry")
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("\n")
        code, _, _ = self.main("add", "write", "--from", path, "--confirmed", confirmed)
        self.assertEqual((code, self.args()), (term.UNCONFIRMED, []))

    def test_with_the_number_one_call_writes_the_document(self):
        code, out, _ = self.main("add", "write", "--from", LASHING, "--confirmed", number("add", LASHING, "term-add-dry"))
        self.assertEqual(code, 0)
        self.assertEqual(self.args(), ["term add --from - --json"])
        self.assertEqual(self.documents(), [text_of(LASHING)])
        self.assertIn("halverse write: written, 9 files", out)
        self.assertNotIn("WARNING", out)

    def test_a_change_and_a_retire_write_the_same_way(self):
        code, _, _ = self.main("change", "write", "--from", CHANGED, "--confirmed", number("change", CHANGED, "term-change-dry"))
        retire = term.number_of(term.retire_request("shipmaster", "pilot"), fixture(TERM, "term-retire-dry")["files"])
        again, out, _ = self.main("retire", "write", "shipmaster", "--by", "pilot", "--confirmed", retire)
        self.assertEqual((code, again), (0, 0))
        self.assertEqual(self.args(), ["term change --from - --json", "term retire shipmaster --by pilot --json"])
        self.assertIn("note: VoiceInk keeps the word shipmaster", out)

    def test_lines_that_differ_from_the_proposal_are_said(self):
        answer = fixture(TERM, "term-add")
        answer["files"][0]["changes"][0]["lines"][2] = "A ship made fast somewhere else."
        self.answer(answer)
        confirmed = number("add", LASHING, "term-add-dry")
        code, out, _ = self.main("add", "write", "--from", LASHING, "--confirmed", confirmed)
        self.assertEqual(code, 0)
        self.assertIn("WARNING: these lines differ from the proposal the user confirmed", out)
        _, out, _ = self.main("add", "write", "--from", LASHING, "--confirmed", confirmed, "--json")
        self.assertTrue(json.loads(out)["differs_from_proposal"])

    def test_a_refused_write_is_the_clis_exit_code_and_advice(self):
        self.use(REFUSED)
        code, _, err = self.main("add", "write", "--from", LASHING, "--confirmed", number("add", LASHING, "term-add-dry"))
        self.assertEqual(code, 3)
        self.assertIn("halverse term: term-exists (exit 3)", err)
        self.assertIn("`/hv change <term>` changes it", err)
        self.assertIn('term "lashing"', err)
        self.assertIn("at line 70", err)


class Short(Term):
    def test_the_list_reads(self):
        code, out, _ = self.main("short")
        self.assertEqual((code, self.args()), (0, ["term short list --json"]))
        self.assertIn("halverse short forms: 3", out)
        self.assertIn("  bt  berth\n  lg  lock gate\n", out)
        self.assertIn("farms (a project folder's name):\n  fy  fishery", out)

    def test_a_short_form_is_written_at_once(self):
        code, out, _ = self.main("short", "set", "kn", "knot", "--spoken")
        self.assertEqual((code, self.args()), (0, ["term short set kn knot --spoken --json"]))
        self.assertIn("    + | kn | knot |", out)
        self.assertIn("    + | knot | kn | |", out)
        self.assertIn("  + knot <- kn", out)

    def test_a_farms_short_form_and_a_removal(self):
        self.main("short", "set", "h9", "harbour-nine", "--farm")
        code, out, _ = self.main("short", "rm", "kn")
        self.assertEqual(code, 0)
        self.assertEqual(self.args(), ["term short set h9 harbour-nine --farm --json", "term short rm kn --json"])
        self.assertIn("  remove line 163\n", out)

    def test_a_refusal_is_exit_3_with_the_problem(self):
        self.use(REFUSED)
        code, _, err = self.main("short", "set", "dock", "berth")
        self.assertEqual(code, 3)
        self.assertIn("the short form dock is itself a term (the glossary, line 87) (short-form-is-a-word)", err)
        code, _, err = self.main("short", "rm", "zz")
        self.assertEqual(code, 3)
        self.assertIn("`/hv short` lists them", err)

    def test_no_short_forms_yet(self):
        self.answer({"files": {}, "short_forms": [], "problems": []})
        self.assertIn("none yet", self.main("short")[1])


class Skill(unittest.TestCase):
    """SKILL.md holds the order the model follows: the check and the fit, the document, the dry run, the one
    question, the one writing call, the report; and every command it names is one this script takes."""

    def setUp(self):
        with open(os.path.join(fake_cli.HERE, os.pardir, "SKILL.md"), encoding="utf-8") as handle:
            self.text = handle.read()

    def test_the_six_steps_stand_in_their_order(self):
        marks = ["**Step 1: the check, then the fit said in words.**", "halverse.py add check", "**Step 2: the document.**",
                 "**Step 3: the dry run.**", "halverse.py add propose --from <file>", "**Step 4: the one question.**",
                 "a) (Recommended) Write as shown", "b) Change something", "c) Do not write",
                 "**Step 5: one writing call, only on the user's yes.**",
                 "halverse.py add write --from <file> --confirmed <proposal number>", "**Step 6: the report.**"]
        places = [self.text.find(mark) for mark in marks]
        self.assertEqual([mark for mark, place in zip(marks, places) if place < 0], [])
        self.assertEqual(places, sorted(places))

    def test_the_wordings_sources_and_the_question_form_are_named(self):
        names = ("_de_:", "farm-words-nl-pt.md", "docs/i18n/glossary.toml", "~/AGENTS.md", "never in a question dialog",
                 "learn the\nterm after a clear")
        self.assertEqual([name for name in names if name not in self.text], [])

    def test_every_command_it_names_is_one_the_script_takes(self):
        import halverse_args
        parser = halverse_args.parser("x")
        named = ("halverse.py add check <word>...", "halverse.py change show <term>", "halverse.py add propose --from <file>",
                 "halverse.py add write --from <file> --confirmed <proposal number>", "halverse.py retire show <term>",
                 "halverse.py retire propose <term> [--by <successor>]", "halverse.py short set <short> <word>",
                 "halverse.py short rm <short>", "halverse.py short` lists", "short set <short> <word> --spoken",
                 "short set <short> <folder name> --farm", "`voiceink prompt`", "`voiceink export [--out <file>]`")
        self.assertEqual([name for name in named if name not in self.text], [])
        for line in ("add check a b", "change show a", "change check a", "add propose --from f", "add write --from f --confirmed n",
                     "retire show a", "retire propose a --by b", "retire write a --by b --confirmed n", "short",
                     "short set a b", "short set a b --farm", "short set a b --spoken", "short rm a", "voiceink prompt",
                     "voiceink export --out f"):
            self.assertEqual(parser.parse_args(line.split()).command, line.split()[0])


if __name__ == "__main__":
    unittest.main()
