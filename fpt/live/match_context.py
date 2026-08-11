"""Contexto live unificado — pro-tempo e scalping."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MatchLiveContext:
    home: str
    away: str
    in_play: bool = False
    elapsed_min: int | None = None
    score_home: int = 0
    score_away: int = 0
    pressure_home: float | None = None
    pressure_away: float | None = None
    prev_pressure: dict[str, float] | None = None
    prev_live: dict[str, float] | None = None
    sofascore_stats: dict[str, Any] = field(default_factory=dict)
    odd_home: float | None = None
    odd_away: float | None = None
    odd_draw: float | None = None
    prev_odds: dict[str, float] | None = None
    graph_momentum: float | None = None
    row_odds: dict[str, float] = field(default_factory=dict)

    @property
    def total_goals(self) -> int:
        return int(self.score_home) + int(self.score_away)

    @property
    def pressure_dom(self) -> float | None:
        if self.pressure_home is None or self.pressure_away is None:
            return None
        return self.pressure_home - self.pressure_away

    @property
    def pressure_velocity(self) -> float | None:
        if self.pressure_dom is None or not self.prev_pressure:
            return None
        prev_dom = float(self.prev_pressure.get("home", 0)) - float(self.prev_pressure.get("away", 0))
        return self.pressure_dom - prev_dom

    @property
    def combined_pressure(self) -> float:
        return float(self.pressure_home or 0) + float(self.pressure_away or 0)

    @property
    def combined_xg(self) -> float:
        ss = self.sofascore_stats
        return float(ss.get("ss_xg_home") or 0) + float(ss.get("ss_xg_away") or 0)

    @property
    def combined_shots(self) -> int:
        ss = self.sofascore_stats
        return int(ss.get("ss_shots_home") or 0) + int(ss.get("ss_shots_away") or 0)

    def favorite_side(self, max_odd: float = 1.85) -> str | None:
        if not self.odd_home or not self.odd_away:
            return None
        if self.odd_home <= self.odd_away and self.odd_home < max_odd:
            return "home"
        if self.odd_away < self.odd_home and self.odd_away < max_odd:
            return "away"
        return None

    def underdog_side(self) -> str | None:
        if not self.odd_home or not self.odd_away:
            return None
        return "away" if self.odd_home <= self.odd_away else "home"

    def implied_over25(self) -> float | None:
        o = self.row_odds.get("over25_ft")
        if o and float(o) > 1.01:
            return 1.0 / float(o)
        u = self.row_odds.get("under25_ft")
        if u and float(u) > 1.01:
            return 1.0 - 1.0 / float(u)
        return None

    def in_window(self, lo: int, hi: int) -> bool:
        if self.elapsed_min is None:
            return False
        return lo <= int(self.elapsed_min) <= hi

    def stat(self, key: str, default: float = 0.0) -> float:
        v = self.sofascore_stats.get(key)
        return float(v) if v is not None else default

    def xg_velocity(self) -> float | None:
        if not self.prev_live:
            return None
        prev_xg = float(self.prev_live.get("xg_home", 0)) + float(self.prev_live.get("xg_away", 0))
        return self.combined_xg - prev_xg


def market_id_for_side(side: str) -> str:
    return {"home": "home_win_ft", "away": "away_win_ft", "draw": "draw_ft"}[side]
