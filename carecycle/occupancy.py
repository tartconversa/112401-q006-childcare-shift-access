"""容量核算：房间座位与跨房间看护组人员限额。

一次照护占用是 (day, 房间, 照护窗口)。同一时刻：

* 每个房间的占用人数不得超过该时段 seats；
* 同一 staff_group 下所有房间的占用人数之和不得超过 staff_limit。

用统一的扫线事件处理两类约束；staff_limit 以具体开班段上记录的值为准，
因此不同房间、不同时段可以有不同的人员上限。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .intervals import Window, format_minutes
from .models import RoomSegment
from .routes import CareWindow


@dataclass(frozen=True)
class Occupancy:
    day: str
    room: str
    window: Window
    child: str
    tag: str


@dataclass
class CapacityViolation:
    day: str
    moment: int
    scope: str          # "room:<房间>" 或 "staff:<组>"
    limit: int
    occupants: tuple[str, ...]

    def describe(self) -> str:
        return (
            f"{self.day} {format_minutes(self.moment)} {self.scope} 超出限额 "
            f"{self.limit}，在场 {len(self.occupants)} 人：{', '.join(self.occupants)}"
        )


@dataclass
class OccupancyRegistry:
    scenario_rooms: dict[tuple[str, str], tuple[RoomSegment, ...]]
    _items: list[Occupancy] = field(default_factory=list)

    def add_care(self, care: CareWindow, day: str, tag: str) -> None:
        self._items.append(
            Occupancy(day, care.room.room, care.window, care.child.name, tag)
        )

    def remove_tag(self, tag: str) -> None:
        self._items = [item for item in self._items if item.tag != tag]

    def tags(self) -> frozenset[str]:
        return frozenset(item.tag for item in self._items)

    def check(self) -> list[CapacityViolation]:
        violations: list[CapacityViolation] = []
        for day in sorted({item.day for item in self._items}):
            day_items = [item for item in self._items if item.day == day]
            violations.extend(self._check_rooms(day, day_items))
            violations.extend(self._check_staff_groups(day, day_items))
        return violations

    def can_fit(
        self, windows: tuple[CareWindow, ...], day: str, tag: str
    ) -> CapacityViolation | None:
        """试探性加入一组照护占用，返回第一条违规（无违规返回 None）。"""
        snapshot = list(self._items)
        for care in windows:
            self.add_care(care, day, tag)
        violation = next(iter(self.check()), None)
        self._items = snapshot
        return violation

    def _segments_for_room(self, day: str, room: str) -> tuple[RoomSegment, ...]:
        result: list[RoomSegment] = []
        for segments in self.scenario_rooms.values():
            for segment in segments:
                if segment.day == day and segment.room == room:
                    result.append(segment)
        return tuple(result)

    def _segment_at(self, day: str, room: str, moment: int) -> RoomSegment | None:
        for segment in self._segments_for_room(day, room):
            if segment.window.start <= moment < segment.window.end:
                return segment
        return None

    def _check_rooms(self, day: str, items: list[Occupancy]) -> list[CapacityViolation]:
        violations: list[CapacityViolation] = []
        for room in sorted({item.room for item in items}):
            room_items = [item for item in items if item.room == room]
            moments = sorted(
                {moment for item in room_items for moment in (item.window.start, item.window.end)}
            )
            for moment in moments:
                active = [
                    item
                    for item in room_items
                    if item.window.start <= moment < item.window.end
                ]
                segment = self._segment_at(day, room, moment)
                limit = segment.seats if segment else 0
                if len(active) > limit:
                    violations.append(
                        CapacityViolation(
                            day=day,
                            moment=moment,
                            scope=f"room:{room}",
                            limit=limit,
                            occupants=tuple(sorted(item.child for item in active)),
                        )
                    )
        return violations

    def _check_staff_groups(
        self, day: str, items: list[Occupancy]
    ) -> list[CapacityViolation]:
        groups = sorted(
            {
                segment.staff_group
                for segments in self.scenario_rooms.values()
                for segment in segments
                if segment.day == day
            }
        )
        moments = sorted(
            {moment for item in items for moment in (item.window.start, item.window.end)}
        )
        violations: list[CapacityViolation] = []
        for group in groups:
            group_rooms = {
                segment.room
                for segments in self.scenario_rooms.values()
                for segment in segments
                if segment.day == day and segment.staff_group == group
            }
            for moment in moments:
                active = [
                    item
                    for item in items
                    if item.room in group_rooms
                    and item.window.start <= moment < item.window.end
                ]
                if not active:
                    continue
                limits = {
                    segment.staff_limit
                    for room in group_rooms
                    for segment in self._segments_for_room(day, room)
                    if segment.window.start <= moment < segment.window.end
                }
                if not limits or len(active) > min(limits):
                    violations.append(
                        CapacityViolation(
                            day=day,
                            moment=moment,
                            scope=f"staff:{group}",
                            limit=min(limits) if limits else 0,
                            occupants=tuple(sorted(item.child for item in active)),
                        )
                    )
        return violations
