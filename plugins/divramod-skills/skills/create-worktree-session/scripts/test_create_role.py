#!/usr/bin/env python3
"""Role on start (hal2 plan 0383, D15): create.py's first prompt loads the session's role skill first (offline, with
test_create's fake hal2 CLIs)."""
import unittest

import test_create

Fake = test_create.TestCreate


class TestRoleOnStart(unittest.TestCase):
    setUp, tearDown, run_create, run_raw, refused, run_call = (
        Fake.setUp, Fake.tearDown, Fake.run_create, Fake.run_raw, Fake.refused, Fake.run_call)

    def prompt(self, *args) -> str:
        self.run_create(*args)
        run = self.run_call()
        return run[run.index("--prompt") + 1]

    def test_a_servant_start_loads_servant_after_restock_and_before_the_task(self):
        prompt = self.prompt("--from", "30", "--role", "servant", "--prompt", "do step 3")
        self.assertTrue(prompt.startswith("Run /merge-from-main first, then /servant ("), prompt)
        self.assertLess(prompt.index("/servant"), prompt.index("do step 3"))
        self.assertIn("roles/servant/ROLE.md", prompt)
        self.assertTrue(prompt.endswith(", then:\n\ndo step 3"), prompt)

    def test_a_foreman_start_loads_foreman_also_exact_and_without_a_prompt(self):
        prompt = self.prompt("--role", "foreman", "--exact", "--prompt", "run plan 0383")
        self.assertTrue(prompt.startswith("Run /foreman ("), prompt)
        self.assertNotIn("/merge-from-main", prompt)
        self.assertTrue(prompt.endswith("\n\nrun plan 0383"), prompt)
        self.log.unlink()
        bare = self.prompt("--role", "foreman")
        self.assertTrue(bare.startswith("Run /merge-from-main first, then /foreman ("), bare)
        self.assertTrue(bare.endswith("."), bare)

    def test_without_a_role_the_prompt_is_unchanged(self):
        self.assertEqual(self.prompt(), "/merge-from-main")
        self.log.unlink()
        self.assertEqual(self.prompt("--prompt", "/shoot 13"), "Run /merge-from-main first, then:\n\n/shoot 13")

    def test_an_unknown_role_is_refused_before_anything_starts(self):
        self.assertIn("--role needs foreman or servant", self.refused("--role", "farmer"))
        self.assertFalse(self.log.exists() and "run" in self.log.read_text())


if __name__ == "__main__":
    unittest.main()
