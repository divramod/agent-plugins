import unittest

import testkit
from checks import floating_tag


class FloatingTagTest(unittest.TestCase):
    IMAGE = {"image": "ghcr.io/me/app"}

    def run_with(self, *images):
        refs = [{"file": "compose.yml", "image": i} for i in images]
        return floating_tag.run(testkit.ctx(container=self.IMAGE, inspect={"image_refs": refs}))

    def test_latest_and_no_tag_float(self):
        self.assertEqual(len(self.run_with("ghcr.io/me/app:latest")), 1)
        self.assertEqual(len(self.run_with("ghcr.io/me/app")), 1)

    def test_a_pinned_ref_and_a_foreign_image_do_not(self):
        self.assertEqual(self.run_with("ghcr.io/me/app:1.2.3"), [])
        self.assertEqual(self.run_with("ghcr.io/me/app@sha256:abc"), [])
        self.assertEqual(self.run_with("postgres:latest", "ghcr.io/other/x:latest"), [])

    def test_without_a_repository_it_finds_nothing(self):
        self.assertEqual(floating_tag.run({"site": "demo", "container": {}, "inspect": None}), [])


if __name__ == "__main__":
    unittest.main()
