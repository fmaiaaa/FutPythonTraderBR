from __future__ import annotations

import re
from typing import Any

from .models import SofaScoreLiveStats

_STAT_ALIASES: dict[str, str] = {
    "ball possession": "possession",
    "possession": "possession",
    "total shots": "shots",
    "shots on target": "shots_on_target",
    "expected goals": "xg",
    "expected goals (xg)": "xg",
    "corner kicks": "corners",
    "corners": "corners",
    "big chances": "big_chances",
    "shots insidebox": "shots_inside_box",
    "shots inside box": "shots_inside_box",
    "shots inside the box": "shots_inside_box",
}


def _norm_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


def _parse_value(raw: Any) -> float | int | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return raw
    s = str(raw).strip().replace(",", ".")
    if s.endswith("%"):
        try:
            return float(s[:-1])
        except ValueError:
            return None
    try:
        if "." in s:
            return float(s)
        return int(s)
    except ValueError:
        return None


def _apply_stat(stats: SofaScoreLiveStats, key: str, home_val: Any, away_val: Any) -> None:
    h = _parse_value(home_val)
    a = _parse_value(away_val)
    if key == "possession":
        stats.possession_home = float(h) if h is not None else None
        stats.possession_away = float(a) if a is not None else None
    elif key == "shots":
        stats.shots_home = int(h) if h is not None else None
        stats.shots_away = int(a) if a is not None else None
    elif key == "shots_on_target":
        stats.shots_on_target_home = int(h) if h is not None else None
        stats.shots_on_target_away = int(a) if a is not None else None
    elif key == "xg":
        stats.xg_home = float(h) if h is not None else None
        stats.xg_away = float(a) if a is not None else None
    elif key == "corners":
        stats.corners_home = int(h) if h is not None else None
        stats.corners_away = int(a) if a is not None else None
    elif key == "big_chances":
        stats.big_chances_home = int(h) if h is not None else None
        stats.big_chances_away = int(a) if a is not None else None
    elif key == "shots_inside_box":
        stats.shots_inside_box_home = int(h) if h is not None else None
        stats.shots_inside_box_away = int(a) if a is not None else None


def parse_event_statistics(payload: dict[str, Any], event_id: int) -> SofaScoreLiveStats:
    stats = SofaScoreLiveStats(event_id=event_id)
    periods = payload.get("statistics") or []
    period = next((p for p in periods if p.get("period") in ("ALL", "all", None)), None)
    if period is None and periods:
        period = periods[0]
    if not period:
        return stats

    for group in period.get("groups") or []:
        gname = str(group.get("groupName") or "")
        stats.raw_groups[gname] = group
        for item in group.get("statisticsItems") or []:
            name = _norm_name(str(item.get("name") or item.get("key") or ""))
            key = _STAT_ALIASES.get(name)
            if not key:
                continue
            _apply_stat(stats, key, item.get("home"), item.get("away"))
    return stats


def parse_graph(payload: dict[str, Any], minute: int | None = None) -> float | None:
    points = payload.get("graphPoints") or []
    if not points:
        return None
    if minute is not None:
        eligible = [p for p in points if int(p.get("minute", -1)) <= minute]
        if eligible:
            return float(eligible[-1].get("value", 0))
    return float(points[-1].get("value", 0))
