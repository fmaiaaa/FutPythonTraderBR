from __future__ import annotations

"""Estratégias live: valor back, saída HT, steam move."""

from ..trading.engine import build_recommendation
from ..trading.fair_odds import exchange_fair_odds
from ..trading.market_sim import MarketOdds
from ..models.predict import get_predictor
from .config import load_live_config
from .models import LiveAlert

MARKET_LABELS = {
    "home_win_ft": "Mandante",
    "draw_ft": "Empate",
    "away_win_ft": "Visitante",
}


def _alert_id(home: str, away: str, market: str, alert_type: str) -> str:
    return f"{home}|{away}|{market}|{alert_type}"


def evaluate_match_strategies(
    df,
    home: str,
    away: str,
    league: str,
    league_slug: str | None,
    match_date: str,
    market_odds: MarketOdds,
    bankroll: float | None = None,
    prev_odds: dict[str, float] | None = None,
    in_play: bool = False,
    score: str = "",
) -> tuple[list[dict], list[LiveAlert]]:
    """
    Avalia mercados 1X2 com odds Betfair + modelo ML.
    Retorna recomendações por mercado e alertas acionáveis.
    """
    cfg = load_live_config()
    live = cfg["live"]
    strat = cfg.get("strategies", {})
    bankroll = bankroll or live.get("bankroll", 1000.0)
    markets = live.get("markets", ["home_win_ft", "draw_ft", "away_win_ft"])
    min_edge = live.get("min_edge_pp", 1.0)
    watch_pct = live.get("watch_near_value_pct", 2.0) / 100

    mkt_dict = market_odds.to_market_dict() if market_odds else {}
    base_pred = get_predictor().predict(
        df, home, away, "home_win_ft", match_date, league_slug, mkt_dict or None,
    )

    recs: list[dict] = []
    alerts: list[LiveAlert] = []

    for mkt in markets:
        rec = build_recommendation(
            df, home, away,
            market=mkt,
            market_odds=market_odds,
            match_date=match_date,
            league_slug=league_slug,
            bankroll=bankroll,
            reference_mode=False,
            pred=base_pred,
        )

        side_key = {"home_win_ft": "home", "draw_ft": "draw", "away_win_ft": "away"}[mkt]
        ex = market_odds.get_exchange(side_key)
        odd_back = ex.back if ex else market_odds.get(mkt)
        odd_lay = ex.lay if ex else market_odds.get_lay(mkt)

        rec_dict = rec.to_dict()
        rec_dict["market_label"] = MARKET_LABELS.get(mkt, mkt)
        rec_dict["odd_back"] = odd_back
        rec_dict["odd_lay"] = odd_lay
        rec_dict["betfair_enriched"] = market_odds.source == "betfair_br"
        recs.append(rec_dict)

        # --- BACK VALUE ---
        if strat.get("back_value", {}).get("enabled", True):
            if rec.action == "ENTER":
                alerts.append(LiveAlert(
                    alert_id=_alert_id(home, away, mkt, "ENTER"),
                    alert_type="ENTER",
                    severity="high",
                    home=home, away=away, league=league, market=mkt,
                    message=(
                        f"ENTRADA {MARKET_LABELS[mkt]}: back {odd_back:.2f} >= min {rec.odd_minima_entrada:.2f} "
                        f"| P={rec.probabilidade_estimada:.1%} edge={rec.edge_pp:+.1f}pp stake R${rec.stake_valor:.2f}"
                    ),
                    prob_est=rec.probabilidade_estimada,
                    odd_back=odd_back, odd_lay=odd_lay,
                    odd_min=rec.odd_minima_entrada,
                    edge_pp=rec.edge_pp,
                    stake_pct=rec.pct_banca,
                    stake_valor=rec.stake_valor,
                    score=score, in_play=in_play,
                ))
            elif odd_back and odd_back >= rec.odd_minima_entrada * (1 - watch_pct):
                if rec.edge_pp is not None and rec.edge_pp >= min_edge * 0.5:
                    alerts.append(LiveAlert(
                        alert_id=_alert_id(home, away, mkt, "WATCH"),
                        alert_type="WATCH",
                        severity="medium",
                        home=home, away=away, league=league, market=mkt,
                        message=(
                            f"QUASE VALOR {MARKET_LABELS[mkt]}: back {odd_back:.2f} "
                            f"(min {rec.odd_minima_entrada:.2f}) P={rec.probabilidade_estimada:.1%}"
                        ),
                        prob_est=rec.probabilidade_estimada,
                        odd_back=odd_back, odd_lay=odd_lay,
                        odd_min=rec.odd_minima_entrada,
                        edge_pp=rec.edge_pp,
                        stake_pct=rec.pct_banca,
                        stake_valor=rec.stake_valor,
                        score=score, in_play=in_play,
                    ))

        # --- HT EXIT (in-play lay) ---
        if in_play and strat.get("lay_exit_ht", {}).get("enabled", True) and odd_lay:
            ex_fair = exchange_fair_odds(rec.probabilidade_estimada, rec.phi_seguranca)
            if odd_lay <= ex_fair.lay_max:
                alerts.append(LiveAlert(
                    alert_id=_alert_id(home, away, mkt, "HT_EXIT"),
                    alert_type="HT_EXIT",
                    severity="high" if in_play else "medium",
                    home=home, away=away, league=league, market=mkt,
                    message=(
                        f"SAIDA HT {MARKET_LABELS[mkt]}: lay {odd_lay:.2f} <= max {ex_fair.lay_max:.2f} "
                        f"| placar {score}"
                    ),
                    prob_est=rec.probabilidade_estimada,
                    odd_back=odd_back, odd_lay=odd_lay,
                    odd_min=rec.odd_minima_entrada,
                    edge_pp=rec.edge_pp,
                    stake_pct=rec.pct_banca,
                    stake_valor=rec.stake_valor,
                    score=score, in_play=True,
                ))

        # --- STEAM MOVE ---
        if prev_odds and strat.get("steam_move", {}).get("enabled", True):
            prev = prev_odds.get(mkt)
            if prev and odd_back and abs(odd_back - prev) / prev >= 0.05:
                direction = "subiu" if odd_back > prev else "caiu"
                alerts.append(LiveAlert(
                    alert_id=_alert_id(home, away, mkt, "STEAM"),
                    alert_type="STEAM",
                    severity="low",
                    home=home, away=away, league=league, market=mkt,
                    message=f"STEAM {MARKET_LABELS[mkt]}: odd {direction} {prev:.2f} → {odd_back:.2f}",
                    prob_est=rec.probabilidade_estimada,
                    odd_back=odd_back, odd_lay=odd_lay,
                    odd_min=rec.odd_minima_entrada,
                    edge_pp=rec.edge_pp,
                    stake_pct=rec.pct_banca,
                    stake_valor=rec.stake_valor,
                    score=score, in_play=in_play,
                ))

    return recs, alerts
