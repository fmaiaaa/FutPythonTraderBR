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

SIDE_KEY = {"home_win_ft": "home", "draw_ft": "draw", "away_win_ft": "away"}


def _alert_id(home: str, away: str, market: str, alert_type: str) -> str:
    return f"{home}|{away}|{market}|{alert_type}"


def _selection_id(market_odds: MarketOdds, market: str) -> int | None:
    ex = market_odds.get_exchange(SIDE_KEY.get(market, "home"))
    return ex.selection_id if ex else None


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

        side_key = SIDE_KEY[mkt]
        ex = market_odds.get_exchange(side_key)
        odd_back = ex.back if ex else market_odds.get(mkt)
        odd_lay = ex.lay if ex else market_odds.get_lay(mkt)
        sel_id = _selection_id(market_odds, mkt)

        rec_dict = rec.to_dict()
        rec_dict["market_label"] = MARKET_LABELS.get(mkt, mkt)
        rec_dict["odd_back"] = odd_back
        rec_dict["odd_lay"] = odd_lay
        rec_dict["betfair_enriched"] = market_odds.source == "betfair_br"
        recs.append(rec_dict)

        def _base_alert(alert_type, severity, message, side="BACK"):
            return LiveAlert(
                alert_id=_alert_id(home, away, mkt, alert_type),
                alert_type=alert_type,
                severity=severity,
                home=home, away=away, league=league, market=mkt,
                message=message,
                prob_est=rec.probabilidade_estimada,
                odd_back=odd_back, odd_lay=odd_lay,
                odd_min=rec.odd_minima_entrada,
                edge_pp=rec.edge_pp,
                stake_pct=rec.stake_back_pct if side == "BACK" else rec.stake_lay_pct,
                stake_valor=rec.stake_valor,
                stake_back_pct=rec.stake_back_pct,
                stake_lay_pct=rec.stake_lay_pct,
                market_id=market_odds.market_id,
                selection_id=sel_id,
                recommended_side=side,
                score=score, in_play=in_play,
            )

        if strat.get("back_value", {}).get("enabled", True):
            enter_side = None
            enter_stake = 0.0
            if mkt == "draw_ft" and rec.stake_back_pct > 0:
                enter_side, enter_stake = "BACK", rec.stake_back_pct
            elif mkt in ("home_win_ft", "away_win_ft") and rec.stake_lay_pct > 0:
                enter_side, enter_stake = "LAY", rec.stake_lay_pct
            if rec.action == "ENTER" and enter_side:
                alerts.append(_base_alert(
                    "ENTER", "high",
                    (
                        f"ENTRADA {MARKET_LABELS[mkt]} ({enter_side}): "
                        f"{'back' if enter_side == 'BACK' else 'lay'} "
                        f"{(odd_back if enter_side == 'BACK' else odd_lay):.2f} "
                        f"| P={rec.probabilidade_estimada:.1%} edge={rec.edge_pp:+.1f}pp "
                        f"stake {enter_stake:.2%}"
                    ),
                    side=enter_side,
                ))
            elif odd_back and mkt == "draw_ft" and odd_back >= rec.odd_minima_entrada * (1 - watch_pct):
                if rec.edge_pp is not None and rec.edge_pp >= min_edge * 0.5:
                    alerts.append(_base_alert(
                        "WATCH", "medium",
                        (
                            f"QUASE VALOR {MARKET_LABELS[mkt]}: back {odd_back:.2f} "
                            f"(min {rec.odd_minima_entrada:.2f}) P={rec.probabilidade_estimada:.1%}"
                        ),
                    ))

        if in_play and strat.get("lay_exit_ht", {}).get("enabled", True) and odd_lay:
            if mkt in ("home_win_ft", "away_win_ft") and rec.stake_lay_pct > 0:
                ex_fair = exchange_fair_odds(rec.probabilidade_estimada, rec.phi_seguranca)
                if odd_lay <= ex_fair.lay_max:
                    alerts.append(_base_alert(
                        "HT_EXIT", "high" if in_play else "medium",
                        (
                            f"SAÍDA HT {MARKET_LABELS[mkt]}: lay {odd_lay:.2f} <= max {ex_fair.lay_max:.2f} "
                            f"| placar {score} | stake lay {rec.stake_lay_pct:.2%}"
                        ),
                        side="LAY",
                    ))

        if prev_odds and strat.get("steam_move", {}).get("enabled", True):
            prev = prev_odds.get(mkt)
            if prev and odd_back and abs(odd_back - prev) / prev >= 0.05:
                direction = "subiu" if odd_back > prev else "caiu"
                alerts.append(_base_alert(
                    "STEAM", "low",
                    f"STEAM {MARKET_LABELS[mkt]}: odd {direction} {prev:.2f} → {odd_back:.2f}",
                ))

    return recs, alerts
