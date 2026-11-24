"""园区服务站命令行入口。

用法：
  python -I -m carecycle coverage   <资料目录>
  python -I -m carecycle allocate   <资料目录> [--scenario current|extension|staff]
  python -I -m carecycle closures   <资料目录>
  python -I -m carecycle reconcile  <本期资料目录> [--planned <上期资料目录>]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .coverage import run_study
from .cycle import reconcile
from .disruptions import analyze_closure
from .loader import load_bundle
from .reporting import (
    render_allocation,
    render_coverage,
    render_impact,
    render_reconciliation,
)
from .scenarios import SCENARIO_ORDER, scenario_segments
from .allocator import run_allocation


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="carecycle",
        description="轮班家庭托育覆盖测算与连带席位确认",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    coverage = sub.add_parser("coverage", help="按家庭/班型比较现状与拟增开服务的覆盖")
    coverage.add_argument("directory", type=Path)

    allocate = sub.add_parser("allocate", help="按优先级与容量承诺执行派位")
    allocate.add_argument("directory", type=Path)
    allocate.add_argument("--scenario", choices=SCENARIO_ORDER, default="current")

    closures = sub.add_parser("closures", help="临时闭园影响与协商清单")
    closures.add_argument("directory", type=Path)

    reconcile_parser = sub.add_parser(
        "reconcile", help="比较规划覆盖与实际接受并完成接送的覆盖"
    )
    reconcile_parser.add_argument("directory", type=Path)
    reconcile_parser.add_argument(
        "--planned",
        type=Path,
        default=None,
        help="上一周期资料目录；缺省时用本期资料重算规划口径",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        bundle = load_bundle(args.directory)
    except (FileNotFoundError, OSError, ValueError) as exc:
        print(f"资料读取失败：{exc}", file=sys.stderr)
        return 1

    if args.command == "coverage":
        study = run_study(bundle)
        print(render_coverage(study))
        return 0

    if args.command == "allocate":
        rooms = scenario_segments(bundle, args.scenario)
        report = run_allocation(bundle, args.scenario, rooms)
        print(render_allocation(report, bundle))
        return 0

    if args.command == "closures":
        impacts = analyze_closure(bundle)
        print(render_impact(impacts))
        return 0

    if args.command == "reconcile":
        try:
            planned_study = (
                run_study(load_bundle(args.planned)) if args.planned else None
            )
        except (FileNotFoundError, OSError, ValueError) as exc:
            print(f"规划资料读取失败：{exc}", file=sys.stderr)
            return 1
        report = reconcile(planned_study, bundle)
        print(render_reconciliation(report))
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
