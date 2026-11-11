import json
import subprocess
import unittest
from unittest import mock

import check_decl
import hal2
import testkit


class CheckTest(unittest.TestCase):
    def setUp(self):
        self.root = hal2.find_root()
        self.tmp = testkit.scratch()

    def check(self, text=testkit.DECLARATION, case="good", repo=None):
        return check_decl.check(testkit.declaration(self.tmp, text), self.root, repo,
                                adapted=testkit.adapted(self.tmp, case))

    def test_good_declaration_and_route(self):
        result = self.check()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["route"]["verdict"], "accepted")

    def test_hals_validation_refuses_a_tagged_image(self):
        result = self.check(testkit.DECLARATION.replace("accounter-web", "accounter-web:latest"))
        self.assertFalse(result["ok"])
        self.assertIn("no tag", result["validation"]["error"])
        self.assertIsNone(result["route"])

    def test_a_static_declaration_is_refused(self):
        text = testkit.DECLARATION.split("[container]")[0] + 'max_size = "1G"\n'
        self.assertIn("[container] table is required", self.check(text)["validation"]["error"])

    def test_a_foreign_upstream_is_the_checkers_refusal(self):
        result = self.check(case="foreign_upstream_postgres")
        self.assertFalse(result["ok"])
        self.assertIn("upstream-foreign", {r["rule"] for r in result["route"]["reasons"]})

    def test_findings_of_the_repository_fail_the_check(self):
        result = self.check(repo=testkit.repo(self.tmp, dockerfile=None))
        self.assertFalse(result["ok"])
        self.assertIn("dockerfile-missing", {f["check"] for f in result["findings"]})

    def test_a_checker_that_cannot_run_is_an_error_not_a_pass(self):
        failed = subprocess.CompletedProcess([], 2, "", "hal9k-site-check: docker: not found")
        with mock.patch.object(check_decl.subprocess, "run", return_value=failed):
            result = check_decl.check(testkit.declaration(self.tmp), self.root)
        self.assertEqual(result["route"]["verdict"], "error")
        self.assertIn("docker", result["route"]["error"])
        self.assertFalse(result["ok"])

    def test_memory_is_summed_over_the_sites_the_next_deploy_loads(self):
        sites, _, _ = hal2.load_modules(self.root)
        other = {"name": "other", "container": {"memory": 2 * 1024**3, "secrets": []}}
        with mock.patch.object(sites, "load_all", return_value=[other]):
            result = self.check()
        self.assertIn("containers_memory", result["validation"]["error"])

    def test_a_clash_of_secret_names_with_another_site(self):
        sites, _, _ = hal2.load_modules(self.root)
        other = {"name": "accounter-x", "container": {"memory": 1024, "secrets": ["Y"]}}
        text = testkit.DECLARATION.replace('secrets = ["DATABASE_URL"]', 'secrets = ["X_Y"]')
        with mock.patch.object(sites, "load_all", return_value=[other]):
            result = self.check(text)
        self.assertIn("hal2-secrets", result["validation"]["error"])

    def test_the_same_site_is_not_counted_twice(self):
        sites, _, _ = hal2.load_modules(self.root)
        old = {"name": "accounter", "container": {"memory": 2 * 1024**3, "secrets": []}}
        with mock.patch.object(sites, "load_all", return_value=[old]):
            self.assertTrue(self.check()["validation"]["ok"])

    def test_an_apex_host_is_refused_and_names_the_reason(self):
        result = self.check(testkit.DECLARATION.replace('hosts = ["accounter"]', 'hosts = ["@"]'))
        self.assertFalse(result["ok"])
        self.assertEqual([f["check"] for f in result["findings"]], ["apex-host"])

    def test_checks_get_the_hosts_the_domain_and_hals_limits(self):
        import checks
        seen = {}
        with mock.patch.object(checks, "run_all", side_effect=lambda ctx: seen.update(ctx) or []):
            self.check()
        _, site_container, _ = hal2.load_modules(self.root)
        self.assertEqual((seen["hosts"], seen["domain"]), (["accounter"], "divramod.me"))
        self.assertEqual(seen["limits"]["default_max_image"], site_container.DEFAULT_MAX_IMAGE)

    def test_a_host_of_another_declared_site_is_a_clash(self):
        sites, _, _ = hal2.load_modules(self.root)
        other = {"name": "diktier", "zone": "divramod-me", "hosts": ["accounter"], "container": None}
        with mock.patch.object(sites, "load_all", return_value=[other]):
            result = self.check()
        self.assertFalse(result["ok"])
        self.assertIn("host-clash", {f["check"] for f in result["findings"]})

    def test_an_adapt_timeout_is_no_verdict_on_the_route(self):
        body = json.dumps({"verdict": "no-verdict", "reasons": [{"rule": "adapt", "detail": "docker: caddy adapt timed out after 60s"}]})
        with mock.patch.object(check_decl.subprocess, "run", return_value=subprocess.CompletedProcess([], 3, body, "")):
            result = check_decl.check(testkit.declaration(self.tmp), self.root)
        self.assertEqual(result["route"]["verdict"], "error")
        self.assertIn("no verdict", result["route"]["error"])
        self.assertFalse(result["ok"])

    def test_missing_file(self):
        result = check_decl.check(self.tmp / "none.toml", self.root)
        self.assertFalse(result["ok"])
        self.assertIn("cannot read", result["validation"]["error"])


if __name__ == "__main__":
    unittest.main()
