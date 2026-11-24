"""情景构造：把临时闭园与规划试算材料作用到开班段上。

三个口径：

* ``current``      现状 + confirmed-closure（现场口径，含临时闭园）
* ``extension``    current + scenario-extension（只延长营业、不加人手）
* ``staff``        current + scenario-staff（延长营业且增加人员座位）

规划情景各自独立，互不叠加；同一情景内按 change 的 notice 顺序作用。
"""
from __future__ import annotations

from dataclasses import replace

from .intervals import Window, merge_adjacent
from .models import (
    CONFIRMED_CLOSURE,
    SCENARIO_EXTENSION,
    SCENARIO_STAFF,
    Bundle,
    Change,
    RoomSegment,
)

SCENARIO_KINDS = {
    "current": frozenset({CONFIRMED_CLOSURE}),
    "extension": frozenset({CONFIRMED_CLOSURE, SCENARIO_EXTENSION}),
    "staff": frozenset({CONFIRMED_CLOSURE, SCENARIO_STAFF}),
}
SCENARIO_ORDER = ("current", "extension", "staff")


def scenario_segments(
    bundle: Bundle, scenario: str
) -> dict[tuple[str, str], tuple[RoomSegment, ...]]:
    """返回该情景下 (day, class) -> 生效开班段的索引。"""
    if scenario not in SCENARIO_KINDS:
        raise ValueError(f"未知情景 {scenario!r}")
    kinds = SCENARIO_KINDS[scenario]
    changes = [change for change in bundle.changes if change.kind in kinds]
    changes.sort(key=lambda change: (change.notice, change.name))

    # 变更按 (room, day) 逐房间作用，最后再按 (day, class) 重建索引。
    per_room: dict[tuple[str, str], list[RoomSegment]] = {}
    for segment in bundle.room_segments:
        per_room.setdefault((segment.room, segment.day), []).append(segment)

    for change in changes:
        target = bundle.room(change.room)
        key = (change.room, target.day)
        per_room[key] = _apply_change(per_room.get(key, []), target, change)

    index: dict[tuple[str, str], list[RoomSegment]] = {}
    for segments in per_room.values():
        for segment in segments:
            index.setdefault((segment.day, segment.klass), []).append(segment)
    return {
        key: tuple(sorted(segments, key=lambda segment: segment.room))
        for key, segments in index.items()
    }


def _apply_change(
    segments: list[RoomSegment], prototype: RoomSegment, change: Change
) -> list[RoomSegment]:
    """把单个变更作用到某房间某天的开班段列表。"""
    window = change.window
    result: list[RoomSegment] = []
    for segment in segments:
        if not segment.window.overlaps(window):
            result.append(segment)
            continue
        # 变更窗口之前/之后的残余部分保留原配置。
        if segment.window.start < window.start:
            result.append(replace(segment, window=Window(segment.window.start, window.start)))
        if window.end < segment.window.end:
            result.append(replace(segment, window=Window(window.end, segment.window.end)))
        overlap = Window(
            max(segment.window.start, window.start),
            min(segment.window.end, window.end),
        )
        result.append(
            replace(
                segment,
                window=overlap,
                seats=change.seats,
            )
        )

    # 变更窗口落在现有开班之外（延时），按原型补一段。
    covered = merge_adjacent([segment.window for segment in result])
    if not any(piece.contains(window) for piece in covered):
        remaining = [window]
        for piece in covered:
            remaining = [
                fragment
                for current in remaining
                for fragment in _subtract(current, piece)
            ]
        for fragment in remaining:
            result.append(
                replace(
                    prototype,
                    window=fragment,
                    seats=change.seats,
                )
            )

    result.sort(key=lambda segment: (segment.window.start, segment.room))
    return _merge_same_config(result)


def _subtract(window: Window, other: Window) -> list[Window]:
    if not window.overlaps(other):
        return [window]
    pieces: list[Window] = []
    if window.start < other.start:
        pieces.append(Window(window.start, other.start))
    if other.end < window.end:
        pieces.append(Window(other.end, window.end))
    return pieces


def _merge_same_config(segments: list[RoomSegment]) -> list[RoomSegment]:
    """合并首尾相接且座位/人员配置一致的相邻段。"""
    ordered = sorted(segments, key=lambda segment: segment.window.start)
    merged: list[RoomSegment] = []
    for segment in ordered:
        if merged:
            previous = merged[-1]
            same_config = (
                previous.room == segment.room
                and previous.centre == segment.centre
                and previous.klass == segment.klass
                and previous.day == segment.day
                and previous.seats == segment.seats
                and previous.staff_group == segment.staff_group
                and previous.staff_limit == segment.staff_limit
                and previous.window.end == segment.window.start
            )
            if same_config:
                merged[-1] = replace(
                    previous, window=Window(previous.window.start, segment.window.end)
                )
                continue
        merged.append(segment)
    return merged
