from __future__ import annotations



"""Estratégias live: pro-tempo contextual + scalping + saídas HT."""



import pandas as pd



from ..markets import available_markets_for_row

from ..trading.engine import build_market_reference, build_recommendation

from ..trading.fair_odds import exchange_fair_odds

from ..trading.market_sim import MarketOdds

from ..calendar import list_market_odds

from ..models.predict import get_predictor

from .config import load_live_config

from .match_context import MatchLiveContext

from .models import LiveAlert

from .pro_tempo import assess_watch, format_action_label

from .pro_tempo_strategies import (

    best_signal_for_market,

    evaluate_pro_tempo_strategies,

)

from .scalping_strategies import evaluate_scalping_strategies, is_scalp_entry
from .entry_exposure import (
    OpenExposure,
    check_entry_exposure,
    load_open_exposures,
)



MARKET_LABELS = {

    "home_win_ft": "Casa",

    "draw_ft": "Empate",

    "away_win_ft": "Visitante",

}



SIDE_KEY = {"home_win_ft": "home", "draw_ft": "draw", "away_win_ft": "away"}





def _fmt_odd(v: float | None) -> str:

    return f"{v:.2f}" if v is not None else "—"





def _alert_id(home: str, away: str, market: str, alert_type: str) -> str:

    return f"{home}|{away}|{market}|{alert_type}"





def _selection_id(market_odds: MarketOdds, market: str) -> int | None:

    ex = market_odds.get_exchange(SIDE_KEY.get(market, "home"))

    return ex.selection_id if ex else None





def _build_context(

    home: str,

    away: str,

    in_play: bool,

    score: str,

    pressure_home: float | None,

    pressure_away: float | None,

    prev_pressure: dict | None,

    prev_live: dict | None,

    elapsed_min: int | None,

    market_odds: MarketOdds,

    prev_odds: dict | None,

    sofascore_stats: dict | None,

    graph_momentum: float | None,

    row_odds: dict,

) -> MatchLiveContext:

    sh, sa = 0, 0

    if score and "-" in score and score != "—":

        try:

            parts = score.split("-", 1)

            sh, sa = int(parts[0]), int(parts[1])

        except ValueError:

            pass

    return MatchLiveContext(

        home=home,

        away=away,

        in_play=in_play,

        elapsed_min=elapsed_min,

        score_home=sh,

        score_away=sa,

        pressure_home=pressure_home,

        pressure_away=pressure_away,

        prev_pressure=prev_pressure,

        prev_live=prev_live,

        sofascore_stats=sofascore_stats or {},

        odd_home=market_odds.get("home_win_ft"),

        odd_away=market_odds.get("away_win_ft"),

        odd_draw=market_odds.get("draw_ft"),

        prev_odds=prev_odds,

        graph_momentum=graph_momentum,

        row_odds=row_odds,

    )





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

    pressure_home: float | None = None,

    pressure_away: float | None = None,

    prev_pressure: dict[str, float] | None = None,

    prev_live: dict[str, float] | None = None,

    elapsed_min: int | None = None,

    row: pd.Series | None = None,

    sofascore_stats: dict | None = None,

    graph_momentum: float | None = None,

    market_id: str | None = None,

    sofascore_event_id: int | None = None,

) -> tuple[list[dict], list[LiveAlert]]:

    cfg = load_live_config()

    live = cfg["live"]

    strat = cfg.get("strategies", {})

    bankroll = bankroll or live.get("bankroll", 1000.0)

    open_exposures = load_open_exposures()

    pending_exposures: list[OpenExposure] = []

    markets = live.get("markets", ["home_win_ft", "draw_ft", "away_win_ft"])

    betfair_ok = market_odds.source == "betfair_br"

    from ..league_ranking import adjust_stake_pct, league_operation_allowed

    from .match_coverage import in_live_feeds_ok, prematch_feeds_ok

    allowed, league_rank, _block = league_operation_allowed(
        league_slug=league_slug,
        league_raw=league,
        cfg=cfg.get("leagues"),
    )
    if not allowed:
        return [], []

    prematch_ok = prematch_feeds_ok(
        in_play=in_play,
        market_id=market_id or market_odds.market_id,
        odds_source=market_odds.source,
        row=row,
        market_odds=market_odds,
        cfg=cfg,
    )
    in_live_ok = in_live_feeds_ok(
        in_play=in_play,
        market_id=market_id or market_odds.market_id,
        sofascore_event_id=sofascore_event_id,
        odds_source=market_odds.source,
        market_odds=market_odds,
        cfg=cfg,
    )
    require_exchange = bool(cfg.get("execution", {}).get("require_exchange", True))
    if require_exchange and not betfair_ok:
        prematch_ok = False
        in_live_ok = False



    row_odds: dict = {}

    if row is not None and hasattr(row, "get"):

        row_odds = list_market_odds(row)



    ctx = _build_context(

        home, away, in_play, score,

        pressure_home, pressure_away, prev_pressure, prev_live,

        elapsed_min, market_odds, prev_odds,

        sofascore_stats, graph_momentum, row_odds,

    )



    mkt_dict = market_odds.to_market_dict() if market_odds else {}

    base_pred = get_predictor().predict(

        df, home, away, "home_win_ft", match_date, league_slug, mkt_dict or None,

    )



    recs: list[dict] = []

    alerts: list[LiveAlert] = []

    rec_objs: dict[str, object] = {}

    odds_map: dict[str, tuple[float | None, float | None]] = {}



    ml_probs = {"home": base_pred.prob_home, "draw": base_pred.prob_draw, "away": base_pred.prob_away}

    confidence = base_pred.confidence



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



        rec_objs[mkt] = rec

        odds_map[mkt] = (odd_back, odd_lay)



        rec_dict = rec.to_dict()

        rec_dict["market"] = mkt

        rec_dict["market_label"] = MARKET_LABELS.get(mkt, mkt)

        rec_dict["odd_back"] = odd_back

        rec_dict["odd_lay"] = odd_lay

        rec_dict["betfair_enriched"] = betfair_ok

        rec_dict["stake_back_pct"] = adjust_stake_pct(float(rec_dict.get("stake_back_pct") or 0), league_rank)

        rec_dict["stake_lay_pct"] = adjust_stake_pct(float(rec_dict.get("stake_lay_pct") or 0), league_rank)

        rec_dict["league_tier"] = league_rank.tier

        rec_dict["league_kelly_mult"] = league_rank.kelly_multiplier

        rec_dict["action"] = "SKIP"

        rec_dict["action_label"] = "—"

        rec_dict["entry_side"] = None

        rec_dict["strategy_id"] = None

        recs.append(rec_dict)



        def _base_alert(alert_type, severity, message, side="BACK", stake_pct=None):

            sb = stake_pct if stake_pct is not None else (

                rec.stake_back_pct if side == "BACK" else rec.stake_lay_pct

            )

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

                stake_pct=sb,

                stake_valor=bankroll * sb,

                stake_back_pct=sb if side == "BACK" else 0.0,

                stake_lay_pct=sb if side == "LAY" else 0.0,

                market_id=market_odds.market_id,

                selection_id=sel_id,

                recommended_side=side,

                score=score, in_play=in_play,

            )



        if in_play and in_live_ok and strat.get("lay_exit_ht", {}).get("enabled", True) and odd_lay:

            if mkt in ("home_win_ft", "away_win_ft") and rec.stake_lay_pct > 0:

                ex_fair = exchange_fair_odds(rec.probabilidade_estimada, rec.phi_seguranca)

                if odd_lay <= ex_fair.lay_max:

                    alerts.append(_base_alert(

                        "HT_EXIT", "high",

                        (

                            f"SAÍDA HT {MARKET_LABELS[mkt]}: lay {odd_lay:.2f} <= max {ex_fair.lay_max:.2f} "

                            f"| placar {score}"

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



        # Scalping — todas as estratégias no mercado mandante (configurável)

        scalp_markets = cfg.get("scalping", {}).get("markets", ["home_win_ft"])

        if mkt in scalp_markets and in_live_ok:

            for sa in evaluate_scalping_strategies(

                ctx,

                home=home, away=away, league=league,

                market=mkt, market_label=MARKET_LABELS.get(mkt, mkt),

                odd_back=odd_back, odd_lay=odd_lay,

                prob_est=rec.probabilidade_estimada,

                odd_min=rec.odd_minima_entrada,

                edge_pp=rec.edge_pp,

                prob_home=ml_probs["home"],

                prob_draw=ml_probs["draw"],

                prob_away=ml_probs["away"],

                phi=float(getattr(rec, "phi_seguranca", 1.08) or 1.08),

                market_id=market_odds.market_id,

                selection_id=sel_id,

                score=score, cfg=cfg, bankroll=bankroll,

                alert_id_fn=_alert_id,

                open_exposures=open_exposures,

                pending_exposures=pending_exposures,

            ):

                sp = sa["stake_pct"]

                alert_type = sa["alert_type"]

                side = sa["side"]

                # Compat legado testes

                if alert_type == "SCALP_PRESSURE_STEAM":

                    legacy_type = "PRESSURE_STEAM"

                else:

                    legacy_type = alert_type

                alerts.append(LiveAlert(

                    alert_id=_alert_id(home, away, mkt, alert_type),

                    alert_type=legacy_type if alert_type == "SCALP_PRESSURE_STEAM" else alert_type,

                    severity="high",

                    home=home, away=away, league=league, market=mkt,

                    message=sa["message"],

                    prob_est=rec.probabilidade_estimada,

                    odd_back=odd_back, odd_lay=odd_lay,

                    odd_min=rec.odd_minima_entrada,

                    edge_pp=rec.edge_pp,

                    stake_pct=sp,

                    stake_valor=bankroll * sp,

                    stake_back_pct=sp if side == "BACK" else 0.0,

                    stake_lay_pct=sp if side == "LAY" else 0.0,

                    market_id=market_odds.market_id,

                    selection_id=sel_id,

                    recommended_side=side,

                    score=score, in_play=in_play,

                ))



    # Under markets — referências FPT

    if row is not None and hasattr(row, "get"):

        for m in available_markets_for_row(row):

            if not m.id.startswith("under"):

                continue

            ref = build_market_reference(

                df, home, away, market=m.id, row_odds=row_odds,

                match_date=match_date, league_slug=league_slug,

                bankroll=bankroll, ml_probs=ml_probs, confidence=confidence,

            )

            odd_back = row_odds.get(m.id)

            rec_objs[m.id] = ref

            odds_map[m.id] = (odd_back, None)

            ref_dict = ref.to_dict()

            ref_dict["market"] = m.id

            ref_dict["market_label"] = m.label

            ref_dict["odd_back"] = odd_back

            ref_dict["odd_lay"] = None

            ref_dict["betfair_enriched"] = False

            ref_dict["action"] = "SKIP"

            ref_dict["action_label"] = "—"

            ref_dict["strategy_id"] = None

            recs.append(ref_dict)



    # Pro-tempo — todas as estratégias (clássicas + live)

    if not in_play:
        if prematch_ok:
            pt_signals = evaluate_pro_tempo_strategies(ctx, rec_objs, odds_map, cfg, betfair_ok=betfair_ok)
        else:
            pt_signals = []
    elif in_live_ok:
        pt_signals = evaluate_pro_tempo_strategies(ctx, rec_objs, odds_map, cfg, betfair_ok=betfair_ok)
    else:
        pt_signals = []



    for rec_dict in recs:

        mkt = rec_dict.get("market", "")

        sig = best_signal_for_market(pt_signals, mkt)

        if not sig:
            watch = assess_watch(rec_objs.get(mkt, rec_dict), mkt, rec_dict.get("odd_back"), cfg)
            if watch:
                rec_dict["watch_label"] = watch
            continue

        if sig.phase == "prematch" and not prematch_ok:
            continue
        if sig.phase != "prematch" and in_play and not in_live_ok:
            continue
        if require_exchange and not betfair_ok:
            continue

        rec_dict["action"] = "ENTER"

        rec_dict["entry_side"] = sig.side

        rec_dict["action_label"] = sig.label

        rec_dict["strategy_id"] = sig.strategy_id



        if not strat.get("back_value", {}).get("enabled", True):

            continue



        rec = rec_objs.get(mkt)

        if rec is None:

            continue

        side = sig.side

        price = rec_dict.get("odd_back") if side == "BACK" else rec_dict.get("odd_lay")

        stake = (

            float(getattr(rec, "stake_back_pct", 0) or rec_dict.get("stake_back_pct", 0))

            if side == "BACK"

            else float(getattr(rec, "stake_lay_pct", 0) or rec_dict.get("stake_lay_pct", 0))

        )

        sel_id = _selection_id(market_odds, mkt) if mkt in SIDE_KEY else None

        exp_ok, _ = check_entry_exposure(
            home, away, mkt, side, open_exposures + pending_exposures, cfg,
        )
        if not exp_ok:
            continue
        pending_exposures.append(OpenExposure(
            home, away, mkt, side, entry_type="pre_live", source="pending",
        ))

        alerts.append(LiveAlert(

            alert_id=_alert_id(home, away, mkt, f"ENTER_{sig.strategy_id}"),

            alert_type="ENTER",

            severity="high",

            home=home, away=away, league=league, market=mkt,

            message=(

                f"{sig.label}: {'back' if side == 'BACK' else 'lay'} {_fmt_odd(price)} "

                f"| P={getattr(rec, 'probabilidade_estimada', 0):.1%} "

                f"edge={getattr(rec, 'edge_pp', 0):+.1f}pp stake {stake:.2%} | saída HT"

            ),

            prob_est=float(getattr(rec, "probabilidade_estimada", 0) or 0),

            odd_back=rec_dict.get("odd_back"),

            odd_lay=rec_dict.get("odd_lay"),

            odd_min=float(getattr(rec, "odd_minima_entrada", 0) or 0),

            edge_pp=getattr(rec, "edge_pp", None),

            stake_pct=stake,

            stake_valor=bankroll * stake,

            stake_back_pct=stake if side == "BACK" else 0.0,

            stake_lay_pct=stake if side == "LAY" else 0.0,

            market_id=market_odds.market_id,

            selection_id=sel_id,

            recommended_side=side,

            score=score, in_play=in_play,

        ))



    return recs, alerts


