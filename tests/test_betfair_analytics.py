"""Testes unitários — logger Betfair e analytics."""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from fpt.live.betfair_logger import (
    COLUMNS,
    export_daily_workbook,
    load_ticks,
    log_states,
    state_to_row,
)
from fpt.live.models import LiveMatchState
from fpt.live.analytics import (
    drawdown_series,
    equity_curve_from_trades,
    odds_by_score_summary,
    odds_evolution_df,
)

BR = ZoneInfo("America/Sao_Paulo")


def _sample_state(**kw) -> LiveMatchState:
    defaults = dict(
        home="Flamengo",
        away="Palmeiras",
        league="BRAZIL 1",
        league_label="Brasileirão",
        kickoff="08/08/2026 16:00",
        status="LIVE",
        score_home=1,
        score_away=0,
        elapsed_min=35,
        in_play=True,
        market_id="1.123",
        event_id="999",
        total_matched=50000.0,
        odds_source="betfair",
        odds_updated_at="16:35:00",
        prob_home=0.55,
        prob_draw=0.25,
        prob_away=0.20,
        odds={
            "Casa": {"back": 1.85, "lay": 1.87},
            "Empate": {"back": 3.5, "lay": 3.55},
            "Visitante": {"back": 4.2, "lay": 4.3},
        },
        recommendations=[],
        alerts=[],
        best_action="WATCH",
        best_market="home_win_ft",
        confidence=0.6,
    )
    defaults.update(kw)
    return LiveMatchState(**defaults)


def test_state_to_row_has_all_columns():
    row = state_to_row(_sample_state())
    for col in COLUMNS:
        assert col in row


def test_log_states_creates_csv(tmp_path, monkeypatch):
    import fpt.live.betfair_logger as bl

    monkeypatch.setenv("FPT_PERSIST_LOCAL", "1")
    monkeypatch.setattr(bl, "TICKS_ROOT", tmp_path)
    ts = datetime(2026, 8, 8, 16, 0, tzinfo=BR)
    path = log_states([_sample_state()], ts=ts)
    assert path is not None
    assert path.exists()
    df = pd.read_csv(path, encoding="utf-8-sig")
    assert len(df) == 1
    assert df.iloc[0]["home"] == "Flamengo"


def test_load_ticks_filter(tmp_path, monkeypatch):
    import fpt.live.betfair_logger as bl

    monkeypatch.setenv("FPT_PERSIST_LOCAL", "1")
    monkeypatch.setattr(bl, "TICKS_ROOT", tmp_path)
    ts = datetime(2026, 8, 8, 16, 0, tzinfo=BR)
    log_states([_sample_state(), _sample_state(home="Santos", away="Corinthians")], ts=ts)
    df = load_ticks(match="Flamengo|Palmeiras")
    assert len(df) == 1


def test_export_daily_workbook(tmp_path, monkeypatch):
    import fpt.live.betfair_logger as bl

    monkeypatch.setenv("FPT_PERSIST_LOCAL", "1")
    monkeypatch.setattr(bl, "TICKS_ROOT", tmp_path)
    ts = datetime(2026, 8, 8, 16, 0, tzinfo=BR)
    log_states([_sample_state()] * 3, ts=ts)
    xlsx = export_daily_workbook(date(2026, 8, 8))
    assert xlsx is not None
    assert xlsx.suffix == ".xlsx"


def test_odds_evolution_and_by_score():
    ticks = pd.DataFrame([
        {
            "timestamp": pd.Timestamp("2026-08-08 16:00"),
            "home": "A", "away": "B", "score": "1-0", "in_play": True,
            "elapsed_min": 30, "back_home": 1.9, "back_draw": 3.4, "back_away": 4.0,
            "lay_home": 1.92, "lay_draw": 3.5, "lay_away": 4.1,
        },
        {
            "timestamp": pd.Timestamp("2026-08-08 16:05"),
            "home": "A", "away": "B", "score": "1-0", "in_play": True,
            "elapsed_min": 35, "back_home": 1.85, "back_draw": 3.5, "back_away": 4.2,
            "lay_home": 1.87, "lay_draw": 3.55, "lay_away": 4.3,
        },
    ])
    evo = odds_evolution_df(ticks, "A|B")
    assert len(evo) >= 6
    by_score = odds_by_score_summary(ticks)
    assert "1-0" in by_score["score"].values


def test_equity_and_drawdown():
    trades = pd.DataFrame([
        {"date": "01/01/2024", "entry_odd": 2.0, "ht_return_pct": 0.1, "p_ht": 0.8,
         "back_min": 1.5, "entered_model": True},
        {"date": "02/01/2024", "entry_odd": 2.0, "ht_return_pct": -0.2, "p_ht": 0.8,
         "back_min": 1.5, "entered_model": True},
    ])
    eq = equity_curve_from_trades(trades, bankroll=1000.0, mode="fixed", fixed_pct=0.01)
    assert len(eq) >= 2
    dd = drawdown_series(eq)
    assert "drawdown_pct" in dd.columns
