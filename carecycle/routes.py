"""接送链路验算。

一位接送人在一个工作日内承担该家庭全部孩子的早送与晚接：

* 早：home → 中心₁ → 中心₂ → … → 工作点（须赶在工时开始前到岗）
* 晚：工作点 → … → 中心₂ → 中心₁ → home（下班才能出发接人）

交通分钟为同一接送人的单程预留；同一家庭的多个孩子若在不同中心，
枚举中心访问顺序，只有某个顺序全程赶得上才算串接可行。
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import permutations

from .intervals import Window, format_minutes, merge_adjacent
from .models import Bundle, Child, RoomSegment, ShiftLine


@dataclass(frozen=True)
class CareWindow:
    """一个孩子在某天必须被照护的区间（左闭右开）。"""

    child: Child
    room: RoomSegment
    dropoff_by: int
    pickup_at: int

    @property
    def window(self) -> Window:
        return Window(self.dropoff_by, self.pickup_at)


@dataclass(frozen=True)
class DayRoute:
    """一天接送验算通过后的完整链路。"""

    caregiver: str
    order: tuple[str, ...]                 # 中心访问顺序（早送方向）
    care: tuple[CareWindow, ...]
    arrival_work: int
    leave_work: int
    arrival_home: int

    def care_for(self, child_name: str) -> CareWindow:
        for item in self.care:
            if item.child.name == child_name:
                return item
        raise KeyError(child_name)


@dataclass(frozen=True)
class Assignment:
    child: Child
    room: RoomSegment


def eligible_caregivers(bundle: Bundle, children: tuple[Child, ...]) -> tuple[str, ...]:
    """同时具备所有孩子接送资格的家庭接送人。"""
    allowed = [set(child.pickup_allowed) for child in children]
    if not allowed:
        return ()
    common = set.intersection(*allowed)
    family = children[0].family
    return tuple(c for c in bundle.families[family].caregivers if c in common)


def room_open_windows(
    room: RoomSegment, merged: dict[str, tuple[Window, ...]]
) -> tuple[Window, ...]:
    """房间在情景下的开放窗口；延时切分时由调用方传入合并窗口。"""
    return merged.get(room.room, (room.window,))


def evaluate_day(
    bundle: Bundle,
    children: tuple[Child, ...],
    shift: ShiftLine,
    assignments: tuple[Assignment, ...],
    room_windows: dict[str, tuple[Window, ...]] | None = None,
    gap_windows: dict[str, tuple[Window, ...]] | None = None,
) -> DayRoute | str:
    """验算某天的房间组合；通过返回 DayRoute，否则返回中文原因。

    room_windows: 房间名 -> 该情景下全部生效段（相邻段视为连续开放），
      用于延时后被切成多段的同一房间；缺省按 assignment 自带单段判断。
    gap_windows: 房间名 -> 真正的闭园/减班缺口（零座位段），
      照护窗与任何缺口相交即判定不连续；延时加段不是缺口。
    """
    if len(assignments) != len(children) or {
        a.child.name for a in assignments
    } != {c.name for c in children}:
        return "房间组合与家庭孩子不一致"

    for assignment in assignments:
        room = assignment.room
        if room.day != shift.day or room.klass != assignment.child.klass:
            return f"房间 {room.room} 与 {assignment.child.name} 的日期/年龄班不符"

    caregivers = eligible_caregivers(bundle, children)
    if not caregivers:
        return "没有一位接送人同时具备所有孩子的接送资格"

    worker_site = bundle.families[children[0].family].worker_site
    centres = tuple(dict.fromkeys(assignment.room.centre for assignment in assignments))
    # 相邻开放段（如延时加段）合并为连续窗口；真正的闭园缺口单列、不参与合并。
    open_map = {
        name: tuple(merge_adjacent(list(windows)))
        for name, windows in (room_windows or {}).items()
    }
    gap_map = {name: tuple(windows) for name, windows in (gap_windows or {}).items()}

    last_error = "无可串接的中心顺序"
    for caregiver in caregivers:
        for order in permutations(centres):
            result = _evaluate_order(
                bundle, caregiver, order, assignments, shift, worker_site,
                open_map, gap_map,
            )
            if isinstance(result, DayRoute):
                return result
            last_error = result
    return last_error


def _evaluate_order(
    bundle: Bundle,
    caregiver: str,
    order: tuple[str, ...],
    assignments: tuple[Assignment, ...],
    shift: ShiftLine,
    worker_site: str,
    open_map: dict[str, tuple[Window, ...]],
    gap_map: dict[str, tuple[Window, ...]],
) -> DayRoute | str:
    by_centre: dict[str, list[Assignment]] = {}
    for assignment in assignments:
        by_centre.setdefault(assignment.room.centre, []).append(assignment)

    # ---- 早送链：从工时开始反推每个中心的最晚送达时刻 ----
    dropoff_by: dict[str, int] = {}
    deadline = shift.work.start
    current_place = worker_site
    for centre in reversed(order):
        deadline -= bundle.travel_minutes(centre, current_place)
        for assignment in by_centre[centre]:
            dropoff_by[assignment.child.name] = deadline
        current_place = centre
    departure_home = deadline - bundle.travel_minutes("home", current_place)
    if departure_home < 0:
        return f"接送人 {caregiver} 早送链无法在当天钟点内完成"

    # ---- 晚接链：下班正向推算到达每个中心的时刻 ----
    clock = shift.work.end
    current_place = worker_site
    pickup_at: dict[str, int] = {}
    for centre in reversed(order):
        clock += bundle.travel_minutes(current_place, centre)
        for assignment in by_centre[centre]:
            pickup_at[assignment.child.name] = clock
        current_place = centre
    arrival_home = clock + bundle.travel_minutes(current_place, "home")

    care: list[CareWindow] = []
    for assignment in assignments:
        room = assignment.room
        start = dropoff_by[assignment.child.name]
        end = pickup_at[assignment.child.name]
        care_window = Window(start, end)
        open_windows = room_open_windows(room, open_map)
        gaps = gap_map.get(room.room, ())
        covered = any(piece.contains(care_window) for piece in open_windows)
        crosses_gap = any(care_window.overlaps(gap) for gap in gaps)
        if not covered or crosses_gap:
            span = "、".join(
                f"{format_minutes(piece.start)}-{format_minutes(piece.end)}"
                for piece in open_windows
            )
            reason = "含临时闭园缺口" if crosses_gap else "开放时段不足"
            return (
                f"{room.room} 开放 {span} 覆盖不了 {assignment.child.name} 需照护的 "
                f"{format_minutes(start)}-{format_minutes(end)}（{reason}）"
            )
        care.append(CareWindow(assignment.child, room, start, end))

    return DayRoute(
        caregiver=caregiver,
        order=order,
        care=tuple(sorted(care, key=lambda item: item.child.name)),
        arrival_work=shift.work.start,
        leave_work=shift.work.end,
        arrival_home=arrival_home,
    )
