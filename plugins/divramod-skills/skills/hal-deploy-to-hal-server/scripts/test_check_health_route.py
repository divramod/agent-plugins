import unittest

import testkit
from checks import health_route


class HealthRouteTest(unittest.TestCase):
    def handler(self, **flags):
        entry = {"files": ["app/health.ts"], "database": False, "status_503": False, "rate_limited": False, **flags}
        return {"health_handlers": {"/health": entry}, "health_routes": {"/health": ["app/health.ts"]}}

    def test_a_path_the_repository_lacks(self):
        found = health_route.run(testkit.ctx(container={"health": "/nope"}, inspect=self.handler()))
        self.assertIn("/nope", found[0]["detail"])
        self.assertIn("/health", found[0]["detail"])

    def test_a_route_only_mentioned_in_text_is_enough(self):
        ctx = testkit.ctx(container={"health": "/up"}, inspect={"health_routes": {"/up": ["srv.py"]}})
        self.assertEqual(health_route.run(ctx), [])

    def test_a_database_handler_answering_503(self):
        found = health_route.run(testkit.ctx(container={"health": "/health"},
                                             inspect=self.handler(database=True, status_503=True)))
        self.assertIn("503", found[0]["detail"])

    def test_a_rate_limit_and_a_plain_handler(self):
        limited = health_route.run(testkit.ctx(container={"health": "/health"}, inspect=self.handler(rate_limited=True)))
        self.assertIn("429", limited[0]["detail"])
        self.assertEqual(health_route.run(testkit.ctx(container={"health": "/health"}, inspect=self.handler())), [])

    def test_without_a_repository_it_finds_nothing(self):
        self.assertEqual(health_route.run({"site": "demo", "container": {}, "inspect": None}), [])


if __name__ == "__main__":
    unittest.main()
