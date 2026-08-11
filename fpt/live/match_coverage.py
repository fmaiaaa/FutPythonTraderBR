"""Cobertura de feeds — pré-live (FPT+Betfair) vs in-live/scalping (SS+Betfair)."""
from __future__ import annotations

from enum import Enum

import pandas as pd

from .models import LiveMatchState
from ..trading.market_sim import MarketOdds


class CoverageTier(str, Enum):
    FPT_ONLY = "fpt_only"
    BETFAIR = "betfair"
    SOFASCORE = "sofascore"
    FULL = "full"


def has_betfair_state(state: LiveMatchState) -> bool:
    return bool(
        state.market_id
        or (state.odds_source or "").startswith("betfair")
    )


def has_sofascore(state: LiveMatchState) -> bool:
    return bool(state.sofascore_event_id)


def has_betfair_odds(market_id: str | None, odds_source: str | None) -> bool:
    if market_id:
        return True
    return str(odds_source or "").startswith("betfair")


def has_fpt_row(row: pd.Series | None) -> bool:
    """Odds pré-jogo do FPT (jogos-do-dia)."""
    if row is None:
        return False
    for col in ("Odd_1_FT", "Odd_H_FT", "Odd_X_FT", "Odd_D_FT", "Odd_2_FT", "Odd_A_FT"):
        if col not in row.index:
            continue
        try:
            if float(row[col]) > 1.01:
                return True
        except (TypeError, ValueError):
            continue
    return False


def has_exchange_quotes(market_odds: MarketOdds, market: str = "home_win_ft") -> bool:
    side_map = {"home_win_ft": "home", "draw_ft": "draw", "away_win_ft": "away"}
    side = side_map.get(market, "home")
    ex = market_odds.get_exchange(side)
    if not ex:
        return False
    try:
        return bool(ex.back and ex.lay and float(ex.back) > 1.01 and float(ex.lay) > 1.01)
    except (TypeError, ValueError):
        return False


def coverage_tier(state: LiveMatchState) -> CoverageTier:
    bf = has_betfair_state(state)
    ss = has_sofascore(state)
    if bf and ss:
        return CoverageTier.FULL
    if bf:
        return CoverageTier.BETFAIR
    if ss:
        return CoverageTier.SOFASCORE
    return CoverageTier.FPT_ONLY


def prematch_feeds_ok(
    *,
    in_play: bool,
    market_id: str | None,
    odds_source: str | None,
    row: pd.Series | None = None,
    market_odds: MarketOdds | None = None,
    cfg: dict | None = None,
) -> bool:
    """Pré-live: FPT + Betfair (exchange) simultâneos."""
    if in_play:
        return False
    cfg = cfg or {}
    cov = cfg.get("coverage", {})
    req_bf = bool(cov.get("pre_live_require_betfair", True))
    req_fpt = bool(cov.get("pre_live_require_fpt", True))
    if req_bf and not has_betfair_odds(market_id, odds_source):
        return False
    if req_fpt and not has_fpt_row(row):
        return False
    if cfg.get("execution", {}).get("require_exchange", True) and market_odds:
        if not has_exchange_quotes(market_odds):
            return False
    return True


def in_live_feeds_ok(
    *,
    in_play: bool,
    market_id: str | None,
    sofascore_event_id: int | None,
    odds_source: str | None,
    market_odds: MarketOdds | None = None,
    cfg: dict | None = None,
) -> bool:
    """In-live / scalping: SofaScore + Betfair simultâneos."""
    if not in_play:
        return False
    cfg = cfg or {}
    cov = cfg.get("coverage", {})
    if bool(cov.get("in_live_require_betfair", True)):
        if not has_betfair_odds(market_id, odds_source):
            return False
    if bool(cov.get("in_live_require_sofascore", True)):
        if not sofascore_event_id:
            return False
    if cfg.get("execution", {}).get("require_exchange", True) and market_odds:
        if not has_exchange_quotes(market_odds):
            return False
    return True


def meets_pre_live(state: LiveMatchState, cfg: dict | None = None) -> bool:
    return prematch_feeds_ok(
        in_play=state.in_play,
        market_id=state.market_id,
        odds_source=state.odds_source,
        cfg=cfg,
    )


def meets_in_live(state: LiveMatchState, cfg: dict | None = None) -> bool:
    return in_live_feeds_ok(
        in_play=state.in_play,
        market_id=state.market_id,
        sofascore_event_id=state.sofascore_event_id,
        odds_source=state.odds_source,
        cfg=cfg,
    )


def in_live_ml_enabled(cfg: dict | None = None) -> bool:
    cfg = cfg or {}
    return bool(cfg.get("models", {}).get("in_live_pressure_ml", False))
