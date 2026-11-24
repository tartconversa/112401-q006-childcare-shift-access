"""读取 CSV 后的领域对象（全部为不可变值对象）。"""
from __future__ import annotations

from dataclasses import dataclass

from .intervals import Window, parse_day, parse_minutes, split_multi

FIRM = "firm"
PROVISIONAL = "provisional"

# 派位台账状态。
RENEWED = "renewed"      # 已接受的续托，永久保留
OFFERED = "offered"      # 联动邀约已发出、家庭尚未整体接受
ACCEPTED = "accepted"    # 邀约中的一部分已接受（单独不能成为派位）
WAITING = "waiting"      # 候补
LEDGER_HOLD_STATES = frozenset({RENEWED, OFFERED, ACCEPTED})
COMMITTED_STATES = frozenset({RENEWED, ACCEPTED})

CONFIRMED_CLOSURE = "confirmed-closure"
SCENARIO_EXTENSION = "scenario-extension"
SCENARIO_STAFF = "scenario-staff"


@dataclass(frozen=True)
class Family:
    name: str
    priority: int
    joined: str
    worker_site: str
    caregivers: tuple[str, ...]
    latest_start: str

    @classmethod
    def from_row(cls, row: dict[str, str]) -> "Family":
        return cls(
            name=row["family"].strip(),
            priority=int(row["priority"]),
            joined=parse_day(row["joined"]),
            worker_site=row["worker_site"].strip(),
            caregivers=split_multi(row["caregiver"]),
            latest_start=parse_day(row["latest_start"]),
        )


@dataclass(frozen=True)
class Child:
    name: str
    family: str
    klass: str
    pickup_allowed: tuple[str, ...]

    @classmethod
    def from_row(cls, row: dict[str, str]) -> "Child":
        return cls(
            name=row["child"].strip(),
            family=row["family"].strip(),
            klass=row["class"].strip(),
            pickup_allowed=split_multi(row["pickup_allowed"]),
        )


@dataclass(frozen=True)
class ShiftLine:
    """一个班表选项在某一天的工时行。"""

    option: str
    family: str
    day: str
    work: Window
    state: str

    @classmethod
    def from_row(cls, row: dict[str, str]) -> "ShiftLine":
        state = row["state"].strip()
        if state not in (FIRM, PROVISIONAL):
            raise ValueError(f"未知班表状态 {state!r}")
        return cls(
            option=row["option"].strip(),
            family=row["family"].strip(),
            day=parse_day(row["day"]),
            work=Window(parse_minutes(row["start"]), parse_minutes(row["end"])),
            state=state,
        )


@dataclass(frozen=True)
class RoomSegment:
    """照护点在某天某段的开班与人员配置。"""

    room: str
    centre: str
    klass: str
    day: str
    window: Window
    seats: int
    staff_group: str
    staff_limit: int

    @classmethod
    def from_row(cls, row: dict[str, str]) -> "RoomSegment":
        return cls(
            room=row["room"].strip(),
            centre=row["centre"].strip(),
            klass=row["class"].strip(),
            day=parse_day(row["day"]),
            window=Window(parse_minutes(row["start"]), parse_minutes(row["end"])),
            seats=int(row["seats"]),
            staff_group=row["staff_group"].strip(),
            staff_limit=int(row["staff_limit"]),
        )


@dataclass(frozen=True)
class TravelEdge:
    place_a: str
    place_b: str
    minutes: int

    @classmethod
    def from_row(cls, row: dict[str, str]) -> "TravelEdge":
        return cls(
            place_a=row["place_a"].strip(),
            place_b=row["place_b"].strip(),
            minutes=int(row["minutes"]),
        )


@dataclass(frozen=True)
class OfferLine:
    offer: str
    family: str
    child: str
    room: str
    state: str
    asof: str

    @classmethod
    def from_row(cls, row: dict[str, str]) -> "OfferLine":
        state = row["state"].strip()
        if state not in (RENEWED, OFFERED, ACCEPTED, WAITING):
            raise ValueError(f"未知邀约状态 {state!r}")
        return cls(
            offer=row["offer"].strip(),
            family=row["family"].strip(),
            child=row["child"].strip(),
            room=row["room"].strip(),
            state=state,
            asof=parse_day(row["asof"]),
        )


@dataclass(frozen=True)
class Change:
    """临时减班或规划试算材料。

    window 为当天钟点窗口；seats 是该窗口内的目标座位数
    （闭园为 0，延时/加座为新增段座位）。
    """

    name: str
    kind: str
    room: str
    window: Window
    seats: int
    notice: str

    @classmethod
    def from_row(cls, row: dict[str, str]) -> "Change":
        kind = row["kind"].strip()
        if kind not in (CONFIRMED_CLOSURE, SCENARIO_EXTENSION, SCENARIO_STAFF):
            raise ValueError(f"未知变更类型 {kind!r}")
        return cls(
            name=row["change"].strip(),
            kind=kind,
            room=row["room"].strip(),
            window=Window(parse_minutes(row["start"]), parse_minutes(row["end"])),
            seats=int(row["seats"]),
            notice=parse_day(row["notice"]),
        )


@dataclass(frozen=True)
class Option:
    """同一 option 名下的完整班型（覆盖轮换周期内的多个日期）。"""

    name: str
    family: str
    lines: tuple[ShiftLine, ...]
    days: tuple[str, ...]
    firm_days: tuple[str, ...]
    provisional_days: tuple[str, ...]

    @property
    def has_provisional(self) -> bool:
        return bool(self.provisional_days)


@dataclass(frozen=True)
class Bundle:
    """一个周期内的全部输入资料。"""

    families: dict[str, Family]
    children: dict[str, Child]
    family_children: dict[str, tuple[Child, ...]]
    options: dict[str, Option]
    family_options: dict[str, tuple[Option, ...]]
    room_segments: tuple[RoomSegment, ...]
    rooms_by_day_class: dict[tuple[str, str], tuple[RoomSegment, ...]]
    travel: dict[tuple[str, str], int]
    offers: tuple[OfferLine, ...]
    changes: tuple[Change, ...]
    days: tuple[str, ...]
    places: frozenset[str]

    def room(self, name: str) -> RoomSegment:
        for segment in self.room_segments:
            if segment.room == name:
                return segment
        raise KeyError(f"房间 {name!r} 不存在")

    def rooms_for(self, child: Child, day: str) -> tuple[RoomSegment, ...]:
        return self.rooms_by_day_class.get((day, child.klass), ())

    def travel_minutes(self, place_a: str, place_b: str) -> int:
        if place_a == place_b:
            return 0
        key = (place_a, place_b)
        if key not in self.travel:
            key = (place_b, place_a)
        if key not in self.travel:
            raise KeyError(f"缺少行程资料：{place_a} <-> {place_b}")
        return self.travel[key]

    def offer_groups(self) -> dict[str, tuple[OfferLine, ...]]:
        groups: dict[str, list[OfferLine]] = {}
        for line in self.offers:
            groups.setdefault(line.offer, []).append(line)
        return {name: tuple(lines) for name, lines in sorted(groups.items())}
