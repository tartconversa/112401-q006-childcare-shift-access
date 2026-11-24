"""接送链路与可行性的单元测试（含手算口径）。"""
import unittest

from support import SAMPLES
from carecycle.feasibility import assess_option
from carecycle.intervals import Window
from carecycle.loader import load_bundle
from carecycle.models import Child, RoomSegment, ShiftLine
from carecycle.routes import Assignment, evaluate_day
from carecycle.scenarios import scenario_segments


class RouteMathTest(unittest.TestCase):
    def setUp(self):
        self.bundle = load_bundle(SAMPLES)
        self.children = self.bundle.family_children["F1"]  # A0 toddler, A1 preK

    def _shift(self, day, start, end):
        return ShiftLine(option="t", family="F1", day=day,
                         work=Window(start, end), state="firm")

    def test_morning_chain_deadlines_hand_computed(self):
        # 09-14 X 班 07:00-16:30；顺序 Ivy->Canal->Mill：
        # 到岗 420；Canal 最晚送达 420-10=410；Ivy 最晚 410-25=385。
        shift = self._shift("2026-09-14", 7 * 60, 16 * 60 + 30)
        rooms = {
            (segment.day, segment.klass): segment
            for segment in self.bundle.room_segments
        }
        assignments = (
            Assignment(self.children[0], rooms[("2026-09-14", "toddler")]),  # T1 Ivy
            Assignment(self.children[1], rooms[("2026-09-14", "preK")]),     # P2 Canal
        )
        route = evaluate_day(self.bundle, self.children, shift, assignments)
        self.assertNotIsInstance(route, str)
        care = {item.child.name: item for item in route.care}
        self.assertEqual(care["A1"].dropoff_by, 410)   # 06:50
        self.assertEqual(care["A0"].dropoff_by, 385)   # 06:25

    def test_evening_chain_pickups_hand_computed(self):
        # 下班 990；Mill->Canal 10 分 => 1000 到 Canal；Canal->Ivy 25 => 1025。
        shift = self._shift("2026-09-14", 7 * 60, 16 * 60 + 30)
        rooms = {
            (segment.day, segment.klass): segment
            for segment in self.bundle.room_segments
        }
        assignments = (
            Assignment(self.children[0], rooms[("2026-09-14", "toddler")]),
            Assignment(self.children[1], rooms[("2026-09-14", "preK")]),
        )
        route = evaluate_day(self.bundle, self.children, shift, assignments)
        care = {item.child.name: item for item in route.care}
        self.assertEqual(care["A1"].pickup_at, 1000)  # 16:40
        self.assertEqual(care["A0"].pickup_at, 1025)  # 17:05
        self.assertEqual(route.arrival_home, 1037)    # +Ivy->home 12

    def test_closure_gap_blocks_continuous_care(self):
        # F5 在 P4 闭园后只剩 P3（17:00 关门），晚接 18:46 无处可托。
        index = scenario_segments(self.bundle, "current")
        assessment = assess_option(self.bundle, index, self.bundle.options["V"])
        self.assertFalse(assessment.upper_ok)
        self.assertTrue(assessment.blocks)
        reason = assessment.blocks[0].primary_reason()
        self.assertIn("覆盖不了", reason)

    def test_closure_gap_itself_recognized_when_room_is_chosen(self):
        # 直接验算闭园房间 P4：照护窗与零座位缺口相交时给出缺口原因。
        index = scenario_segments(self.bundle, "current")
        shift = self.bundle.options["V"].lines[0]
        child = self.bundle.children["E0"]
        p4 = next(s for s in index[("2026-09-21", "preK")] if s.room == "P4")
        room_windows = {"P4": tuple(s.window for s in index[("2026-09-21", "preK")] if s.room == "P4")}
        gap_windows = {"P4": tuple(s.window for s in index[("2026-09-21", "preK")] if s.seats <= 0)}
        result = evaluate_day(
            self.bundle, (child,), shift,
            (Assignment(child, p4),), room_windows, gap_windows,
        )
        self.assertIsInstance(result, str)
        self.assertIn("缺口", result)

    def test_extension_restores_feasibility(self):
        index = scenario_segments(self.bundle, "extension")
        for name in ("V", "X2", "X"):
            self.assertTrue(
                assess_option(self.bundle, index, self.bundle.options[name]).upper_ok,
                name,
            )

    def test_provisional_day_kept_out_of_firm_band(self):
        # F1 的 Y 班 09-21 为 provisional：firm 口径只承诺 09-14 一天，
        # 上沿口径才覆盖完整两天周期。
        index = scenario_segments(self.bundle, "extension")
        assessment = assess_option(self.bundle, index, self.bundle.options["Y"])
        self.assertEqual(assessment.option.firm_days, ("2026-09-14",))
        self.assertTrue(assessment.by_day["2026-09-14"])
        self.assertTrue(assessment.firm_ok)       # 承诺的那一天本身可行
        self.assertTrue(assessment.upper_ok)
        # 但 firm 口径下家庭能拿到的只是单日照护，覆盖不到完整轮换周期。
        self.assertNotEqual(assessment.option.firm_days, assessment.option.days)

    def test_caregiver_qualification_enforced(self):
        bundle = load_bundle(SAMPLES)
        # 构造一个没有接送资格的孩子，应直接拒绝。
        child = Child(name="Z9", family="F1", klass="toddler", pickup_allowed=("Z",))
        shift = self._shift("2026-09-14", 7 * 60, 16 * 60 + 30)
        room = next(s for s in bundle.room_segments if s.room == "T1")
        result = evaluate_day(bundle, (child,), shift, (Assignment(child, room),))
        self.assertIsInstance(result, str)
        self.assertIn("接送资格", result)


if __name__ == "__main__":
    unittest.main()
