from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import pandas as pd


@dataclass
class MarketOdds:
    home: float | None = None
    draw: float | None = None
    away: float | None = None
    source: str = "unknown"

    def get(self, market: str) -> float | None:
        return {"home_win_ft": self.home, "draw_ft": self.draw, "away_win_ft": self.away}.get(market)


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
            home=_f(row.get("Odd_1_FT")),
            draw=_f(row.get("Odd_X_FT")),
            away=_f(row.get("Odd_2_FT")),
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
