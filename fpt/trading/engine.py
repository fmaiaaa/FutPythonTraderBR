from __future__ import annotations

from datetime import date

import pandas as pd

from ..models.predict import get_predictor
from ..calendar import list_market_odds
from .config import load_config
from .fair_odds import fair_odd, min_entry_odd
from .ht_trading import estimate_ht_trade
from .kelly import kelly_ht_trade, kelly_simple
from .market_probs import probability_for_market
from .market_sim import MarketOdds, MarketProvider, SimulatedMarket
from .probabilities import estimate_match_probabilities
from .recommendation import TradeRecommendation
from ..markets import market_by_id, prematch_ht_markets_for_row
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

    pred = get_predictor().predict(
        df, home, away, market, match_date, league_slug,
        market_odds={
            "Odd_1_FT": market_odds.home if market_odds else None,
            "Odd_X_FT": market_odds.draw if market_odds else None,
            "Odd_2_FT": market_odds.away if market_odds else None,
        } if market_odds else None,
    )

    p = pred.prob_selection
    phi = pred.phi_dynamic
    fo = fair_odd(p)
    mo = min_entry_odd(p, phi)
    m_odd = market_odds.get(market) if market_odds else None
    implied = (1 / m_odd) if m_odd and m_odd > 1.01 else None
    edge = round((p - implied) * 100, 2) if implied else None

    entry_odd = mo if (reference_mode or ignore_odds) else (m_odd or mo)
    from .probabilities import MatchProbabilities
    mp = MatchProbabilities(
        home=pred.prob_home, draw=pred.prob_draw, away=pred.prob_away,
        lambda_home=1.4, lambda_away=1.1, sample_home=10, sample_away=10,
    )
    ht = estimate_ht_trade(mp, entry_odd, market)
    p_ht = pred.p_ht_profitable if pred.model_loaded else ht.p_profitable

    if market in ("home_win_ft", "draw_ft", "away_win_ft"):
        stake = kelly_ht_trade(
            p_ht, entry_odd, ht.expected_exit_odd, bankroll,
            confidence=pred.confidence, edge_pp=None if ignore_odds else edge,
        )
        lucro = ht.expected_profit_pct
    else:
        stake = kelly_simple(p, entry_odd, bankroll, confidence=pred.confidence)
        lucro = round((p * entry_odd - 1) * 100, 2)

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
        if stake.stake_amount <= 0:
            reasons.append("Kelly = 0")
            action = "SKIP"
        if p_ht < 0.48 and market in ("home_win_ft", "draw_ft", "away_win_ft"):
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
        phi_seguranca=phi,
        odd_minima_entrada=round(mo, 3),
        odd_mercado=m_odd,
        edge_pp=edge,
        implied_market=round(implied, 4) if implied else None,
        lucro_estimado_pct=lucro,
        kelly_cheio=stake.kelly_full,
        kelly_quarto=stake.kelly_quarter,
        pct_banca=stake.stake_pct,
        stake_valor=stake.stake_amount,
        confianca=pred.confidence,
        model_loaded=pred.model_loaded,
        schedule_notes=pred.schedule_notes,
        reasons=reasons,
    )


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
) -> TradeRecommendation:
    """Linha de referência: odd justa, φ, odd mínima e stake — sem filtro de odd atual."""
    cfg = load_config()
    bankroll = bankroll or cfg["trading"]["bankroll"]

    mp = estimate_match_probabilities(df, home, away, league_slug)
    p = probability_for_market(market, mp, ml_probs)
    phi = dynamic_phi(p, "outcome")
    fo = fair_odd(p)
    mo = min_entry_odd(p, phi)
    m_odd = (row_odds or {}).get(market)
    implied = (1 / m_odd) if m_odd and m_odd > 1.01 else None
    edge = round((p - implied) * 100, 2) if implied else None

    ht = estimate_ht_trade(mp, mo, market)
    if market in ("home_win_ft", "draw_ft", "away_win_ft"):
        p_ht = ht.p_profitable
        stake = kelly_ht_trade(p_ht, mo, ht.expected_exit_odd, bankroll, confidence=confidence)
        lucro = ht.expected_profit_pct
    else:
        stake = kelly_simple(p, mo, bankroll, confidence=confidence)
        lucro = round((p * mo - 1) * 100, 2)
        p_ht = p

    mdef = market_by_id(market)
    prob_h, prob_d, prob_a = mp.home, mp.draw, mp.away
    if ml_probs:
        prob_h, prob_d, prob_a = ml_probs["home"], ml_probs["draw"], ml_probs["away"]

    return TradeRecommendation(
        home=home, away=away, market=market, action="INFO",
        probabilidade_estimada=round(p, 4),
        prob_home=prob_h, prob_draw=prob_d, prob_away=prob_a,
        p_lucro_ht=round(p_ht, 4),
        odd_justa=round(fo, 3),
        phi_seguranca=phi,
        odd_minima_entrada=round(mo, 3),
        odd_mercado=m_odd,
        edge_pp=edge,
        implied_market=round(implied, 4) if implied else None,
        lucro_estimado_pct=lucro,
        kelly_cheio=stake.kelly_full,
        kelly_quarto=stake.kelly_quarter,
        pct_banca=stake.stake_pct,
        stake_valor=stake.stake_amount,
        confianca=confidence,
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
    """Referencia pre-jogo → saida HT: 1X2 FT (Mandante/Empate/Visitante)."""
    row_odds = list_market_odds(row) if hasattr(row, "get") else {}
    league_slug = row.get("League_Slug") if hasattr(row, "get") else None
    odds = MarketOdds(
        home=row_odds.get("home_win_ft"),
        draw=row_odds.get("draw_ft"),
        away=row_odds.get("away_win_ft"),
        source="fpt_jogos_dia",
    )

    recs = []
    for m in prematch_ht_markets_for_row(row):
        recs.append(build_recommendation(
            df, home, away, market=m.id, market_odds=odds,
            match_date=match_date, league_slug=league_slug,
            bankroll=bankroll, reference_mode=True,
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
