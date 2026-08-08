from __future__ import annotations

from datetime import date

import pandas as pd

from ..models.predict import get_predictor, ModelPrediction
from ..calendar import list_market_odds
from .config import load_config
from .fair_odds import exchange_fair_odds, fair_odd, min_entry_odd
from .ht_trading import estimate_ht_trade
from .kelly import explain_zero_stake, kelly_ht_trade, compute_back_lay_stakes, apply_pro_tempo_stake_policy
from .market_probs import p_ht_profit_proxy, probability_for_market
from .market_sim import MarketOdds, MarketProvider, SimulatedMarket
from .probabilities import estimate_match_probabilities
from .recommendation import TradeRecommendation
from ..markets import TRADING_MARKETS, available_markets_for_row, market_by_id, stake_sides_allowed
from ..models.calibration import dynamic_phi


def build_recommendation(
    df: pd.DataFrame,
    home: str,
    away: str,
    market: str = "home_win_ft",
    market_odds: MarketOdds | None = None,
    match_date: str | None = None,
    league_slug: str | None = None,
    bankroll: float | None = None,
    reference_mode: bool | None = None,
    pred: ModelPrediction | None = None,
) -> TradeRecommendation:
    cfg = load_config()
    bankroll = bankroll or cfg["trading"]["bankroll"]
    min_conf = cfg["trading"]["min_confidence"]
    reference_mode = (
        reference_mode
        if reference_mode is not None
        else cfg["trading"].get("reference_mode", False)
    )
    ignore_odds = cfg["trading"].get("ignore_market_odds_filter", False)

    if pred is None:
        pred = get_predictor().predict(
            df, home, away, market, match_date, league_slug,
            market_odds=(
                market_odds.to_market_dict()
                if market_odds and hasattr(market_odds, "to_market_dict")
                else {
                    "Odd_1_FT": market_odds.home if market_odds else None,
                    "Odd_X_FT": market_odds.draw if market_odds else None,
                    "Odd_2_FT": market_odds.away if market_odds else None,
                }
            ) if market_odds else None,
        )
    else:
        sel_map = {
            "home_win_ft": pred.prob_home,
            "draw_ft": pred.prob_draw,
            "away_win_ft": pred.prob_away,
        }
        pred = ModelPrediction(
            prob_home=pred.prob_home,
            prob_draw=pred.prob_draw,
            prob_away=pred.prob_away,
            prob_selection=sel_map.get(market, pred.prob_selection),
            p_ht_profitable=pred.p_ht_profitable,
            phi_dynamic=dynamic_phi(sel_map.get(market, pred.prob_selection), "outcome"),
            confidence=pred.confidence,
            schedule_notes=pred.schedule_notes,
            model_loaded=pred.model_loaded,
        )

    p = pred.prob_selection
    phi = pred.phi_dynamic
    ex = exchange_fair_odds(p, phi)
    fo, mo = ex.back_fair, ex.back_min
    m_odd = market_odds.get(market) if market_odds else None
    implied = (1 / m_odd) if m_odd and m_odd > 1.01 else None
    edge = round((p - implied) * 100, 2) if implied else None

    entry_odd = mo if (reference_mode or ignore_odds) else (m_odd or mo)
    from .probabilities import MatchProbabilities
    mp = MatchProbabilities(
        home=pred.prob_home, draw=pred.prob_draw, away=pred.prob_away,
        lambda_home=1.4, lambda_away=1.1, sample_home=10, sample_away=10,
    )
    ht = estimate_ht_trade(mp, ex.back_min if market in TRADING_MARKETS else entry_odd, market)
    p_ht = pred.p_ht_profitable if pred.model_loaded else ht.p_profitable

    uses_ht = market in TRADING_MARKETS
    # Kelly conservador: entrada back mín; lay stake no lay máx; saída HT pelo modelo @ back mín
    odd_back_kelly = ex.back_min
    odd_lay_kelly = ex.lay_max

    exit_odd = ht.expected_exit_odd if uses_ht else max(ex.lay_max, 1.02)
    stake_back, stake_lay = compute_back_lay_stakes(
        p, odd_back_kelly, odd_lay_kelly, bankroll, pred.confidence,
        p_ht=p_ht if uses_ht else None,
        exit_odd=exit_odd if uses_ht else None,
        uses_ht=uses_ht,
    )
    allow_back, allow_lay = stake_sides_allowed(market)
    stake_back, stake_lay = apply_pro_tempo_stake_policy(market, stake_back, stake_lay)
    stake = stake_back if allow_back else stake_lay
    lucro = ht.expected_profit_pct if uses_ht else round((p * entry_odd - 1) * 100, 2)

    if not allow_back and not allow_lay:
        stake_motivo = "Stake apenas: lay time FT, back empate FT ou under gols"
    else:
        stake_motivo = explain_zero_stake(stake_back if allow_back else stake_lay, p, p_ht, mo, uses_ht and allow_back)
        if stake_back.stake_pct <= 0 and stake_lay.stake_pct <= 0 and not stake_motivo:
            stake_motivo = explain_zero_stake(stake_lay, 1 - p, p_ht, ex.lay_fair, False) if allow_lay else stake_motivo

    has_stake = stake_back.stake_pct > 0 or stake_lay.stake_pct > 0

    reasons = []
    action = "INFO" if reference_mode else "ENTER"
    if not reference_mode:
        has_value = m_odd is None or m_odd >= mo
        if not has_value and not ignore_odds:
            reasons.append(f"odd {m_odd:.2f} < mínima {mo:.2f}")
            action = "SKIP"
        if pred.confidence < min_conf:
            reasons.append(f"confiança {pred.confidence:.0f} < {min_conf}")
            action = "SKIP"
        if not has_stake:
            reasons.append(stake_motivo or "Kelly = 0")
            action = "SKIP"
        if p_ht < 0.48 and uses_ht:
            reasons.append(f"P(lucro HT) {p_ht:.1%} baixa")
            action = "SKIP"
        if edge is not None and edge < 1.0 and not ignore_odds:
            reasons.append(f"edge {edge:.1f}p.p. < 1")
            action = "SKIP"

    return TradeRecommendation(
        home=home, away=away, market=market, action=action,
        probabilidade_estimada=p,
        prob_home=pred.prob_home, prob_draw=pred.prob_draw, prob_away=pred.prob_away,
        p_lucro_ht=p_ht,
        odd_justa=round(fo, 3),
        back_justa=ex.back_fair,
        lay_justa=ex.lay_fair,
        lay_max=ex.lay_max,
        phi_seguranca=phi,
        odd_minima_entrada=round(mo, 3),
        odd_mercado=m_odd,
        edge_pp=edge,
        implied_market=round(implied, 4) if implied else None,
        lucro_estimado_pct=lucro,
        kelly_cheio=stake.kelly_full,
        kelly_quarto=stake.kelly_quarter,
        pct_banca=stake_back.stake_pct,
        stake_back_pct=stake_back.stake_pct,
        stake_lay_pct=stake_lay.stake_pct,
        stake_valor=stake_back.stake_amount if stake_back.stake_pct > 0 else round(bankroll * stake_lay.stake_pct, 2),
        confianca=pred.confidence,
        stake_motivo=stake_motivo,
        model_loaded=pred.model_loaded,
        schedule_notes=pred.schedule_notes,
        reasons=reasons,
    )


def build_recommendations_1x2(
    df: pd.DataFrame,
    home: str,
    away: str,
    market_odds: MarketOdds | None = None,
    match_date: str | None = None,
    league_slug: str | None = None,
    bankroll: float | None = None,
    markets: list[str] | None = None,
    reference_mode: bool = False,
) -> list[TradeRecommendation]:
    """Mercados 1X2 com uma única passagem de features/ML."""
    markets = markets or ["home_win_ft", "draw_ft", "away_win_ft"]
    mkt_dict = None
    if market_odds:
        mkt_dict = (
            market_odds.to_market_dict()
            if hasattr(market_odds, "to_market_dict")
            else {
                "Odd_1_FT": market_odds.home,
                "Odd_X_FT": market_odds.draw,
                "Odd_2_FT": market_odds.away,
            }
        )
    base_pred = get_predictor().predict(
        df, home, away, "home_win_ft", match_date, league_slug, mkt_dict,
    )
    return [
        build_recommendation(
            df, home, away, mkt, market_odds, match_date, league_slug,
            bankroll, reference_mode=reference_mode, pred=base_pred,
        )
        for mkt in markets
    ]


def build_market_reference(
    df: pd.DataFrame,
    home: str,
    away: str,
    market: str,
    row_odds: dict[str, float] | None = None,
    match_date: str | None = None,
    league_slug: str | None = None,
    bankroll: float | None = None,
    ml_probs: dict[str, float] | None = None,
    confidence: float = 70.0,
    p_ht_ml: float | None = None,
) -> TradeRecommendation:
    """Linha de referencia: back/lay justos, phi, stake HT — sem filtro de odd atual."""
    cfg = load_config()
    bankroll = bankroll or cfg["trading"]["bankroll"]

    mp = estimate_match_probabilities(df, home, away, league_slug)
    p = probability_for_market(market, mp, ml_probs)
    phi = dynamic_phi(p, "outcome")
    ex = exchange_fair_odds(p, phi)
    m_odd = (row_odds or {}).get(market)
    implied = (1 / m_odd) if m_odd and m_odd > 1.01 else None
    edge = round((p - implied) * 100, 2) if implied else None

    mdef = market_by_id(market)
    ht = estimate_ht_trade(mp, ex.back_min, market if market in TRADING_MARKETS else "home_win_ft")

    if market in TRADING_MARKETS:
        p_ht = p_ht_ml if p_ht_ml is not None else ht.p_profitable
        exit_odd = ht.expected_exit_odd
        lucro = ht.expected_profit_pct
        uses_ht = True
    else:
        p_ht = p_ht_profit_proxy(market, mp, p)
        exit_odd = max(ex.lay_max, 1.02)
        if mdef and mdef.group.endswith("_ht"):
            exit_odd = max(ex.back_fair * 0.95, 1.02)
        lucro = round((p_ht * (ex.back_min / exit_odd) - 1) * 100, 2)
        uses_ht = True

    odd_back_kelly = ex.back_min
    odd_lay_kelly = ex.lay_max
    stake_back, stake_lay = compute_back_lay_stakes(
        p, odd_back_kelly, odd_lay_kelly, bankroll, confidence,
        p_ht=p_ht, exit_odd=exit_odd, uses_ht=uses_ht,
    )
    allow_back, allow_lay = stake_sides_allowed(market)
    stake_back, stake_lay = apply_pro_tempo_stake_policy(market, stake_back, stake_lay)
    stake = stake_back if allow_back else stake_lay
    if not allow_back and not allow_lay:
        stake_motivo = "Stake apenas: lay time FT, back empate FT ou under gols"
    else:
        stake_motivo = explain_zero_stake(stake_back if allow_back else stake_lay, p, p_ht, ex.back_min, uses_ht and allow_back)

    prob_h, prob_d, prob_a = mp.home, mp.draw, mp.away
    if ml_probs:
        prob_h, prob_d, prob_a = ml_probs["home"], ml_probs["draw"], ml_probs["away"]

    return TradeRecommendation(
        home=home, away=away, market=market, action="INFO",
        probabilidade_estimada=round(p, 4),
        prob_home=prob_h, prob_draw=prob_d, prob_away=prob_a,
        p_lucro_ht=round(p_ht, 4),
        odd_justa=ex.back_fair,
        back_justa=ex.back_fair,
        lay_justa=ex.lay_fair,
        lay_max=ex.lay_max,
        phi_seguranca=phi,
        odd_minima_entrada=ex.back_min,
        odd_mercado=m_odd,
        edge_pp=edge,
        implied_market=round(implied, 4) if implied else None,
        lucro_estimado_pct=lucro,
        kelly_cheio=stake.kelly_full,
        kelly_quarto=stake.kelly_quarter,
        pct_banca=stake_back.stake_pct,
        stake_back_pct=stake_back.stake_pct,
        stake_lay_pct=stake_lay.stake_pct,
        stake_valor=stake_back.stake_amount if stake_back.stake_pct > 0 else round(bankroll * stake_lay.stake_pct, 2),
        confianca=confidence,
        stake_motivo=stake_motivo,
        model_loaded=ml_probs is not None,
        schedule_notes=[],
        reasons=[],
    )


def scan_match_all_markets(
    df: pd.DataFrame,
    home: str,
    away: str,
    row: pd.Series,
    match_date: str | None = None,
    bankroll: float | None = None,
) -> list[TradeRecommendation]:
    """Todos os mercados FPT do jogo — estrategia entrada pre / saida HT."""
    row_odds = list_market_odds(row) if hasattr(row, "get") else {}
    league_slug = row.get("League_Slug") if hasattr(row, "get") else None

    ml_probs = None
    confidence = 70.0
    p_ht_by_market: dict[str, float] = {}
    mp = estimate_match_probabilities(df, home, away, league_slug)
    try:
        pred = get_predictor().predict(
            df, home, away, "home_win_ft", match_date, league_slug,
            market_odds={
                "Odd_1_FT": row_odds.get("home_win_ft"),
                "Odd_X_FT": row_odds.get("draw_ft"),
                "Odd_2_FT": row_odds.get("away_win_ft"),
            },
        )
        ml_probs = {"home": pred.prob_home, "draw": pred.prob_draw, "away": pred.prob_away}
        confidence = pred.confidence
        from .probabilities import MatchProbabilities
        mp_ml = MatchProbabilities(
            home=pred.prob_home, draw=pred.prob_draw, away=pred.prob_away,
            lambda_home=mp.lambda_home, lambda_away=mp.lambda_away,
            sample_home=mp.sample_home, sample_away=mp.sample_away,
        )
        for mid in TRADING_MARKETS:
            ht = estimate_ht_trade(mp_ml, min_entry_odd(
                probability_for_market(mid, mp_ml, ml_probs),
                dynamic_phi(probability_for_market(mid, mp_ml, ml_probs), "outcome"),
            ), mid)
            p_ht_by_market[mid] = ht.p_profitable
    except Exception:
        pass

    recs = []
    for m in available_markets_for_row(row):
        recs.append(build_market_reference(
            df, home, away, market=m.id, row_odds=row_odds,
            match_date=match_date, league_slug=league_slug,
            bankroll=bankroll, ml_probs=ml_probs, confidence=confidence,
            p_ht_ml=p_ht_by_market.get(m.id),
        ))
    return recs


def scan_day(
    df: pd.DataFrame,
    day: str | None = None,
    markets: list[str] | None = None,
    bankroll: float | None = None,
) -> list[TradeRecommendation]:
    from ..downloader import fetch_jogos_do_dia
    from ..operation import filter_brazil_today

    day = day or date.today().isoformat()
    markets = markets or ["home_win_ft", "draw_ft", "away_win_ft"]
    out: list[TradeRecommendation] = []

    try:
        jogos = filter_brazil_today(fetch_jogos_do_dia(day))
    except Exception:
        jogos = pd.DataFrame()

    if jogos.empty:
        return out

    home_col = next((c for c in jogos.columns if c.lower() in ("home", "mandante")), "Home")
    away_col = next((c for c in jogos.columns if c.lower() in ("away", "visitante")), "Away")
    sim = SimulatedMarket(df)

    for _, row in jogos.iterrows():
        home, away = str(row[home_col]), str(row[away_col])
        if home in ("nan", "") or away in ("nan", ""):
            continue
        odds = sim.odds_from_row(row) if "Odd_1_FT" in row.index else sim.get_odds(home, away)
        for mkt in markets:
            rec = build_recommendation(
                df, home, away, market=mkt, market_odds=odds,
                match_date=day, bankroll=bankroll,
            )
            if rec.action == "ENTER":
                out.append(rec)
    return out


def format_report(recs: list[TradeRecommendation], day: str | None = None) -> str:
    day = day or date.today().isoformat()
    lines = [f"=== SCAN TRADING ML — {day} ===", f"Entradas: {len(recs)}", ""]
    for r in recs:
        lines.append(r.report())
        lines.append("")
    return "\n".join(lines)
