"""Kelly conservador — back mín / lay máx."""
from __future__ import annotations

from fpt.trading.fair_odds import exchange_fair_odds
from fpt.trading.kelly import compute_back_lay_stakes, kelly_fraction, kelly_simple


def test_kelly_at_back_min_differs_from_fair():
    p = 0.55
    ex = exchange_fair_odds(p, phi=1.08)
    stake_fair, _ = compute_back_lay_stakes(p, ex.back_fair, ex.lay_fair, 1000.0, 80.0)
    stake_min, _ = compute_back_lay_stakes(p, ex.back_min, ex.lay_max, 1000.0, 80.0)
    assert stake_fair.stake_pct == 0.0
    assert stake_min.stake_pct > 0.0


def test_lay_kelly_zero_at_lay_max_when_no_edge():
    p = 0.85
    ex = exchange_fair_odds(p, phi=1.08)
    q = 1 - p
    L = ex.lay_max
    assert kelly_fraction(q, 1 / (L - 1)) <= 0
    _, stake_lay = compute_back_lay_stakes(p, ex.back_min, ex.lay_max, 1000.0, 80.0)
    assert stake_lay.stake_pct == 0.0


def test_kelly_positive_with_edge_at_back_min():
    p = 0.58
    ex = exchange_fair_odds(p, phi=1.05)
    b = ex.back_min - 1
    assert kelly_fraction(p, b) > 0
    stake, _ = compute_back_lay_stakes(p, ex.back_min, ex.lay_max, 1000.0, 100.0, uses_ht=False)
    assert stake.stake_pct > 0


def test_kelly_ht_uses_back_min_entry():
    p = 0.55
    p_ht = 0.80
    ex = exchange_fair_odds(p, phi=1.08)
    exit_odd = 1.5
    stake_ht, _ = compute_back_lay_stakes(
        p, ex.back_min, ex.lay_max, 1000.0, 100.0,
        p_ht=p_ht, exit_odd=exit_odd, uses_ht=True,
    )
    assert stake_ht.stake_pct > 0.0


def test_kelly_simple_on_back_min():
    p = 0.60
    ex = exchange_fair_odds(p, phi=1.05)
    sd = kelly_simple(p, ex.back_min, 1000.0, confidence=100.0)
    sd_fair = kelly_simple(p, ex.back_fair, 1000.0, confidence=100.0)
    assert sd.kelly_full >= sd_fair.kelly_full
