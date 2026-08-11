"""Testes — estratégias pro-tempo contextual e scalping."""
from __future__ import annotations

from fpt.live.match_context import MatchLiveContext
from fpt.live.pro_tempo_strategies import evaluate_pro_tempo_strategies
from fpt.live.scalping_strategies import evaluate_scalping_strategies, is_scalp_entry
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
        stake_valor=2.0, confianca=65.0, model_loaded=True,
        stake_motivo="", schedule_notes=[], reasons=[],
    )
    defaults.update(kwargs)
    return TradeRecommendation(**defaults)


def _cfg() -> dict:
    return {
        "live": {"min_edge_pp": 1.0, "min_confidence": 40, "min_p_ht_profit": 0.48},
        "pro_tempo": {"classic_prematch_only": True},
        "pro_tempo_strategies": {
            "back_draw_classic": {"enabled": True},
            "lay_1x2_classic": {"enabled": True},
            "under_dead_game": {"enabled": True, "window_min": [15, 38], "markets": ["under25_ft"]},
            "lay_favorite_absent": {"enabled": True, "window_min": [10, 40]},
        },
        "scalping": {"enabled": True, "stake_pct": 0.02, "max_elapsed_min": 75},
        "scalping_gates": {"enabled": False},
        "entry_exposure": {"enabled": False},
        "scalping_strategies": {
            "pressure_steam": {"enabled": True, "min_dominance": 12, "min_pressure_delta": 8, "steam_pct": 0.03},
            "pressure_surge": {"enabled": True},
        },
        "pressure_odds": {"enabled": False},
    }


def test_under_dead_game_live():
    ctx = MatchLiveContext(
        home="A", away="B", in_play=True, elapsed_min=25,
        score_home=0, score_away=0,
        pressure_home=8, pressure_away=6,
        row_odds={"over25_ft": 1.75, "under25_ft": 2.10},
        sofascore_stats={"ss_xg_home": 0.1, "ss_xg_away": 0.05},
    )
    rec = _rec(market="under25_ft", stake_back_pct=0.015, stake_lay_pct=0.0, p_lucro_ht=0.0)
    recs = {"under25_ft": rec}
    odds = {"under25_ft": (2.10, None)}
    signals = evaluate_pro_tempo_strategies(ctx, recs, odds, _cfg(), betfair_ok=False)
    ids = [s.strategy_id for s in signals]
    assert "under_dead_game" in ids


def test_lay_favorite_absent():
    ctx = MatchLiveContext(
        home="Mandante", away="Favorito", in_play=True, elapsed_min=30,
        score_home=1, score_away=0,
        odd_home=4.5, odd_away=1.55,
        pressure_home=42, pressure_away=18,
        sofascore_stats={"ss_sot_home": 4, "ss_sot_away": 0},
    )
    rec = _rec(
        market="away_win_ft", stake_lay_pct=0.015, stake_back_pct=0.0,
        probabilidade_estimada=0.55, lay_max=1.65, edge_pp=2.0,
    )
    signals = evaluate_pro_tempo_strategies(
        ctx,
        {"away_win_ft": rec},
        {"away_win_ft": (6.0, 1.58)},
        _cfg(),
        betfair_ok=True,
    )
    assert any(s.strategy_id == "lay_favorite_absent" for s in signals)


def test_scalp_pressure_steam():
    ctx = MatchLiveContext(
        home="H", away="A", in_play=True, elapsed_min=35,
        pressure_home=55, pressure_away=30,
        prev_pressure={"home": 48, "away": 32},
        prev_odds={"home_win_ft": 2.10},
        graph_momentum=15,
        sofascore_stats={"ss_xg_home": 0.8, "ss_xg_away": 0.2},
    )
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


def test_is_scalp_entry_types():
    assert is_scalp_entry("PRESSURE_STEAM")
    assert is_scalp_entry("SCALP_XG_SPIKE")
    assert not is_scalp_entry("ENTER")
