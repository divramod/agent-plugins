import tomllib
import unittest
from pathlib import Path

import declare
import hal2
import testkit

ARGS = {"site": "accounter", "zone": "divramod-me", "hosts": ["accounter"], "keys": [testkit.KEY],
        "image": "ghcr.io/divramod/accounter-web", "port": 3000, "health": "/healthcheck", "memory": "512M",
        "cpus": 1.0, "egress": True, "max_body": "50M", "secrets": ["DATABASE_URL"], "env": {"NODE_ENV": "production"},
        "writable": ["/tmp"]}


class DeclareTest(unittest.TestCase):
    def test_draft_is_toml_of_the_declared_shape(self):
        data = tomllib.loads(declare.render(ARGS))
        self.assertEqual(data["container"]["port"], 3000)
        self.assertEqual(data["container"]["env"], {"NODE_ENV": "production"})
        self.assertEqual(data["hosts"], ["accounter"])

    def test_max_image_is_written_and_passes_hals_validation(self):
        import check_decl
        tmp = testkit.scratch()
        data = tomllib.loads(declare.render({**ARGS, "max_image": "3G"}))
        self.assertEqual(data["container"]["max_image"], "3G")
        path = declare.write(declare.render({**ARGS, "max_image": "3G"}), tmp / "accounter.toml", None, False)
        self.assertTrue(check_decl.check(path, hal2.find_root(), adapted=testkit.adapted(tmp))["validation"]["ok"])
        over = declare.write(declare.render({**ARGS, "max_image": "5G"}), tmp / "over.toml", None, False)
        self.assertIn("max_image", check_decl.check(over, hal2.find_root(), adapted=testkit.adapted(tmp))["validation"]["error"])

    def test_writes_a_named_path_never_over_a_file(self):
        tmp = testkit.scratch()
        out = declare.write(declare.render(ARGS), tmp / "a.toml", None, False)
        self.assertTrue(out.is_file())
        with self.assertRaises(FileExistsError):
            declare.write("x", out, None, False)

    def test_real_sites_folder_needs_the_go(self):
        root = hal2.find_root()
        target = root / hal2.SITES_DIR / "never-written.toml"
        with self.assertRaises(PermissionError):
            declare.write("x", target, root, False)
        self.assertFalse(target.exists())

    def test_the_draft_passes_hals_validation(self):
        import check_decl
        tmp = testkit.scratch()
        path = declare.write(declare.render(ARGS), tmp / "accounter.toml", None, False)
        result = check_decl.check(path, hal2.find_root(), adapted=testkit.adapted(tmp))
        self.assertTrue(result["validation"]["ok"], result["validation"])


if __name__ == "__main__":
    unittest.main()
