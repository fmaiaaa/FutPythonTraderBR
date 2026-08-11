"""Testes — gates de entrada scalping (janela + confirmação de tendência)."""
from __future__ import annotations

from fpt.live.match_context import MatchLiveContext
from fpt.live.scalping_gates import (
    scalp_entry_gates_ok,
    scalp_minute_window_ok,
    scalp_trend_confirmed,
)
from fpt.live.scalping_strategies import evaluate_scalping_strategies


def _cfg(*, gates: dict | None = None, pressure_odds: bool = False) -> dict:
    return {
        "scalping": {"enabled": True, "stake_pct": 0.02},
        "scalping_gates": gates or {
            "enabled": True,
            "min_elapsed_min": 10,
            "max_elapsed_min": 70,
            "require_trend_confirmation": True,
            "require_prev_pressure": True,
            "require_momentum_align": True,
            "require_xg_align": True,
            "require_sot_align": False,
            "min_dominance": 10,
            "min_velocity": 5,
            "min_momentum": 5,
            "min_xg_diff": 0.10,
        },
        "scalping_strategies": {
            "pressure_steam": {"enabled": True, "min_dominance": 12, "min_pressure_delta": 8, "steam_pct": 0.03},
        },
        "pressure_odds": {"enabled": pressure_odds},
        "exchange_execution": {"require_spread_ok": False},
        "paper": {"commission": 0.05},
    }


def _confirmed_ctx(**kwargs) -> MatchLiveContext:
    base = dict(
        home="H", away="A", in_play=True, elapsed_min=35,
        pressure_home=55, pressure_away=30,
        prev_pressure={"home": 48, "away": 32},
        graph_momentum=15,
        sofascore_stats={"ss_xg_home": 0.8, "ss_xg_away": 0.2, "ss_sot_home": 3, "ss_sot_away": 1},
        prev_odds={"home_win_ft": 2.10},
    )
    base.update(kwargs)
    return MatchLiveContext(**base)


def test_blocks_before_10_minutes():
    ctx = _confirmed_ctx(elapsed_min=8)
    r = scalp_minute_window_ok(ctx, _cfg())
    assert not r.ok
    assert r.reason == "antes_10m"


def test_blocks_after_70_minutes():
    ctx = _confirmed_ctx(elapsed_min=72)
    r = scalp_minute_window_ok(ctx, _cfg())
    assert not r.ok
    assert r.reason == "apos_70m"


def test_blocks_without_prev_pressure():
    ctx = _confirmed_ctx(prev_pressure=None)
    r = scalp_trend_confirmed(ctx, "BACK", "home_win_ft", _cfg())
    assert not r.ok
    assert r.reason == "sem_historico_pressao"


def test_blocks_when_xg_not_aligned():
    ctx = _confirmed_ctx(sofascore_stats={"ss_xg_home": 0.2, "ss_xg_away": 0.2})
    r = scalp_trend_confirmed(ctx, "BACK", "home_win_ft", _cfg())
    assert not r.ok
    assert r.reason == "xg_desalinhado"


def test_confirms_trend_back_home():
    ctx = _confirmed_ctx()
    r = scalp_trend_confirmed(ctx, "BACK", "home_win_ft", _cfg())
    assert r.ok


def test_scalp_strategy_respects_gates():
    ctx = _confirmed_ctx()
    alerts = evaluate_scalping_strategies(
        ctx,
        home="H", away="A", league="L",
        market="home_win_ft", market_label="Casa",
        odd_back=2.00, odd_lay=2.02,
        prob_est=0.5, odd_min=1.9, edge_pp=1.0,
        prob_home=0.45, prob_draw=0.28, prob_away=0.27, phi=1.08,
        market_id="1", selection_id=1,
        score="1-0", cfg=_cfg(), bankroll=100,
        alert_id_fn=lambda *a: "id",
    )
    assert any(a["alert_type"] == "SCALP_PRESSURE_STEAM" for a in alerts)


def test_scalp_strategy_blocked_early_minute():
    ctx = _confirmed_ctx(elapsed_min=5)
    alerts = evaluate_scalping_strategies(
        ctx,
        home="H", away="A", league="L",
        market="home_win_ft", market_label="Casa",
        odd_back=2.00, odd_lay=2.02,
        prob_est=0.5, odd_min=1.9, edge_pp=1.0,
        prob_home=0.45, prob_draw=0.28, prob_away=0.27, phi=1.08,
        market_id="1", selection_id=1,
        score="1-0", cfg=_cfg(), bankroll=100,
        alert_id_fn=lambda *a: "id",
    )
    assert alerts == []


def test_entry_gates_ok_with_pressure_odds_off():
    ctx = _confirmed_ctx()
    ok, _, reason = scalp_entry_gates_ok(
        "BACK", "home_win_ft", 2.0, 2.02, ctx,
        0.45, 0.28, 0.27, 1.08, _cfg(pressure_odds=False),
        odd_move=-0.05,
    )
    assert ok
    assert reason == ""
