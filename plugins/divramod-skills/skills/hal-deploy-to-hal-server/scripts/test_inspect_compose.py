import contextlib
import io
import json
import tomllib
import unittest

import inspect_compose
import inspect_repo
import main
import testkit

FILE = """# the app
services:
  hub:
    image: "ghcr.io/me/hub:${TAG:-latest}"  # pinned by digest at deploy
    ports:
      - "127.0.0.1:3100:3000"
    environment:
      NODE_ENV: production
      DATABASE_URL: ${DATABASE_URL}
      API_KEY:
    deploy:
      resources:
        limits:
          memory: 512m
    healthcheck:
      test: ["CMD", "wget", "http://localhost:3000/up"]
      interval: 5s
  db:
    image: postgres:17
    expose:
      - 5432
    environment:
      - POSTGRES_DB=app
      - POSTGRES_PASSWORD
    mem_limit: 1g
"""


def repo(text=FILE):
    r = testkit.repo(testkit.scratch())
    path = r / inspect_compose.PATH
    path.parent.mkdir(parents=True)
    path.write_text(text)
    return r


def call(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main.main(list(args))
    return code, json.loads(out.getvalue())


class ComposeTest(unittest.TestCase):
    def test_a_service_is_read(self):
        hub = inspect_compose.parse(FILE)["hub"]
        self.assertEqual((hub["image"], hub["port"], hub["memory"]), ("ghcr.io/me/hub", 3000, "512M"))
        self.assertEqual(hub["env"], {"NODE_ENV": "production", "DATABASE_URL": None, "API_KEY": None})

    def test_list_environment_expose_and_mem_limit(self):
        db = inspect_compose.parse(FILE)["db"]
        self.assertEqual((db["port"], db["memory"]), (5432, "1G"))
        self.assertEqual(db["env"], {"POSTGRES_DB": "app", "POSTGRES_PASSWORD": None})

    def test_derive_splits_values_from_secret_names(self):
        derived = inspect_compose.derive(inspect_compose.parse(FILE)["hub"])
        self.assertEqual(derived["env"], {"NODE_ENV": "production"})
        self.assertEqual(derived["secrets"], ["API_KEY", "DATABASE_URL"])

    def test_inspect_reports_the_file_and_its_absence(self):
        self.assertEqual(inspect_repo.inspect(repo())["deploy_compose"]["path"], inspect_compose.PATH)
        self.assertIsNone(inspect_repo.inspect(testkit.repo(testkit.scratch()))["deploy_compose"])

    def base(self, r, *more):
        return ("declare", "--repo", str(r), "--compose-service", "hub", "--site", "hub", "--zone", "divramod-me", "--host", "hub",
                "--key", testkit.KEY, "--health", "/up", "--json", *more)

    def test_declare_derives_from_the_compose_file(self):
        code, out = call(*self.base(repo()))
        data = tomllib.loads(out["draft"])["container"]
        self.assertEqual(code, 0)
        self.assertEqual((data["image"], data["port"], data["memory"]), ("ghcr.io/me/hub", 3000, "512M"))
        self.assertEqual((data["secrets"], data["env"]), (["API_KEY", "DATABASE_URL"], {"NODE_ENV": "production"}))

    def test_declare_refuses_a_flag_the_compose_file_contradicts(self):
        code, out = call(*self.base(repo(), "--port", "8080"))
        self.assertEqual(code, 1)
        self.assertIn("port", out["error"])

    def test_declare_reports_a_mismatch_with_an_existing_table_and_never_overwrites(self):
        r, tmp = repo(), testkit.scratch()
        existing = testkit.declaration(tmp, name="hub")
        before = existing.read_text()
        code, out = call("declare", "--repo", str(r), "--compose-service", "hub", "--out", str(existing), "--json")
        self.assertEqual(code, 1)
        self.assertIn("image: compose ghcr.io/me/hub", " ".join(out["mismatches"]))
        self.assertEqual(existing.read_text(), before)

    def test_several_services_need_a_name(self):
        code, out = call("declare", "--repo", str(repo()), "--site", "hub", "--json")
        self.assertEqual(code, 2)
        self.assertIn("--compose-service", out["error"])


if __name__ == "__main__":
    unittest.main()
