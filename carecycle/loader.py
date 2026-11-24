"""CSV 资料读取、关联校验与 Bundle 构造。

只读标准库；调用方应使用 ``python -I`` 运行，避免输入目录里的
同名模块干扰导入。
"""
from __future__ import annotations

import csv
from pathlib import Path

from .models import (
    Bundle,
    Change,
    Child,
    Family,
    OfferLine,
    Option,
    RoomSegment,
    ShiftLine,
    TravelEdge,
)

TABLES = (
    "families",
    "children",
    "shifts",
    "rooms",
    "travel",
    "offers",
    "changes",
)


def _read_table(directory: Path, table: str) -> list[dict[str, str]]:
    path = directory / f"{table}.csv"
    with path.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source, strict=True)
        if reader.fieldnames is None:
            raise ValueError(f"{path} 缺少列名行")
        rows = []
        for index, row in enumerate(reader, start=2):
            if None in row or None in row.values():
                raise ValueError(f"{path} 第 {index} 行列数不齐或存在空列名")
            rows.append({key: (value or "").strip() for key, value in row.items()})
    return rows


def load_bundle(directory: str | Path) -> Bundle:
    """读取目录下七张 CSV 并做外键与一致性校验。"""
    directory = Path(directory)
    raw = {table: _read_table(directory, table) for table in TABLES}

    families = {line.name: line for line in map(Family.from_row, raw["families"])}
    children = {line.name: line for line in map(Child.from_row, raw["children"])}
    shifts = tuple(map(ShiftLine.from_row, raw["shifts"]))
    segments = tuple(map(RoomSegment.from_row, raw["rooms"]))
    travel_edges = tuple(map(TravelEdge.from_row, raw["travel"]))
    offers = tuple(map(OfferLine.from_row, raw["offers"]))
    changes = tuple(map(Change.from_row, raw["changes"]))

    _validate_references(families, children, shifts, segments, offers, changes)

    family_children: dict[str, list[Child]] = {}
    for child in children.values():
        family_children.setdefault(child.family, []).append(child)
    children_by_family = {
        name: tuple(sorted(items, key=lambda child: child.name))
        for name, items in family_children.items()
    }

    option_map = _group_options(shifts)
    family_options: dict[str, list[Option]] = {}
    for option in option_map.values():
        family_options.setdefault(option.family, []).append(option)
    options_by_family = {
        name: tuple(sorted(items, key=lambda option: option.name))
        for name, items in family_options.items()
    }

    rooms_by_day_class: dict[tuple[str, str], list[RoomSegment]] = {}
    for segment in segments:
        rooms_by_day_class.setdefault((segment.day, segment.klass), []).append(segment)
    rooms_index = {
        key: tuple(sorted(items, key=lambda segment: segment.room))
        for key, items in rooms_by_day_class.items()
    }

    travel: dict[tuple[str, str], int] = {}
    for edge in travel_edges:
        travel[(edge.place_a, edge.place_b)] = edge.minutes
        travel[(edge.place_b, edge.place_a)] = edge.minutes

    days = tuple(sorted({segment.day for segment in segments}))
    places = {family.worker_site for family in families.values()}
    for segment in segments:
        places.add(segment.centre)
    places.add("home")

    return Bundle(
        families=families,
        children=children,
        family_children=children_by_family,
        options=option_map,
        family_options=options_by_family,
        room_segments=segments,
        rooms_by_day_class=rooms_index,
        travel=travel,
        offers=offers,
        changes=changes,
        days=days,
        places=frozenset(places),
    )


def _group_options(shifts: tuple[ShiftLine, ...]) -> dict[str, Option]:
    grouped: dict[str, list[ShiftLine]] = {}
    for line in shifts:
        grouped.setdefault(line.option, []).append(line)
    options: dict[str, Option] = {}
    for name, lines in grouped.items():
        families = {line.family for line in lines}
        if len(families) != 1:
            raise ValueError(f"班表选项 {name!r} 挂了多个家庭：{families}")
        days = sorted({line.day for line in lines})
        per_day: dict[str, list[ShiftLine]] = {}
        for line in lines:
            per_day.setdefault(line.day, []).append(line)
        for day, day_lines in per_day.items():
            if len(day_lines) != 1:
                raise ValueError(f"班表选项 {name!r} 在 {day} 存在多行工时")
        ordered = tuple(sorted(lines, key=lambda line: line.day))
        firm_days = tuple(line.day for line in ordered if line.state == "firm")
        provisional_days = tuple(
            line.day for line in ordered if line.state == "provisional"
        )
        options[name] = Option(
            name=name,
            family=families.pop(),
            lines=ordered,
            days=tuple(days),
            firm_days=firm_days,
            provisional_days=provisional_days,
        )
    return dict(sorted(options.items()))


def _validate_references(
    families: dict[str, Family],
    children: dict[str, Child],
    shifts: tuple[ShiftLine, ...],
    segments: tuple[RoomSegment, ...],
    offers: tuple[OfferLine, ...],
    changes: tuple[Change, ...],
) -> None:
    room_names = {segment.room for segment in segments}

    for child in children.values():
        if child.family not in families:
            raise ValueError(f"儿童 {child.name!r} 的家庭 {child.family!r} 不存在")
        family = families[child.family]
        unknown = set(child.pickup_allowed) - set(family.caregivers)
        if unknown:
            raise ValueError(
                f"儿童 {child.name!r} 的接送人 {sorted(unknown)} 不在家庭接送人名单内"
            )

    for line in shifts:
        if line.family not in families:
            raise ValueError(f"班表 {line.option!r} 的家庭 {line.family!r} 不存在")

    seen_offer_pairs: set[tuple[str, str, str]] = set()
    for line in offers:
        if line.family not in families:
            raise ValueError(f"邀约 {line.offer!r} 的家庭 {line.family!r} 不存在")
        if line.child not in children:
            raise ValueError(f"邀约 {line.offer!r} 的儿童 {line.child!r} 不存在")
        if line.room not in room_names:
            raise ValueError(f"邀约 {line.offer!r} 的房间 {line.room!r} 不存在")
        if children[line.child].family != line.family:
            raise ValueError(f"邀约 {line.offer!r} 的儿童与家庭不一致")
        pair = (line.offer, line.child, line.room)
        if pair in seen_offer_pairs:
            raise ValueError(f"邀约 {line.offer!r} 出现重复明细 {pair}")
        seen_offer_pairs.add(pair)

    for change in changes:
        if change.room not in room_names:
            raise ValueError(f"变更 {change.name!r} 的房间 {change.room!r} 不存在")

    # 同一房间同一天不得出现重叠开班段。
    by_room_day: dict[tuple[str, str], list[RoomSegment]] = {}
    for segment in segments:
        by_room_day.setdefault((segment.room, segment.day), []).append(segment)
    for (room, day), items in by_room_day.items():
        ordered = sorted(items, key=lambda item: item.window.start)
        for earlier, later in zip(ordered, ordered[1:]):
            if earlier.window.overlaps(later.window):
                raise ValueError(f"房间 {room} 在 {day} 的开班时段重叠")
