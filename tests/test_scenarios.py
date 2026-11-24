"""区间与情景切分的单元测试。"""
import unittest

from support import SAMPLES
from carecycle.intervals import Window, merge_adjacent
from carecycle.loader import load_bundle
from carecycle.scenarios import scenario_segments


class WindowTest(unittest.TestCase):
    def test_half_open_interval(self):
        window = Window(0, 60)
        self.assertTrue(window.contains(Window(0, 60)))
        self.assertTrue(window.contains(Window(10, 60)))
        self.assertFalse(window.contains(Window(0, 61)))

    def test_touching_intervals_merge_but_overlap_detection_uses_half_open(self):
        merged = merge_adjacent([Window(0, 60), Window(60, 120)])
        self.assertEqual(merged, [Window(0, 120)])
        self.assertFalse(Window(0, 60).overlaps(Window(60, 120)))


class ScenarioTest(unittest.TestCase):
    def setUp(self):
        self.bundle = load_bundle(SAMPLES)

    def test_closure_splits_room_into_open_and_zero_seat_segments(self):
        index = scenario_segments(self.bundle, "current")
        p4 = [segment for segment in index[("2026-09-21", "preK")] if segment.room == "P4"]
        self.assertEqual([(s.window.start, s.window.end, s.seats) for s in p4],
                         [(390, 1080, 2), (1080, 1185, 0)])

    def test_extension_adds_evening_segment_without_closing_original(self):
        index = scenario_segments(self.bundle, "extension")
        p3 = [segment for segment in index[("2026-09-21", "preK")] if segment.room == "P3"]
        # 17:00=1020, 20:00=1200；延时段与原段首尾相接，座位 2。
        self.assertEqual([(s.window.start, s.window.end, s.seats) for s in p3],
                         [(380, 1200, 2)])

    def test_staff_scenario_extension_has_more_seats_in_evening(self):
        index = scenario_segments(self.bundle, "staff")
        p3 = [segment for segment in index[("2026-09-21", "preK")] if segment.room == "P3"]
        self.assertEqual([(s.window.start, s.window.end, s.seats) for s in p3],
                         [(380, 1020, 2), (1020, 1200, 3)])

    def test_scenarios_are_independent(self):
        extension = scenario_segments(self.bundle, "extension")
        staff = scenario_segments(self.bundle, "staff")
        ext_p3 = [s for s in extension[("2026-09-21", "preK")] if s.room == "P3"]
        staff_p3 = [s for s in staff[("2026-09-21", "preK")] if s.room == "P3"]
        self.assertNotEqual(ext_p3, staff_p3)


if __name__ == "__main__":
    unittest.main()
