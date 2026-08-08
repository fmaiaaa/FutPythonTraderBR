"""Probabilidades Poisson para todos os mercados jogos-do-dia."""
from __future__ import annotations

import math
import re

from ..markets import JOGOS_DIA_MARKETS, market_by_id
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
    m = re.search(r"(over|under)(\d+)(?:_(\d))?", market_id)
    if not m:
        return None
    whole, frac = int(m.group(2)), int(m.group(3) or 0)
    return whole + frac / 10


def prob_over_line(lh: float, la: float, line: float) -> float:
    grid = _score_probs(lh, la)
    p = 0.0
    for (h, a), pr in grid.items():
        if h + a > line:
            p += pr
        elif abs(h + a - line) < 1e-9 and line == int(line):
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
    """Probabilidade estimada por mercado (ML para 1X2 FT; Poisson para demais)."""
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


def all_market_probabilities(
    mp: MatchProbabilities,
    ml_probs: dict[str, float] | None = None,
) -> dict[str, float]:
    return {
        m.id: round(probability_for_market(m.id, mp, ml_probs), 4)
        for m in JOGOS_DIA_MARKETS
    }
