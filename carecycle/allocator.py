"""派位引擎。

处理顺序：

1. 先把台账里的既有承诺装进容量表——renewed 续托锁定原房间；
   offered/accepted 属于同一份连带邀约，按“半份接受不能独立成派位”处理。
2. 候选家庭按优先组（数字小者优先）、同组按等待日期、再按家庭名排序。
3. 逐户枚举可行选项与全周期房间组合，只有在不冲破任何既有承诺的前提下
   才能派位；一户多选项只贡献一次返岗机会。
4. 候补家庭记录“可行但容量被占”的组合与实际冲突；同时给出可推迟的
   开工日与超过雇主期限的缺口。
"""
from __future__ import annotations

from dataclasses import dataclass

from .feasibility import DayCombination, OptionAssessment, assess_option
from .intervals import Window
from .models import (
    ACCEPTED,
    OFFERED,
    WAITING,
    Bundle,
    Option,
)
from .occupancy import CapacityViolation, OccupancyRegistry
from .routes import Assignment, DayRoute, evaluate_day


@dataclass(frozen=True)
class HoldCheck:
    offer: str
    family: str
    intact: bool
    holds: tuple[tuple[str, str, str], ...]   # (day, child, room)
    problems: tuple[str, ...]
    is_joint: bool


@dataclass(frozen=True)
class AllocationDecision:
    family: str
    priority: int
    joined: str
    status: str
    option: str | None
    band: str | None                         # firm / upper
    combination: tuple[DayCombination, ...] | None
    reason: str
    waiting_viable: tuple[str, ...]          # 可达但容量被占的选项
    latest_start: str
    deferrable_days: tuple[str, ...]         # 可推迟但仍可维持返岗的开工日
    deadline_gap: tuple[str, ...]            # 超过雇主期限的实际缺口


@dataclass
class AllocationReport:
    scenario: str
    hold_checks: list[HoldCheck]
    decisions: list[AllocationDecision]
    registry: OccupancyRegistry
    assessments: dict[str, OptionAssessment]

    def fulfilled_families(self) -> tuple[str, ...]:
        return tuple(
            decision.family
            for decision in self.decisions
            if decision.status in ("renewed", "offered-joint", "allocated", "allocated-provisional")
        )


def _family_shift_on(bundle: Bundle, family: str, day: str):
    for option in bundle.family_options.get(family, ()):
        for line in option.lines:
            if line.day == day:
                return line
    return None


def _room_available(scenario_rooms, day: str, room_name: str) -> bool:
    for segments in scenario_rooms.values():
        if any(segment.day == day and segment.room == room_name for segment in segments):
            return True
    return False


def _pinned_day_route(
    bundle: Bundle, scenario_rooms, family: str, day: str, pins: dict[tuple[str, str], str]
) -> tuple[DayRoute | None, str]:
    """按锁定房间重算某天的接送链路，返回 (链路, 失败原因)。"""
    shift = _family_shift_on(bundle, family, day)
    if shift is None:
        return None, f"{day} 缺少家庭工时行，无法验算接送"
    children = bundle.family_children[family]
    assignments: list[Assignment] = []
    for child in children:
        room_name = pins.get((day, child.name))
        if room_name is None:
            return None, f"{day} {child.name} 缺少锁定房间"
        rooms = [
            segment
            for segment in scenario_rooms.get((day, child.klass), ())
            if segment.room == room_name
        ]
        if not rooms:
            return None, (
                f"{day} {child.name} 锁定的房间 {room_name} 已不可用（临时闭园或减班）"
            )
        assignments.append(Assignment(child=child, room=rooms[0]))
    room_windows: dict[str, tuple[Window, ...]] = {}
    gap_windows: dict[str, tuple[Window, ...]] = {}
    for assignment in assignments:
        segments = [
            segment
            for segment in scenario_rooms.get((day, assignment.child.klass), ())
            if segment.room == assignment.room.room
        ]
        room_windows[assignment.room.room] = tuple(
            segment.window for segment in segments
        )
        gap_windows[assignment.room.room] = tuple(
            segment.window for segment in segments if segment.seats <= 0
        )
    result = evaluate_day(
        bundle, children, shift, tuple(assignments), room_windows, gap_windows
    )
    if isinstance(result, DayRoute):
        return result, ""
    return None, result


def build_hold_checks(
    bundle: Bundle,
    scenario_rooms,
) -> tuple[list[HoldCheck], dict[str, dict[tuple[str, str], str]]]:
    """逐份邀约验算既有承诺；返回检查结果与续托/邀约锁定表。"""
    pins_by_family: dict[str, dict[tuple[str, str], str]] = {}
    for line in bundle.offers:
        if line.state == WAITING:
            continue
        room = bundle.room(line.room)
        pins_by_family.setdefault(line.family, {})[(room.day, line.child)] = line.room

    checks: list[HoldCheck] = []
    for offer_name, lines in bundle.offer_groups().items():
        family = lines[0].family
        active_lines = [line for line in lines if line.state != WAITING]
        if not active_lines:
            # 纯候补：没有任何已发承诺，不进入容量锁定与协商清单。
            checks.append(
                HoldCheck(
                    offer=offer_name,
                    family=family,
                    intact=True,
                    holds=(),
                    problems=(),
                    is_joint=False,
                )
            )
            continue
        states = {line.state for line in active_lines}
        is_joint = bool(states & {OFFERED, ACCEPTED})
        holds = tuple(
            sorted((bundle.room(line.room).day, line.child, line.room) for line in active_lines)
        )
        problems: list[str] = []
        pins = pins_by_family.get(family, {})
        for day in sorted({bundle.room(line.room).day for line in active_lines}):
            _, error = _pinned_day_route(bundle, scenario_rooms, family, day, pins)
            if error:
                problems.append(error)
        if states & {OFFERED}:
            problems.append("联动邀约尚未被家庭整体接受（半份接受不能独立成派位）")
        checks.append(
            HoldCheck(
                offer=offer_name,
                family=family,
                intact=not problems,
                holds=holds,
                problems=tuple(problems),
                is_joint=is_joint,
            )
        )
    return checks, pins_by_family


def seed_registry(
    bundle: Bundle,
    scenario_rooms,
    hold_checks: list[HoldCheck],
    pins_by_family: dict[str, dict[tuple[str, str], str]],
) -> OccupancyRegistry:
    """把仍然有效的既有承诺按实际照护窗装入容量表。

    闭园导致链路断裂的那天不再占用容量（席位视为待协商释放），
    其余日期照常锁定。
    """
    registry = OccupancyRegistry(scenario_rooms)
    impacted_days: dict[str, set[str]] = {}
    for check in hold_checks:
        days = {day for day, _, _ in check.holds}
        for day in days:
            route, error = _pinned_day_route(
                bundle, scenario_rooms, check.family, day, pins_by_family.get(check.family, {})
            )
            if error:
                impacted_days.setdefault(check.offer, set()).add(day)
                continue
            for care in route.care:
                registry.add_care(care, day, tag=f"offer:{check.offer}")
    return registry


def run_allocation(bundle: Bundle, scenario: str, scenario_rooms) -> AllocationReport:
    hold_checks, pins_by_family = build_hold_checks(bundle, scenario_rooms)
    registry = seed_registry(bundle, scenario_rooms, hold_checks, pins_by_family)

    assessments: dict[str, OptionAssessment] = {}
    for option in bundle.options.values():
        assessments[option.name] = assess_option(
            bundle, scenario_rooms, option, pins_by_family.get(option.family)
        )

    decisions: list[AllocationDecision] = []
    offered_families = {
        check.family for check in hold_checks if check.holds
    }
    ordered = sorted(
        bundle.families.values(),
        key=lambda family: (family.priority, family.joined, family.name),
    )
    for family in ordered:
        decisions.append(
            _decide_family(bundle, family, assessments, registry, offered_families)
        )

    return AllocationReport(
        scenario=scenario,
        hold_checks=hold_checks,
        decisions=decisions,
        registry=registry,
        assessments=assessments,
    )


def _decide_family(
    bundle: Bundle,
    family,
    assessments: dict[str, OptionAssessment],
    registry: OccupancyRegistry,
    offered_families: set[str],
) -> AllocationDecision:
    options = bundle.family_options.get(family.name, ())
    waiting_viable: list[str] = []
    deadline_gap: list[str] = []
    deferrable: list[str] = []
    capacity_reasons: list[str] = []

    firm_candidate: tuple[Option, tuple[DayCombination, ...]] | None = None
    upper_candidate: tuple[Option, tuple[DayCombination, ...]] | None = None

    for option in options:
        assessment = assessments[option.name]
        viable_combos, first_violation = _viable_combinations(assessment, registry)
        for day in option.days:
            if assessment.by_day[day] and day <= family.latest_start:
                deferrable.append(day)
        if not viable_combos:
            if assessment.upper_ok or assessment.firm_ok:
                waiting_viable.append(option.name)
                if first_violation is not None:
                    capacity_reasons.append(
                        f"{option.name}：{first_violation.describe()}"
                    )
            for day in sorted(option.days):
                if day > family.latest_start and not assessment.by_day[day]:
                    deadline_gap.append(
                        f"{option.name} 在 {day} 无照护，且已晚于最迟开工日 {family.latest_start}"
                    )
            continue
        combo = viable_combos[0]
        if assessment.firm_ok and firm_candidate is None:
            firm_candidate = (option, combo)
        if upper_candidate is None:
            upper_candidate = (option, combo)

    common = dict(
        family=family.name,
        priority=family.priority,
        joined=family.joined,
        latest_start=family.latest_start,
        waiting_viable=tuple(dict.fromkeys(waiting_viable)),
        deadline_gap=tuple(dict.fromkeys(deadline_gap)),
        deferrable_days=tuple(dict.fromkeys(deferrable)),
    )

    if family.name in offered_families:
        return AllocationDecision(
            **common,
            status="offered-joint",
            option=options[0].name if options else None,
            band=None,
            combination=None,
            reason="已有联动邀约在途，等待家庭整体接受或协商替代",
        )

    if firm_candidate is not None:
        option, combo = firm_candidate
        _commit_combo(registry, combo, family.name)
        return AllocationDecision(
            **common,
            status="allocated",
            option=option.name,
            band="firm",
            combination=combo,
            reason="firm 班表全周期可派位",
        )

    if upper_candidate is not None:
        option, combo = upper_candidate
        _commit_combo(registry, combo, family.name)
        return AllocationDecision(
            **common,
            status="allocated-provisional",
            option=option.name,
            band="upper",
            combination=combo,
            reason="仅在含 provisional 班表的上沿口径可派位，需雇主确认半日班表",
        )

    reason = _refusal_reason(bundle, family.name, assessments, capacity_reasons)
    return AllocationDecision(
        **common,
        status="waiting" if waiting_viable else "uncovered",
        option=None,
        band=None,
        combination=None,
        reason=reason,
    )


def _viable_combinations(
    assessment: OptionAssessment, registry: OccupancyRegistry
) -> tuple[list[tuple[DayCombination, ...]], CapacityViolation | None]:
    """返回 (当前容量承诺下能同时守住的全周期组合, 首个容量冲突)。"""
    viable: list[tuple[DayCombination, ...]] = []
    first_violation: CapacityViolation | None = None
    for combo in assessment.all_cycle_combinations():
        tag = f"try:{assessment.option.name}:{id(combo)}"
        violation: CapacityViolation | None = None
        for day_combo in combo:
            windows = tuple(
                day_combo.route.care_for(assignment.child.name)
                for assignment in day_combo.assignments
            )
            violation = registry.can_fit(windows, day_combo.day, tag)
            if violation is not None:
                break
        registry.remove_tag(tag)
        if violation is None:
            viable.append(combo)
        elif first_violation is None:
            first_violation = violation
    return viable, first_violation


def _commit_combo(
    registry: OccupancyRegistry, combo: tuple[DayCombination, ...], family: str
) -> None:
    for day_combo in combo:
        for assignment in day_combo.assignments:
            care = day_combo.route.care_for(assignment.child.name)
            registry.add_care(care, day_combo.day, tag=f"alloc:{family}")


def _refusal_reason(
    bundle: Bundle,
    family: str,
    assessments: dict[str, OptionAssessment],
    capacity_reasons: list[str],
) -> str:
    reasons: list[str] = []
    for option in bundle.family_options.get(family, ()):
        assessment = assessments[option.name]
        for block in assessment.blocks:
            reasons.append(f"{option.name} {block.day}：{block.primary_reason()}")
    reasons.extend(capacity_reasons)
    if not reasons:
        return "本周期无可行班表选项"
    return "；".join(dict.fromkeys(reasons))
