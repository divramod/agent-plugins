"""Hal2 plan 0294 step 8: the yard job's functions (yard.py, yard_rules.py) over temporary repositories: a bare
origin, the yard (its clone on `main`), the tollman's field and a foreman's field 07 (worktrees). Never a real
checkout. Here: sort and settle; survey and carry are test_yard_carry.py's, the rounds with a train
test_yard_train.py's."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path: git_seed)
import git_seed
import yard
import yard_rules

import sys
sys.path.insert(0, next(str(_p / "scripts") for _p in Path(__file__).resolve().parents if (_p / ".claude-plugin").is_dir()))
from skillpath import repo_root, sibling  # noqa: E402  (the skills unit's scripts/, plan 0360 D20)
RECORD = """# Repo root is a curated allowlist

## Decision

Only these git-tracked top-level entries are allowed:

- `.adr/`, `.gitignore`, `.hal/` (tool config only: `cleanup` (plan 0216), `ALIAS`; runtime
  state is ignored)
- `README.md`, `CLAUDE.md` (symlink to `AGENTS.md`) and `docs/`: guides, also `not-this/`
- `code/<language or platform>/{apps,libs,scripts}/<name>`: all source code

## Consequences

- `scratch/` is not in the list.
"""
BARN = {yard_rules.RECORD: RECORD, ".gitignore": "ignored.txt\n", ".gitattributes": "* text=auto\n", "docs/a.md": "a\n",
        "docs/b.md": "b\n", "docs/c.md": "c\n", "docs/secrets.md": "about secrets\n", "code/x/build/gen.ts": "x\n"}
SECRET, JUNK = "secret-shaped", "junk (build output, an editor's or the system's file)"


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class Yard(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.yard = self.tmp / "hal2"
        self.field, self.seven = self.tmp / "fields/tollman-hal2", self.tmp / "fields/07"
        git_seed.guard(self)
        git_seed.grow(self.tmp, tuple(c for c in type(self).__mro__ if "grow" in vars(c)), self.grow)

    def grow(self):
        """The yard, its origin and the two fields, grown once per process (git_seed)."""
        origin = self.tmp / "hal2.git"
        git(self.tmp, "init", "-q", "--bare", "-b", "main", str(origin))
        git(self.tmp, "clone", "-q", str(origin), str(self.yard))
        for key, value in (("user.email", "t@t"), ("user.name", "t")):
            git(self.yard, "config", key, value)
        self.write(BARN)
        git(self.yard, "add", ".")
        git(self.yard, "commit", "-qm", "init")
        git(self.yard, "push", "-q", "origin", "main")
        for path in (self.field, self.seven):
            git(self.yard, "worktree", "add", "-q", "-b", path.name, str(path))

    def write(self, files, cwd=None):
        for name, text in files.items():
            path = (cwd or self.yard) / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)

    def crop(self, files):
        """Field 07 commits `files`: its head."""
        self.write(files, self.seven)
        git(self.seven, "add", ".")
        git(self.seven, "commit", "-qm", "crop")
        return git(self.seven, "rev-parse", "HEAD")

    def look(self, **kw):
        return yard.look(str(self.yard), git(self.field, "rev-parse", "HEAD"), "origin/main", **kw)

    def sorted(self, **kw):
        seen = self.look(**kw)
        self.assertIsNone(seen["skipped"])
        return [e["path"] for e in seen["placed"]], {x["path"]: x["why"] for x in seen["left"]}

    def carry(self, **kw):
        return yard.carry(str(self.yard), str(self.field), self.look(**kw)["placed"])

    def land(self):
        """The field's head is the barn's: the train landed."""
        git(self.field, "push", "-q", "origin", "HEAD:main")
        git(self.field, "fetch", "-q", "origin", "main")

    def state(self, cwd=None):
        cwd = cwd or self.yard
        return git(cwd, "status", "--porcelain", "-uall"), git(cwd, "rev-parse", "HEAD")


class Sorting(Yard):
    def test_a_tracked_change_and_an_untracked_file_in_an_allowed_root_are_placed(self):
        self.write({"docs/a.md": "changed\n", "docs/new.md": "new\n", ".hal/cleanup": "target\n",
                    "docs/secrets.md": "the barn has this name already\n", "code/x/build/more.ts": "a source\n",
                    ".gitattributes": "* text\n"})
        os.symlink("a.md", self.yard / "docs/link")
        (self.yard / "docs/c.md").unlink()
        before = self.state()
        placed, left = self.sorted()
        self.assertEqual((placed, left), ([".gitattributes", ".hal/cleanup", "code/x/build/more.ts", "docs/a.md",
                                           "docs/c.md", "docs/link", "docs/new.md", "docs/secrets.md"], {}))
        seen = {e["path"]: (e["deleted"], e["known"]) for e in self.look()["placed"]}
        self.assertEqual((seen["docs/c.md"], seen["docs/new.md"], seen["docs/a.md"]),
                         ((True, True), (False, False), (False, True)))
        self.assertEqual(self.state(), before, "looking changes nothing")

    def test_secret_shaped_files_stay(self):
        names = [".env.local", "docs/server.pem", "docs/API_SEC", "docs/id_rsa", "docs/deploy.key", "docs/cert.p12",
                 "docs/my-token.txt", "docs/Credentials.json", "docs/top-secret.md"]
        self.write({name: "x\n" for name in names} | {".env": "A=1\n", "docs/fine.md": "x\n"})
        git(self.yard, "add", "-f", "docs/API_SEC")  # staged or not: the name decides
        placed, left = self.sorted()
        self.assertEqual((placed, left), (["docs/fine.md"], {name: SECRET for name in [*names, ".env"]}))
        self.assertTrue(yard_rules.secret("docs/a.pem", known=True), "a pattern counts for a tracked file too")
        self.assertFalse(yard_rules.secret("docs/secrets.md", known=True))

    def test_junk_is_left_named_once_and_never_gitignored(self):
        self.write({".DS_Store": "x", "docs/a.md.swp": "x", "docs/b.md~": "x", "node_modules/p/index.js": "x",
                    "node_modules/q/index.js": "x", "docs/build/out.js": "x", "code/x/build/more.ts": "a source\n"})
        before = self.state()
        placed, left = self.sorted()
        self.assertEqual(placed, ["code/x/build/more.ts"], "the barn tracks that build folder: sources")
        self.assertEqual(left, {name: JUNK for name in (".DS_Store", "docs/a.md.swp", "docs/b.md~", "node_modules/",
                                                        "docs/build/")})
        self.assertEqual((self.state(), (self.yard / ".gitignore").read_text()), (before, "ignored.txt\n"))

    def test_a_root_outside_the_allowlist_stays(self):
        self.write({"scratch/notes.md": "x", "scratch/deep/more.md": "x", "notes.txt": "x", "docs/fine.md": "x"})
        why = "`{}` is no entry of the root allowlist (.adr/repo-root-allowlist.md)"
        self.assertEqual(self.sorted(), (["docs/fine.md"], {"scratch/": why.format("scratch"),
                                                            "notes.txt": why.format("notes.txt")}))
        self.assertEqual(yard_rules.allowlist(RECORD),
                         {".adr", ".gitignore", ".hal", "README.md", "CLAUDE.md", "docs", "code"})
        self.write({yard_rules.RECORD: RECORD.replace("- `.adr/`,", "- `.adr/`, `scratch/`,")})
        self.assertEqual(self.sorted()[0], [yard_rules.RECORD, "docs/fine.md", "scratch/deep/more.md",
                                            "scratch/notes.md"], "the amendment rides with the entry it allows")

    def test_hal2_s_own_record_is_read_as_it_is_held(self):
        record = repo_root(__file__) / yard_rules.RECORD
        if not record.is_file():
            self.skipTest("no .adr/repo-root-allowlist.md above this unit (the published plugin)")
        roots = yard_rules.allowlist(record.read_text())
        self.assertLessEqual({".adr", ".gitignore", ".hal", ".github", "AGENTS.md", "CLAUDE.md", "README.md",
                              "GLOSSARY.md", ".taplo.toml", ".claude", "assets", "code", "INTENT.md", "HANDOFF.md",
                              "roles", "plans", "research", "shotfiles", "docs", "utils", "workflows", "projects",
                              ".secrets", ".gitsecret"}, roots)
        self.assertFalse({r for r in roots if " " in r or "<" in r or r in ("cleanup", "CURRENT_PLAN")})

    def test_the_file_s_own_reasons(self):
        self.write({"docs/b.md": "staged\n", "docs/big.bin": "12345", "docs/ignored.txt": "x", "docs/fine.md": "x",
                    "docs/line\nbreak.md": "x"})
        git(self.yard, "add", "docs/b.md")
        self.write({"docs/b.md": "and changed again\n"})
        nested = self.yard / "docs/nested"
        nested.mkdir()
        git(nested, "init", "-q")
        (self.tmp / "outside.txt").write_text("x")
        os.symlink(self.tmp / "outside.txt", self.yard / "docs/out")
        with mock.patch.object(yard, "MAX", 4):
            placed, left = self.sorted()
        self.assertEqual(placed, ["docs/fine.md"])
        self.assertEqual(left, {"docs/b.md": "staged and changed again in the working tree",
                                "docs/big.bin": "larger than 5 MB (0.0 MB)", "docs/line\nbreak.md": "a line break in its name",
                                "docs/nested/": "a submodule or a nested repository",
                                "docs/out": "a symlink leaving the repository"})
        os.mkfifo(self.yard / "docs/pipe")  # what status does not list here: sort says why all the same
        entries = [{"xy": "??", "path": "docs/ignored.txt"}, {"xy": "UU", "path": "docs/a.md"},
                   {"xy": "??", "path": "docs/pipe"}]
        self.assertEqual(yard.sort(str(self.yard), entries, "HEAD")[1],
                         [{"path": "docs/a.md", "why": "a merge conflict"}, {"path": "docs/ignored.txt", "why": "gitignored"},
                          {"path": "docs/pipe", "why": "no regular file"}])

    def test_a_deletion_another_field_changes_and_a_file_a_car_changes(self):
        head = self.crop({"docs/a.md": "seven's\n", "docs/b.md": "seven's\n"})
        self.write({"docs/a.md": "the yard's\n"})
        (self.yard / "docs/b.md").unlink()
        (self.yard / "docs/c.md").unlink()
        self.assertEqual(self.sorted(), (["docs/a.md", "docs/c.md"],
                                         {"docs/b.md": "deleted here, but field 07's crop changes it"}))
        self.assertEqual(self.sorted(cars=[{"field": "07", "head": head}]),
                         (["docs/c.md"], {"docs/a.md": "field 07's crop changes it too",
                                          "docs/b.md": "deleted here, but field 07's crop changes it"}))

    def test_a_file_the_barn_changed_since_the_yard_s_head(self):
        self.write({"docs/a.md": "the barn's\n", "docs/new.md": "the barn's\n"}, self.field)
        git(self.field, "add", ".")
        git(self.field, "commit", "-qm", "landed meanwhile")
        self.land()
        self.write({"docs/a.md": "the yard's\n", "docs/new.md": "the yard's\n", "docs/b.md": "the yard's\n"})
        self.assertEqual(self.sorted(), (["docs/b.md"], {
            "docs/a.md": "the barn changed it since the yard's head: pull the yard",
            "docs/new.md": "the barn has a file of that name"}))
        own = {p: [git(self.field, "rev-parse", f"HEAD:{p}")] for p in ("docs/a.md", "docs/new.md")}
        self.assertEqual(self.sorted(past={"carried": own}), (["docs/a.md", "docs/b.md", "docs/new.md"], {}),
                         "what the yard itself brought in is the yard's to change again")


class Settling(Yard):
    def settle(self, carried):
        return yard.settle(str(self.yard), carried, "origin/main")

    def test_identical_files_are_dropped_and_the_yard_is_fast_forwarded(self):
        self.write({"docs/a.md": "changed\n", "docs/new.md": "new\n", "docs/staged.md": "staged\n", ".env": "A=1\n"})
        git(self.yard, "add", "docs/staged.md")
        git(self.yard, "rm", "-q", "docs/b.md")
        (self.yard / "docs/c.md").unlink()
        carried = self.carry()[1]
        self.land()
        self.assertEqual(self.settle(carried), {"dropped": ["docs/a.md", "docs/b.md", "docs/c.md", "docs/new.md",
                                                            "docs/staged.md"], "kept": [], "pulled": True, "why": ""})
        self.assertEqual(self.state(), ("?? .env", git(self.yard, "rev-parse", "origin/main")), "only what was left")
        self.assertEqual(((self.yard / "docs/a.md").read_text(), (self.yard / "docs/new.md").read_text(),
                          (self.yard / "docs/b.md").exists(), (self.yard / "docs/c.md").exists()),
                         ("changed\n", "new\n", False, False))

    def test_a_file_changed_meanwhile_stays_and_the_yard_is_not_forced(self):
        self.write({"docs/a.md": "changed\n", "docs/new.md": "new\n"})
        (self.yard / "docs/c.md").unlink()
        commit, carried, _ = self.carry()
        self.land()
        self.write({"docs/a.md": "changed meanwhile\n"})
        before = self.state()
        done = self.settle(carried)
        back = "put back: the yard was not fast-forwarded"
        self.assertEqual((done["dropped"], done["pulled"], done["kept"]),
                         ([], False, [{"path": "docs/a.md", "why": "changed meanwhile"},
                                      {"path": "docs/c.md", "why": back}, {"path": "docs/new.md", "why": back}]))
        self.assertIn("docs/a.md", done["why"], "git's own words: the file is in the way of the fast-forward")
        self.assertEqual((self.state(), (self.yard / "docs/new.md").read_text()), (before, "new\n"),
                         "the yard as it was: nothing forced, nothing gone")
        past = {"carried": {c["path"]: [c["hash"]] for c in carried}}  # the next train heals it: the files are the yard's
        self.assertEqual(self.sorted(past=past), (["docs/a.md", "docs/c.md", "docs/new.md"], {}))
        commit, again, _ = yard.carry(str(self.yard), str(self.field), self.look(past=past)["placed"])
        self.assertEqual(git(self.field, "show", "--name-status", "--format=", commit).split(), ["M", "docs/a.md"])
        self.assertEqual([c["path"] for c in again], ["docs/a.md", "docs/c.md", "docs/new.md"], "the same ones too")
        self.land()
        self.assertEqual(self.settle(again), {"dropped": ["docs/a.md", "docs/c.md", "docs/new.md"], "kept": [],
                                              "pulled": True, "why": ""})
        self.assertEqual((self.state(), (self.yard / "docs/a.md").read_text()),
                         (("", git(self.yard, "rev-parse", "origin/main")), "changed meanwhile\n"))

    def test_nothing_is_dropped_that_is_not_in_the_barn_or_staged_differently_or_in_a_skipped_yard(self):
        self.write({"docs/a.md": "changed\n", "docs/new.md": "new\n"})
        carried = self.carry()[1]
        before = self.state()
        done = self.settle(carried)  # a red train never comes here; if it did: the barn lacks the content
        self.assertEqual((done["dropped"], {k["why"] for k in done["kept"]}, self.state()),
                         ([], {"the barn does not hold what was carried"}, before))
        self.land()
        git(self.yard, "checkout", "-q", "-b", "side")
        done = self.settle(carried)
        self.assertEqual((done["dropped"], done["pulled"], done["why"], self.state()[0]),
                         ([], False, "the yard is on side, not on main", before[0]))
        git(self.yard, "checkout", "-q", "main")
        self.write({"docs/a.md": "another\n"})
        git(self.yard, "add", "docs/a.md")
        self.write({"docs/a.md": "changed\n"})
        done = self.settle(carried)
        self.assertEqual((done["dropped"], done["kept"]),
                         ([], [{"path": "docs/a.md", "why": "staged differently meanwhile"},
                               {"path": "docs/new.md", "why": "put back: the yard was not fast-forwarded"}]))
        self.assertEqual((git(self.yard, "show", ":docs/a.md"), (self.yard / "docs/new.md").read_text()),
                         ("another", "new\n"))


if __name__ == "__main__":
    unittest.main()
