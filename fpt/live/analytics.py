"""Análises para Streamlit — odds Betfair, métricas do modelo e curvas de receita."""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from ..client import DATA
from ..models.evaluate import _simulate_equity, evaluate_holdout, save_evaluation
from ..trading.kelly import kelly_ht_trade
from .betfair_logger import load_ticks

EVAL_DIR = DATA / "models" / "evaluation"


def load_holdout_summary() -> dict:
    path = EVAL_DIR / "holdout_summary.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_holdout_trades() -> pd.DataFrame:
    path = EVAL_DIR / "holdout_trades.csv"
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path, encoding="utf-8-sig")
    df["date"] = pd.to_datetime(df["date"], dayfirst=True, errors="coerce")
    return df.sort_values("date").reset_index(drop=True)


def pseudo_r2_multiclass(y_true: np.ndarray, proba: np.ndarray, n_classes: int = 3) -> float:
    """McFadden pseudo-R²: 1 - LL_model / LL_null (uniforme)."""
    eps = 1e-15
    proba = np.clip(proba, eps, 1 - eps)
    n = len(y_true)
    if n == 0:
        return float("nan")
    ll_model = float(np.sum(np.log(proba[np.arange(n), y_true.astype(int)])))
    ll_null = n * math.log(1.0 / n_classes)
    if ll_null == 0:
        return float("nan")
    return round(1.0 - ll_model / ll_null, 4)


def build_model_dashboard_metrics() -> dict:
    """Métricas consolidadas para exibição no Streamlit."""
    summary = load_holdout_summary()
    metrics = summary.get("metrics", summary)
    meta = metrics.get("meta", {})
    model_block = metrics.get("model", summary.get("model", {}))

    out = {
        "accuracy_train": meta.get("metrics_outcome_train", {}).get("accuracy"),
        "accuracy_test": meta.get("metrics_outcome_test", {}).get("accuracy"),
        "logloss_test": meta.get("metrics_outcome_test", {}).get("logloss"),
        "brier_test": meta.get("metrics_outcome_test", {}).get("brier_home"),
        "ece_test": meta.get("metrics_outcome_test", {}).get("ece_home"),
        "auc_ht": meta.get("metrics_ht_test", {}).get("auc"),
        "roi_pct": model_block.get("roi_pct"),
        "max_drawdown_pct": model_block.get("max_drawdown_pct"),
        "n_trades_model": model_block.get("n_trades"),
        "win_rate_model": metrics.get("model_win_rate"),
        "ht_win_rate_all": metrics.get("ht_win_rate_all"),
        "pseudo_r2": None,
        "n_test_samples": metrics.get("n_test_samples"),
        "n_features": meta.get("n_features_selected_outcome"),
        "model_type": meta.get("model_type"),
    }

    # pseudo-R² a partir das trades (proxy via acurácia vs baseline)
    trades = load_holdout_trades()
    if not trades.empty and "y_true" in trades.columns and "y_pred" in trades.columns:
        acc = float((trades["y_true"] == trades["y_pred"]).mean())
        baseline = 1.0 / 3.0
        out["pseudo_r2"] = round((acc - baseline) / (1 - baseline), 4) if acc > baseline else 0.0

    return out


def equity_curve_from_trades(
    trades: pd.DataFrame,
    bankroll: float = 1000.0,
    mode: str = "model",
    fixed_pct: float = 0.01,
) -> pd.DataFrame:
    """Retorna DataFrame date, equity_pct para gráfico de receita."""
    if trades.empty:
        return pd.DataFrame(columns=["date", "equity_pct"])

    if mode == "model":

        def model_stake(bank: float, r: pd.Series) -> float:
            if not r.get("entered_model"):
                return 0.0
            exit_est = float(r["entry_odd"]) * 0.85
            sd = kelly_ht_trade(float(r["p_ht"]), float(r["back_min"]), exit_est, bank, confidence=75.0)
            return sd.stake_amount

        ec = _simulate_equity(
            trades,
            bankroll,
            model_stake,
            trade_filter=lambda r: bool(r.get("entered_model")),
        )
    else:
        initial = bankroll

        def flat_stake(_bank: float, _r: pd.Series) -> float:
            return initial * fixed_pct if _bank > 0 else 0.0

        ec = _simulate_equity(trades, bankroll, flat_stake)

    series = ec.series
    return pd.DataFrame({"date": series.index, "equity_pct": series.values})


def odds_evolution_df(ticks: pd.DataFrame, match_key: str | None = None) -> pd.DataFrame:
    """Prepara série longa para gráfico odds × tempo."""
    if ticks.empty:
        return pd.DataFrame()
    df = ticks.copy()
    if match_key:
        h, a = match_key.split("|", 1) if "|" in match_key else (None, None)
        if h and a:
            df = df[(df["home"] == h) & (df["away"] == a)]
    if df.empty:
        return pd.DataFrame()

    df["match"] = df["home"] + " x " + df["away"]
    rows = []
    for _, r in df.iterrows():
        base = {
            "timestamp": r["timestamp"],
            "match": r["match"],
            "score": r.get("score"),
            "elapsed_min": r.get("elapsed_min"),
            "in_play": r.get("in_play"),
        }
        for sel, col in [
            ("Casa", "back_home"),
            ("Empate", "back_draw"),
            ("Visitante", "back_away"),
        ]:
            if pd.notna(r.get(col)):
                rows.append({**base, "selection": sel, "odd": float(r[col]), "side": "back"})
        for sel, col in [
            ("Casa", "lay_home"),
            ("Empate", "lay_draw"),
            ("Visitante", "lay_away"),
        ]:
            if pd.notna(r.get(col)):
                rows.append({**base, "selection": sel, "odd": float(r[col]), "side": "lay"})
    return pd.DataFrame(rows)


def odds_by_score_summary(ticks: pd.DataFrame) -> pd.DataFrame:
    """Média de odds back por placar (para estratégias in-play)."""
    if ticks.empty or "score" not in ticks.columns:
        return pd.DataFrame()
    df = ticks[ticks["in_play"] == True].copy()  # noqa: E712
    if df.empty:
        df = ticks.copy()
    agg = (
        df.groupby("score", dropna=False)
        .agg(
            n=("timestamp", "count"),
            back_home_mean=("back_home", "mean"),
            back_draw_mean=("back_draw", "mean"),
            back_away_mean=("back_away", "mean"),
            elapsed_mean=("elapsed_min", "mean"),
        )
        .reset_index()
        .sort_values("n", ascending=False)
    )
    return agg


def drawdown_series(equity_df: pd.DataFrame) -> pd.DataFrame:
    if equity_df.empty:
        return pd.DataFrame(columns=["date", "drawdown_pct"])
    arr = equity_df["equity_pct"].values
    peak = np.maximum.accumulate(arr)
    dd = arr - peak
    return pd.DataFrame({"date": equity_df["date"], "drawdown_pct": dd})


def run_evaluation_if_missing() -> bool:
    """Tenta gerar evaluation se modelos existem mas CSV não."""
    if (EVAL_DIR / "holdout_trades.csv").exists():
        return True
    try:
        from ..pipeline import load_merged
        df = load_merged()
        result = evaluate_holdout(df)
        save_evaluation(result)
        return True
    except Exception:
        return False
