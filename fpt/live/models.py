from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class LiveAlert:
    alert_id: str
    alert_type: str  # ENTER | WATCH | HT_EXIT | STEAM
    severity: str    # high | medium | low
    home: str
    away: str
    league: str
    market: str
    message: str
    prob_est: float
    odd_back: float | None
    odd_lay: float | None
    odd_min: float
    edge_pp: float | None
    stake_pct: float
    stake_valor: float
    stake_back_pct: float = 0.0
    stake_lay_pct: float = 0.0
    market_id: str | None = None
    selection_id: int | None = None
    recommended_side: str = "BACK"  # BACK | LAY
    score: str = ""
    in_play: bool = False
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "alert_type": self.alert_type,
            "severity": self.severity,
            "home": self.home,
            "away": self.away,
            "league": self.league,
            "market": self.market,
            "message": self.message,
            "prob_est": self.prob_est,
            "odd_back": self.odd_back,
            "odd_lay": self.odd_lay,
            "odd_min": self.odd_min,
            "edge_pp": self.edge_pp,
            "stake_pct": self.stake_pct,
            "stake_valor": self.stake_valor,
            "stake_back_pct": self.stake_back_pct,
            "stake_lay_pct": self.stake_lay_pct,
            "market_id": self.market_id,
            "selection_id": self.selection_id,
            "recommended_side": self.recommended_side,
            "score": self.score,
            "in_play": self.in_play,
            "timestamp": self.timestamp,
        }


@dataclass
class LiveMatchState:
    home: str
    away: str
    league: str
    league_label: str
    kickoff: str
    status: str  # PRE | LIVE | HT | FT | UNKNOWN
    score_home: int | None = None
    score_away: int | None = None
    elapsed_min: int | None = None
    in_play: bool = False
    market_id: str | None = None
    event_id: str | None = None
    total_matched: float | None = None
    odds_source: str = "none"
    odds_updated_at: str = ""
    prob_home: float | None = None
    prob_draw: float | None = None
    prob_away: float | None = None
    odds: dict[str, dict[str, float | None]] = field(default_factory=dict)
    recommendations: list[dict] = field(default_factory=list)
    alerts: list[LiveAlert] = field(default_factory=list)
    best_action: str = "—"
    best_market: str = ""
    confidence: float = 0.0

    @property
    def score_display(self) -> str:
        if self.score_home is not None and self.score_away is not None:
            return f"{self.score_home}-{self.score_away}"
        return "—"

    def to_dict(self) -> dict[str, Any]:
        return {
            "home": self.home,
            "away": self.away,
            "league": self.league,
            "league_label": self.league_label,
            "kickoff": self.kickoff,
            "status": self.status,
            "score": self.score_display,
            "elapsed_min": self.elapsed_min,
            "in_play": self.in_play,
            "market_id": self.market_id,
            "odds_source": self.odds_source,
            "odds_updated_at": self.odds_updated_at,
            "prob_home": self.prob_home,
            "prob_draw": self.prob_draw,
            "prob_away": self.prob_away,
            "odds": self.odds,
            "recommendations": self.recommendations,
            "alerts": [a.to_dict() for a in self.alerts],
            "best_action": self.best_action,
            "best_market": self.best_market,
            "confidence": self.confidence,
        }
