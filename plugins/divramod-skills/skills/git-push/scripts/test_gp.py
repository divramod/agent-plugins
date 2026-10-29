"""Tests of gp.py and gp_scan.py in temporary git repositories (a bare remote for the push)."""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gp  # noqa: E402
import gp_scan  # noqa: E402


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


def write(root, rel, text="x\n"):
    path = Path(root, rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def new_repo(base, name="repo", branch="main"):
    root = Path(base, name)
    root.mkdir()
    git(root, "init", "-q", "-b", branch)
    git(root, "config", "user.name", "T")
    git(root, "config", "user.email", "t@example.com")
    write(root, "README.md", "hi\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "chore: start")
    return root


def run_gp(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = gp.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = os.path.realpath(self._tmp.name)
        self.root = new_repo(self.base)

    def scan(self):
        code, out, _ = run_gp("--repo", str(self.root), "scan", "--json")
        self.assertEqual(code, 0)
        return json.loads(out)


class UnitTests(unittest.TestCase):
    def test_units_and_scopes(self):
        cases = {
            "code/agents/apps/skills/skills/x/SKILL.md": "code/agents/apps/skills",
            "code/rust/libs/hal2-core/src/lib.rs": "code/rust/libs/hal2-core",
            "code/rust/docs/codemap.md": "code/rust",
            "plans/0364-x/plan.md": "plans/0364-x",
            "research/0093-y/research.md": "research/0093-y",
            "docs/ci.md": "docs",
            ".adr/a.md": ".adr",
            "Cargo.toml": "root",
        }
        for path, unit in cases.items():
            self.assertEqual(gp_scan.unit_of(path), unit, path)
        self.assertEqual(gp_scan.scope_of("code/rust/libs/hal2-core"), "hal2-core")
        self.assertEqual(gp_scan.scope_of(".adr"), "adr")
        self.assertEqual(gp_scan.scope_of("root"), "")

    def test_secrets(self):
        for path in (".env", "a/.env.local", "x_SEC", "k/server.pem", "id_ed25519", ".secrets/plain.txt", "credentials.json",
                     ".ENV", "a/.Env.Production", "K/Server.PEM", "Credentials.JSON", "x_sec", ".envrc", "app/.ENVRC", ".npmrc",
                     "infra/prod.tfvars", "infra/Prod.TFVARS", "infra/prod.tfvars.json", "id_rsa", "ID_RSA", "id_rsa_work",
                     "id_ed25519_work", "id_ecdsa", "id_dsa", "id_rsa.bak"):
            self.assertTrue(gp_scan.is_secret(path), path)
        for path in (".env.example", "x_SEC.secret", ".secrets/x_SEC.secret", "id_ed25519.pub", "id_rsa_work.pub",
                     "src/credentials.rs", "a.rs", ".ENV.EXAMPLE", "infra/prod.tfvars.example", "infra/main.tf"):
            self.assertFalse(gp_scan.is_secret(path), path)

    def test_ignore_candidates_only_untracked(self):
        self.assertEqual(gp_scan.ignore_candidate("a/target/debug/x", "/", True), ("build output", "a/target/"))
        self.assertEqual(gp_scan.ignore_candidate("a/__pycache__/x.pyc", "/", True)[1], "__pycache__/")
        self.assertEqual(gp_scan.ignore_candidate("a/.DS_Store", "/", True)[1], ".DS_Store")
        self.assertEqual(gp_scan.ignore_candidate("run.log", "/", True)[1], "*.log")
        self.assertEqual(gp_scan.ignore_candidate("run.log", "/", False), ("", ""))
        self.assertEqual(gp_scan.ignore_candidate("src/main.rs", "/", True), ("", ""))

    def test_subject_validation(self):
        gp.check_subject("feat(skills): add the git-push skill")
        gp.check_subject("fix: handle spaces in names")
        gp.check_subject("feat(0391|15): commit subjects name the plan and step")
        for bad in ("update stuff", "Feat: x", "feat(x): ", "feat: ends with a period.", "wip: half", "feat: " + "x" * 80,
                    "feat: wip things", "other(x): y"):
            with self.assertRaises(gp.Refused, msg=bad):
                gp.check_subject(bad)

    def test_parse_status_rename(self):
        entries = gp_scan.parse_status("R  new name.txt\0old.txt\0?? b.txt\0 M c.txt\0")
        self.assertEqual([(e["state"], e["path"], e["orig"]) for e in entries],
                         [("R ", "new name.txt", "old.txt"), ("??", "b.txt", ""), (" M", "c.txt", "")])


class ScanTests(Base):
    def test_clean_repo(self):
        result = self.scan()
        self.assertTrue(result["clean"])
        self.assertEqual(result["groups"], [])
        self.assertIn("clean", run_gp("--repo", str(self.root), "scan")[1])

    def test_groups_classes_and_untracked_files_one_by_one(self):
        write(self.root, "README.md", "changed\n")
        write(self.root, "code/py/apps/tool/main.py")
        write(self.root, "code/py/apps/tool/test_main.py")
        write(self.root, "docs/a b.md")
        write(self.root, ".env", "KEY=1\n")
        write(self.root, "code/py/apps/tool/__pycache__/m.pyc")
        write(self.root, "notes.log")
        result = self.scan()
        groups = {g["unit"]: sorted(g["files"]) for g in result["groups"]}
        self.assertEqual(groups["code/py/apps/tool"], ["code/py/apps/tool/main.py", "code/py/apps/tool/test_main.py"])
        self.assertEqual(groups["docs"], ["docs/a b.md"])
        self.assertEqual(groups["root"], ["README.md"])
        self.assertEqual(result["secrets"], [".env"])
        patterns = {c["pattern"] for c in result["ignore_candidates"]}
        self.assertEqual(patterns, {"__pycache__/", "*.log"})
        self.assertNotIn(".env", [p for g in groups.values() for p in g])
        self.assertEqual(next(g for g in result["groups"] if g["unit"] == "code/py/apps/tool")["scope"], "tool")

    def test_a_current_plan_scopes_every_group_by_its_number(self):
        write(self.root, "plans/0391-deploy/plan.md")
        write(self.root, "plans/CURRENT_PLAN", "0391-deploy\n")
        write(self.root, "code/py/apps/tool/main.py")
        scopes = {g["unit"]: g["scope"] for g in self.scan()["groups"]}
        self.assertEqual(scopes["code/py/apps/tool"], "0391")
        self.assertEqual(scopes["plans"], "0391")

    def test_large_untracked_file_is_a_candidate(self):
        big = write(self.root, "data/blob.bin", "")
        with open(big, "wb") as handle:
            handle.truncate(gp_scan.LARGE_BYTES + 1)
        cand = self.scan()["ignore_candidates"][0]
        self.assertEqual(cand["pattern"], "data/blob.bin")
        self.assertIn("large", cand["reason"])

    def test_rename_keeps_both_paths(self):
        git(self.root, "mv", "README.md", "READ ME.md")
        group = self.scan()["groups"][0]
        self.assertEqual(sorted(group["files"]), ["READ ME.md", "README.md"])

    def test_conflicts_reported(self):
        git(self.root, "checkout", "-q", "-b", "side")
        write(self.root, "f.txt", "side\n")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "feat: side")
        git(self.root, "checkout", "-q", "main")
        write(self.root, "f.txt", "main\n")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "feat: main")
        subprocess.run(["git", "merge", "side"], cwd=self.root, capture_output=True)
        self.assertEqual(self.scan()["conflicts"], ["f.txt"])
        write(self.root, "g.txt")
        code, _, err = run_gp("--repo", str(self.root), "commit", "--group", "root", "--subject", "feat: x")
        self.assertEqual(code, 1)
        self.assertIn("conflict", err)


class CommitTests(Base):
    def commit(self, *extra, group="code/py/apps/tool", subject="feat(tool): add the tool"):
        return run_gp("--repo", str(self.root), "commit", "--group", group, "--subject", subject, *extra)

    def test_commits_exactly_the_group(self):
        write(self.root, "code/py/apps/tool/main.py")
        write(self.root, "docs/a.md")
        git(self.root, "add", "docs/a.md")  # staged, but another group
        code, out, _ = self.commit("--body", "why it exists")
        self.assertEqual(code, 0, out)
        self.assertEqual(git(self.root, "show", "--name-only", "--format=", "HEAD").split(), ["code/py/apps/tool/main.py"])
        self.assertEqual(git(self.root, "status", "--porcelain").split(), ["A", "docs/a.md"])
        body = git(self.root, "log", "-1", "--format=%B")
        self.assertTrue(body.startswith("feat(tool): add the tool\n\nwhy it exists\n"))

    def test_glob_characters_in_a_path_are_literal(self):
        write(self.root, "[ab]/f.txt")  # as a glob this also names a/f.txt and b/f.txt, other groups
        write(self.root, "a/f.txt")
        code, out, err = self.commit(group="[ab]", subject="feat: bracket folder")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(git(self.root, "show", "--name-only", "--format=", "HEAD").split(), ["[ab]/f.txt"])
        self.assertEqual(git(self.root, "status", "--porcelain").split(), ["??", "a/"])

    def test_bad_subject_commits_nothing(self):
        write(self.root, "code/py/apps/tool/main.py")
        before = git(self.root, "rev-parse", "HEAD")
        code, _, err = self.commit(subject="added stuff")
        self.assertEqual(code, 1)
        self.assertIn("Conventional", err)
        self.assertEqual(git(self.root, "rev-parse", "HEAD"), before)

    def test_unknown_group_names_the_groups(self):
        write(self.root, "docs/a.md")
        code, _, err = self.commit(group="nope")
        self.assertEqual(code, 1)
        self.assertIn("docs", err)

    def test_secret_never_committed_even_with_also(self):
        write(self.root, ".env", "KEY=1\n")
        write(self.root, "a.txt")
        code, _, err = self.commit("--also", ".env", group="root", subject="chore: x")
        self.assertEqual(code, 1)
        self.assertIn("secret", err)
        self.assertEqual(git(self.root, "log", "--oneline").count("\n"), 1)

    def test_also_commits_an_ignore_candidate(self):
        write(self.root, "a.txt")
        write(self.root, "x.log", "l\n")
        self.assertEqual(self.commit(group="root", subject="chore: add files")[0], 0)
        self.assertNotIn("x.log", git(self.root, "ls-files"))
        self.assertEqual(self.commit("--also", "x.log", group="root", subject="chore: x")[0], 1)  # no group left
        write(self.root, "b.txt")
        self.assertEqual(self.commit("--also", "x.log", group="root", subject="chore: add log")[0], 0)
        self.assertIn("x.log", git(self.root, "ls-files"))

    def test_also_refuses_a_committable_file(self):
        write(self.root, "a.txt")
        code, _, err = self.commit("--also", "a.txt", group="root", subject="chore: x")
        self.assertEqual(code, 1)
        self.assertIn("ignore-candidate", err)

    def test_trailers_plan_step_and_attribution(self):
        write(self.root, "plans/0364-skills/plan.md")
        write(self.root, "plans/CURRENT_PLAN", "0364-skills\n")
        git(self.root, "add", "plans/0364-skills")
        git(self.root, "commit", "-q", "-m", "docs(plans): plan")
        write(self.root, "code/py/apps/tool/main.py")
        code, out, _ = self.commit("--step", "7/8", "--trailer", "Co-Authored-By: C <c@example.com>", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["trailers"], ["Plan: 0364-skills", "Step: 7/8", "Co-Authored-By: C <c@example.com>"])
        last = git(self.root, "log", "-1", "--format=%B").strip().split("\n\n")[-1].split("\n")
        self.assertEqual(last, ["Plan: 0364-skills", "Step: 7/8", "Co-Authored-By: C <c@example.com>"])

    def test_the_plan_trailer_reads_a_pointer_that_sits_only_in_the_git_dir(self):
        write(self.root, "plans/0364-skills/plan.md")
        write(self.root, ".git/hal/CURRENT_PLAN", "0364-skills\n")
        git(self.root, "add", "plans/0364-skills")
        git(self.root, "commit", "-q", "-m", "docs(plans): plan")
        write(self.root, "code/py/apps/tool/main.py")
        code, out, _ = self.commit("--step", "7/8", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["trailers"], ["Plan: 0364-skills", "Step: 7/8"])

    def test_current_plan_that_is_no_plan_adds_nothing(self):
        write(self.root, "plans/CURRENT_PLAN", "some-task\n")
        write(self.root, "code/py/apps/tool/main.py")
        code, out, _ = self.commit("--step", "1/2", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["trailers"], [])

    def test_worktree_trailer_in_a_linked_worktree(self):
        field = Path(self.base, "05")
        git(self.root, "worktree", "add", "-q", "-b", "05", str(field))
        write(field, "a.txt")
        code, out, _ = run_gp("--repo", str(field), "commit", "--group", "root", "--subject", "chore: add a", "--json")
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(out)["trailers"], ["Worktree: 05"])
        code, out, _ = run_gp("--repo", str(self.root), "commit", "--group", "root", "--subject", "chore: add a", "--json")
        self.assertEqual(code, 1)  # nothing in main's tree: no group

    def test_bad_step(self):
        write(self.root, "a.txt")
        self.assertEqual(self.commit("--step", "seven", group="root", subject="chore: x")[0], 1)

    def test_commit_hook_failure_is_reported(self):
        hook = Path(self.root, ".git", "hooks", "commit-msg")
        hook.write_text("#!/bin/sh\necho no >&2\nexit 1\n")
        hook.chmod(0o755)
        write(self.root, "a.txt")
        code, _, err = self.commit(group="root", subject="chore: x")
        self.assertEqual(code, 1)
        self.assertIn("hook", err)


if __name__ == "__main__":
    unittest.main()
