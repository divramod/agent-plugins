import json
import unittest
from pathlib import Path

import inspect_app
import inspect_repo
import testkit


def put(root: Path, rel: str, text: str = "") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


class InspectTest(unittest.TestCase):
    def test_findings(self):
        found = inspect_repo.inspect(testkit.repo(testkit.scratch()))
        self.assertEqual(found["dockerfiles"], ["Dockerfile"])
        self.assertEqual(found["ports"], {"Dockerfile": [3000]})
        self.assertEqual(list(found["health_routes"]), ["/healthcheck"])
        self.assertEqual(found["env_names"], ["DATABASE_URL", "NODE_ENV", "STORAGE_DRIVER"])
        self.assertEqual(found["drivers"], ["pg"])
        self.assertEqual(found["frameworks"], ["astro"])
        self.assertEqual(found["platform"], "node")

    def test_never_reads_the_real_env(self):
        found = inspect_repo.inspect(testkit.repo(testkit.scratch()))
        self.assertNotIn("REAL_SECRET", found["env_names"])

    def test_a_deep_route_of_a_monorepo_is_found(self):
        r = testkit.repo(testkit.scratch())
        put(r, "code/typescript/apps/web/src/app/api/health/route.ts", "// the database\nreturn new Response('', {status: 503})\n")
        found = inspect_repo.inspect(r)
        handler = found["health_handlers"]["/api/health"]
        self.assertEqual(handler["files"], ["code/typescript/apps/web/src/app/api/health/route.ts"])
        self.assertTrue(handler["database"] and handler["status_503"])
        self.assertFalse(handler["rate_limited"])

    def test_file_based_routes_of_each_router(self):
        for rel, route in (("app/api/health/route.ts", "/api/health"), ("src/pages/api/health.ts", "/api/health"),
                           ("app/routes/healthcheck.ts", "/healthcheck"), ("app/(ops)/health/route.ts", "/health"),
                           ("src/pages/index.astro", None), ("app/routes/users.ts", None)):
            with self.subTest(rel=rel):
                self.assertEqual(inspect_app.route_of(rel), route)

    def test_tests_do_not_count_as_routes(self):
        r = testkit.repo(testkit.scratch())
        put(r, "app/api/ready/route.test.ts", "")
        put(r, "tests/ping.spec.ts", '"/readyz"')
        found = inspect_repo.inspect(r)
        self.assertNotIn("/api/ready", found["health_handlers"])
        self.assertNotIn("/readyz", found["health_routes"])

    def test_a_cap_ending_the_walk_still_saw_what_is_near_the_root(self):
        r = testkit.repo(testkit.scratch())
        for n in range(30):
            put(r, f"aaa/{n}.md")
        put(r, ".github/workflows/ci.yml", "docker build .")
        original = inspect_repo.MAX_FILES
        inspect_repo.MAX_FILES = 20
        try:
            found = inspect_repo.inspect(r)
        finally:
            inspect_repo.MAX_FILES = original
        self.assertTrue(found["truncated"])
        self.assertEqual(found["workflows"], [".github/workflows/ci.yml"])

    def test_a_farms_plans_are_not_walked(self):
        r = testkit.repo(testkit.scratch())
        put(r, "plans/0001-x/Dockerfile", "FROM scratch\n")
        self.assertEqual(inspect_repo.inspect(r)["dockerfiles"], ["Dockerfile"])

    def test_env_production_example_counts(self):
        r = testkit.repo(testkit.scratch())
        put(r, ".env.production.example", "ONLY_IN_PRODUCTION=\n")
        self.assertIn("ONLY_IN_PRODUCTION", inspect_repo.inspect(r)["env_names"])

    def test_docker_facts_of_the_final_stage(self):
        r = testkit.repo(testkit.scratch(), dockerfile="FROM node AS b\nUSER node\nFROM node\nCOPY --from=b /a/node_modules .\nEXPOSE 3000\n")
        self.assertEqual(inspect_repo.inspect(r)["docker"]["Dockerfile"],
                         {"ports": [3000], "user": None, "copies_node_modules": True})

    def test_a_build_context_without_the_copy_sources(self):
        r = testkit.repo(testkit.scratch(), dockerfile=None)
        put(r, "apps/a/Dockerfile", "FROM node\nCOPY package.json lock ./\nCOPY --from=x /y .\nCOPY src/*.ts ./\n")
        put(r, "apps/a/package.json", json.dumps({"dependencies": {"astro": "5"}}))
        (r / "package.json").unlink()
        put(r, "apps/a/lock")
        workflow = "steps:\n  - name: b\n    uses: docker/build-push-action@v6\n    with:\n      context: {c}\n      file: apps/a/Dockerfile\n"
        put(r, ".github/workflows/d.yml", workflow.format(c="."))
        self.assertEqual(inspect_repo.inspect(r)["build_contexts"][0]["missing"], ["lock", "package.json"])
        put(r, ".github/workflows/d.yml", workflow.format(c="apps/a"))
        self.assertEqual(inspect_repo.inspect(r)["build_contexts"][0]["missing"], [])

    def test_several_apps_and_compose_images(self):
        r = testkit.repo(testkit.scratch())
        for app in ("web", "admin"):
            put(r, f"code/ts/apps/{app}/package.json", json.dumps({"dependencies": {"next": "16"}}))
        put(r, "code/ts/libs/ui/package.json", json.dumps({"dependencies": {"next": "16"}}))
        put(r, "deploy/docker-compose.yml", "services:\n  web:\n    image: ghcr.io/me/app:latest\n")
        found = inspect_repo.inspect(r)
        self.assertEqual(found["apps"], ["code/ts/apps/admin", "code/ts/apps/web"])
        self.assertEqual(found["image_refs"], [{"file": "deploy/docker-compose.yml", "image": "ghcr.io/me/app:latest"}])

    def test_next_config_and_vercel_signs(self):
        r = testkit.repo(testkit.scratch())
        put(r, "web/next.config.ts", 'export default { output: "standalone" }')
        put(r, "web/package.json", json.dumps({"dependencies": {"@vercel/react-router": "1"}}))
        put(r, "web/src/env.ts", "process.env.VERCEL_ENV")
        put(r, "web/src/env.test.ts", "process.env.VERCEL_ENV")
        found = inspect_repo.inspect(r)
        self.assertEqual(found["next_configs"], [{"path": "web/next.config.ts", "standalone": True}])
        self.assertEqual(found["vercel"], {"deps": ["@vercel/react-router"], "env_readers": ["web/src/env.ts"]})

    def test_read_only(self):
        r = testkit.repo(testkit.scratch())
        before = sorted((p, p.stat().st_mtime_ns) for p in r.rglob("*"))
        inspect_repo.inspect(r)
        self.assertEqual(before, sorted((p, p.stat().st_mtime_ns) for p in r.rglob("*")))

    def test_no_dockerfile_and_missing_folder(self):
        tmp = testkit.scratch()
        self.assertEqual(inspect_repo.inspect(testkit.repo(tmp, dockerfile=None))["dockerfiles"], [])
        with self.assertRaises(FileNotFoundError):
            inspect_repo.inspect(tmp / "nothing")


if __name__ == "__main__":
    unittest.main()
