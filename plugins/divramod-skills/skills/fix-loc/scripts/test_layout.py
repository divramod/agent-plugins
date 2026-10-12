import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import layout  # noqa: E402


class Excluded(unittest.TestCase):
    def test_tests_generated_and_build_output_are_left_out(self):
        for path in [
            "code/rust/libs/x/tests/spawn.rs",
            "code/rust/libs/x/src/sources/github/tests.rs",
            "code/swift/libs/Hal2Kit/Tests/FeatureGitTests/FeatureGitTests.swift",
            "code/python/scripts/build/test_main.py",
            "code/typescript/apps/v/src/view.test.ts",
            "code/rust/libs/x/src/fixtures/ps.txt",
            "code/typescript/apps/v/dist/index.js",
        ]:
            self.assertTrue(layout.excluded(path), path)

    def test_production_files_count(self):
        for path in ["code/rust/libs/x/src/lib.rs", "code/typescript/apps/v/src/view.ts", "code/bash/scripts/a/main.sh"]:
            self.assertFalse(layout.excluded(path), path)

    def test_extra_globs_from_the_settings(self):
        self.assertTrue(layout.excluded("code/rust/libs/x/src/big.rs", ["code/rust/libs/x/src/big.rs"]))


class UnitOf(unittest.TestCase):
    def test_apps_libs_and_scripts_are_units(self):
        self.assertEqual(layout.unit_of("code/rust/libs/hal2-git/src/worktree.rs"), "code/rust/libs/hal2-git")
        self.assertEqual(layout.unit_of("code/bash/scripts/build-core/main.sh"), "code/bash/scripts/build-core")
        self.assertIsNone(layout.unit_of("docs/agents.md"))

    def test_the_most_specific_unit_wins(self):
        globs = ["code/swift/libs/Hal2Kit/Sources/*"]
        self.assertEqual(
            layout.unit_of("code/swift/libs/Hal2Kit/Sources/FeatureGit/GitViews.swift", globs),
            "code/swift/libs/Hal2Kit/Sources/FeatureGit",
        )
        self.assertEqual(layout.unit_of("code/swift/libs/Hal2Kit/Package.swift", globs), "code/swift/libs/Hal2Kit")


class Settings(unittest.TestCase):
    def test_defaults_without_a_file(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(layout.settings(root), layout.Settings())

    def test_the_file_overrides(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, ".hal").mkdir()
            Path(root, ".hal/fix-loc.toml").write_text('limit = 250\nunits = ["a/*"]\nexclude = ["b/*"]\n')
            self.assertEqual(layout.settings(root), layout.Settings(limit=250, exclude=["b/*"], units=["a/*"]))


if __name__ == "__main__":
    unittest.main()
