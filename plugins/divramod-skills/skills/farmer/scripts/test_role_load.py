"""Role on start (hal2 plan 0383, D15): every prompt that starts a foreman loads the /foreman role skill first."""
import unittest

import delegation
import role_sync


class RoleLoadTest(unittest.TestCase):
    def test_the_delegation_prompt_opens_with_the_foreman_role_skill(self):
        prompt = delegation.PROMPT
        self.assertTrue(prompt.startswith("Run /foreman first:"), prompt)
        self.assertIn("roles/foreman/ROLE.md", prompt)
        self.assertLess(prompt.index("/foreman"), prompt.index("{role}"))  # before its task file
        self.assertLess(prompt.index("/foreman"), prompt.index("{brief}"))
        self.assertNotIn("/servant", prompt)

    def test_the_sync_prompt_loads_the_role_before_anything_else_but_the_boss_words(self):
        prompt = role_sync.LAND.format(boss="tollman") + role_sync.PROMPT
        self.assertTrue(prompt.startswith("tollman: land now. You are a foreman"), prompt)  # the go every /mtm knows
        self.assertLess(prompt.index("run /foreman first"), prompt.index("{role}"))
        self.assertLess(prompt.index("run /foreman first"), prompt.index("/merge-from-main"))

    def test_the_prompt_a_started_foreman_gets_carries_it(self):
        prompt = delegation.PROMPT.format(repo="app", farmer_slot="farmer-app", brief="/b.md", title="t", role="/r.md")
        self.assertTrue(prompt.startswith("Run /foreman first:"))
        self.assertIn("Read your task file at /r.md next", prompt)


if __name__ == "__main__":
    unittest.main()
