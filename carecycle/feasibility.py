"""班表选项的全周期可行性评估。

对每个工作日枚举“每个孩子一间适龄房间”的组合，交给 routes 验算接送链；
全部工作日都至少存在一个可行组合，选项才贯穿完整轮换周期。
firm 口径只看 firm 日期，upper 口径把 provisional 日期也算入。
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Iterator

from .intervals import Window
from .models import Bundle, Child, Option, RoomSegment
from .routes import Assignment, DayRoute, evaluate_day


@dataclass(frozen=True)
class DayCombination:
    """某一天的一个可行房间组合及其接送链路。"""

    day: str
    assignments: tuple[Assignment, ...]
    route: DayRoute

    def rooms(self) -> tuple[RoomSegment, ...]:
        return tuple(assignment.room for assignment in assignments)


@dataclass(frozen=True)
class DayBlock:
    """某一天没有任何可行组合时的诊断记录。"""

    day: str
    reasons: tuple[str, ...]

    def primary_reason(self) -> str:
        # 出现频次最高的原因通常就是真正的卡点（如闭园、人手不足）。
        counts: dict[str, int] = {}
        for reason in self.reasons:
            counts[reason] = counts.get(reason, 0) + 1
        return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]


@dataclass(frozen=True)
class OptionAssessment:
    option: Option
    firm_ok: bool
    upper_ok: bool
    by_day: dict[str, tuple[DayCombination, ...]]
    blocks: tuple[DayBlock, ...]

    @property
    def feasible(self) -> bool:
        return self.upper_ok

    def all_cycle_combinations(self) -> Iterator[tuple[DayCombination, ...]]:
        """枚举贯穿全周期的组合（每天选一个可行组合）。"""
        daily = [self.by_day[day] for day in self.option.days]
        if any(not choices for choices in daily):
            return iter(())
        return product(*daily)


def assess_option(
    bundle: Bundle,
    scenario_rooms: dict[tuple[str, str], tuple[RoomSegment, ...]],
    option: Option,
    pinned: dict[tuple[str, str], str] | None = None,
) -> OptionAssessment:
    """评估单个选项。

    pinned: (day, child_name) -> room 名称，续托/已接受明细锁定原房间时使用。
    """
    pinned = pinned or {}
    children = bundle.family_children[option.family]
    by_day: dict[str, tuple[DayCombination, ...]] = {}
    blocks: list[DayBlock] = []

    for line in option.lines:
        combinations, reasons = _assess_day(
            bundle, scenario_rooms, children, line, pinned
        )
        by_day[line.day] = tuple(combinations)
        if not combinations:
            blocks.append(DayBlock(day=line.day, reasons=tuple(reasons)))

    firm_ok = all(by_day[day] for day in option.firm_days)
    upper_ok = all(by_day[day] for day in option.days)
    return OptionAssessment(
        option=option,
        firm_ok=firm_ok,
        upper_ok=upper_ok,
        by_day=by_day,
        blocks=tuple(blocks),
    )


def _assess_day(
    bundle: Bundle,
    scenario_rooms: dict[tuple[str, str], tuple[RoomSegment, ...]],
    children: tuple[Child, ...],
    shift,
    pinned: dict[tuple[str, str], str],
) -> tuple[list[DayCombination], list[str]]:
    per_child_rooms: list[list[RoomSegment]] = []
    day = shift.day

    def _dedup(segments: tuple[RoomSegment, ...]) -> list[RoomSegment]:
        """同一房间被变更切成多段时只保留一个代表段，开放窗口另行联合判断。"""
        unique: dict[str, RoomSegment] = {}
        for segment in segments:
            unique.setdefault(segment.room, segment)
        return list(unique.values())

    for child in children:
        rooms = _dedup(scenario_rooms.get((day, child.klass), ()))
        pinned_name = pinned.get((day, child.name))
        if pinned_name is not None:
            rooms = [room for room in rooms if room.room == pinned_name]
        if not rooms:
            # 锁定房间在该情景下已不可用（如闭园），直接给出明确原因。
            if pinned_name is not None:
                return [], [
                    f"{child.name} 锁定的房间 {pinned_name} 在 {day} 已不可用（临时闭园或减班）"
                ]
            return [], [f"{day} 没有 {child.klass} 年龄班的开班房间可接收 {child.name}"]
        per_child_rooms.append(rooms)

    combinations: list[DayCombination] = []
    reasons: list[str] = []
    room_windows: dict[str, tuple[Window, ...]] = {}
    gap_windows: dict[str, tuple[Window, ...]] = {}
    for rooms in per_child_rooms:
        for room in rooms:
            segments = [
                segment
                for segment in scenario_rooms.get((day, room.klass), ())
                if segment.room == room.room
            ]
            room_windows[room.room] = tuple(segment.window for segment in segments)
            gap_windows[room.room] = tuple(
                segment.window for segment in segments if segment.seats <= 0
            )
    for room_choice in product(*per_child_rooms):
        assignments = tuple(
            Assignment(child=child, room=room)
            for child, room in zip(children, room_choice)
        )
        result = evaluate_day(
            bundle, children, shift, assignments, room_windows, gap_windows
        )
        if isinstance(result, DayRoute):
            combinations.append(DayCombination(day=day, assignments=assignments, route=result))
        else:
            reasons.append(result)
    return combinations, reasons
