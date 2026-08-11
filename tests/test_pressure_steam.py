from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd

from fpt.live.scalping import ScalpPosition, build_scalp_plan, should_exit
from fpt.live.scalping_backtest import _signal, run_scalping_backtest
from fpt.live.config import load_live_config
from fpt.live.strategies import evaluate_match_strategies
from fpt.live.models import LiveAlert
from fpt.trading.market_sim import MarketOdds, ExchangeSide


def _mock_rec(**kwargs):
    defaults = dict(
        to_dict=lambda: {},
        probabilidade_estimada=0.5,
        stake_back_pct=0.01,
        stake_lay_pct=0.01,
        action="SKIP",
        odd_minima_entrada=1.9,
        lay_max=1.35,
        edge_pp=1.0,
        confianca=70.0,
        p_lucro_ht=0.55,
        phi_seguranca=1.08,
    )
    defaults.update(kwargs)
    rec = MagicMock(**defaults)
    rec.to_dict = lambda: {k: getattr(rec, k) for k in (
        "market", "probabilidade_estimada", "stake_back_pct", "stake_lay_pct", "action",
        "odd_minima_entrada", "lay_max", "edge_pp", "confianca", "p_lucro_ht",
        "prob_home", "prob_draw", "prob_away", "kelly_quarto", "pct_banca",
    ) if hasattr(rec, k)}
    return rec


def _market_odds(back: float) -> MarketOdds:
    ex = ExchangeSide(back=back, lay=back + 0.02, selection_id=1)
    return MarketOdds(
        home=back, draw=3.5, away=4.0, source="betfair_br",
        exchange={"home": ex, "draw": ExchangeSide(back=3.5, lay=3.52), "away": ExchangeSide(back=4.0, lay=4.02)},
        market_id="1.1", in_play=True, elapsed_min=35,
    )


@patch("fpt.live.strategies.load_live_config")
@patch("fpt.live.strategies.exchange_fair_odds")
@patch("fpt.live.strategies.build_recommendation", return_value=_mock_rec(stake_lay_pct=0.0))
@patch("fpt.live.strategies.get_predictor")
def test_pressure_steam_alert_back(_gp, _br, _ef, _cfg):
    cfg = load_live_config()
    cfg.setdefault("pressure_odds", {})["enabled"] = False
    cfg["scalping_gates"] = {"enabled": False}
    cfg["entry_exposure"] = {"enabled": False}
    _cfg.return_value = cfg
    _gp.return_value.predict.return_value = MagicMock(
        prob_home=0.4, prob_draw=0.3, prob_away=0.3,
    )
    _ef.return_value = MagicMock(lay_max=999.0)
    odds = _market_odds(2.00)
    _, alerts = evaluate_match_strategies(
        pd.DataFrame(), "Flamengo", "Palmeiras", "BRA", None, "2026-03-15",
        odds, prev_odds={"home_win_ft": 2.10},
        in_play=True, score="1-0",
        pressure_home=55.0, pressure_away=30.0,
        prev_pressure={"home": 40.0, "away": 35.0},
        elapsed_min=35,
        market_id="1.1",
        sofascore_event_id=999001,
    )
    types = [a.alert_type for a in alerts]
    assert "PRESSURE_STEAM" in types
    ps = next(a for a in alerts if a.alert_type == "PRESSURE_STEAM")
    assert ps.recommended_side == "BACK"


@patch("fpt.live.strategies.exchange_fair_odds")
@patch("fpt.live.strategies.build_recommendation")
@patch("fpt.live.strategies.get_predictor")
def test_enter_alert_lay_home_with_betfair_lay(_gp, mock_rec, _ef):
    def _side_effect(*args, **kwargs):
        mkt = kwargs.get("market") or (args[3] if len(args) > 3 else "")
        if mkt == "draw_ft":
            return _mock_rec(market="draw_ft", stake_back_pct=0.0, stake_lay_pct=0.0, edge_pp=0.0)
        if mkt == "away_win_ft":
            return _mock_rec(market="away_win_ft", stake_back_pct=0.0, stake_lay_pct=0.0, edge_pp=0.0)
        return _mock_rec(
            market="home_win_ft", action="ENTER", stake_lay_pct=0.01, stake_back_pct=0.0,
            lay_max=1.35, edge_pp=2.0, confianca=70, p_lucro_ht=0.55,
        )

    mock_rec.side_effect = _side_effect
    _gp.return_value.predict.return_value = MagicMock(prob_home=0.4, prob_draw=0.3, prob_away=0.3)
    _ef.return_value = MagicMock(lay_max=1.35)
    ex = ExchangeSide(back=2.0, lay=1.33, selection_id=1)
    odds = MarketOdds(
        home=2.0, draw=3.5, away=4.0, source="betfair_br",
        exchange={"home": ex, "draw": ExchangeSide(back=3.5, lay=3.52), "away": ExchangeSide(back=4.0, lay=4.02)},
        market_id="1.1", in_play=False,
    )
    _, alerts = evaluate_match_strategies(
        pd.DataFrame(), "A", "B", "L", None, "2026-03-15", odds,
        row=pd.Series({"Odd_1_FT": 2.0, "Odd_X_FT": 3.5, "Odd_2_FT": 4.0}),
    )
    enter = [a for a in alerts if a.alert_type == "ENTER"]
    assert enter
    assert enter[0].recommended_side == "LAY"


def test_scalp_plan_tp_sl(monkeypatch):
    monkeypatch.setattr(
        "fpt.live.scalping.load_live_config",
        lambda: {
            "scalping": {"stake_pct": 0.005, "take_profit_pct": 0.015, "stop_loss_pct": 0.02, "timeout_seconds": 60},
            "exchange_execution": {"require_spread_ok": False},
            "paper": {"commission": 0.05},
        },
    )
    alert = LiveAlert(
        alert_id="t", alert_type="PRESSURE_STEAM", severity="high",
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
    assert plan.stop_exit_odd > 2.02

    pos = ScalpPosition(
        position_id="p1", alert_id="t", home="A", away="B", market="home_win_ft",
        side="BACK", entry_odd=2.0, stake_pct=0.005,
        exit_side="LAY", target_odd=plan.target_exit_odd, stop_odd=plan.stop_exit_odd,
        timeout_sec=60, entry_ts="2026-01-01T12:00:00",
    )
    hit, reason = should_exit(pos, 1.98, 10)
    assert hit and reason == "TP"


def test_scalping_backtest_on_synthetic_ticks():
    rows = []
    base_ts = pd.Timestamp("2026-03-15 16:00:00")
    for i in range(20):
        rows.append({
            "timestamp": base_ts + pd.Timedelta(seconds=15 * i),
            "home": "Time A", "away": "Time B",
            "in_play": True, "elapsed_min": 30 + i // 4,
            "back_home": 2.10 - i * 0.01,
            "ss_pressure_home": 40 + i * 2,
            "ss_pressure_away": 35 - i * 0.5,
        })
    df = pd.DataFrame(rows)
    cfg_signal = {"enabled": True, "min_pressure_delta": 5.0, "min_dominance": 8.0, "steam_pct": 0.02, "max_elapsed_min": 90}
    assert _signal(df.iloc[5], df.iloc[4], cfg_signal) in (None, "BACK", "LAY")
    bt = run_scalping_backtest(df, horizons=(10,))
    assert bt.trades >= 0
