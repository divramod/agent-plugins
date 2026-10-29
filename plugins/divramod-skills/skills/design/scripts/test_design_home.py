"""design_home.py (hal2 plan 0409 step 9): the files home is untouched (no copy, nothing applied); in the store home the
review server's saves are applied as they happen. The store home's whole flow: the spec skill's test_spec_store.py."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import design_home
import review


class DesignHome(unittest.TestCase):
    def test_the_files_home_has_no_copy_and_applies_nothing(self):
        tmp = Path(tempfile.mkdtemp(prefix="design-home-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        subprocess.run(["git", "init", "-q", str(tmp)], check=True)
        self.assertIsNone(design_home.folder(tmp, "1"))
        self.assertEqual(design_home._VIEWS, [])
        design_home.apply()

    def test_a_review_save_is_applied_at_once(self):
        calls = []
        with mock.patch.object(review, "write", lambda at, data: calls.append("write")), \
                mock.patch.object(design_home, "apply", lambda: calls.append("apply")):
            design_home.follow(review)
            review.write(Path("x"), {})
        self.assertEqual(calls, ["write", "apply"])


if __name__ == "__main__":
    unittest.main()
