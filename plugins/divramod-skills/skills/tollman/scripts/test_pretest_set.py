"""Hal2 plan 0522 D8: the pretest's job set pinned against the gate. Every job `gate/main.sh list` names is either in
`.github/hal2-pretest.toml` (the pretest runs it on the train's candidate) or named here as heavy, with the reason it
does not run on the Mac; a new gate job is a red test here until it is placed, never a red train. Reads the real
repository's config and gate (`gate list` reads job files only: no build, no job runs)."""

import subprocess
import unittest
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import pretest

ROOT = next(p for p in Path(__file__).resolve().parents if (p / pretest.GATE).is_file())
NONE = "lane none: no land run runs it, only a production pipeline"
HEAVY = {
    "agents-test": "CI 286 s (each changed plugin's suites and bats): past the budget",
    "bash-test-docker": "Docker, CI 66 s",
    "ci-rules": "Linux only (`# systems: linux`), like leak-scan (plan 0532)",
    "bash-test-linux": "a Linux build, CI 94-477 s",
    "bash-test": "the macOS VM's suites, CI 94-477 s",
    "desktop-e2e": "the hub stack's e2e: never on the Mac",
    "hub-build": "the hub stack's build: never on the Mac",
    "hub-e2e": "the hub stack's e2e: never on the Mac",
    "leak-scan": "Linux only (`# systems: linux`), the candidate's hal2-cli-git; the pre-push hook runs it",
    "n8n-e2e": "the hub stack's e2e: never on the Mac",
    "node-web-e2e": "the hub stack's e2e: never on the Mac",
    "records-check": "builds five CLIs cold in every train's field, cut at the budget (plan 0490 step 17, 0522 D22)",
    "python-test": "CI 24 s, here 248 s: past the budget",
    "rust-budget-linux": "timing tests alone on the quiet server (lane `quiet`, plan 0532)",
    "rust-build-linux": "a cargo build: the tollman builds nothing (plan 0467 D21)",
    "rust-build-mac": "a cargo build: the tollman builds nothing (plan 0467 D21)",
    "rust-build-test-fixtures": "a cargo build: the tollman builds nothing (plan 0467 D21)",
    "rust-lint": "clippy compiles every affected crate, CI 82 s",
    "rust-test": "cargo builds and tests: never on the Mac",
    "ts-budget-linux": "timing tests alone on the quiet server (lane `quiet`, plan 0532)",
    "ts-check-plugins": "its validator is the installed main's hal2-daemon, not the candidate's: may differ from CI",
    "ts-test": "CI 96 s, the suites of every TypeScript unit",
    "web-e2e": "the hub stack's e2e: never on the Mac",
    "web-lighthouse": "the hub stack's measure: never on the Mac",
    "web-plugins-e2e": "the hub stack's e2e: never on the Mac",
    **{job: NONE for job in (
        "desktop-e2e-mac", "desktop-e2e-windows", "mac-check-vm-runner", "rust-build-apps-linux",
        "rust-build-apps-windows", "rust-bundle-apps-linux", "rust-bundle-apps-windows", "rust-check-apps-mac",
        "rust-check-apps-windows", "rust-test-mac", "rust-test-windows",
        "ts-bundle-desktop-linux", "ts-bundle-desktop-mac", "ts-bundle-desktop-windows", "ts-bundle-mobile-android",
        "ts-bundle-mobile-ios", "ts-lint-windows", "ts-test-mac", "ts-test-windows")},
}


def gate(*args: str) -> set[str]:
    p = subprocess.run(["bash", str(ROOT / pretest.GATE), *args], cwd=ROOT, capture_output=True, text=True,
                       timeout=60, check=True)
    return set(p.stdout.split())


class JobSet(unittest.TestCase):
    def setUp(self):
        cfg, why = pretest.read_config(ROOT / pretest.CONFIG, switch=False)  # the job set, whether the pretest is on or off
        self.assertIsNotNone(cfg, why)
        self.listed = set(cfg["jobs"])

    def test_every_gate_job_is_pretested_or_named_heavy_with_a_reason(self):
        jobs = gate("list")
        self.assertEqual(sorted(jobs - self.listed - set(HEAVY)), [], "a gate job neither pretested nor named heavy")
        self.assertEqual(sorted(self.listed & set(HEAVY)), [], "pretested and named heavy")
        self.assertEqual(sorted((self.listed | set(HEAVY)) - jobs), [], "no such gate job")
        self.assertTrue(all(len(why) > 10 for why in HEAVY.values()), "every heavy job says why")

    def test_the_light_jobs_of_train_32_are_pretested(self):
        # train 32's reds that a Mac can see: lint (its ts-lint), lua-test; agents-test and records-check (a cold
        # five-CLI build, plan 0490 step 17) are heavy
        self.assertLessEqual({"ts-lint", "lua-test", "python-lint", "bash-lint", "lua-lint", "protobuf-lint"},
                             self.listed)
        self.assertIn("records-check", HEAVY)
        self.assertLessEqual(gate("list", "lint") - {"leak-scan", "ci-rules"}, self.listed, "every lint job but the Linux-only ones")


if __name__ == "__main__":
    unittest.main()
