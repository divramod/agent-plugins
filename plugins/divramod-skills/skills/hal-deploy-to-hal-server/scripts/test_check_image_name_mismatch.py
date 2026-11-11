import unittest

import testkit
from checks import image_name_mismatch


class ImageNameMismatchTest(unittest.TestCase):
    def ctx(self, image, **inspect):
        return testkit.ctx(container={"image": image}, inspect=inspect)

    def test_another_published_name(self):
        refs = [{"file": "compose.yml", "image": "ghcr.io/me/old:latest"}]
        found = image_name_mismatch.run(self.ctx("ghcr.io/me/new", image_refs=refs))
        self.assertIn("ghcr.io/me/old", found[0]["detail"])

    def test_ci_published_name_counts_when_compose_is_silent(self):
        ctx = self.ctx("ghcr.io/me/new", ci_builds_image=True, image_candidate="ghcr.io/me/repo")
        self.assertEqual(len(image_name_mismatch.run(ctx)), 1)

    def test_the_same_name_and_nothing_published(self):
        refs = [{"file": "compose.yml", "image": "ghcr.io/me/new:latest"}]
        self.assertEqual(image_name_mismatch.run(self.ctx("ghcr.io/me/new", image_refs=refs)), [])
        self.assertEqual(image_name_mismatch.run(self.ctx("ghcr.io/me/new")), [])

    def test_without_a_repository_it_finds_nothing(self):
        self.assertEqual(image_name_mismatch.run({"site": "demo", "container": {}, "inspect": None}), [])


if __name__ == "__main__":
    unittest.main()
