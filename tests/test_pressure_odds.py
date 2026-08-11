"""Testes — pressão → odds de entrada."""
from __future__ import annotations

from fpt.live.match_context import MatchLiveContext
from fpt.live.pressure_odds import blend_1x2_with_pressure, scalp_entry_ok


def _cfg() -> dict:
    return {
        "pressure_odds": {
            "enabled": True,
            "require_pressure": True,
            "blend_weight": 0.35,
            "min_edge_pp": 0.5,
        },
    }


def test_blend_shifts_toward_pressure():
    ctx = MatchLiveContext(
        home="H", away="A", in_play=True,
        pressure_home=80, pressure_away=20,
        sofascore_stats={"ss_xg_home": 1.2, "ss_xg_away": 0.3},
    )
    p_h, p_d, p_a = blend_1x2_with_pressure(0.40, 0.30, 0.30, ctx)
    assert p_h > 0.40
    assert p_a < 0.30
    assert abs(p_h + p_d + p_a - 1.0) < 0.01


def test_scalp_back_requires_min_odd():
    ctx = MatchLiveContext(
        home="H", away="A", in_play=True,
        pressure_home=75, pressure_away=25,
        sofascore_stats={"ss_xg_home": 0.8, "ss_xg_away": 0.2},
    )
    ok, view = scalp_entry_ok(
        "BACK", "home_win_ft", 2.50, 2.52, ctx,
        0.35, 0.30, 0.35, 1.08, _cfg(),
    )
    assert view is not None
    assert view.back_min > 0
    # odd baixa demais → sem valor
    ok_low, _ = scalp_entry_ok(
        "BACK", "home_win_ft", 1.05, 1.06, ctx,
        0.35, 0.30, 0.35, 1.08, _cfg(),
    )
    assert not ok_low
