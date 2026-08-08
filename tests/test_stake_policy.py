"""Testes — politica de stake pre-jogo / HT."""
from __future__ import annotations

from fpt.markets import stake_sides_allowed
from fpt.trading.kelly import StakeDecision, apply_pro_tempo_stake_policy


def _stake(pct: float) -> StakeDecision:
    return StakeDecision(0.05, 0.0125, pct, 10.0, 80.0, None)


def test_stake_sides_draw_back_only():
    assert stake_sides_allowed("draw_ft") == (True, False)


def test_stake_sides_home_lay_only():
    assert stake_sides_allowed("home_win_ft") == (False, True)


def test_stake_sides_under_back_only():
    assert stake_sides_allowed("under25_ft") == (True, False)
    assert stake_sides_allowed("under15_ht") == (True, False)


def test_stake_sides_over_zero():
    assert stake_sides_allowed("over25_ft") == (False, False)
    assert stake_sides_allowed("btts_yes") == (False, False)


def test_apply_policy_zeros_wrong_side():
    back, lay = apply_pro_tempo_stake_policy("home_win_ft", _stake(0.02), _stake(0.03))
    assert back.stake_pct == 0
    assert lay.stake_pct == 0.03

    back, lay = apply_pro_tempo_stake_policy("draw_ft", _stake(0.02), _stake(0.03))
    assert back.stake_pct == 0.02
    assert lay.stake_pct == 0
