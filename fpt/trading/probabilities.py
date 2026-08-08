from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from .config import load_config


@dataclass
class MatchProbabilities:
    home: float
    draw: float
    away: float
    lambda_home: float
    lambda_away: float
    sample_home: int
    sample_away: int

    def as_dict(self) -> dict[str, float]:
        return {"home": self.home, "draw": self.draw, "away": self.away}

    def selection_prob(self, market: str) -> float:
        return {"home_win_ft": self.home, "draw_ft": self.draw, "away_win_ft": self.away}.get(market, 0.0)


def _poisson_pmf(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam**k) / math.factorial(k)


def poisson_1x2(lambda_home: float, lambda_away: float, max_goals: int = 8) -> tuple[float, float, float]:
    p_home = p_draw = p_away = 0.0
    for h in range(max_goals + 1):
        ph = _poisson_pmf(h, lambda_home)
        for a in range(max_goals + 1):
            pa = _poisson_pmf(a, lambda_away)
            p = ph * pa
            if h > a:
                p_home += p
            elif h == a:
                p_draw += p
            else:
                p_away += p
    total = p_home + p_draw + p_away
    if total <= 0:
        return 1 / 3, 1 / 3, 1 / 3
    return p_home / total, p_draw / total, p_away / total


def _team_goal_rates(df: pd.DataFrame, team: str, last_n: int) -> tuple[float, float, int]:
    mask = (df["Home"] == team) | (df["Away"] == team)
    sub = df.loc[mask].copy()
    if "Date" in sub.columns:
        sub = sub.sort_values("Date", ascending=False)
    sub = sub.head(last_n)
    scored, conceded, n = 0.0, 0.0, 0
    for _, row in sub.iterrows():
        hs, aws = row.get("Home_Score"), row.get("Away_Score")
        if pd.isna(hs) or pd.isna(aws):
            continue
        hs, aws = float(hs), float(aws)
        if row["Home"] == team:
            scored += hs
            conceded += aws
        else:
            scored += aws
            conceded += hs
        n += 1
    if n == 0:
        return 1.0, 1.0, 0
    return scored / n, conceded / n, n


def league_averages(df: pd.DataFrame, league_slug: str | None = None) -> tuple[float, float]:
    sub = df[df["League_Slug"] == league_slug] if league_slug and "League_Slug" in df.columns else df
    sub = sub.dropna(subset=["Home_Score", "Away_Score"])
    if sub.empty:
        return 1.3, 1.1
    home_goals = sub["Home_Score"].astype(float).mean()
    away_goals = sub["Away_Score"].astype(float).mean()
    return float(home_goals), float(away_goals)


def estimate_match_probabilities(
    df: pd.DataFrame,
    home: str,
    away: str,
    league_slug: str | None = None,
) -> MatchProbabilities:
    cfg = load_config()["model"]
    last_n = cfg["form_games"]
    ha = cfg["home_advantage"]

    lg_home, lg_away = league_averages(df, league_slug)
    h_scored, h_conceded, h_n = _team_goal_rates(df, home, last_n)
    a_scored, a_conceded, a_n = _team_goal_rates(df, away, last_n)

    h_attack = h_scored / max(lg_home, 0.5)
    h_defense = h_conceded / max(lg_away, 0.5)
    a_attack = a_scored / max(lg_away, 0.5)
    a_defense = a_conceded / max(lg_home, 0.5)

    lambda_home = max(0.15, lg_home * h_attack * a_defense * ha)
    lambda_away = max(0.15, lg_away * a_attack * h_defense)

    p_h, p_d, p_a = poisson_1x2(lambda_home, lambda_away)
    return MatchProbabilities(
        home=round(p_h, 4),
        draw=round(p_d, 4),
        away=round(p_a, 4),
        lambda_home=round(lambda_home, 3),
        lambda_away=round(lambda_away, 3),
        sample_home=h_n,
        sample_away=a_n,
    )


def ht_state_probabilities(probs: MatchProbabilities) -> dict[str, float]:
    """Probabilidades de estado no HT (Modelo 1 aplicado ao 1º tempo)."""
    cfg = load_config()["model"]
    share = cfg["ht_goal_share"]
    lh, la = probs.lambda_home * share, probs.lambda_away * share
    p_h, p_d, p_a = poisson_1x2(lh, la)
    return {"home_leading": p_h, "draw": p_d, "home_losing": p_a}
