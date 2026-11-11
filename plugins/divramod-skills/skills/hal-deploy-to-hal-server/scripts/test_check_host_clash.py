import unittest

from checks import host_clash


def ctx(hosts, zone="z", static=True):
    return {"site": "app", "container": {}, "inspect": None, "hosts": hosts, "zone": zone,
            "other_sites": [{"name": "diktier", "zone": "z", "hosts": ["diktier", "x"], "static": static}]}


class HostClashTest(unittest.TestCase):
    def test_a_shared_host_names_the_one_commit_move(self):
        found = host_clash.run(ctx(["diktier"]))
        self.assertEqual(found[0]["severity"], "error")
        self.assertIn("static site diktier", found[0]["detail"])
        self.assertIn("one commit", found[0]["detail"])

    def test_another_host_or_zone_passes(self):
        self.assertEqual(host_clash.run(ctx(["other"])), [])
        self.assertEqual(host_clash.run(ctx(["diktier"], zone="y")), [])

    def test_without_other_sites_it_finds_nothing(self):
        self.assertEqual(host_clash.run({"site": "demo", "container": {}, "inspect": None}), [])


if __name__ == "__main__":
    unittest.main()
