"""Probabilidades Poisson para todos os mercados jogos-do-dia."""
from __future__ import annotations

import math
import re

from ..markets import JOGOS_DIA_MARKETS, TRADING_MARKETS, market_by_id
from .config import load_config
from .probabilities import MatchProbabilities, _poisson_pmf, ht_state_probabilities


def _score_probs(lh: float, la: float, max_goals: int = 8) -> dict[tuple[int, int], float]:
    grid: dict[tuple[int, int], float] = {}
    for h in range(max_goals + 1):
        ph = _poisson_pmf(h, lh)
        for a in range(max_goals + 1):
            grid[(h, a)] = ph * _poisson_pmf(a, la)
    total = sum(grid.values())
    if total <= 0:
        return grid
    return {k: v / total for k, v in grid.items()}


def _ou_line(market_id: str) -> float | None:
    """over05 -> 0.5, over15 -> 1.5, over25 -> 2.5, etc."""
    m = re.search(r"(?:over|under)(\d{2})", market_id)
    if not m:
        return None
    return int(m.group(1)) / 10.0


def prob_over_line(lh: float, la: float, line: float) -> float:
    grid = _score_probs(lh, la)
    p = 0.0
    for (h, a), pr in grid.items():
        total = h + a
        if total > line:
            p += pr
        elif abs(total - line) < 1e-9 and line == int(line):
            p += pr * 0.5
    return max(0.001, min(0.999, p))


def prob_btts(lh: float, la: float) -> float:
    p0h = math.exp(-lh)
    p0a = math.exp(-la)
    p_btts = 1 - p0h - p0a + p0h * p0a
    return max(0.001, min(0.999, p_btts))


def probability_for_market(
    market_id: str,
    mp: MatchProbabilities,
    ml_probs: dict[str, float] | None = None,
) -> float:
    mdef = market_by_id(market_id)
    if not mdef:
        return 0.5

    cfg = load_config()["model"]
    share = cfg["ht_goal_share"]
    lh_ft, la_ft = mp.lambda_home, mp.lambda_away
    lh_ht, la_ht = lh_ft * share, la_ft * share

    group, sel = mdef.group, mdef.selection

    if group == "1x2_ft" and ml_probs:
        key = {"home": "home", "draw": "draw", "away": "away"}[sel]
        return ml_probs.get(key, mp.selection_prob(market_id))

    if group == "1x2_ft":
        return mp.selection_prob(market_id)

    if group == "1x2_ht":
        ht = ht_state_probabilities(mp)
        if sel == "home":
            return ht["home_leading"]
        if sel == "draw":
            return ht["draw"]
        return ht["home_losing"]

    if group.startswith("ou_"):
        line = _ou_line(market_id)
        if line is None:
            return 0.5
        lh, la = (lh_ht, la_ht) if "_ht" in group else (lh_ft, la_ft)
        p_over = prob_over_line(lh, la, line)
        return p_over if sel == "over" else 1 - p_over

    if group == "btts":
        p_yes = prob_btts(lh_ft, la_ft)
        return p_yes if sel == "yes" else 1 - p_yes

    if group == "dc":
        p_h, p_d, p_a = mp.home, mp.draw, mp.away
        if ml_probs:
            p_h, p_d, p_a = ml_probs["home"], ml_probs["draw"], ml_probs["away"]
        if market_id == "dc_1x":
            return p_h + p_d
        if market_id == "dc_12":
            return p_h + p_a
        return p_d + p_a

    return 0.5


def p_ht_profit_proxy(market_id: str, mp: MatchProbabilities, p_sel: float) -> float:
    """
    P(lucro ao fechar no intervalo) — proxy por tipo de mercado.
    1X2 FT: usa estimate_ht_trade externamente; aqui fallback Poisson HT.
    """
    mdef = market_by_id(market_id)
    if not mdef:
        return p_sel

    cfg = load_config()["model"]
    share = cfg["ht_goal_share"]
    lh_ht = mp.lambda_home * share
    la_ht = mp.lambda_away * share
    group = mdef.group

    if market_id in TRADING_MARKETS:
        ht = ht_state_probabilities(mp)
        if market_id == "home_win_ft":
            return ht["home_leading"] + ht["draw"] * 0.55
        if market_id == "away_win_ft":
            return ht["home_losing"] + ht["draw"] * 0.55
        return ht["draw"] + (ht["home_leading"] + ht["home_losing"]) * 0.2

    if group.endswith("_ht"):
        return p_sel

    if group.startswith("ou_") and "_ft" in group:
        line = _ou_line(market_id)
        if line is None:
            return p_sel * 0.7
        ht_line = max(0.5, line * share * 2)
        p_over_ht = prob_over_line(lh_ht, la_ht, ht_line)
        if mdef.selection == "over":
            return p_over_ht
        return 1 - p_over_ht

    if group == "btts":
        p_btts_ht = prob_btts(lh_ht, la_ht)
        return p_btts_ht if mdef.selection == "yes" else 1 - p_btts_ht

    return p_sel * 0.65
