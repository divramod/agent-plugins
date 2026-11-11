import contextlib
import io
import json
import os
import unittest
from unittest import mock

import main
import testkit


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class MainTest(unittest.TestCase):
    def test_help(self):
        for word in ("h", "help"):
            code, out, _ = run(word)
            self.assertEqual(code, 0)
            self.assertIn("deploy --site", out)

    def test_inspect_json(self):
        code, out, _ = run("inspect", str(testkit.repo(testkit.scratch())), "--json")
        self.assertEqual((code, json.loads(out)["schema"]), (0, 1))

    def test_declare_draft_and_missing_args(self):
        code, out, _ = run("declare", "--site", "a", "--zone", "divramod-me", "--host", "a", "--key", testkit.KEY,
                           "--image", "ghcr.io/x/a", "--port", "3000", "--health", "/h", "--memory", "256M", "--json")
        self.assertEqual(code, 0)
        self.assertIn("[container]", json.loads(out)["draft"])
        self.assertEqual(run("declare", "--site", "a", "--json")[0], 2)

    def test_check_json_and_exit(self):
        tmp = testkit.scratch()
        decl, adapted = testkit.declaration(tmp), testkit.adapted(tmp)
        code, out, _ = run("check", "--declaration", str(decl), "--adapted", adapted, "--json")
        self.assertEqual((code, json.loads(out)["ok"]), (0, True))
        code, out, _ = run("check", "--declaration", str(decl), "--adapted", testkit.adapted(tmp, "foreign_upstream_postgres"),
                           "--json")
        self.assertEqual((code, json.loads(out)["ok"]), (1, False))

    def test_check_outside_hal2_says_so(self):
        with mock.patch.dict(os.environ, {"HAL2_ROOT": "/nonexistent"}):
            code, out, _ = run("check", "--declaration", "x.toml", "--json")
        self.assertEqual(code, 2)
        self.assertIn("hal2's tree was not found", json.loads(out)["error"])

    def test_ci_step(self):
        code, out, _ = run("ci-step", "--site", "a", "--image", "ghcr.io/x/a", "--json")
        self.assertEqual(code, 0)
        self.assertIn("deploy $DIGEST", json.loads(out)["steps"])

    def test_deploy_without_go_is_refused_and_exit_codes_pass_through(self):
        tmp = testkit.scratch()
        base = ["deploy", "--site", "a", "--digest", testkit.DIGEST, "--key", "k", "--known-hosts", "h", "--json",
                "--ssh", str(testkit.fake_ssh(tmp, "", 3))]
        code, out, _ = run(*base)
        self.assertEqual(code, 2)
        self.assertIn("user's go", json.loads(out)["error"])
        self.assertFalse((tmp / "argv").exists())
        code, out, _ = run(*base, "--go")
        self.assertEqual((code, json.loads(out)["outcome"]), (3, "pending"))

    def test_status_json(self):
        tmp = testkit.scratch()
        ssh = testkit.fake_ssh(tmp, json.dumps({"verdict": "failed", "reasons": []}), 1)
        code, out, _ = run("status", "--site", "a", "--key", "k", "--known-hosts", "h", "--ssh", str(ssh), "--json")
        self.assertEqual((code, json.loads(out)["tell_user_now"]), (1, True))

    def test_learn_brief_and_outside_hal2(self):
        code, out, _ = run("learn", "some-problem", "--brief", "--json")
        self.assertEqual(code, 0)
        self.assertIn("test_check_some_problem.py", json.loads(out)["brief"])
        with mock.patch.dict(os.environ, {"HAL2_ROOT": "/nonexistent"}):
            code, out, _ = run("learn", "some-problem", "--json")
        self.assertEqual(code, 2)
        self.assertIn("--brief", json.loads(out)["error"])


if __name__ == "__main__":
    unittest.main()
