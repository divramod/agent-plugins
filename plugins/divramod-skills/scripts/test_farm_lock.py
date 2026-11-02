"""farm_lock: a farm lock names its holder (hal2 plan 0561); the record is the one hal2_core::farm_lock writes
(the shared JSON fixture), a waiter never wipes it, the probe names a holder only while its pid is the one that
wrote it, the exclusive-create lock of the daybook is stale by its dead holder, not by age."""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import farm_lock

HERE = Path(__file__).resolve().parent
FIXTURE = HERE.parents[3] / "rust" / "libs" / "hal2-core" / "tests" / "fixtures" / "farm_lock.json"

HOLDER = r"""
import sys
sys.path.insert(0, sys.argv[1])
import farm_lock
with farm_lock.hold(sys.argv[2], wait=float(sys.argv[3]) if len(sys.argv) > 3 else None):
    print("held", flush=True)
    sys.stdin.readline()
"""


def holder(test, path, *extra):
    """A child that takes the lock at `path`, says "held" and keeps it until its stdin gets a line; killed and its
    pipes closed when the test ends."""
    child = subprocess.Popen([sys.executable, "-c", HOLDER, str(HERE), str(path), *extra], text=True,
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    def end():
        child.kill()
        child.wait()
        child.stdin.close()
        child.stdout.close()

    test.addCleanup(end)
    return child


def release(child):
    try:
        child.stdin.write("\n")
        child.stdin.flush()
    except BrokenPipeError:
        pass
    child.wait(timeout=10)


class Record(unittest.TestCase):
    @unittest.skipUnless(FIXTURE.is_file(), "the Rust fixture is not beside this unit (a published copy)")
    def test_the_line_is_what_the_rust_fixture_pins(self):
        fixture = json.loads(FIXTURE.read_text())
        self.assertEqual(fixture["schema"], 1)
        for record in fixture["records"]:
            self.assertEqual(farm_lock.line(record["pid"], farm_lock.epoch(record["taken"])), record["line"] + "\n")
            parsed = farm_lock.parse(record["line"])
            self.assertEqual((parsed["pid"], parsed["taken"]), (record["pid"], record["taken"]))
        for text in fixture["refused"]:
            self.assertIsNone(farm_lock.parse(text), text)

    def test_the_line_is_compact_whole_seconds_with_z_and_a_newline(self):
        text = farm_lock.line(7, 1793480823.9)
        self.assertEqual(text, '{"schema":1,"pid":7,"taken":"2026-10-31T21:07:03Z"}\n')

    def test_a_reused_pid_is_not_the_holder(self):
        record = farm_lock.parse(farm_lock.line(5, 1000))
        self.assertTrue(farm_lock.trusts(record, 990))
        self.assertTrue(farm_lock.trusts(record, 1000 + farm_lock.START_SLACK_S))
        self.assertFalse(farm_lock.trusts(record, 1000 + farm_lock.START_SLACK_S + 1))
        for start in (None, 0, farm_lock.UNKNOWN):
            self.assertFalse(farm_lock.trusts(record, start))

    def test_a_process_start_is_read_by_ps(self):
        start = farm_lock.pid_start(os.getpid())
        self.assertIsInstance(start, int)
        self.assertLessEqual(start, int(time.time()) + 1)
        self.assertIsNone(farm_lock.pid_start(2 ** 22 + 12345))


class Hold(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "farm" / "plan-numbers.json.lock"

    def test_a_held_lock_names_its_holder_and_a_free_one_nobody(self):
        self.assertEqual(farm_lock.probe(self.path), (False, None))
        self.assertFalse(self.path.parent.exists(), "a probe never creates")
        with farm_lock.hold(self.path):
            self.assertEqual(self.path.read_text(), farm_lock.line())
            self.assertEqual(oct(self.path.stat().st_mode & 0o777), "0o600")
        self.assertEqual(farm_lock.probe(self.path), (False, None))

    def test_the_probe_of_another_process_names_the_holder_pid(self):
        child = holder(self, self.path)
        self.assertEqual(child.stdout.readline().strip(), "held")
        found = farm_lock.probe(self.path)
        self.assertTrue(found.held)
        self.assertEqual(found.record["pid"], child.pid)
        release(child)
        self.assertEqual(farm_lock.probe(self.path), (False, None))

    def test_a_waiter_does_not_wipe_the_holders_record(self):
        child = holder(self, self.path)
        child.stdout.readline()
        before = self.path.read_text()
        with self.assertRaises(TimeoutError):
            farm_lock.hold(self.path, wait=0.2)
        self.assertEqual(self.path.read_text(), before)
        self.assertEqual(json.loads(before)["pid"], child.pid)
        release(child)

    def test_a_waiter_gets_the_lock_when_the_holder_ends_and_names_itself(self):
        child = holder(self, self.path)
        child.stdout.readline()
        waiter = holder(self, self.path, "30")
        time.sleep(0.2)
        self.assertEqual(json.loads(self.path.read_text())["pid"], child.pid)
        release(child)
        self.assertEqual(waiter.stdout.readline().strip(), "held")
        self.assertEqual(farm_lock.probe(self.path).record["pid"], waiter.pid)
        release(waiter)

    def test_a_killed_holder_drops_the_lock_and_its_stale_line_names_nobody(self):
        child = holder(self, self.path)
        child.stdout.readline()
        child.kill()
        child.wait(timeout=10)
        self.assertEqual(farm_lock.probe(self.path), (False, None))
        with farm_lock.hold(self.path, wait=1):
            self.assertEqual(json.loads(self.path.read_text())["pid"], os.getpid())

    def test_a_pid_that_started_after_the_record_is_an_unnamed_holder(self):
        child = holder(self, self.path)
        child.stdout.readline()
        late = farm_lock.probe(self.path, start_of=lambda pid: int(time.time()) + 3600)
        self.assertEqual(late, (True, None))
        none = farm_lock.probe(self.path, start_of=lambda pid: None)
        self.assertEqual(none, (True, None))
        release(child)

    def test_a_release_empties_the_record_so_a_later_unnamed_holder_names_nobody(self):
        with farm_lock.hold(self.path):
            pass
        self.assertEqual(self.path.read_text(), "", "emptied while still held (D15)")
        fd = farm_lock.open_lock(self.path)  # an older taker: the lock, no record
        try:
            farm_lock.lock(fd)
            self.assertEqual(farm_lock.probe(self.path), (True, None), "never the old holder")
        finally:
            os.close(fd)
        fd = farm_lock.open_lock(self.path)
        farm_lock.lock(fd)
        farm_lock.name(fd)
        farm_lock.release(fd)
        self.assertEqual(self.path.read_text(), "", "the low-level release empties it too")

    def test_a_take_is_announced_until_its_release(self):
        intent = Path(f"{self.path}.{os.getpid()}")
        with farm_lock.hold(self.path):
            self.assertTrue(intent.exists(), "announced before the take (D16)")
            self.assertEqual(json.loads(intent.read_text())["pid"], os.getpid())
        self.assertFalse(intent.exists(), "withdrawn after the release")
        child = holder(self, self.path)
        child.stdout.readline()
        waiter = holder(self, self.path, "30")
        waiting = Path(f"{self.path}.{waiter.pid}")
        deadline = time.monotonic() + 5
        while not waiting.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(waiting.exists(), "a waiter is announced too")
        with self.assertRaises(TimeoutError):
            farm_lock.hold(self.path, wait=0.05)
        self.assertFalse(intent.exists(), "a take that timed out withdraws it")
        release(child)
        self.assertEqual(waiter.stdout.readline().strip(), "held")
        release(waiter)
        deadline = time.monotonic() + 5
        while waiting.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertFalse(waiting.exists(), "the waiter's goes with its release")

    def test_nested_announcements_of_one_lock_go_with_the_last(self):
        self.path.parent.mkdir(parents=True)
        first = farm_lock.intend(self.path)
        second = farm_lock.intend(self.path)
        self.assertEqual(first, second)
        farm_lock.unintend(first)
        self.assertTrue(os.path.exists(first), "the other take still announces it")
        farm_lock.unintend(second)
        self.assertFalse(os.path.exists(first))

    def test_the_lock_is_released_when_the_with_ends_even_by_an_error(self):
        with self.assertRaises(ValueError):
            with farm_lock.hold(self.path):
                raise ValueError("boom")
        with farm_lock.hold(self.path, wait=0.5):
            pass


class Exclusive(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, ".daybook.lock")

    def test_the_file_holds_the_record_and_is_taken_once(self):
        self.assertTrue(farm_lock.create_exclusive(self.path))
        self.assertFalse(farm_lock.create_exclusive(self.path))
        self.assertEqual(json.loads(Path(self.path).read_text())["pid"], os.getpid())

    def test_the_create_is_announced_only_until_the_record_is_written(self):
        intent = f"{self.path}.{os.getpid()}"
        self.assertTrue(farm_lock.create_exclusive(self.path))
        self.assertFalse(os.path.exists(intent), "the record names the holder now")
        self.assertFalse(farm_lock.create_exclusive(self.path))
        self.assertFalse(os.path.exists(intent), "a failed take withdraws it")

    def test_a_live_holder_keeps_its_lock_however_old_it_is(self):
        farm_lock.create_exclusive(self.path)
        old = time.time() - 3600
        os.utime(self.path, (old, old))
        self.assertFalse(farm_lock.exclusive_stale(self.path, 60))

    def test_a_dead_holder_or_a_reused_pid_leaves_a_stale_lock_at_once(self):
        farm_lock.create_exclusive(self.path)
        self.assertTrue(farm_lock.exclusive_stale(self.path, 60, start_of=lambda pid: None))
        self.assertTrue(farm_lock.exclusive_stale(self.path, 60, start_of=lambda pid: int(time.time()) + 3600))

    def test_a_file_without_a_record_is_stale_by_age_only(self):
        Path(self.path).write_text("")
        self.assertFalse(farm_lock.exclusive_stale(self.path, 60))
        old = time.time() - 61
        os.utime(self.path, (old, old))
        self.assertTrue(farm_lock.exclusive_stale(self.path, 60))

    def test_where_a_start_cannot_be_read_the_age_decides(self):
        farm_lock.create_exclusive(self.path)
        self.assertFalse(farm_lock.exclusive_stale(self.path, 60, start_of=lambda pid: farm_lock.UNKNOWN))
        old = time.time() - 61
        os.utime(self.path, (old, old))
        self.assertTrue(farm_lock.exclusive_stale(self.path, 60, start_of=lambda pid: farm_lock.UNKNOWN))

    def test_a_missing_file_is_not_stale(self):
        self.assertFalse(farm_lock.exclusive_stale(self.path, 60))


if __name__ == "__main__":
    unittest.main()
