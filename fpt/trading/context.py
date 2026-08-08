from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .config import load_config
from .probabilities import MatchProbabilities


@dataclass
class ContextInput:
    """Informações contextuais opcionais — preencher manualmente ou via API futura."""
    home_missing_key_players: int = 0
    away_missing_key_players: int = 0
    home_days_rest: int | None = None
    away_days_rest: int | None = None
    home_must_win: bool = False       # luta por título/classificação
    away_must_win: bool = False
    home_relegation_fight: bool = False
    away_relegation_fight: bool = False
    home_table_position: int | None = None
    away_table_position: int | None = None
    league_size: int = 20
    notes: str = ""


@dataclass
class AdjustedProbabilities:
    home: float
    draw: float
    away: float
    adjustments: dict[str, float] = field(default_factory=dict)
    raw: MatchProbabilities | None = None


def _form_delta(df: pd.DataFrame, home: str, away: str, last_n: int = 5) -> float:
    """Diferença de forma recente (-1 a +1) favorecendo mandante."""
    from ..operation import team_form

    hf = team_form(df, home, last_n)
    af = team_form(df, away, last_n)
    if not hf or not af:
        return 0.0
    h_pts = hf.get("wins", 0) * 3 + hf.get("draws", 0)
    a_pts = af.get("wins", 0) * 3 + af.get("draws", 0)
    h_g = max(hf.get("games", 1), 1)
    a_g = max(af.get("games", 1), 1)
    return max(-1.0, min(1.0, (h_pts / h_g - a_pts / a_g) / 3))


def _motivation_delta(ctx: ContextInput) -> float:
    score = 0.0
    if ctx.home_must_win:
        score += 0.3
    if ctx.away_must_win:
        score -= 0.3
    if ctx.home_relegation_fight:
        score += 0.25
    if ctx.away_relegation_fight:
        score -= 0.25
    if ctx.home_table_position and ctx.away_table_position:
        # time mais mal colocado tende a lutar mais em casa no fim do campeonato
        diff = (ctx.away_table_position - ctx.home_table_position) / max(ctx.league_size, 1)
        score += max(-0.3, min(0.3, diff * 0.5))
    return max(-1.0, min(1.0, score))


def _lineup_delta(ctx: ContextInput) -> float:
    return max(-0.5, min(0.5, (ctx.away_missing_key_players - ctx.home_missing_key_players) * 0.08))


def _rest_delta(ctx: ContextInput) -> float:
    if ctx.home_days_rest is None or ctx.away_days_rest is None:
        return 0.0
    diff = ctx.home_days_rest - ctx.away_days_rest
    return max(-0.3, min(0.3, diff / 14))


def apply_context(
    probs: MatchProbabilities,
    df: pd.DataFrame,
    home: str,
    away: str,
    ctx: ContextInput | None = None,
) -> AdjustedProbabilities:
    """Atualiza probabilidades via log-odds (não soma % arbitrária)."""
    cfg = load_config()["context"]
    ctx = ctx or ContextInput()
    max_adj = cfg["max_adjustment"]

    form_d = _form_delta(df, home, away) * cfg["form_weight"]
    motiv_d = _motivation_delta(ctx) * cfg["motivation_weight"]
    rest_d = _rest_delta(ctx) * cfg["rest_weight"]
    lineup_d = _lineup_delta(ctx) * 0.08

    total_shift = max(-max_adj, min(max_adj, form_d + motiv_d + rest_d + lineup_d))

    # shift log-odds do mandante vs visitante; empate absorve metade inversa
    import math

    def logit(p: float) -> float:
        p = max(0.01, min(0.99, p))
        return math.log(p / (1 - p))

    def inv_logit(x: float) -> float:
        return 1 / (1 + math.exp(-x))

    h = inv_logit(logit(probs.home) + total_shift * 3)
    a = inv_logit(logit(probs.away) - total_shift * 3)
    d = max(0.05, 1 - h - a)
    s = h + d + a
    return AdjustedProbabilities(
        home=round(h / s, 4),
        draw=round(d / s, 4),
        away=round(a / s, 4),
        adjustments={
            "form": round(form_d, 4),
            "motivation": round(motiv_d, 4),
            "rest": round(rest_d, 4),
            "lineup": round(lineup_d, 4),
            "total_shift": round(total_shift, 4),
        },
        raw=probs,
    )
