from __future__ import annotations

"""Construção de curvas de receita — pré-live, scalping e combinado."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from ..client import DATA
from ..live.betfair_logger import load_ticks
from ..live.scalping_backtest import run_scalping_backtest
from ..live.tick_labels import label_ticks
from ..models.evaluate import (
    EquityCurve,
    ModelEvaluationResult,
    _build_equity_curves,
    _simulate_equity,
    evaluate_holdout,
    save_evaluation,
)
from ..trading.config import load_config
from ..trading.kelly import kelly_ht_trade
from .revenue_metrics import compute_revenue_stats


@dataclass
class RevenueReport:
    method: str
    title: str
    equity: EquityCurve
    trades: pd.DataFrame
    stats: dict
    note: str = ""


def _parse_ts(val) -> pd.Timestamp:
    ts = pd.to_datetime(val, dayfirst=True, errors="coerce")
    return ts if pd.notna(ts) else pd.Timestamp.now()


def _load_cached_holdout(bankroll: float) -> ModelEvaluationResult | None:
    """Reutiliza holdout salvo para evitar re-predizer todo o merged no CI."""
    eval_dir = DATA / "models" / "evaluation"
    trades_path = eval_dir / "holdout_trades.csv"
    summary_path = eval_dir / "holdout_summary.json"
    if not trades_path.exists():
        return None
    try:
        import json

        trades = pd.read_csv(trades_path, encoding="utf-8-sig")
        summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
        from ..models.config import load_model_config

        fixed = load_model_config()["evaluation"]["fixed_stakes_pct"]
        equity = _build_equity_curves(trades, bankroll, fixed)
        return ModelEvaluationResult(
            metrics=summary.get("metrics", summary),
            trades=trades,
            equity_curves=equity,
            summary=summary.get("summary", summary),
        )
    except Exception:
        return None


def build_pre_live_report(
    hist: pd.DataFrame,
    bankroll: float | None = None,
    *,
    use_cache: bool = True,
) -> RevenueReport:
    cfg = load_config()["trading"]
    bankroll = bankroll or cfg["bankroll"]
    result = _load_cached_holdout(bankroll) if use_cache else None
    if result is None:
        result = evaluate_holdout(hist, bankroll=bankroll)
        save_evaluation(result)
    trades = result.trades.copy()
    if not trades.empty and "entered_model" in trades.columns:
        entered = trades[trades["entered_model"]].copy()
    else:
        entered = trades
    if not entered.empty:
        entered["win"] = entered["ht_return_pct"] > 0
        entered["pnl_pct"] = entered["ht_return_pct"]
        entered["method"] = "pre_live"

    equity = result.equity_curves.get("model", EquityCurve(series=pd.Series([0.0], index=[pd.Timestamp.now()])))
    stats = compute_revenue_stats(equity, entered, pnl_col="pnl_pct")
    stats["method"] = "pre_live"
    stats["label"] = "Entradas pré-live (holdout 30%, ¼ Kelly HT)"
    return RevenueReport(
        method="pre_live",
        title="Evolução da Receita — Pré-Live",
        equity=equity,
        trades=entered,
        stats=stats,
    )


def build_scalping_report(bankroll: float | None = None, ticks: pd.DataFrame | None = None) -> RevenueReport:
    cfg = load_config()["trading"]
    bankroll = bankroll or cfg["bankroll"]
    from ..live.config import load_live_config

    scalp_cfg = load_live_config().get("scalping", {})
    stake_pct = float(scalp_cfg.get("stake_pct", 0.005))

    if ticks is None:
        ticks = load_ticks()
    note = ""
    if ticks.empty:
        note = "Sem ticks Betfair acumulados — métricas indisponíveis até coleta live."
        empty = EquityCurve(series=pd.Series([0.0], index=[pd.Timestamp.now()]))
        return RevenueReport(
            method="scalping",
            title="Evolução da Receita — Scalping PRESSURE_STEAM",
            equity=empty,
            trades=pd.DataFrame(),
            stats={"roi_pct": 0, "max_drawdown_pct": 0, "n_trades": 0, "win_rate_pct": 0,
                   "max_losing_streak": 0, "method": "scalping", "label": "Scalping in-play"},
            note=note,
        )

    labeled = label_ticks(ticks)
    bt = run_scalping_backtest(labeled)

    records = []
    for t in bt.trade_log:
        ts = _parse_ts(t["timestamp"])
        pnl = float(t["pnl_pct"]) / 100.0
        records.append({
            "date": ts,
            "timestamp": ts,
            "home": t["home"],
            "away": t["away"],
            "side": t["side"],
            "entry_odd": t["entry_odd"],
            "exit_odd": t["exit_odd"],
            "reason": t["reason"],
            "pnl_pct": pnl,
            "win": pnl > 0,
            "method": "scalping",
        })
    trades = pd.DataFrame(records)
    if not trades.empty:
        trades = trades.sort_values("timestamp").reset_index(drop=True)
        trades["date"] = trades["timestamp"]
        trades["ht_return_pct"] = trades["pnl_pct"]

    def scalp_stake(bank: float, _r: pd.Series) -> float:
        return bank * stake_pct if bank > 0 else 0.0

    equity = _simulate_equity(trades, bankroll, scalp_stake) if not trades.empty else EquityCurve(
        series=pd.Series([0.0], index=[pd.Timestamp.now()])
    )

    stats = compute_revenue_stats(equity, trades, pnl_col="pnl_pct")
    stats["method"] = "scalping"
    stats["label"] = "Scalping PRESSURE_STEAM (ticks Betfair + SofaScore)"
    stats["timeouts"] = bt.timeouts
    return RevenueReport(
        method="scalping",
        title="Evolução da Receita — Scalping",
        equity=equity,
        trades=trades,
        stats=stats,
        note=note,
    )


def build_combined_report(
    pre: RevenueReport,
    scalp: RevenueReport,
    bankroll: float | None = None,
) -> RevenueReport:
    cfg = load_config()["trading"]
    bankroll = bankroll or cfg["bankroll"]
    from ..live.config import load_live_config

    scalp_cfg = load_live_config().get("scalping", {})
    scalp_stake_pct = float(scalp_cfg.get("stake_pct", 0.005))

    frames = []
    if not pre.trades.empty:
        t = pre.trades.copy()
        t["timestamp"] = t["date"].apply(_parse_ts)
        t["method"] = "pre_live"
        frames.append(t)
    if not scalp.trades.empty:
        frames.append(scalp.trades.copy())

    if not frames:
        empty = EquityCurve(series=pd.Series([0.0], index=[pd.Timestamp.now()]))
        return RevenueReport(
            method="combined",
            title="Evolução da Receita — Pré-Live + Scalping",
            equity=empty,
            trades=pd.DataFrame(),
            stats={"roi_pct": 0, "max_drawdown_pct": 0, "n_trades": 0, "win_rate_pct": 0,
                   "max_losing_streak": 0, "method": "combined"},
            note="Sem trades para combinar.",
        )

    combined = pd.concat(frames, ignore_index=True).sort_values("timestamp").reset_index(drop=True)
    combined["date"] = combined["timestamp"]

    def combined_stake(bank: float, r: pd.Series) -> float:
        if bank <= 0:
            return 0.0
        if r.get("method") == "scalping":
            return bank * scalp_stake_pct
        if not r.get("entered_model", True):
            return 0.0
        exit_est = float(r.get("entry_odd", 2.0)) * 0.85
        sd = kelly_ht_trade(float(r.get("p_ht", 0.5)), float(r.get("back_min", 1.5)), exit_est, bank, confidence=75.0)
        return sd.stake_amount

    ret_col = combined.apply(
        lambda r: float(r.get("pnl_pct", r.get("ht_return_pct", 0))),
        axis=1,
    )
    combined["ht_return_pct"] = ret_col
    combined["win"] = combined["ht_return_pct"] > 0

    equity = _simulate_equity(combined, bankroll, combined_stake)
    stats = compute_revenue_stats(equity, combined, pnl_col="ht_return_pct")
    stats["method"] = "combined"
    stats["label"] = "Pré-live + Scalping (mesma banca, ordem cronológica)"
    stats["n_pre_live"] = int((combined["method"] == "pre_live").sum())
    stats["n_scalping"] = int((combined["method"] == "scalping").sum())

    return RevenueReport(
        method="combined",
        title="Evolução da Receita — Pré-Live + Scalping",
        equity=equity,
        trades=combined,
        stats=stats,
    )


def build_all_revenue_reports(
    hist: pd.DataFrame,
    bankroll: float | None = None,
    *,
    use_cache: bool = True,
) -> dict[str, RevenueReport]:
    pre = build_pre_live_report(hist, bankroll, use_cache=use_cache)
    scalp = build_scalping_report(bankroll)
    combined = build_combined_report(pre, scalp, bankroll)
    return {"pre_live": pre, "scalping": scalp, "combined": combined}
