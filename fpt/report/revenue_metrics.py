from __future__ import annotations

"""Métricas de receita — drawdown, sequência de perdas, ROI."""

import numpy as np
import pandas as pd

from ..models.evaluate import EquityCurve


def max_losing_streak(wins: list[bool] | pd.Series) -> int:
    if len(wins) == 0:
        return 0
    best = cur = 0
    for w in wins:
        if not w:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def max_winning_streak(wins: list[bool] | pd.Series) -> int:
    if len(wins) == 0:
        return 0
    best = cur = 0
    for w in wins:
        if w:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def compute_revenue_stats(
    equity: EquityCurve,
    trades: pd.DataFrame,
    *,
    win_col: str = "win",
    pnl_col: str | None = "pnl_pct",
) -> dict:
    wins = trades[win_col].tolist() if not trades.empty and win_col in trades.columns else []
    n = len(wins) or equity.n_trades
    win_rate = float(sum(wins) / len(wins) * 100) if wins else 0.0

    pnl_vals = []
    if pnl_col and not trades.empty and pnl_col in trades.columns:
        pnl_vals = trades[pnl_col].dropna().astype(float).tolist()

    arr = equity.series.values.astype(float) if len(equity.series) else np.array([0.0])
    peak = np.maximum.accumulate(arr) if len(arr) else np.array([0.0])
    dd = arr - peak

    return {
        "roi_pct": equity.final_pct,
        "final_pct": equity.final_pct,
        "max_drawdown_pct": equity.max_drawdown_pct,
        "max_losing_streak": max_losing_streak(wins),
        "max_winning_streak": max_winning_streak(wins),
        "n_trades": n,
        "win_rate_pct": round(win_rate, 2),
        "bankruptcies": len(equity.bankruptcies),
        "bankruptcy_dates": equity.bankruptcies,
        "avg_pnl_pct": round(float(np.mean(pnl_vals)) * 100, 3) if pnl_vals else 0.0,
        "total_pnl_pct": round(float(np.sum(pnl_vals)) * 100, 3) if pnl_vals else 0.0,
        "cycle_volatility_pp": round(float(np.std(equity.series.values - np.polyval(
            np.polyfit(np.arange(len(arr)), arr, 1), np.arange(len(arr))
        ))), 3) if len(arr) > 2 else 0.0,
    }
