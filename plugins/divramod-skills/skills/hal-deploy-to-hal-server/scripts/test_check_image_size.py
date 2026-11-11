import unittest

import testkit
from checks import image_size


class ImageSizeTest(unittest.TestCase):
    def docker(self, heavy):
        return {"docker": {"Dockerfile": {"ports": [], "user": "node", "copies_node_modules": heavy}}}

    def test_a_full_node_modules_names_the_cap(self):
        found = image_size.run(testkit.ctx(inspect=self.docker(True), limits={"default_max_image": "2G"}))
        self.assertIn("2G", found[0]["detail"])
        declared = image_size.run(testkit.ctx(container={"max_image": "3G"}, inspect=self.docker(True)))
        self.assertIn("3G", declared[0]["detail"])

    def test_a_lean_image(self):
        self.assertEqual(image_size.run(testkit.ctx(inspect=self.docker(False))), [])

    def test_without_a_repository_it_finds_nothing(self):
        self.assertEqual(image_size.run({"site": "demo", "container": {}, "inspect": None}), [])


if __name__ == "__main__":
    unittest.main()
