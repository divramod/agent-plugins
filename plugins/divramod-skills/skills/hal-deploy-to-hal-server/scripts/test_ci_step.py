import re
import unittest

import ci_step
import testkit


class CiStepTest(unittest.TestCase):
    def test_publish_then_deploy_by_digest_over_the_forced_user(self):
        text = ci_step.render("accounter", "ghcr.io/divramod/accounter-web")
        self.assertLess(text.index("Publish the image"), text.index("Deploy to the hal9k server"))
        self.assertIn("hal9k-site-accounter@hal9k.app", text)
        self.assertIn('"deploy $DIGEST"', text)
        self.assertIn("steps.push.outputs.digest", text)
        self.assertIn("StrictHostKeyChecking=yes", text)

    def farm(self, *folders):
        repo = testkit.scratch()
        for folder in folders:
            (repo / folder).mkdir()
        return repo

    def test_a_farm_on_git_secret_reveals_the_key_and_removes_it(self):
        text = ci_step.render("a", "ghcr.io/x/a", repo=self.farm(".gitsecret", ".secrets"))
        self.assertLess(text.index("gpg --batch --import"), text.index("git secret reveal"))
        self.assertLess(text.index("git secret reveal"), text.index('"deploy $DIGEST"'))
        self.assertIn("""trap 'rm -f "$key"; rm -rf "$GNUPGHOME"' EXIT""", text)
        self.assertEqual(set(re.findall(r"secrets\.(\w+)", text)), {"HAL_CI_GPG_KEY", "GITHUB_TOKEN"})  # GITHUB_TOKEN is GitHub's own
        self.assertNotIn("OFF THE STANDARD", text)

    def test_a_farm_without_git_secret_gets_the_plain_form_and_is_told(self):
        for repo in (self.farm(), self.farm(".secrets"), None):
            with self.subTest(repo=repo):
                text = ci_step.render("a", "ghcr.io/x/a", repo=repo)
                self.assertIn("OFF THE STANDARD", text)
                self.assertIn("secrets.HAL9K_DEPLOY_KEY", text)
                self.assertNotIn("git secret reveal", text)

    def test_logs_in_before_the_push(self):
        text = ci_step.render("a", "ghcr.io/x/a")
        self.assertLess(text.index("docker/login-action"), text.index("build-push-action"))
        self.assertIn("registry: ghcr.io", text)

    def test_context_file_and_build_args_for_an_app_in_a_subfolder(self):
        text = ci_step.render("a", "ghcr.io/x/a", "apps/astro", "apps/astro/Dockerfile", ["NEXT_PUBLIC_URL"])
        self.assertIn("context: apps/astro\n", text)
        self.assertIn("file: apps/astro/Dockerfile\n", text)
        self.assertIn("NEXT_PUBLIC_URL=${{ vars.NEXT_PUBLIC_URL }}", text)
        names = [line for line in text.splitlines() if line.startswith("- name:")]
        self.assertEqual(len(names), 3)  # the build args stay inside the publish step

    def test_refuses_what_would_break_the_yaml(self):
        for args in (("a b", "Dockerfile", []), (".", "x\ny", []), (".", "Dockerfile", ["bad name"])):
            with self.subTest(args=args), self.assertRaises(ValueError):
                ci_step.render("a", "ghcr.io/x/a", *args)

    def test_the_image_rule_is_hals(self):
        with self.assertRaises(ValueError) as caught:  # the shape passes, site_container refuses: no registry host
            ci_step.render("a", "nohost/app")
        self.assertIn("registry host", str(caught.exception))

    def test_refuses_bad_names(self):
        for site, image in (("A b", "ghcr.io/x/y"), ("ok", "ghcr.io/x/y:latest"), ("ok", "ghcr.io/x/y@sha256:1"),
                            ("ok", "x")):
            with self.subTest(site=site, image=image), self.assertRaises(ValueError):
                ci_step.render(site, image)


if __name__ == "__main__":
    unittest.main()
