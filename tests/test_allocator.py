"""派位引擎、容量双约束、连带邀约与周期复盘的单元测试。"""
import unittest

from support import SAMPLES
from carecycle.allocator import run_allocation
from carecycle.coverage import run_study
from carecycle.cycle import reconcile
from carecycle.disruptions import analyze_closure
from carecycle.loader import load_bundle
from carecycle.occupancy import OccupancyRegistry
from carecycle.intervals import Window
from carecycle.models import RoomSegment
from carecycle.routes import CareWindow, Child
from carecycle.scenarios import scenario_segments


class OccupancyTest(unittest.TestCase):
    def _registry(self):
        segment = RoomSegment(
            room="R1", centre="C", klass="preK", day="d",
            window=Window(360, 1080), seats=1, staff_group="g", staff_limit=2,
        )
        other = RoomSegment(
            room="R2", centre="C", klass="toddler", day="d",
            window=Window(360, 1080), seats=5, staff_group="g", staff_limit=2,
        )
        return OccupancyRegistry({("d", "preK"): (segment,), ("d", "toddler"): (other,)})

    def _care(self, child_name, room):
        child = Child(child_name, "f", "preK", ("a",))
        return CareWindow(child, room, 480, 600)

    def test_room_seat_limit_enforced(self):
        registry = self._registry()
        r1 = registry.scenario_rooms[("d", "preK")][0]
        self.assertIsNone(registry.can_fit((self._care("c1", r1),), "d", "t1"))
        violation = registry.can_fit(
            (self._care("c1", r1), self._care("c2", r1)), "d", "t2"
        )
        self.assertIsNotNone(violation)
        self.assertEqual(violation.scope, "room:R1")

    def test_staff_group_limit_spans_rooms(self):
        registry = self._registry()
        r1 = registry.scenario_rooms[("d", "preK")][0]
        r2 = registry.scenario_rooms[("d", "toddler")][0]
        toddler = Child("c2", "f", "toddler", ("a",))
        windows = (
            self._care("c1", r1),
            CareWindow(toddler, r2, 480, 600),
        )
        # 两个房间各有余座，但同组人员上限 2；两人恰好不违规，第三人违规。
        self.assertIsNone(registry.can_fit(windows, "d", "t"))
        third = Child("c3", "f", "toddler", ("a",))
        violation = registry.can_fit(
            windows + (CareWindow(third, r2, 480, 600),), "d", "t3"
        )
        self.assertIsNotNone(violation)
        self.assertEqual(violation.scope, "staff:g")


class AllocationTest(unittest.TestCase):
    def setUp(self):
        self.bundle = load_bundle(SAMPLES)

    def test_joint_offer_half_acceptance_is_not_independent_placement(self):
        index = scenario_segments(self.bundle, "extension")
        report = run_allocation(self.bundle, "extension", index)
        f1 = next(d for d in report.decisions if d.family == "F1")
        self.assertEqual(f1.status, "offered-joint")
        self.assertIsNone(f1.combination)
        check = next(c for c in report.hold_checks if c.offer == "O2")
        self.assertTrue(check.is_joint)
        self.assertFalse(check.intact)

    def test_waiting_offer_holds_no_capacity(self):
        index = scenario_segments(self.bundle, "current")
        report = run_allocation(self.bundle, "current", index)
        o3 = next(c for c in report.hold_checks if c.offer == "O3")
        self.assertEqual(o3.holds, ())
        self.assertNotIn("offer:O3", report.registry.tags())

    def test_priority_order_respected(self):
        index = scenario_segments(self.bundle, "extension")
        report = run_allocation(self.bundle, "extension", index)
        ordered = [d.family for d in report.decisions]
        # 组1（F1、F2）排在组2之前，同组按 joined。
        self.assertLess(ordered.index("F2"), ordered.index("F5"))

    def test_extension_allocation_marginal_over_current(self):
        study = run_study(self.bundle)
        current = set(study.scenarios["current"].allocated_upper)
        extension = set(study.scenarios["extension"].allocated_upper)
        # 延时不增员：F2 可派位，F5 仍被 P3 日间座位挡住。
        self.assertEqual(extension - current, {"F2"})
        self.assertNotIn("F5", extension)

    def test_one_family_counts_once_despite_multiple_options(self):
        study = run_study(self.bundle)
        coverage = study.scenarios["current"]
        # F1 有 X、Y 两个选项，但只计一次。
        self.assertEqual(coverage.accessibility_firm.count("F1"), 1)

    def test_latest_start_gap_reported_when_uncovered_past_deadline(self):
        index = scenario_segments(self.bundle, "current")
        report = run_allocation(self.bundle, "current", index)
        f2 = next(d for d in report.decisions if d.family == "F2")
        # 09-21 超出 F2 的最迟开工 09-15，缺口必须显式列出。
        self.assertTrue(any("2026-09-21" in gap for gap in f2.deadline_gap))


class ClosureTest(unittest.TestCase):
    def setUp(self):
        self.bundle = load_bundle(SAMPLES)

    def test_closure_flags_joint_offer_and_analytical_combos(self):
        impacts = analyze_closure(self.bundle)
        self.assertEqual(len(impacts), 1)
        impact = impacts[0]
        impacted_offers = {item.offer for item in impact.impacted_offers}
        self.assertEqual(impacted_offers, {"O2"})
        # F2/F5 只是分析中的备用组合，不联系家长。
        analytical_families = {text.split("（")[0] for text in impact.analytical_only}
        self.assertEqual(analytical_families, {"F2", "F5"})

    def test_release_resolution_frees_damaged_lines(self):
        from carecycle.disruptions import apply_resolutions

        impact = analyze_closure(self.bundle)[0]

        # 仅放弃受损日：09-14 明细保留，09-21 受损明细释放。
        partial = apply_resolutions(self.bundle, impact, {"O2": "release-damaged"})
        partial_lines = [line for line in partial.offers if line.offer == "O2"]
        self.assertTrue(partial_lines)
        self.assertTrue(all(self.bundle.room(line.room).day == "2026-09-14"
                            for line in partial_lines))

        # 整份放弃：O2 全部明细删除。
        full = apply_resolutions(self.bundle, impact, {"O2": "release"})
        self.assertFalse([line for line in full.offers if line.offer == "O2"])

    def test_alternative_acceptance_keeps_joint_offer_intact(self):
        from carecycle.disruptions import apply_resolutions

        impact = analyze_closure(self.bundle)[0]
        updated = apply_resolutions(self.bundle, impact, {"O2": "accept:P3"})
        lines = [line for line in updated.offers if line.offer == "O2"]
        # 受损的 09-21 A1 明细改到 P3，09-14 明细原样保留，整份仍联动。
        self.assertEqual(len(lines), 4)
        changed = [line for line in lines
                   if self.bundle.room(line.room).day == "2026-09-21" and line.child == "A1"]
        self.assertEqual([line.room for line in changed], ["P3"])


class ReconciliationTest(unittest.TestCase):
    def test_plan_vs_actual_difference_per_family(self):
        bundle = load_bundle(SAMPLES)
        report = reconcile(None, bundle)
        by_family = {item.family: item for item in report.differences}
        # F1 半接受不兑现；O3 纯候补不算实际；F3/F4 续托兑现。
        self.assertFalse(by_family["F1"].actual_fulfilled)
        self.assertFalse(by_family["F2"].actual_fulfilled)
        self.assertTrue(by_family["F3"].actual_fulfilled)
        self.assertTrue(by_family["F4"].actual_fulfilled)
        self.assertEqual(set(report.actual_families), {"F3", "F4"})


if __name__ == "__main__":
    unittest.main()
