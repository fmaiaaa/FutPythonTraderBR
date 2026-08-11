"""Testes — execução exchange-aware (back/lay, spread, scalp)."""
from __future__ import annotations

from fpt.live.models import LiveAlert
from fpt.live.scalping import build_scalp_plan, should_exit, ScalpPosition
from fpt.live.paper_db import compute_close_pnl
from fpt.trading.exchange_odds import (
    ExchangeQuote,
    build_scalp_exit_targets,
    check_exchange_value,
    scalp_covers_costs,
)


def test_exchange_quote_mid_and_spread():
    q = ExchangeQuote.from_prices(1.86, 1.88)
    assert q.mid == 1.87
    assert q.spread_pct is not None
    assert q.spread_pct < 2.0
    assert q.entry_price("BACK") == 1.86
    assert q.entry_price("LAY") == 1.88
    assert q.exit_price("BACK") == 1.88
    assert q.exit_price("LAY") == 1.86


def test_check_exchange_value_back():
    q = ExchangeQuote.from_prices(2.10, 2.12)
    chk = check_exchange_value(0.55, 1.08, q, "BACK", min_edge_pp=0.0)
    assert chk.has_value
    assert chk.market_price == 2.10
    assert chk.edge_pp is not None


def test_check_exchange_value_lay():
    q = ExchangeQuote.from_prices(6.0, 1.58)
    chk = check_exchange_value(0.55, 1.08, q, "LAY", min_edge_pp=0.0)
    assert chk.has_value
    assert chk.market_price == 1.58


def test_scalp_exit_targets_back():
    q = ExchangeQuote.from_prices(2.00, 2.02)
    target, stop, entry = build_scalp_exit_targets(q, "BACK", take_profit_pct=0.015, stop_loss_pct=0.02)
    assert entry == 2.00
    assert target is not None and stop is not None
    assert target < 2.02  # lay cai = lucro
    assert stop > 2.02


def test_scalp_plan_exchange_aware(monkeypatch):
    monkeypatch.setattr(
        "fpt.live.scalping.load_live_config",
        lambda: {
            "scalping": {"stake_pct": 0.005, "take_profit_pct": 0.02, "stop_loss_pct": 0.02, "timeout_seconds": 60},
            "exchange_execution": {"require_spread_ok": False},
            "paper": {"commission": 0.05},
        },
    )
    alert = LiveAlert(
        alert_id="t", alert_type="SCALP_PRESSURE_STEAM", severity="high",
        home="A", away="B", league="L", market="home_win_ft", message="m",
        prob_est=0.5, odd_back=2.0, odd_lay=2.02, odd_min=1.9, edge_pp=1.0,
        stake_pct=0.005, stake_valor=5.0, recommended_side="BACK",
        market_id="1", selection_id=1, in_play=True,
    )
    plan = build_scalp_plan(alert)
    assert plan is not None
    assert plan.entry_odd == 2.0
    assert plan.exit_side == "LAY"
    assert plan.target_exit_odd < 2.02


def test_should_exit_on_exit_side_odd():
    pos = ScalpPosition(
        position_id="p1", alert_id="t", home="A", away="B", market="home_win_ft",
        side="BACK", entry_odd=2.0, stake_pct=0.005,
        exit_side="LAY", target_odd=1.99, stop_odd=2.06, timeout_sec=60,
        entry_ts="2026-01-01T12:00:00",
    )
    hit, reason = should_exit(pos, 1.98, 10)
    assert hit and reason == "TP"


def test_scalp_covers_costs():
    q_tight = ExchangeQuote.from_prices(1.86, 1.87)
    assert scalp_covers_costs(q_tight, "BACK", take_profit_pct=0.04, commission=0.05, min_margin_pp=0.3)
    q_wide = ExchangeQuote.from_prices(2.0, 2.04)
    assert not scalp_covers_costs(q_wide, "BACK", take_profit_pct=0.015, commission=0.05, min_margin_pp=0.3)


def test_paper_pnl_back_entry_lay_exit():
    """Entrada BACK @ back, saída LAY @ lay — P&L coerente."""
    pnl, exit_stake = compute_close_pnl("BACK", 2.0, 2.0, 1.95, commission=0.05)
    assert exit_stake > 0
    assert isinstance(pnl, float)
