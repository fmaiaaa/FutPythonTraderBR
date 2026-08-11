"""Testes — critérios pro-tempo live."""
from __future__ import annotations

from fpt.live.pro_tempo import assess_pro_tempo_entry, format_action_label, pick_best_action
from fpt.trading.recommendation import TradeRecommendation


def _rec(**kwargs) -> TradeRecommendation:
    defaults = dict(
        home="A", away="B", market="draw_ft", action="ENTER",
        probabilidade_estimada=0.30,
        prob_home=0.45, prob_draw=0.30, prob_away=0.25,
        p_lucro_ht=0.55,
        odd_justa=3.3, back_justa=3.3, lay_justa=1.43, lay_max=1.35,
        phi_seguranca=1.08, odd_minima_entrada=3.56,
        odd_mercado=3.80, edge_pp=2.5, implied_market=0.263,
        lucro_estimado_pct=5.0, kelly_cheio=0.04, kelly_quarto=0.01,
        pct_banca=0.01, stake_back_pct=0.012, stake_lay_pct=0.0,
        stake_valor=12.0, confianca=65.0, model_loaded=True,
        stake_motivo="", schedule_notes=[], reasons=[],
    )
    defaults.update(kwargs)
    return TradeRecommendation(**defaults)


def test_format_action_label():
    assert format_action_label("draw_ft", "BACK") == "BACK Empate FT"
    assert format_action_label("home_win_ft", "LAY") == "LAY Mandante FT"
    assert format_action_label("under25_ft", "BACK") == "BACK Under 2.5 FT"


def test_draw_enter_strict():
    cfg = {
        "live": {"min_edge_pp": 1.0, "min_confidence": 40, "min_p_ht_profit": 0.48},
        "pro_tempo": {"classic_prematch_only": True},
        "pro_tempo_strategies": {"back_draw_classic": {"enabled": True}},
    }
    rec = _rec(market="draw_ft", stake_back_pct=0.012, stake_lay_pct=0.0)
    ok, side, label = assess_pro_tempo_entry(rec, "draw_ft", 3.80, None, cfg)
    assert ok and side == "BACK" and label == "BACK Empate FT"


def test_draw_skip_low_odd():
    cfg = {
        "live": {"min_edge_pp": 1.0, "min_confidence": 40},
        "pro_tempo": {"classic_prematch_only": True},
        "pro_tempo_strategies": {"back_draw_classic": {"enabled": True}},
    }
    rec = _rec(stake_back_pct=0.012)
    ok, _, _ = assess_pro_tempo_entry(rec, "draw_ft", 3.20, None, cfg)
    assert not ok


def test_lay_home_requires_lay_odd():
    cfg = {
        "live": {"min_edge_pp": 1.0, "min_confidence": 40, "min_p_ht_profit": 0.48},
        "pro_tempo": {"classic_prematch_only": True},
        "pro_tempo_strategies": {"lay_1x2_classic": {"enabled": True}},
    }
    rec = _rec(
        market="home_win_ft", stake_back_pct=0.0, stake_lay_pct=0.015,
        lay_max=1.40, edge_pp=2.0, probabilidade_estimada=0.55,
    )
    ok, side, label = assess_pro_tempo_entry(rec, "home_win_ft", 2.0, 1.38, cfg)
    assert ok and side == "LAY" and "Mandante" in label

    ok_none, _, _ = assess_pro_tempo_entry(rec, "home_win_ft", 2.0, None, cfg, require_exchange_odd=True)
    assert not ok_none


def test_pick_best_prefers_enter_label():
    recs = [
        {"action": "SKIP", "market": "home_win_ft"},
        {"action": "ENTER", "action_label": "BACK Empate FT", "market": "draw_ft",
         "edge_pp": 2.5, "confianca": 70, "entry_side": "BACK"},
    ]
    label, mkt, conf, side = pick_best_action(recs, [])
    assert label == "BACK Empate FT"
    assert mkt == "draw_ft"
    assert conf == 70
    assert side == "BACK"
