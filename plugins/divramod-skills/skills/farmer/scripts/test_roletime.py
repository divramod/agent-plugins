"""Hal2 plan 0530 step 1: the one time helper of the farmer and tollman state files."""

import datetime as dt
import re
import unittest

import roletime

UTC = dt.timezone.utc
SHAPES = ["2026-10-31T09:52:24", "2026-10-31T09:52:24+02:00", "2026-10-31T09:52:24+00:00",
          "2026-10-31T07:52:24Z", "2026-10-31T09:52:24.123456", "2026-10-31"]


class Parse(unittest.TestCase):
    def test_z_and_offsets_are_normalised_to_utc(self):
        want = dt.datetime(2026, 10, 31, 7, 52, 24, tzinfo=UTC)
        self.assertEqual(roletime.parse("2026-10-31T07:52:24Z"), want)
        self.assertEqual(roletime.parse("2026-10-31T07:52:24z"), want)
        self.assertEqual(roletime.parse("2026-10-31T09:52:24+02:00"), want)
        self.assertEqual(roletime.parse("2026-10-31T07:52:24+00:00"), want)
        self.assertEqual(roletime.parse("2026-10-31T07:52:24Z").utcoffset(), dt.timedelta(0))

    def test_a_naive_value_is_local_time(self):
        naive = "2026-10-31T09:52:24"
        want = dt.datetime.fromisoformat(naive).astimezone(UTC)
        self.assertEqual(roletime.parse(naive), want)
        self.assertEqual(roletime.parse(" " + naive + " "), want)

    def test_naive_local_and_z_of_the_same_instant_are_equal(self):
        local = dt.datetime(2026, 7, 1, 12, 0, 0)  # summer
        winter = dt.datetime(2026, 12, 1, 12, 0, 0)  # winter: the DST rule differs, the helper must follow it
        for naive in (local, winter):
            z = naive.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            self.assertEqual(roletime.parse(naive.isoformat()), roletime.parse(z))

    def test_fractional_seconds(self):
        got = roletime.parse("2026-10-31T07:52:24.5Z")
        self.assertEqual(got, dt.datetime(2026, 10, 31, 7, 52, 24, 500000, tzinfo=UTC))
        self.assertIsNotNone(roletime.parse("2026-10-31T09:52:24.123456"))

    def test_a_date_only_is_midnight_local(self):
        want = dt.datetime(2026, 10, 31).astimezone(UTC)
        self.assertEqual(roletime.parse("2026-10-31"), want)

    def test_garbage_is_none_and_never_raises(self):
        for bad in (None, "", "   ", "garbage", "2026-13-45T99:99:99", "T", 5, 1.5, b"2026-10-31", [], {}, "Z"):
            self.assertIsNone(roletime.parse(bad), repr(bad))

    def test_the_incident_shapes_compare_and_sort_together(self):
        parsed = [roletime.parse(s) for s in SHAPES]
        self.assertTrue(all(p is not None and p.tzinfo is not None for p in parsed))
        ordered = sorted(parsed)  # a naive/aware mix raised TypeError here in the 2026-10-30 night
        self.assertEqual(len(ordered), len(SHAPES))
        self.assertTrue(parsed[1] <= max(parsed))


class Writers(unittest.TestCase):
    def test_now_is_whole_seconds_utc_z(self):
        self.assertRegex(roletime.now(), r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        clock = dt.datetime(2026, 10, 31, 9, 52, 24, 999999, tzinfo=dt.timezone(dt.timedelta(hours=2)))
        self.assertEqual(roletime.now(clock), "2026-10-31T07:52:24Z")

    def test_stamp_takes_naive_local_and_aware(self):
        naive = dt.datetime(2026, 10, 31, 9, 52, 24)
        self.assertEqual(roletime.stamp(naive), naive.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
        aware = dt.datetime(2026, 10, 31, 7, 52, 24, tzinfo=UTC)
        self.assertEqual(roletime.stamp(aware), "2026-10-31T07:52:24Z")

    def test_what_stamp_writes_parse_reads_back(self):
        t = dt.datetime(2026, 10, 31, 7, 52, 24, tzinfo=UTC)
        self.assertEqual(roletime.parse(roletime.stamp(t)), t)
        self.assertIsNotNone(re.match(r".*Z$", roletime.stamp(t)))

    def test_utcnow_is_aware_utc(self):
        self.assertEqual(roletime.utcnow().utcoffset(), dt.timedelta(0))


class Age(unittest.TestCase):
    def test_age_across_shapes(self):
        now = dt.datetime(2026, 10, 31, 8, 0, 0, tzinfo=UTC)
        self.assertEqual(roletime.age("2026-10-31T07:30:00Z", now), dt.timedelta(minutes=30))
        self.assertEqual(roletime.age("2026-10-31T09:00:00+02:00", now), dt.timedelta(hours=1))

    def test_a_naive_now_is_local_too(self):
        naive_now = dt.datetime(2026, 10, 31, 12, 0, 0)
        self.assertEqual(roletime.age("2026-10-31T11:00:00", naive_now), dt.timedelta(hours=1))
        z_then = roletime.stamp(dt.datetime(2026, 10, 31, 11, 0, 0))
        self.assertEqual(roletime.age(z_then, naive_now), dt.timedelta(hours=1))

    def test_a_string_now_and_unusable_values(self):
        self.assertEqual(roletime.age("2026-10-31T07:00:00Z", "2026-10-31T08:00:00Z"), dt.timedelta(hours=1))
        self.assertIsNone(roletime.age("garbage", dt.datetime(2026, 10, 31, tzinfo=UTC)))
        self.assertIsNone(roletime.age(None, dt.datetime(2026, 10, 31, tzinfo=UTC)))
        self.assertIsNone(roletime.age("2026-10-31T07:00:00Z", "garbage"))
        self.assertIsNone(roletime.age("2026-10-31T07:00:00Z", None))

    def test_a_future_value_is_negative(self):
        now = dt.datetime(2026, 10, 31, 8, 0, 0, tzinfo=UTC)
        self.assertEqual(roletime.age("2026-10-31T09:00:00Z", now), dt.timedelta(hours=-1))


class Aware(unittest.TestCase):
    def test_every_now_shape_is_aware_utc(self):
        naive = dt.datetime(2026, 10, 31, 10, 52, 24)
        self.assertEqual(roletime.aware(naive), naive.astimezone().astimezone(dt.timezone.utc))
        self.assertEqual(roletime.aware(naive).utcoffset(), dt.timedelta(0))
        self.assertEqual(roletime.aware("2026-10-31T09:52:24Z"),
                         dt.datetime(2026, 10, 31, 9, 52, 24, tzinfo=dt.timezone.utc))
        self.assertEqual(roletime.aware(None).utcoffset(), dt.timedelta(0))
        self.assertIsNone(roletime.aware("garbage"))


if __name__ == "__main__":
    unittest.main()
