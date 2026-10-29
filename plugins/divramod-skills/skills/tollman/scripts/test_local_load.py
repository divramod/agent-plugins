"""Plan 0472 step 4: the train's local phase costs (local_load.py), with fake probes: no real sleep, no load added."""

import unittest

import local_load


def reader(rows):
    """Probes in order: (seconds, load1, ops)."""
    it = iter(rows)

    def read():
        t, load, ops = next(it)
        return {"at": float(t), "utc": f"2026-10-29T10:{int(t) // 60:02d}:{int(t) % 60:02d}Z", "load1": load, "ops": ops}
    return read


class PhaseTest(unittest.TestCase):
    def run_phase(self, rows, ticks=0):
        phase = local_load.Phase(reader(rows), thread=False)
        with phase:
            for _ in range(ticks):
                phase.mark("tick")
        return phase.record()

    def test_start_mid_end_with_rates_and_the_peak(self):
        rec = self.run_phase([(0, 2.0, 1000), (60, 5.0, 7000), (120, 20.0, 19000), (180, 9.0, 19600), (200, 3.0, 19680)],
                             ticks=3)
        self.assertEqual([m["t"] for m in rec["marks"]], ["start", "mid", "end"])
        self.assertEqual(rec["marks"][1]["load1"], 20.0, "the tick nearest the middle (100 s of 200)")
        self.assertEqual([m["ops_s"] for m in rec["marks"]], [None, 150.0, 8.5])
        self.assertEqual((rec["seconds"], rec["load_peak"], rec["disk_ops_s"]), (200.0, 20.0, 93.4))

    def test_a_short_phase_has_no_mid(self):
        rec = self.run_phase([(0, 1.0, 10), (30, 2.0, 70)])
        self.assertEqual([m["t"] for m in rec["marks"]], ["start", "end"])
        self.assertEqual(rec["disk_ops_s"], 2.0)

    def test_without_disk_counters_ops_are_null(self):
        rec = self.run_phase([(0, 1.0, None), (10, 4.0, None)])
        self.assertEqual((rec["disk_ops_s"], rec["load_peak"], rec["marks"][1]["ops_s"]), (None, 4.0, None))

    def test_a_failing_probe_is_a_gap_never_an_error(self):
        def broken():
            raise OSError("no iostat")
        phase = local_load.Phase(broken, thread=False)
        with phase:
            pass
        self.assertIsNone(phase.record())

    def test_the_timer_thread_starts_and_stops_without_a_real_sleep(self):
        phase = local_load.Phase(reader([(0, 1.0, 1), (5, 1.0, 2)]), interval=3600)
        with phase:
            pass  # stop is set at once: the wait ends, the thread joins
        self.assertEqual(len(phase.record()["marks"]), 2)

    def test_disk_ops_parsers_on_this_os_return_a_number_or_none(self):
        got = local_load.disk_ops()
        self.assertTrue(got is None or got >= 0)
        self.assertIsNone(local_load.disk_ops("win32"))


if __name__ == "__main__":
    unittest.main()
