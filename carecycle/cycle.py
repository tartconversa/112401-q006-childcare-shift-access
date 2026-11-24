"""下一周期录入后的规划/实际复盘。

规划口径取上一周期研究中的可达性与容量派位；实际口径只认台账里
家庭整体接受（renewed / 全 accepted 联动邀约）且接送链路在现场
情景下仍然走得通的明细。逐户给出差异原因。
"""
from __future__ import annotations

from dataclasses import dataclass

from .allocator import build_hold_checks
from .coverage import CoverageStudy, run_study
from .feasibility import assess_option
from .models import ACCEPTED, OFFERED, RENEWED, WAITING, Bundle
from .scenarios import scenario_segments


@dataclass(frozen=True)
class FamilyDifference:
    family: str
    planned_access: bool
    planned_allocation: bool
    actual_fulfilled: bool
    category: str
    explanation: str


@dataclass(frozen=True)
class CycleReconciliation:
    planned_access_families: tuple[str, ...]
    planned_allocated_families: tuple[str, ...]
    actual_families: tuple[str, ...]
    differences: tuple[FamilyDifference, ...]


def reconcile(planned: CoverageStudy | None, actual_bundle: Bundle) -> CycleReconciliation:
    """比较规划覆盖与最终实际接受并能完成接送的覆盖。"""
    if planned is None:
        planned = run_study(actual_bundle)

    current_rooms = scenario_segments(actual_bundle, "current")
    hold_checks, pins_by_family = build_hold_checks(actual_bundle, current_rooms)
    actual_by_family = _actual_fulfilled(actual_bundle, current_rooms, hold_checks, pins_by_family)

    planned_access = set(planned.scenarios["current"].accessibility_upper)
    planned_alloc = set(planned.scenarios["current"].allocated_upper)

    all_families = sorted(set(planned.bundle.families) | set(actual_bundle.families))
    differences: list[FamilyDifference] = []
    for family in all_families:
        in_access = family in planned_access
        in_alloc = family in planned_alloc
        actual = actual_by_family.get(family)
        fulfilled = bool(actual and actual[0])
        category, explanation = _explain(
            family, in_access, in_alloc, actual, actual_bundle
        )
        differences.append(
            FamilyDifference(
                family=family,
                planned_access=in_access,
                planned_allocation=in_alloc,
                actual_fulfilled=fulfilled,
                category=category,
                explanation=explanation,
            )
        )

    return CycleReconciliation(
        planned_access_families=tuple(sorted(planned_access)),
        planned_allocated_families=tuple(sorted(planned_alloc)),
        actual_families=tuple(sorted(name for name, value in actual_by_family.items() if value[0])),
        differences=tuple(differences),
    )


def _actual_fulfilled(
    bundle: Bundle, current_rooms, hold_checks, pins_by_family
) -> dict[str, tuple[bool, str]]:
    """实际兑现 = 邀约整体被接受，且现场情景下接送链路仍然可行。"""
    result: dict[str, tuple[bool, str]] = {}
    for check in hold_checks:
        active = [
            line for line in bundle.offers if line.offer == check.offer and line.state != WAITING
        ]
        if not active:
            # 纯候补：没有任何已接受/在途承诺，不算实际兑现，也不占协商资源。
            result[check.family] = (False, f"邀约 {check.offer} 仍在候补，未形成派位")
            continue
        states = {line.state for line in active}
        if OFFERED in states:
            result[check.family] = (False, "联动邀约仍有明细未接受，半份接受不能独立派位")
            continue
        if not states <= {RENEWED, ACCEPTED}:
            result[check.family] = (False, f"邀约 {check.offer} 未整体接受")
            continue
        broken = [problem for problem in check.problems if "整体接受" not in problem]
        if broken:
            result[check.family] = (False, "；".join(broken))
            continue
        result[check.family] = (True, f"邀约 {check.offer} 已整体接受且接送链路可完成")

    for family in bundle.families:
        result.setdefault(family, (False, "本周期没有任何已接受的邀约"))
    return dict(sorted(result.items()))


def _explain(family, in_access, in_alloc, actual, bundle) -> tuple[str, str]:
    fulfilled = bool(actual and actual[0])
    if fulfilled and in_alloc:
        return "matched", "规划可派位且实际已兑现"
    if fulfilled and not in_alloc:
        return "actual-only", "规划未列入派位但现场实际完成，复核容量与优先排序"
    if in_access and not in_alloc:
        return "capacity-gap", "仅可达性可行：座位/看护人员被既有承诺占满，实际未能派位"
    if in_alloc and not fulfilled:
        return "declined-or-broken", actual[1] if actual else "规划已派位但家庭未接受"
    if in_access and not fulfilled:
        return "access-only", "接送可达但无容量且未获邀约"
    if not in_access and not fulfilled:
        return "uncovered", _access_block_reason(bundle, family)
    return "matched", "规划与实际均无覆盖"


def _access_block_reason(bundle: Bundle, family: str) -> str:
    current_rooms = scenario_segments(bundle, "current")
    reasons: list[str] = []
    for option in bundle.family_options.get(family, ()):
        assessment = assess_option(bundle, current_rooms, option)
        for block in assessment.blocks:
            reasons.append(f"{option.name} {block.day}：{block.primary_reason()}")
    return "；".join(dict.fromkeys(reasons)) or "周期内无可行班表选项"
