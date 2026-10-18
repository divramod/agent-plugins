"""Tests of `halverse.py christen|rechristen|swap|move|avatar|who` on a fake CLI (plan 0283 step 4; every name invented)."""
import json
import unittest

import fake_cli


class Names(fake_cli.InFolder):
    def setUp(self):
        super().setUp()
        self.use(fake_cli.NAMES)

    def test_christen_with_a_name(self):
        code, out, err = self.main("christen", "Mira", "--field", "/farms/barley/wt/07", "--avatar", "12")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("christened Mira, foreman of barley field 07, avatar 12", out)
        self.assertEqual(self.args(), ["names christen Mira --field /farms/barley/wt/07 --avatar 12 --json"])

    def test_christen_json_is_the_clis_data(self):
        code, out, _ = self.main("christen", "Mira", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["named"][0]["name"], "Mira")

    def test_christen_without_a_name_lists_the_ideas(self):
        code, out, _ = self.main("christen", "--field", "/farms/barley/wt/07")
        self.assertEqual(code, 0)
        self.assertEqual(self.args(), ["names ideas --count 20 --json"])
        self.assertIn("20 name ideas", out)
        self.assertIn(" 1. Aino", out)
        self.assertIn("20. Teo", out)
        self.assertIn("halverse.py christen <name> --field /farms/barley/wt/07", out)

    def test_rechristen_swap_move_avatar(self):
        self.assertIn("rechristened Mira", self.main("rechristen", "Odd", "Mira")[1])
        out = self.main("swap", "Mira", "Ilse")[1]
        self.assertIn("swapped Ilse, foreman of barley field 07", out)
        self.assertIn("swapped Mira, foreman of barley field 09", out)
        self.assertIn("moved Mira, foreman of meadow field 02", self.main("move", "Mira", "--to", "/farms/meadow/wt/02")[1])
        self.assertIn("gave a new avatar to Mira, foreman of barley field 07, avatar 40", self.main("avatar", "Mira", "40")[1])
        self.assertEqual(self.args(), ["names rechristen Odd Mira --json", "names swap Mira Ilse --json",
                                       "names move Mira --to /farms/meadow/wt/02 --json", "names avatar Mira 40 --json"])

    def test_rechristen_without_the_new_name_lists_ideas(self):
        code, out, _ = self.main("rechristen", "Mira")
        self.assertEqual(code, 0)
        self.assertIn("halverse.py rechristen Mira <new name>", out)

    def test_a_name_in_use_is_refused_with_its_holder(self):
        code, out, err = self.main("christen", "Taken")
        self.assertEqual((code, out), (4, ""))
        self.assertIn("Refused (NAME_IN_USE): Mira is the foreman of barley field 07 since 2026-10-14.", err)
        self.assertIn("A name is given only once.", err)
        self.assertIn("Nothing was changed.", err)

    def test_a_reserved_name_names_its_holder_and_place(self):
        code, _, err = self.main("christen", "Odd")
        self.assertEqual(code, 4)
        self.assertIn("Odd was a name of Mira until 2026-10-14", err)
        self.assertIn("The holder is Mira, the foreman of barley field 07.", err)

    def test_who_of_a_posted_name_gives_farm_field_and_the_way_to_it(self):
        code, out, _ = self.main("who", "Mira")
        self.assertEqual(code, 0)
        self.assertEqual(self.args(), ["names lookup Mira --json"])
        self.assertIn("Posted now: the foreman of barley field 07 since 2026-10-14, plans 0042-sample-plan.", out)
        self.assertIn("Farm: barley. Field: 07. Folder: /farms/barley/wt/07", out)
        self.assertIn("ListAgents shows the session of barley field 07", out)
        self.assertIn("Earlier name Odd: 2026-10-12 to 2026-10-14.", out)

    def test_who_by_an_earlier_name(self):
        code, out, _ = self.main("who", "Odd")
        self.assertEqual(code, 0)
        self.assertIn("Mira, foreman of barley field 07, avatar 12 (found by an earlier name)", out)

    def test_who_of_a_name_not_posted_now(self):
        code, out, _ = self.main("who", "Tove")
        self.assertEqual(code, 0)
        self.assertIn("Tove, at no field, avatar 31", out)
        self.assertIn("Not posted now. Last posting: the servant of barley field 03, 2026-10-01 to 2026-10-10, "
                      "plans 0040-old-plan, 0041-next-plan.", out)
        self.assertNotIn("ListAgents", out)

    def test_who_of_an_unknown_name_exits_3(self):
        code, out, err = self.main("who", "nobody")
        self.assertEqual((code, out), (3, ""))
        self.assertIn("nobody is named nobody", err)
        self.assertIn("`/hv who <name>` finds one", err)

    def test_the_cli_is_missing(self):
        import os
        os.remove(self.path)
        code, out, err = self.main("who", "Mira")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("not installed", err)

    def test_the_cli_answers_what_the_skill_cannot_read(self):
        self.answer("not json", 1)
        code, _, err = self.main("who", "Mira")
        self.assertEqual(code, 1)
        self.assertIn("cannot read", err)


if __name__ == "__main__":
    unittest.main()
