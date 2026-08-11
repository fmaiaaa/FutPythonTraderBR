from __future__ import annotations

import pandas as pd

from fpt.league_filter import filter_calendar, is_excluded_league
from fpt.league_ranking import adjust_stake_pct, load_league_rankings, resolve_league_rank


def test_excluded_women_league():
    assert is_excluded_league("ENGLAND W 1") is True
    assert is_excluded_league("BRAZIL 1") is False


def test_filter_watchlist_mode():
    df = pd.DataFrame([
        {"Home": "A", "Away": "B", "League": "BRAZIL 1", "Odd_1_FT": 1.5},
        {"Home": "C", "Away": "D", "League": "TURKEY 1", "Odd_1_FT": 2.0},
    ])
    out = filter_calendar(df, mode="watchlist", require_fpt_base=False)
    assert len(out) == 1
    assert out.iloc[0]["League"] == "BRAZIL 1"


def test_filter_robust_mode():
    df = pd.DataFrame([
        {"Home": "A", "Away": "B", "League": "BRAZIL 1", "Odd_1_FT": 1.5},
        {"Home": "C", "Away": "D", "League": "TURKEY 1", "Odd_1_FT": 2.0},
    ])
    out = filter_calendar(df, mode="robust", require_fpt_base=False)
    assert len(out) == 1
    assert out.iloc[0]["League"] == "BRAZIL 1"


def test_league_operation_allowed_robust():
    from fpt.league_ranking import league_operation_allowed

    ok, rank, reason = league_operation_allowed(
        league_raw="BRAZIL 1",
        league_slug="serie-a-betano",
        cfg={"operate_min_tier": 1, "watchlist_only": True},
    )
    assert ok is True
    assert rank.tier == 1

    ok2, _, reason2 = league_operation_allowed(
        league_raw="TURKEY 1",
        league_slug="super-lig",
        cfg={"operate_min_tier": 1, "watchlist_only": True},
    )
    assert ok2 is False
    assert reason2 == "fora_watchlist"


def test_league_rank_kelly_multiplier():
    rank = resolve_league_rank(league_slug="premier-league")
    assert rank.tier == 1
    assert adjust_stake_pct(0.02, rank) == round(0.02 * rank.kelly_multiplier, 6)


def test_default_probation_rank():
    rank = resolve_league_rank(league_slug="unknown-league-xyz")
    assert rank.tier == 3
    assert rank.kelly_multiplier <= 0.05


def test_rankings_load():
    ranks = load_league_rankings()
    assert "premier-league" in ranks
    assert "_default_probation" in ranks
