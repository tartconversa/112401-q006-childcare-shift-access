"""命令行报告渲染。所有输出为中文，表格按显示宽度对齐（含全角字符）。"""
from __future__ import annotations

import unicodedata

from .allocator import AllocationReport
from .coverage import CoverageStudy
from .cycle import CycleReconciliation
from .disruptions import ClosureImpact
from .intervals import format_minutes
from .models import Bundle
from .scenarios import SCENARIO_ORDER

SCENARIO_TITLES = {
    "current": "现状（含已确认临时闭园）",
    "extension": "规划情景：延长营业（不加人）",
    "staff": "规划情景：延长营业且增加人员",
}
METRICS = (
    ("access_firm", "可达性 · firm 班表"),
    ("access_upper", "可达性 · 上沿（含半日承诺）"),
    ("alloc_firm", "容量派位 · firm 班表"),
    ("alloc_upper", "容量派位 · 上沿（含半日承诺）"),
)


def display_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(char) in ("F", "W") else 1 for char in text)


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - display_width(text))


def table(headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> str:
    widths = [display_width(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], display_width(cell))
    line = "  ".join(_pad(header, widths[index]) for index, header in enumerate(headers))
    sep = "  ".join("-" * width for width in widths)
    body = [
        "  ".join(_pad(cell, widths[index]) for index, cell in enumerate(row))
        for row in rows
    ]
    return "\n".join([line, sep, *body])


def render_coverage(study: CoverageStudy) -> str:
    bundle = study.bundle
    total = len(bundle.families)
    lines = [
        "托育覆盖测算（家庭去重：一户多选项只计一次返岗机会）",
        f"轮换周期日期：{', '.join(bundle.days)}；在册家庭：{total} 户",
        "",
    ]

    summary_rows: list[tuple[str, ...]] = []
    for scenario in SCENARIO_ORDER:
        coverage = study.scenarios[scenario]
        summary_rows.append(
            (
                SCENARIO_TITLES[scenario],
                str(len(coverage.accessibility_firm)),
                str(len(coverage.accessibility_upper)),
                str(len(coverage.allocated_firm)),
                str(len(coverage.allocated_upper)),
            )
        )
    lines.append(
        table(
            ("情景", "可达firm", "可达上沿", "派位firm", "派位上沿"),
            summary_rows,
        )
    )
    lines.append("")

    for metric, title in METRICS:
        lines.append(f"【{title}】各情景覆盖家庭与情景边际")
        marginal = study.marginal(metric)
        rows = []
        for scenario in SCENARIO_ORDER:
            families = study._metric(scenario, metric)
            delta = marginal[scenario]
            rows.append(
                (
                    SCENARIO_TITLES[scenario],
                    f"{len(families)}/{total}",
                    ", ".join(families) or "—",
                    ("新增：" + ", ".join(delta)) if delta else "无新增",
                )
            )
        lines.append(table(("情景", "覆盖", "家庭", "相对上一情景"), rows))
        lines.append("")

    lines.extend(_family_diagnosis(study))
    return "\n".join(lines)


def _family_diagnosis(study: CoverageStudy) -> list[str]:
    lines = ["逐户诊断（指出阻断完整周期的日期/孩子/接送段）", ""]
    bundle = study.bundle
    rows: list[tuple[str, ...]] = []
    for family_name in sorted(bundle.families):
        family = bundle.families[family_name]
        options = bundle.family_options.get(family_name, ())
        option_text = []
        for option in options:
            assessment = study.scenarios["current"].assessments[option.name]
            if assessment.upper_ok:
                band = "firm 全通" if assessment.firm_ok else "仅上沿（provisional 待确认）"
                option_text.append(f"{option.name}: {band}")
            else:
                block = assessment.blocks[0]
                option_text.append(
                    f"{option.name}: 阻断于 {block.day} — {block.primary_reason()}"
                )
        rows.append(
            (
                f"{family_name}(组{family.priority}/等{family.joined})",
                "；".join(option_text),
                f"最迟开工 {family.latest_start}",
            )
        )
    lines.append(table(("家庭", "班表选项现状（current 情景）", "雇主期限"), rows))
    return lines


def render_allocation(report: AllocationReport, bundle: Bundle) -> str:
    lines = [
        f"派位台账 · {SCENARIO_TITLES[report.scenario]}",
        "",
        "既有承诺验算：",
    ]
    rows = []
    for check in report.hold_checks:
        if not check.holds:
            kind = "候补（无已发承诺）"
        elif check.is_joint:
            kind = "连带邀约"
        else:
            kind = "续托"
        rows.append(
            (
                check.offer,
                check.family,
                kind,
                "完整" if check.intact else "受损",
                "；".join(check.problems) or "全部明细可守住",
            )
        )
    lines.append(table(("邀约", "家庭", "类型", "状态", "说明"), rows))
    lines.append("")

    lines.append("候选家庭派位（优先组 → 等待日期排序）：")
    decision_rows = []
    for decision in report.decisions:
        combo_text = "—"
        if decision.combination:
            pieces = []
            for day_combo in decision.combination:
                rooms = ", ".join(
                    f"{assignment.child.name}→{assignment.room.room}"
                    for assignment in day_combo.assignments
                )
                pieces.append(f"{day_combo.day}[{rooms}]")
            combo_text = "；".join(pieces)
        decision_rows.append(
            (
                decision.family,
                f"组{decision.priority}",
                decision.joined,
                decision.status,
                decision.option or "—",
                decision.band or "—",
                decision.reason,
                combo_text,
            )
        )
    lines.append(
        table(
            ("家庭", "优先", "等待日", "结论", "选项", "口径", "原因", "全周期房间组合"),
            decision_rows,
        )
    )
    lines.append("")

    waiting_rows = []
    for decision in report.decisions:
        if decision.status in ("waiting", "uncovered"):
            waiting_rows.append(
                (
                    decision.family,
                    ", ".join(decision.waiting_viable) or "无可达选项",
                    ", ".join(decision.deferrable_days) or "无",
                    ", ".join(decision.deadline_gap) or "未超期",
                )
            )
    if waiting_rows:
        lines.append("候补与开工日（可推迟日交家庭决定；超期显示实际缺口）：")
        lines.append(
            table(
                ("家庭", "可达但被占的选项", "可推迟开工日", "超过雇主期限的缺口"),
                waiting_rows,
            )
        )
        lines.append("")
    return "\n".join(lines)


def render_impact(impacts: list[ClosureImpact]) -> str:
    lines = ["临时闭园影响与协商清单", ""]
    for impact in impacts:
        change = impact.change
        lines.append(
            f"变更 {change.name}：房间 {change.room} "
            f"{format_minutes(change.window.start)}-{format_minutes(change.window.end)} 闭园"
            f"（通知日 {change.notice}）"
        )
        if impact.impacted_offers:
            rows = [
                (
                    item.offer,
                    item.family,
                    "连带邀约（需联系已接受家长）" if item.is_joint else "续托（需联系家长）",
                    ", ".join(item.damaged_days),
                    "；".join(item.detail),
                )
                for item in impact.impacted_offers
            ]
            lines.append(table(("邀约", "家庭", "处置层级", "受损日期", "明细"), rows))
        else:
            lines.append("  没有已发出的承诺受牵连。")
        lines.append(
            "  仅分析中的备用组合（不联系家长）："
            + (", ".join(impact.analytical_only) or "无")
        )
        released = ", ".join(
            f"{day} {room} {format_minutes(start)}-{format_minutes(end)}"
            for day, room, _, start, end in impact.released_windows
        )
        lines.append(f"  家长确认放弃后真正释放：{released}")
        lines.append("")
    return "\n".join(lines)


def render_reconciliation(report: CycleReconciliation) -> str:
    lines = [
        "周期复盘：规划覆盖 vs 实际接受并完成接送",
        "",
        f"规划可达家庭：{', '.join(report.planned_access_families) or '无'}",
        f"规划派位家庭：{', '.join(report.planned_allocated_families) or '无'}",
        f"实际兑现家庭：{', '.join(report.actual_families) or '无'}",
        "",
    ]
    rows = [
        (
            item.family,
            "是" if item.planned_access else "否",
            "是" if item.planned_allocation else "否",
            "是" if item.actual_fulfilled else "否",
            item.category,
            item.explanation,
        )
        for item in report.differences
    ]
    lines.append(table(("家庭", "规划可达", "规划派位", "实际兑现", "差异类别", "逐户解释"), rows))
    return "\n".join(lines)
