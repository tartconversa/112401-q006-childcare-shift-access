"""覆盖测算编排。

两套口径必须分开：

* 可达性（accessibility）：只看房间开放与接送链路，不考虑座位争抢；
  回答“延长营业本身能救回多少家庭”。
* 容量派位（allocated）：在既有承诺之外逐户抢座位，回答“增加人员/座位
  实际能兑现多少返岗”。

每条口径再分两条不确定带：

* firm：只统计 firm 工时行；只承诺一半班表（provisional）的日子不计入。
* upper：把 provisional 行也算入的上沿。

一个家庭申报多个班表选项也只贡献一次返岗机会。
"""
from __future__ import annotations

from dataclasses import dataclass

from .allocator import AllocationReport, run_allocation
from .feasibility import OptionAssessment, assess_option
from .models import Bundle
from .scenarios import SCENARIO_ORDER, scenario_segments


@dataclass(frozen=True)
class ScenarioCoverage:
    scenario: str
    accessibility_firm: tuple[str, ...]
    accessibility_upper: tuple[str, ...]
    allocated_firm: tuple[str, ...]
    allocated_upper: tuple[str, ...]
    assessments: dict[str, OptionAssessment]
    allocation: AllocationReport


@dataclass(frozen=True)
class CoverageStudy:
    bundle: Bundle
    scenarios: dict[str, ScenarioCoverage]

    def marginal(self, metric: str) -> dict[str, tuple[str, ...]]:
        """各情景相对上一情景新救回的家庭。"""
        result: dict[str, tuple[str, ...]] = {}
        previous: frozenset[str] = frozenset()
        for name in SCENARIO_ORDER:
            current = frozenset(self._metric(name, metric))
            result[name] = tuple(sorted(current - previous))
            previous = current
        return result

    def _metric(self, scenario: str, metric: str) -> tuple[str, ...]:
        coverage = self.scenarios[scenario]
        return {
            "access_firm": coverage.accessibility_firm,
            "access_upper": coverage.accessibility_upper,
            "alloc_firm": coverage.allocated_firm,
            "alloc_upper": coverage.allocated_upper,
        }[metric]


def run_study(bundle: Bundle) -> CoverageStudy:
    scenarios: dict[str, ScenarioCoverage] = {}
    for scenario in SCENARIO_ORDER:
        rooms = scenario_segments(bundle, scenario)
        scenarios[scenario] = _coverage_for(bundle, scenario, rooms)
    return CoverageStudy(bundle=bundle, scenarios=scenarios)


def _coverage_for(bundle: Bundle, scenario: str, scenario_rooms) -> ScenarioCoverage:
    assessments: dict[str, OptionAssessment] = {
        option.name: assess_option(bundle, scenario_rooms, option)
        for option in bundle.options.values()
    }

    access_firm: set[str] = set()
    access_upper: set[str] = set()
    for family_name in sorted(bundle.families):
        option_names = [
            option.name for option in bundle.family_options.get(family_name, ())
        ]
        if any(assessments[name].firm_ok for name in option_names):
            access_firm.add(family_name)
        if any(assessments[name].upper_ok for name in option_names):
            access_upper.add(family_name)

    allocation = run_allocation(bundle, scenario, scenario_rooms)
    alloc_firm = {
        decision.family
        for decision in allocation.decisions
        if decision.status in ("renewed", "offered-joint", "allocated")
    }
    alloc_upper = set(allocation.fulfilled_families())

    return ScenarioCoverage(
        scenario=scenario,
        accessibility_firm=tuple(sorted(access_firm)),
        accessibility_upper=tuple(sorted(access_upper)),
        allocated_firm=tuple(sorted(alloc_firm)),
        allocated_upper=tuple(sorted(alloc_upper)),
        assessments=assessments,
        allocation=allocation,
    )
