import tempfile
import unittest
from pathlib import Path

import collect_images as ci
import dockerfiles
import findings as fx
from testutil import FakeRunner, data, make_farm, ok

DOCKER = ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"]
TART = ["tart", "list", "--format", "json"]


def trivy(image):
    return ci.TRIVY_IMAGE + [image]


class DockerfileParsing(unittest.TestCase):
    def test_from_lines(self):
        images, unresolved = dockerfiles.parse(data("sample-dockerfile.txt"))
        self.assertEqual(images, ["node:22-slim", "rust:1.90", "gcr.io/distroless/cc-debian12"])
        self.assertEqual(unresolved, ["${REGISTRY}/base:1"])

    def test_default_in_expression_and_stage_reference(self):
        images, unresolved = dockerfiles.parse("ARG V\nFROM alpine:${V:-3.20} AS a\nFROM a\n")
        self.assertEqual((images, unresolved), (["alpine:3.20"], []))

    def test_arg_after_from_is_not_visible(self):
        images, unresolved = dockerfiles.parse("FROM alpine:3\nARG V=1\nFROM busybox:$V\n")
        self.assertEqual((images, unresolved), (["alpine:3"], ["busybox:$V"]))

    def test_file_names(self):
        self.assertTrue(all(map(dockerfiles.is_dockerfile, ("Dockerfile", "Dockerfile.ci", "web.Dockerfile"))))
        self.assertFalse(dockerfiles.is_dockerfile("dockerfile-notes.md"))


class Images(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.farm = make_farm(Path(self.tmp.name), "io")
        (self.farm / "api").mkdir()
        (self.farm / "api" / "Dockerfile").write_text(data("sample-dockerfile.txt"))
        (self.farm / "node_modules" / "x").mkdir(parents=True)
        (self.farm / "node_modules" / "x" / "Dockerfile").write_text("FROM ignored:1\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_docker_and_dockerfile_images_are_scanned_once_each(self):
        runner = FakeRunner({
            tuple(DOCKER): ok("node:22-slim\n<none>:<none>\nredis:7\n\n"),
            tuple(trivy("node:22-slim")): ok(data("trivy.json")),
            tuple(trivy("redis:7")): ok('{"Results": []}'),
            tuple(trivy("rust:1.90")): ok('{"Results": []}'),
            tuple(trivy("gcr.io/distroless/cc-debian12")): ok('{"Results": []}'),
        })
        report = fx.Report()
        ci.collect(runner, report, [self.farm])
        scanned = [c[-1] for c in runner.calls if c[:2] == ["trivy", "image"]]
        self.assertEqual(scanned, ["gcr.io/distroless/cc-debian12", "node:22-slim", "redis:7", "rust:1.90"])
        self.assertEqual(len(report.findings), 3)
        self.assertEqual({f.target_kind for f in report.findings}, {"image"})
        self.assertEqual(report.errors, [])
        self.assertTrue(any("REGISTRY" in s["target"] for s in report.skipped))

    def test_missing_tools_are_entries_not_crashes(self):
        report = fx.Report()
        ci.collect(FakeRunner(), report, [self.farm])
        targets = [e["target"] for e in report.errors]
        self.assertEqual(targets, ["docker", "trivy"])
        self.assertEqual(report.errors[1]["message"], "trivy not installed")
        self.assertTrue(any(s["target"] == "tart" for s in report.skipped))

    def test_docker_daemon_down_still_scans_dockerfiles(self):
        runner = FakeRunner({tuple(DOCKER): ok("", 1, "Cannot connect to the Docker daemon"),
                             tuple(trivy("rust:1.90")): ok('{"Results": []}'),
                             tuple(trivy("node:22-slim")): ok('{"Results": []}'),
                             tuple(trivy("gcr.io/distroless/cc-debian12")): ok('{"Results": []}')})
        report = fx.Report()
        ci.collect(runner, report, [self.farm])
        self.assertIn("Cannot connect", report.errors[0]["message"])
        self.assertIn(trivy("rust:1.90"), runner.calls)

    def test_a_failing_scan_is_an_error_and_the_rest_goes_on(self):
        runner = FakeRunner({tuple(DOCKER): ok(""), tuple(trivy("node:22-slim")): ok("", 1, "db error"),
                             tuple(trivy("rust:1.90")): ok('{"Results": []}'),
                             tuple(trivy("gcr.io/distroless/cc-debian12")): ok('{"Results": []}')})
        report = fx.Report()
        ci.collect(runner, report, [self.farm])
        self.assertEqual([e["target"] for e in report.errors], ["node:22-slim"])


class Vms(unittest.TestCase):
    def test_vm_needs_a_mount_else_is_skipped(self):
        runner = FakeRunner({tuple(DOCKER): ok(""), tuple(TART): ok(data("tart.json")),
                             tuple(ci.TRIVY_ROOTFS + ["/Volumes/vm1"]): ok(data("trivy.json"))})
        report = fx.Report()
        ci.collect(runner, report, [], {"hal2/ci-runner-macos": "/Volumes/vm1"})
        self.assertEqual({f.target_kind for f in report.findings}, {"vm"})
        self.assertEqual({f.target for f in report.findings}, {"hal2/ci-runner-macos"})
        report = fx.Report()
        ci.collect(FakeRunner({tuple(DOCKER): ok(""), tuple(TART): ok(data("tart.json"))}), report, [])
        self.assertEqual(report.skipped, [{"target": "hal2/ci-runner-macos", "why": ci.VM_NEEDS}])
        self.assertEqual(report.findings, [])  # the OCI base image is not a local VM

    def test_tart_output_not_json(self):
        report = fx.Report()
        ci.collect(FakeRunner({tuple(DOCKER): ok(""), tuple(TART): ok("nope")}), report, [])
        self.assertEqual(report.errors[0]["target"], "tart")


if __name__ == "__main__":
    unittest.main()
