from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd

from .config import load_config
from .probabilities import MatchProbabilities, ht_state_probabilities


@dataclass
class HTTradeEstimate:
    """Modelo 2 — trading pré-jogo com saída obrigatória no HT."""
    p_profitable: float
    expected_exit_odd: float
    expected_profit_pct: float
    ht_states: dict[str, float]
    exit_multipliers: dict[str, float]

    def summary(self) -> str:
        return (
            f"P(lucro no HT)={self.p_profitable:.1%} | "
            f"odd saída esp.={self.expected_exit_odd:.2f} | "
            f"retorno esp.={self.expected_profit_pct:.2f}%"
        )


def parse_ht_score(min_home: str | float | None, min_away: str | float | None) -> tuple[int, int]:
    """Infere placar do HT a partir dos minutos dos gols."""

    def goals_before_ht(raw) -> int:
        if raw is None or (isinstance(raw, float) and pd.isna(raw)):
            return 0
        s = str(raw).strip()
        if not s or s.lower() in ("nan", "none", "-"):
            return 0
        nums = [int(x) for x in re.findall(r"\d+", s)]
        return sum(1 for m in nums if m <= 45)

    return goals_before_ht(min_home), goals_before_ht(min_away)


def ht_state_label(hg: int, ag: int, selection: str) -> str:
    if selection == "home_win_ft":
        if hg > ag:
            return "home_leading"
        if hg == ag:
            return "draw"
        return "home_losing"
    if selection == "away_win_ft":
        if ag > hg:
            return "away_leading"
        if hg == ag:
            return "draw"
        return "away_losing"
    # empate FT: simplificado
    if hg == ag:
        return "draw"
    return "home_losing" if hg > ag else "away_leading"


def _multipliers(selection: str) -> dict[str, float]:
    cfg = load_config()["ht_exit"]
    if selection == "away_win_ft":
        return {
            "away_leading": cfg["away_leading"],
            "draw": cfg["draw"],
            "away_losing": cfg["away_losing"],
        }
    return {
        "home_leading": cfg["home_leading"],
        "draw": cfg["draw"],
        "home_losing": cfg["home_losing"],
    }


def estimate_ht_trade(
    probs: MatchProbabilities,
    entry_odd: float,
    selection: str = "home_win_ft",
    commission: float | None = None,
) -> HTTradeEstimate:
    """
    Estima P&L de back pré-jogo + lay no HT.

    Sem odds in-play da Betfair, usa multiplicadores empíricos configuráveis
    por estado do HT (calibrar depois com dados reais).
    """
    cfg = load_config()
    comm = commission if commission is not None else cfg["trading"]["commission"]
    states = ht_state_probabilities(probs)
    mults = _multipliers(selection)

    if selection == "away_win_ft":
        state_probs = {
            "away_leading": states["home_losing"],
            "draw": states["draw"],
            "away_losing": states["home_leading"],
        }
    elif selection == "draw_ft":
        # proxy: empate FT favorecido quando HT empatado
        state_probs = {"draw": 0.55, "home_leading": 0.22, "home_losing": 0.23}
        mults = {"draw": 0.85, "home_leading": 1.05, "home_losing": 1.05}
    else:
        state_probs = states

    exp_exit = 0.0
    exp_profit = 0.0
    p_profitable = 0.0

    for state, p_state in state_probs.items():
        m = mults.get(state, 1.0)
        exit_odd = entry_odd * m
        # back @ entry, lay @ exit → retorno aproximado
        profit_pct = (entry_odd / exit_odd - 1) * (1 - 2 * comm) * 100
        exp_exit += p_state * exit_odd
        exp_profit += p_state * profit_pct
        if profit_pct > 0:
            p_profitable += p_state

    return HTTradeEstimate(
        p_profitable=round(p_profitable, 4),
        expected_exit_odd=round(exp_exit, 3),
        expected_profit_pct=round(exp_profit, 3),
        ht_states={k: round(v, 4) for k, v in state_probs.items()},
        exit_multipliers=mults,
    )


def calibrate_ht_multipliers(df: pd.DataFrame, selection: str = "home_win_ft") -> dict[str, float]:
    """
    Calibra multiplicadores usando histórico FPT (proxy).
    Usa relação Odd_1_FT vs resultado HT quando odds HT disponíveis.
    """
    odd_col = {"home_win_ft": "Odd_1_FT", "draw_ft": "Odd_X_FT", "away_win_ft": "Odd_2_FT"}.get(
        selection, "Odd_1_FT"
    )
    if odd_col not in df.columns:
        return load_config()["ht_exit"]

    buckets: dict[str, list[float]] = {"leading": [], "draw": [], "losing": []}
    sub = df.dropna(subset=[odd_col, "Min_Goals_Home", "Min_Goals_Away"]).copy()

    for _, row in sub.iterrows():
        entry = float(row[odd_col])
        if entry <= 1.01:
            continue
        hg, ag = parse_ht_score(row.get("Min_Goals_Home"), row.get("Min_Goals_Away"))
        if selection == "home_win_ft":
            if hg > ag:
                state = "leading"
            elif hg == ag:
                state = "draw"
            else:
                state = "losing"
        elif selection == "away_win_ft":
            if ag > hg:
                state = "leading"
            elif hg == ag:
                state = "draw"
            else:
                state = "losing"
        else:
            state = "draw" if hg == ag else ("leading" if hg > ag else "losing")

        # proxy: odd HT do mercado 1X2 HT como referência de encurtamento
        ht_odd_col = {"home_win_ft": "Odd_1_HT", "away_win_ft": "Odd_2_HT", "draw_ft": "Odd_X_HT"}.get(
            selection
        )
        if ht_odd_col and ht_odd_col in row and pd.notna(row[ht_odd_col]):
            ht_ref = float(row[ht_odd_col])
            if ht_ref > 1.01:
                buckets[state].append(ht_ref / entry)

    defaults = load_config()["ht_exit"]
    result = {}
    for state, values in buckets.items():
        if values:
            key = f"home_{state}" if selection == "home_win_ft" else f"away_{state}"
            if state == "draw":
                key = "draw"
            result[key] = round(float(pd.Series(values).median()), 3)
        else:
            result[state] = defaults.get(f"home_{state}", defaults.get("draw", 0.9))
    return result
