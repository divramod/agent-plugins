import unittest

import testkit
from checks import deploy_content

SERVICE = {"image": "ghcr.io/me/app", "port": 3000, "memory": "1G", "env": {"NODE_ENV": "production", "DATABASE_URL": None}}
COMPOSE = {"path": "c.yml", "services": {"app": SERVICE}}
TABLE = {"image": "ghcr.io/me/app", "port": 3000, "memory": "1024M", "env": {"NODE_ENV": "production"}, "secrets": ["DATABASE_URL"]}


class DeployContentTest(unittest.TestCase):
    def run_with(self, table, compose=COMPOSE):
        return deploy_content.run(testkit.ctx(container=table, inspect={"deploy_compose": compose}))

    def test_the_same_content_passes_whatever_the_memory_unit(self):
        self.assertEqual(self.run_with(TABLE), [])

    def test_each_difference_is_named(self):
        table = {**TABLE, "port": 8080, "memory": "2G", "secrets": ["OTHER"]}
        detail = self.run_with(table)[0]["detail"]
        for word in ("port: compose 3000", "memory: compose 1G", "only in compose: ['DATABASE_URL']", "only in [container]: ['OTHER']"):
            self.assertIn(word, detail)

    def test_several_services_and_no_match_is_an_error(self):
        compose = {"path": "c.yml", "services": {"a": SERVICE, "b": SERVICE}}
        self.assertEqual(self.run_with({**TABLE, "image": "ghcr.io/me/x"}, compose)[0]["severity"], "error")

    def test_no_compose_file(self):
        self.assertEqual(deploy_content.run(testkit.ctx(container=TABLE)), [])

    def test_without_a_repository_it_finds_nothing(self):
        self.assertEqual(deploy_content.run({"site": "demo", "container": {}, "inspect": None}), [])


if __name__ == "__main__":
    unittest.main()
