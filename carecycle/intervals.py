"""区间、钟点与日类型的基础工具。

所有钟点按当天分钟数处理；区间统一为左闭右开 [start, end)。
"""
from __future__ import annotations

from dataclasses import dataclass

MINUTES_PER_DAY = 24 * 60


def parse_minutes(text: str) -> int:
    """把 ``HH:MM`` 转成当天分钟数。"""
    hour, minute = text.strip().split(":")
    return int(hour) * 60 + int(minute)


def format_minutes(value: int) -> str:
    """分钟数转回 ``HH:MM``。"""
    return f"{value // 60:02d}:{value % 60:02d}"


def parse_day(text: str) -> str:
    """校验并归一化日期字段（YYYY-MM-DD，字典序即时间序）。"""
    parts = text.strip().split("-")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise ValueError(f"日期格式应为 YYYY-MM-DD：{text!r}")
    year, month, day = (int(part) for part in parts)
    return f"{year:04d}-{month:02d}-{day:02d}"


def split_multi(text: str) -> tuple[str, ...]:
    """竖线分隔的多值字段；空单元格返回空元组。"""
    return tuple(part.strip() for part in text.split("|") if part.strip())


@dataclass(frozen=True)
class Window:
    """左闭右开的分钟区间。"""

    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start >= self.end:
            raise ValueError(f"区间起点必须早于终点：{self.start} >= {self.end}")

    @property
    def length(self) -> int:
        return self.end - self.start

    def overlaps(self, other: "Window") -> bool:
        return self.start < other.end and other.start < self.end

    def contains(self, other: "Window") -> bool:
        """左闭右开口径下，other 是否完全落在本区间内。"""
        return self.start <= other.start and other.end <= self.end

    def touches(self, other: "Window") -> bool:
        return self.end == other.start or other.end == self.start


def merge_adjacent(windows: list[Window]) -> list[Window]:
    """合并相交或首尾相接的区间，返回按起点排序的列表。"""
    ordered = sorted(windows, key=lambda item: item.start)
    merged: list[Window] = []
    for window in ordered:
        if merged and window.start <= merged[-1].end:
            merged[-1] = Window(merged[-1].start, max(merged[-1].end, window.end))
        else:
            merged.append(window)
    return merged
