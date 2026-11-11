import unittest

import testkit
from checks import object_storage


class ObjectStorageTest(unittest.TestCase):
    def test_the_sdk_or_its_names(self):
        self.assertEqual(len(object_storage.run(testkit.ctx(inspect={"drivers": ["@aws-sdk/client-s3"]}))), 1)
        self.assertEqual(len(object_storage.run(testkit.ctx(inspect={"env_names": ["S3_BUCKET"]}))), 1)

    def test_an_unnamed_driver_is_named(self):
        found = object_storage.run(testkit.ctx(inspect={"env_names": ["STORAGE_DRIVER"]}))
        self.assertIn("STORAGE_DRIVER", found[1]["detail"])
        named = testkit.ctx(container={"env": {"STORAGE_DRIVER": "s3"}}, inspect={"env_names": ["STORAGE_DRIVER"]})
        self.assertEqual(len(object_storage.run(named)), 1)

    def test_an_app_without_storage(self):
        self.assertEqual(object_storage.run(testkit.ctx()), [])

    def test_without_a_repository_it_finds_nothing(self):
        self.assertEqual(object_storage.run({"site": "demo", "container": {}, "inspect": None}), [])


if __name__ == "__main__":
    unittest.main()
