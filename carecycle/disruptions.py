"""临时减班/闭园的影响分析与协商流转。

值班人先看到受牵连的整份邀约，区分：

* 已发出的承诺（renewed / offered / accepted）——必须联系已接受的家长协商；
* 仅存在于分析中的备用组合——不联系家长，只在候补视图里剔除。

家长确认替代安排或放弃后，真正释放的时段才对递补家庭可见。
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from .allocator import build_hold_checks
from .models import CONFIRMED_CLOSURE, Bundle, Change
from .scenarios import scenario_segments


@dataclass(frozen=True)
class ImpactedOffer:
    offer: str
    family: str
    is_joint: bool
    damaged_days: tuple[str, ...]
    detail: tuple[str, ...]


@dataclass(frozen=True)
class ClosureImpact:
    change: Change
    impacted_offers: tuple[ImpactedOffer, ...]
    analytical_only: tuple[str, ...]       # 只在分析组合里出现、无需联系家长的家庭
    released_windows: tuple[tuple[str, str, str, int, int], ...]


def analyze_closure(bundle: Bundle) -> list[ClosureImpact]:
    """对每份 confirmed-closure 给出影响清单。"""
    baseline = scenario_segments(bundle, "current")
    # 不带闭园的参考情景，用于识别“分析中本来可行”的备用组合。
    reference = _reference_segments(bundle)

    impacts: list[ClosureImpact] = []
    closures = [
        change for change in bundle.changes if change.kind == CONFIRMED_CLOSURE
    ]
    for change in sorted(closures, key=lambda item: (item.notice, item.name)):
        hold_checks, _ = build_hold_checks(bundle, baseline)
        impacted: list[ImpactedOffer] = []
        for check in hold_checks:
            damaged: set[str] = set()
            details: list[str] = []
            for day, child, room in check.holds:
                if room != change.room:
                    continue
                still_open = any(
                    segment.room == room for segment in baseline.get((day, room), ())
                )
                if not still_open or _window_gone(baseline[(day, room)], change):
                    damaged.add(day)
                    details.append(f"{day} {child} 在 {room} 的照护段被削去")
            if damaged:
                impacted.append(
                    ImpactedOffer(
                        offer=check.offer,
                        family=check.family,
                        is_joint=check.is_joint,
                        damaged_days=tuple(sorted(damaged)),
                        detail=tuple(details),
                    )
                )

        analytical = _analytical_only_families(bundle, reference, baseline, change)
        released = _released_windows(bundle, change)
        impacts.append(
            ClosureImpact(
                change=change,
                impacted_offers=tuple(impacted),
                analytical_only=tuple(analytical),
                released_windows=tuple(released),
            )
        )
    return impacts


def _window_gone(segments, change: Change) -> bool:
    """闭园窗口是否确实削掉了原开班（合并后窗口不再覆盖变更起点）。"""
    return not any(
        segment.window.start <= change.window.start < segment.window.end
        for segment in segments
    )


def _reference_segments(bundle: Bundle):
    """构造不含任何 confirmed-closure 的房间索引（规划参考），键为 (day, class)。"""
    index: dict[tuple[str, str], list] = {}
    for segment in bundle.room_segments:
        index.setdefault((segment.day, segment.klass), []).append(segment)
    return {
        key: tuple(sorted(segments, key=lambda segment: segment.room))
        for key, segments in index.items()
    }


def _analytical_only_families(bundle: Bundle, reference, baseline, change: Change) -> list[str]:
    """参考情景可达、闭园情景不可达，且没有已发邀约受牵连的家庭。"""
    from .feasibility import assess_option

    impacted_families: set[str] = set()
    hold_checks, _ = build_hold_checks(bundle, baseline)
    for check in hold_checks:
        if any(room == change.room for _, _, room in check.holds):
            impacted_families.add(check.family)

    result: list[str] = []
    for family_name in sorted(bundle.families):
        if family_name in impacted_families:
            continue
        lost_options: list[str] = []
        for option in bundle.family_options.get(family_name, ()):
            ref = assess_option(bundle, reference, option)
            cur = assess_option(bundle, baseline, option)
            # 同一选项在无闭园时可行、闭园后断掉，才是被这次减班打掉的备用组合。
            if ref.upper_ok and not cur.upper_ok:
                lost_options.append(option.name)
        if lost_options:
            result.append(f"{family_name}（受影响选项：{', '.join(lost_options)}）")
    return result


def _released_windows(bundle: Bundle, change: Change):
    """闭园后真正空出的 (day, room, staff_group, start, end) 列表。"""
    prototype = bundle.room(change.room)
    return [
        (
            prototype.day,
            change.room,
            prototype.staff_group,
            change.window.start,
            change.window.end,
        )
    ]


@dataclass(frozen=True)
class FamilyResolution:
    offer: str
    family: str
    action: str                  # accept-alternative / release
    alternative_rooms: tuple[str, ...]


def apply_resolutions(
    bundle: Bundle,
    impact: ClosureImpact,
    resolutions: dict[str, str],
) -> Bundle:
    """按家长决定更新台账。

    resolutions 取值：

    * ``"release"``：家长放弃整份邀约，全部明细删除、整份席位释放；
    * ``"release-damaged"``：只放弃受损日期，未受损日期的承诺保留；
    * ``"accept:<房间1|房间2...>"``：接受替代房间，保持整份联动。

    只有处理完的邀约才会真正改变容量，递补家庭随后看到释放时段。
    """
    from .models import OfferLine

    lines = list(bundle.offers)
    damaged = {
        item.offer: set(item.damaged_days) for item in impact.impacted_offers
    }
    new_lines: list[OfferLine] = []
    for line in lines:
        if line.offer not in resolutions:
            new_lines.append(line)
            continue
        decision = resolutions[line.offer]
        day = bundle.room(line.room).day
        is_damaged = day in damaged.get(line.offer, set())

        if decision == "release":
            continue  # 整份放弃
        if decision == "release-damaged":
            if is_damaged:
                continue  # 仅受损日释放
            new_lines.append(line)
            continue
        if decision.startswith("accept:"):
            if not is_damaged:
                new_lines.append(line)
                continue
            replacement = decision.split(":", 1)[1].split("|")
            target = next((name for name in replacement if name), line.room)
            new_lines.append(replace(line, room=target))
            continue
        raise ValueError(f"未知的家长决定：{decision!r}")
    return replace(bundle, offers=tuple(new_lines))
