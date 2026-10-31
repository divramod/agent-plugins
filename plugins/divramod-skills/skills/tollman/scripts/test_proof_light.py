"""Hal2 plan 0490 step 8: the light checks proof_light adds to a car's proof, each replaying its learning's train
(L54, L61, L100, L102, L119, L126), over test_proof's temporary barn `main`, crop `06` and field. git runs for real;
every other command is faked and counted by its check's name."""

import subprocess
import unittest
from pathlib import Path

import proof
import proof_keys
import proof_light
from test_proof import Field

HALVERSE = 'id = "hal2.halverse"\n[[contributes.commands]]\nid = "hal2.halverse.find"\nkeys = ["cmd-shift-f2"]\n'
TYPING = 'id = "hal2.typing"\n[[contributes.commands]]\nid = "hal2.typing.start"\nkeys = ["shift-command-F2"]\n'
APP = '[{"command": "home.dashboard.resize", "keys": "s", "when": "dashboard"}]\n'
COUNTER = '''import re
OWNERS = ("code/rust/libs/hal2-secrets/",)
ENV_FILE = re.compile(r"(?<![\\w.$-])\\.env(?![\\w.(-])")
def is_test(name):
    return name.split("/")[-1].startswith("test_")
def counted(line):
    return not line.lstrip().startswith("//") and ENV_FILE.search(line) is not None
'''


class Light(Field):
    def setUp(self):
        super().setUp()
        self.gits = []

    def run_(self, argv, cwd):
        """git for real (its verb kept); a check is named by its command and answers from `answers`."""
        if argv[0] == "git":
            self.gits.append(argv[1])
            return proof.sh(argv, cwd)
        tool = argv[1] if argv[0] == "python3" else argv[0]
        name = next((n for k, n in (("names-inventory", "names"), ("check-plugins", "skills"), ("hal2-cli-records",
                     "records"), ("hal2-cli-state", "state"), ("env-readers", "env-readers")) if k in tool), tool)
        self.calls.append(name)
        return self.answers.get(name, (0, "ok"))

    def restock(self, files):
        """The barn moves on with `files` after the crop left it."""
        self.g("checkout", "-q", "main")
        self.commit(files)
        self.g("checkout", "-q", "06")


class Refused(Light):
    def test_records_exit_10_waits_with_the_refusal_and_is_not_kept(self):
        """L54, train 8: car 07's head pinned checker >=0.8.0, the installed records check exited 10 and the car rode."""
        self.names_script()
        head = self.commit({"plans/0376-x/plan.md": "x\n"})
        self.answers["records"] = (10, "error: this binary 0.7.9 is older than the repository's checker >=0.8.0")
        v = self.verdict(head)
        self.assertEqual(v["state"], "wait")
        self.assertIn("refused (exit 10", v["lines"][0])
        self.assertIn("checker >=0.8.0", v["lines"][0])
        self.assertEqual(list(self.cache.glob("*.json")), [], "a refusal is looked at again next round")

    def test_a_red_finding_wins_over_a_refusal(self):
        self.names_script()
        head = self.commit({"plans/0376-x/plan.md": "the slot\n"})
        self.answers["records"] = (10, "too old")
        self.answers["names"] = (1, "plans/0376-x/plan.md:1: slot - use worktree")
        self.assertEqual(self.verdict(head)["state"], "red")


class Untouched(Light):
    def test_a_crop_touching_no_input_starts_no_new_process(self):
        """D9: the train's path is unchanged for a crop none of the new checks reads."""
        self.restock({proof_light.CEILINGS["env-readers"]: COUNTER})
        self.g("merge", "-q", "main")
        self.names_script()
        head = self.commit({"code/rust/b.rs": "fn b() {}\n", "code/rust/c.toml": "a = 1\n"})
        v = self.verdict(head)
        self.assertEqual((v["state"], v["checks"], self.calls), ("green", ["names"], ["names"]))
        self.assertEqual(self.gits, ["rev-parse", "diff", "-c"], "rev-parse, the crop's diff, its status: as before")


class Keys(Light):
    """L61, train 8: car 50's new typing plugin took cmd-shift-f2, held by the barn's halverse plugin."""

    def test_a_new_plugin_key_held_by_the_barn_is_red_on_the_crops_manifest(self):
        self.names_script()
        self.restock({"code/rust/libs/hal2-halverse-node/hal2-plugin.toml": HALVERSE, proof_keys.APP_KEYS: APP})
        self.g("merge", "-q", "main")
        head = self.commit({"code/rust/libs/hal2-typing-node/hal2-plugin.toml": TYPING})
        v = self.verdict(head)
        self.assertEqual((v["state"], v["checks"]), ("red", ["names", "keys", "state"]), "a manifest is a state declaration too")
        self.assertEqual(v["lines"], ["keys: code/rust/libs/hal2-typing-node/hal2-plugin.toml: key cmd-shift-f2 "
                                      "(everywhere): held by hal2.halverse hal2.halverse.find and hal2.typing "
                                      "hal2.typing.start; take a free key (L61, plugin_keys)"])

    def test_the_barns_key_taken_after_the_car_left_is_read_from_the_barn(self):
        self.names_script()
        head = self.commit({"code/rust/libs/hal2-typing-node/hal2-plugin.toml": TYPING})
        self.restock({"code/rust/libs/hal2-halverse-node/hal2-plugin.toml": HALVERSE})
        v = self.verdict(head)
        self.assertEqual(v["state"], "red", "the trial merge holds both")
        self.assertIn("show", self.gits)

    def test_a_clash_between_barn_files_is_not_the_cars(self):
        other = HALVERSE.replace("halverse", "other")
        self.restock({"code/rust/libs/hal2-halverse-node/hal2-plugin.toml": HALVERSE,
                      "code/rust/libs/hal2-other-node/hal2-plugin.toml": other})
        self.g("merge", "-q", "main")
        self.names_script()
        head = self.commit({"code/rust/libs/hal2-typing-node/hal2-plugin.toml": TYPING.replace("F2", "F3")})
        self.assertEqual(self.verdict(head)["state"], "green")

    def test_sequences_and_when_compare_as_the_rust_check_does(self):
        self.assertEqual(proof_keys.sequence("Command-Shift-F2 ctrl-esc"), "cmd-shift-f2 ctrl-escape")
        self.assertEqual(proof_keys.sequence("cmd--"), "cmd--")
        keys = [proof_keys.held("a", "p", "p.x", "s", "dashboard"), proof_keys.held("b", "q", "q.y", "s", "queue")]
        self.assertEqual(proof_keys.conflicts(keys, {"a"}), [], "different contexts do not clash")
        keys[1]["when"] = None
        self.assertEqual(len(proof_keys.conflicts(keys, {"a"})), 1, "a key without `when` holds everywhere")


class Skills(Light):
    SKILL = "code/agents/apps/skills/skills/roles/newone/SKILL.md"

    def test_a_new_skill_runs_check_plugins_and_its_error_is_the_cars(self):
        """L100, train 12: car 12 added a skill without regenerating the shortcut skills."""
        self.names_script()
        script = Path(self.d) / "code/agents/apps/skills/scripts/check-plugins.py"
        script.parent.mkdir(parents=True)
        script.write_text("")
        head = self.commit({self.SKILL: "---\nname: newone\n---\n"})
        self.answers["skills"] = (1, "error: shortcut skills are out of date: run scripts/gen-aliases.py")
        v = self.verdict(head)
        self.assertEqual((v["state"], self.calls), ("red", ["names", "records", "skills"]))
        self.assertEqual(v["lines"], [f"skills: {self.SKILL}: check-plugins: shortcut skills are out of date: run "
                                      "scripts/gen-aliases.py"])

    def test_a_plugin_without_check_plugins_is_skipped(self):
        self.names_script()
        head = self.commit({self.SKILL: "x\n"})
        v = self.verdict(head)
        self.assertEqual((v["state"], v["skipped"]), ("green", ["skills"]))


class Ceilings(Light):
    """L102, train 24: car 13 added a .env reader in hal2-host-runner's hooks.rs, env-readers 135 > ceiling 134."""

    def setUp(self):
        super().setUp()
        self.restock({proof_light.CEILINGS["env-readers"]: COUNTER,
                      "code/rust/apps/r/hooks.rs": 'let a = "~/a/hal2/.env";\n'})
        self.g("merge", "-q", "main")
        self.names_script()
        self.answers["env-readers"] = (1, "env-readers: 135 code lines name a .env file, the ceiling is 134: ...")

    def test_an_added_counted_line_over_the_ceiling_is_red_on_its_file(self):
        head = self.commit({"code/rust/apps/r/hooks.rs": 'let a = "~/a/hal2/.env";\nlet b = dir.join(".env");\n'})
        v = self.verdict(head)
        self.assertEqual((v["state"], self.calls), ("red", ["names", "env-readers"]))
        self.assertTrue(v["lines"][0].startswith("env-readers: code/rust/apps/r/hooks.rs: adds a line env-readers "
                                                 "counts and the count passes its ceiling (env-readers: 135"), v)

    def test_a_file_whose_counted_line_came_from_the_barn_runs_no_counter(self):
        head = self.commit({"code/rust/apps/r/hooks.rs": 'let a = "~/a/hal2/.env";\nfn x() {}\n'})
        v = self.verdict(head)
        self.assertEqual((v["state"], self.calls), ("green", ["names"]))
        self.assertEqual(self.gits.count("diff"), 2, "one diff of the crop's files, one of its added lines")

    def test_hal2s_own_counters_load(self):
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=Path(__file__).parent, text=True,
                             capture_output=True).stdout.strip()
        for check in proof_light.CEILINGS:
            module = proof_light.counter(top, check)
            self.assertIsNotNone(module, check)
            line = 'p = "~/.config/' + 'hal2/.env"'  # split: the repo's own root count must not see test data
            self.assertTrue(proof_light.counts(module, "code/rust/apps/x/src/a.rs", line))
            self.assertFalse(proof_light.counts(module, "code/rust/apps/x/README.md", line))


class Nodes(Light):
    """L119, train 25-13: six cars' new node plugin services were not in hub-core's NODE_PACKAGES."""

    ROUTES = 'pub(crate) const NODE_PACKAGES: &[&str] = &[\n    "hal2.node.",\n];\n'

    def setUp(self):
        super().setUp()
        self.restock({proof_light.ROUTES: self.ROUTES})
        self.g("merge", "-q", "main")
        self.names_script()
        self.crop = {"code/protobuf/hal2/remarkable/v1/remarkable.proto": "syntax = \"proto3\";\n",
                     "code/rust/libs/hal2-remarkable-node/Cargo.toml": "[package]\n"}

    def test_a_new_node_package_missing_from_node_packages_is_red(self):
        v = self.verdict(self.commit(self.crop))
        self.assertEqual((v["state"], v["checks"], self.calls), ("red", ["names", "nodes"], ["names"]))
        self.assertIn('add "hal2.remarkable." there', v["lines"][0])

    def test_listed_in_the_field_or_in_the_barn_rides(self):
        listed = self.ROUTES.replace('"hal2.node.",', '"hal2.node.",\n    "hal2.remarkable.",')
        self.assertEqual(self.verdict(self.commit({**self.crop, proof_light.ROUTES: listed}))["state"], "green")
        self.g("checkout", "-q", "-b", "07", "main")
        head = self.commit(self.crop)
        self.restock({proof_light.ROUTES: listed})
        self.g("checkout", "-q", "07")
        self.assertEqual(self.verdict(head)["state"], "green", "the barn listed it after the car left")

    def test_a_proto_package_without_a_node_crate_is_not_judged(self):
        v = self.verdict(self.commit({"code/protobuf/hal2/billing/v1/b.proto": "x\n"}))
        self.assertEqual((v["state"], v["checks"]), ("green", ["names", "nodes"]))


class State(Light):
    """L126, train 27: car 09's access.toml why.processes ran over 240 chars; the proof had passed it."""

    ACCESS = "code/rust/apps/x/access.toml"

    def test_a_problem_in_the_crops_declaration_is_red(self):
        self.names_script()
        head = self.commit({self.ACCESS: "[unit]\n"})
        self.answers["state"] = (10, f"error: 2 problems:\n  {self.ACCESS}: why.processes is 280 chars, at most 240\n"
                                     "  code/rust/apps/other/access.toml: unknown key")
        v = self.verdict(head)
        self.assertEqual((v["state"], self.calls), ("red", ["names", "state"]))
        self.assertEqual(v["lines"], [f"state: {self.ACCESS}: why.processes is 280 chars, at most 240"])

    def test_a_problem_elsewhere_is_not_the_cars(self):
        self.names_script()
        head = self.commit({self.ACCESS: "[unit]\n"})
        self.answers["state"] = (10, "error: 1 problems:\n  designs/state/state-map.toml: not the map")
        self.assertEqual(self.verdict(head)["state"], "green")


if __name__ == "__main__":
    unittest.main()
