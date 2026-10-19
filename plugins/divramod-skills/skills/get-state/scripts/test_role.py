import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import role


class Detect(unittest.TestCase):
    """Every role path of D2 and D11 over plain folders (detection reads only paths)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.main = self.tmp / "hal2"
        self.places = {r: self.tmp / name for r, name in (("mayor", "village"), ("lord", "city"), ("pope", "planet"))}
        for d in (self.main, *self.places.values()):
            d.mkdir()
        env = {"HAL_VILLAGE": str(self.places["mayor"]), "HAL_CITY": str(self.places["lord"]),
               "HAL_PLANET": str(self.places["pope"])}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)

    def field(self, name: str) -> str:
        d = self.tmp / "wt" / name
        d.mkdir(parents=True, exist_ok=True)
        return str(d)

    def test_named_worktrees(self):
        self.assertEqual(role.detect(self.field("farmer-hal2"), str(self.main)), "farmer")
        self.assertEqual(role.detect(self.field("tollman-hal2"), str(self.main)), "tollman")

    def test_a_field_is_a_foreman_whatever_its_number(self):
        for name in ("00", "10", "29", "30", "99"):
            self.assertEqual(role.detect(self.field(name), str(self.main)), "foreman", name)

    def test_a_field_holding_plans_lead_is_a_servant_whatever_its_number(self):
        for name in ("05", "30", "99"):
            d = Path(self.field(name))
            (d / "plans").mkdir()
            (d / "plans" / "LEAD").write_text("07 0383-train-rules 16\n")
            self.assertEqual(role.detect(str(d), str(self.main)), "servant", name)

    def test_other_names_are_unknown(self):
        for name in ("1", "100", "feature", "farmer-", "tollman", "a10"):
            self.assertEqual(role.detect(self.field(name), str(self.main)), "unknown", name)
        self.assertEqual(role.detect(None, str(self.main)), "unknown")

    def test_the_main_checkout_is_the_steward(self):
        self.assertEqual(role.detect(str(self.main), str(self.main)), "steward")

    def test_a_link_to_the_main_checkout_is_the_steward_too(self):
        link = self.tmp / "link"
        link.symlink_to(self.main)
        self.assertEqual(role.detect(str(link), str(self.main)), "steward")

    def test_each_place_s_main_checkout_is_its_role(self):
        for want, d in self.places.items():
            self.assertEqual(role.detect(str(d), str(d)), want)

    def test_lord_and_pope_are_detected_not_only_by_role(self):
        self.assertEqual(role.detect(str(self.places["lord"]), str(self.places["lord"])), "lord")
        self.assertEqual(role.detect(str(self.places["pope"]), str(self.places["pope"])), "pope")

    def test_a_field_of_the_village_is_a_foreman(self):
        self.assertEqual(role.detect(self.field("05"), str(self.places["mayor"])), "foreman")

    def test_places_default_under_a(self):
        with mock.patch.dict(os.environ, {"HOME": str(self.tmp)}):
            for env in ("HAL_VILLAGE", "HAL_CITY", "HAL_PLANET"):
                os.environ.pop(env, None)
            self.assertEqual(role.place("mayor"), os.path.realpath(self.tmp / "a/village"))
            self.assertEqual(role.place("lord"), os.path.realpath(self.tmp / "a/city"))
            self.assertEqual(role.place("pope"), os.path.realpath(self.tmp / "a/planet"))
            self.assertEqual(role.village(), role.place("mayor"))

    def test_the_override_wins(self):
        for r in role.ROLES:
            self.assertEqual(role.resolve(r, str(self.main), str(self.main)), r)
        self.assertEqual(role.resolve(None, self.field("31"), str(self.main)), "foreman")

    def test_roles(self):
        self.assertEqual(set(role.ROLES), {"farmer", "foreman", "servant", "steward", "tollman", "mayor", "lord", "pope"})
        self.assertEqual(set(role.PLACES), {"mayor", "lord", "pope"})


if __name__ == "__main__":
    unittest.main()
