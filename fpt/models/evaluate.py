"""Avaliação holdout 30% — métricas, backtest ML e curvas de receita."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from ..client import DATA
from ..features.builder import FeatureBuilder
from ..trading.config import load_config as load_trading_config
from ..trading.fair_odds import min_back_odd
from ..trading.ht_trading import ht_state_label, parse_ht_score
from ..trading.kelly import kelly_ht_trade
from .calibration import dynamic_phi
from .config import load_model_config

MODEL_DIR = DATA / "models"
HT_MULT = {"home_leading": 0.62, "draw": 0.90, "home_losing": 1.38}


@dataclass
class EquityCurve:
    """Série temporal: % retorno sobre banca inicial (0 = start, -100 = falência)."""
    series: pd.Series
    bankruptcies: list = field(default_factory=list)
    final_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    n_trades: int = 0


@dataclass
class ModelEvaluationResult:
    metrics: dict
    trades: pd.DataFrame
    equity_curves: dict[str, EquityCurve] = field(default_factory=dict)
    summary: dict = field(default_factory=dict)


def _load_models():
    return (
        joblib.load(MODEL_DIR / "model_outcome.joblib"),
        joblib.load(MODEL_DIR / "model_ht_trade.joblib"),
        joblib.load(MODEL_DIR / "feature_names.joblib"),
    )


def _ht_return_pct(row: pd.Series, comm: float) -> float:
    """Retorno percentual da operação (independente do stake)."""
    entry = float(row["Odd_1_FT"] if "Odd_1_FT" in row.index else row.get("entry_odd"))
    hg, ag = parse_ht_score(row.get("Min_Goals_Home"), row.get("Min_Goals_Away"))
    state = ht_state_label(hg, ag, "home_win_ft")
    exit_odd = entry * HT_MULT.get(state, 1.0)
    return (entry / exit_odd - 1) * (1 - 2 * comm)


def _parse_date(val) -> pd.Timestamp:
    return pd.to_datetime(val, dayfirst=True, errors="coerce")


def _simulate_equity(
    trades: pd.DataFrame,
    initial_bankroll: float,
    stake_resolver,
    trade_filter=None,
) -> EquityCurve:
    """
    Simula banca com compounding (% stake sobre banca ATUAL).
    Y = (banca / inicial - 1) * 100. Falência em -100%.
    """
    if trades.empty:
        t0 = pd.Timestamp.now()
        return EquityCurve(series=pd.Series([0.0], index=[t0]))

    bank = float(initial_bankroll)
    dates: list[pd.Timestamp] = []
    pcts: list[float] = []
    bankruptcies: list[pd.Timestamp] = []
    n_trades = 0

    first_dt = _parse_date(trades.iloc[0]["date"])
    if pd.isna(first_dt):
        first_dt = pd.Timestamp.now()
    dates.append(first_dt - pd.Timedelta(days=1))
    pcts.append(0.0)

    for _, r in trades.iterrows():
        if bank <= 0:
            break
        if trade_filter is not None and not trade_filter(r):
            continue

        ret_pct = float(r.get("ht_return_pct", 0))
        stake = stake_resolver(bank, r)
        stake = min(max(stake, 0), bank)
        if stake <= 0:
            continue

        n_trades += 1
        pnl = stake * ret_pct
        bank += pnl
        dt = _parse_date(r["date"])
        if pd.isna(dt):
            dt = dates[-1] + pd.Timedelta(days=1)

        if bank <= 0:
            bank = 0
            pcts.append(-100.0)
            dates.append(dt)
            bankruptcies.append(dt)
            break

        pcts.append((bank / initial_bankroll - 1) * 100)
        dates.append(dt)

    series = pd.Series(pcts, index=pd.DatetimeIndex(dates))
    arr = series.values
    peak = np.maximum.accumulate(arr)
    dd = float((arr - peak).min()) if len(arr) else 0.0

    return EquityCurve(
        series=series,
        bankruptcies=[str(d.date()) for d in bankruptcies],
        final_pct=round(float(arr[-1]), 2) if len(arr) else 0.0,
        max_drawdown_pct=round(dd, 2),
        n_trades=n_trades,
    )


def evaluate_holdout(
    df: pd.DataFrame,
    bankroll: float | None = None,
    min_history: int | None = None,
) -> ModelEvaluationResult:
    cfg = load_model_config()
    tcfg = load_trading_config()["trading"]
    bankroll = bankroll or cfg["evaluation"]["bankroll"]
    min_history = min_history or cfg["evaluation"]["min_history"]
    train_frac = cfg["split"]["train_fraction"]
    comm = tcfg["commission"]
    fixed_stakes = cfg["evaluation"]["fixed_stakes_pct"]

    try:
        cal_out, cal_ht, feature_names = _load_models()
    except FileNotFoundError as ex:
        raise FileNotFoundError("Modelos nao encontrados — rode: python main.py treinar") from ex

    meta_path = MODEL_DIR / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}

    fb = FeatureBuilder(df)
    X, y_out, y_ht, row_idx = fb.build_training_matrix(min_history=min_history, return_indices=True)
    X = X.reindex(columns=feature_names, fill_value=0)

    split = int(len(X) * train_frac)
    X_test = X.iloc[split:]
    y_test = y_out.iloc[split:]
    idx_test = row_idx.iloc[split:]

    proba_out = cal_out.predict_proba(X_test)
    proba_ht = cal_ht.predict_proba(X_test)
    ht_classes = list(cal_ht.classes_)
    if proba_ht.shape[1] == 1:
        p_ht_all = proba_ht[:, 0] if ht_classes[0] == 1 else 1.0 - proba_ht[:, 0]
    else:
        idx_pos = ht_classes.index(1) if 1 in ht_classes else 1
        p_ht_all = proba_ht[:, idx_pos]

    records = []
    for j in range(len(X_test)):
        df_i = idx_test.iloc[j]
        row = df.loc[df_i]
        entry = row.get("Odd_1_FT")
        if entry is None or pd.isna(entry) or float(entry) <= 1.05:
            continue
        if pd.isna(row.get("Min_Goals_Home")) and pd.isna(row.get("Min_Goals_Away")):
            continue

        entry_odd = float(entry)
        p_home = float(proba_out[j, 0])
        p_draw = float(proba_out[j, 1])
        p_away = float(proba_out[j, 2])
        from .predict import apply_probability_shrinkage
        p_home, p_draw, p_away = apply_probability_shrinkage(
            p_home, p_draw, p_away,
            {"Odd_1_FT": entry_odd, "Odd_X_FT": row.get("Odd_X_FT"), "Odd_2_FT": row.get("Odd_2_FT")},
        )
        p_ht = float(p_ht_all[j])
        phi = dynamic_phi(p_home, "outcome")
        back_min = min_back_odd(p_home, phi)
        exit_est = entry_odd * 0.85
        stake_d = kelly_ht_trade(p_ht, back_min, exit_est, bankroll, confidence=75.0)
        ht_ret = _ht_return_pct(row, comm)
        win = ht_ret > 0

        records.append({
            "date": row.get("Date"),
            "home": row.get("Home"),
            "away": row.get("Away"),
            "league": row.get("League") or row.get("League_Slug"),
            "Odd_1_FT": entry_odd,
            "entry_odd": entry_odd,
            "ht_return_pct": round(ht_ret, 5),
            "p_home": round(p_home, 4),
            "p_ht": round(p_ht, 4),
            "phi": round(phi, 3),
            "back_min": round(back_min, 3),
            "y_true": int(y_test.iloc[j]),
            "y_pred": int(np.argmax(proba_out[j])),
            "ht_true": int(y_ht.iloc[split + j]) if pd.notna(y_ht.iloc[split + j]) else np.nan,
            "stake_pct_model": stake_d.stake_pct,
            "entered_model": stake_d.stake_pct > 0 and entry_odd >= back_min,
            "win": win,
        })

    trades = pd.DataFrame(records)
    if not trades.empty:
        trades = trades.sort_values("date").reset_index(drop=True)

    equity = _build_equity_curves(trades, bankroll, fixed_stakes)
    summary = _summarize_equity(equity, trades)
    metrics = {
        "meta": meta,
        "n_test_samples": len(X_test),
        "n_trades_all": len(trades),
        "n_trades_model": equity.get("model", EquityCurve(pd.Series([0]))).n_trades,
        **summary,
    }
    return ModelEvaluationResult(metrics=metrics, trades=trades, equity_curves=equity, summary=summary)


def _build_equity_curves(
    trades: pd.DataFrame,
    bankroll: float,
    fixed_stakes: list[float],
) -> dict[str, EquityCurve]:
    curves: dict[str, EquityCurve] = {}
    if trades.empty:
        t0 = pd.Timestamp.now()
        empty = EquityCurve(series=pd.Series([0.0], index=[t0]))
        curves["model"] = empty
        for fs in fixed_stakes:
            curves[f"fixed_{fs:.1%}"] = empty
        return curves

    def model_stake(bank: float, r: pd.Series) -> float:
        if not r.get("entered_model"):
            return 0.0
        exit_est = float(r["entry_odd"]) * 0.85
        sd = kelly_ht_trade(float(r["p_ht"]), float(r["back_min"]), exit_est, bank, confidence=75.0)
        return sd.stake_amount

    curves["model"] = _simulate_equity(
        trades, bankroll, model_stake,
        trade_filter=lambda r: bool(r.get("entered_model")),
    )

    for fs in fixed_stakes:
        pct = fs
        initial = bankroll

        def flat_stake(_bank: float, _r: pd.Series, p=pct, init=initial) -> float:
            return init * p if _bank > 0 else 0.0

        curves[f"fixed_{fs:.1%}"] = _simulate_equity(trades, bankroll, flat_stake)

    return curves


def _summarize_equity(equity: dict[str, EquityCurve], trades: pd.DataFrame) -> dict:
    out = {}
    for name, ec in equity.items():
        out[name] = {
            "final_pct": ec.final_pct,
            "roi_pct": ec.final_pct,
            "max_drawdown_pct": ec.max_drawdown_pct,
            "n_trades": ec.n_trades,
            "bankruptcies": len(ec.bankruptcies),
            "bankruptcy_dates": ec.bankruptcies,
        }
    if not trades.empty:
        entered = trades[trades["entered_model"]] if "entered_model" in trades.columns else trades.iloc[:0]
        out["model_win_rate"] = round(float(entered["win"].mean()), 4) if len(entered) else 0.0
        out["test_accuracy"] = round(float((trades["y_true"] == trades["y_pred"]).mean()), 4)
        out["ht_win_rate_all"] = round(float(trades["win"].mean()), 4)
    return out


def save_evaluation(result: ModelEvaluationResult, out_dir: Path | None = None) -> Path:
    out_dir = out_dir or DATA / "models" / "evaluation"
    out_dir.mkdir(parents=True, exist_ok=True)
    result.trades.to_csv(out_dir / "holdout_trades.csv", index=False, encoding="utf-8-sig")
    serial = {
        "metrics": result.metrics,
        "summary": result.summary,
    }
    (out_dir / "holdout_summary.json").write_text(
        json.dumps(serial, indent=2, default=str), encoding="utf-8",
    )
    return out_dir
