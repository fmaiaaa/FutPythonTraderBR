from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import pandas as pd


@dataclass
class ExchangeSide:
    """Back/lay disponíveis na exchange (melhor nível)."""
    back: float | None = None
    lay: float | None = None
    back_size: float | None = None
    lay_size: float | None = None
    selection_id: int | None = None

    def spread_pct(self) -> float | None:
        if self.back and self.lay and self.back > 1.01:
            return round((self.lay - self.back) / self.back * 100, 2)
        return None


@dataclass
class MarketOdds:
    home: float | None = None
    draw: float | None = None
    away: float | None = None
    source: str = "unknown"
    exchange: dict[str, ExchangeSide] | None = None
    market_id: str | None = None
    event_id: str | None = None
    in_play: bool = False
    status: str | None = None
    total_matched: float | None = None
    score_home: int | None = None
    score_away: int | None = None
    elapsed_min: int | None = None

    def get(self, market: str) -> float | None:
        return {"home_win_ft": self.home, "draw_ft": self.draw, "away_win_ft": self.away}.get(market)

    def get_exchange(self, side: str) -> ExchangeSide | None:
        if not self.exchange:
            return None
        return self.exchange.get(side)

    def get_lay(self, market: str) -> float | None:
        key = {"home_win_ft": "home", "draw_ft": "draw", "away_win_ft": "away"}.get(market, "")
        ex = self.get_exchange(key)
        return ex.lay if ex else None

    def to_market_dict(self) -> dict:
        """Dict para shrinkage / features do modelo."""
        d = {
            "Odd_1_FT": self.home,
            "Odd_X_FT": self.draw,
            "Odd_2_FT": self.away,
            "home_win_ft": self.home,
            "draw_ft": self.draw,
            "away_win_ft": self.away,
        }
        if self.exchange:
            for side, ex in self.exchange.items():
                if ex.back:
                    d[f"bf_back_{side}"] = ex.back
                if ex.lay:
                    d[f"bf_lay_{side}"] = ex.lay
                sp = ex.spread_pct()
                if sp is not None:
                    d[f"bf_spread_{side}"] = sp
        if self.total_matched:
            d["bf_total_matched"] = self.total_matched
        if self.in_play:
            d["bf_in_play"] = 1.0
        return d


class MarketProvider(ABC):
    @abstractmethod
    def get_odds(self, home: str, away: str, **kwargs) -> MarketOdds:
        ...


class SimulatedMarket(MarketProvider):
    """
    Modo simulação — usa odds do FPT (fechamento histórico ou jogos do dia).
    Não requer Betfair.
    """

    ODD_MAP = {"home_win_ft": "Odd_1_FT", "draw_ft": "Odd_X_FT", "away_win_ft": "Odd_2_FT"}

    def __init__(self, df: pd.DataFrame):
        self.df = df

    def get_odds(self, home: str, away: str, **kwargs) -> MarketOdds:
        league = kwargs.get("league_slug")
        sub = self.df[(self.df["Home"] == home) & (self.df["Away"] == away)]
        if league and "League_Slug" in sub.columns:
            sub = sub[sub["League_Slug"] == league]
        if sub.empty:
            return MarketOdds(source="simulated_not_found")
        row = sub.iloc[-1]
        return MarketOdds(
            home=_f(row.get("Odd_1_FT")),
            draw=_f(row.get("Odd_X_FT")),
            away=_f(row.get("Odd_2_FT")),
            source="fpt_historical",
        )

    def odds_from_row(self, row: pd.Series) -> MarketOdds:
        return MarketOdds(
            home=_f(row.get("Odd_1_FT") or row.get("Odd_H_FT")),
            draw=_f(row.get("Odd_X_FT") or row.get("Odd_D_FT")),
            away=_f(row.get("Odd_2_FT") or row.get("Odd_A_FT")),
            source="fpt_row",
        )

    @staticmethod
    def manual(home: float | None = None, draw: float | None = None, away: float | None = None) -> MarketOdds:
        return MarketOdds(home=home, draw=draw, away=away, source="manual")


def _f(v) -> float | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        x = float(v)
        return x if x > 1.01 else None
    except (TypeError, ValueError):
        return None
