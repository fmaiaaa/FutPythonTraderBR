from __future__ import annotations

"""Backtest rule-based de scalping PRESSURE_STEAM sobre ticks rotulados."""

from dataclasses import dataclass, field

import pandas as pd

from .config import load_live_config


@dataclass
class ScalpingBacktestResult:
    trades: int = 0
    wins: int = 0
    losses: int = 0
    timeouts: int = 0
    total_pnl_pct: float = 0.0
    avg_pnl_pct: float = 0.0
    win_rate: float = 0.0
    max_drawdown_pct: float = 0.0
    by_horizon: dict[int, dict] = field(default_factory=dict)
    trade_log: list[dict] = field(default_factory=list)


def _pressure_cfg() -> dict:
    cfg = load_live_config()
    return cfg.get("strategies", {}).get("pressure_steam", {})


def _scalping_cfg() -> dict:
    return load_live_config().get("scalping", {})


def _dominance_row(row: pd.Series) -> float | None:
    h = row.get("ss_pressure_home")
    a = row.get("ss_pressure_away")
    if pd.isna(h) or pd.isna(a):
        return None
    return float(h) - float(a)


def _signal(row: pd.Series, prev_row: pd.Series | None, cfg: dict) -> str | None:
    if not cfg.get("enabled", True):
        return None
    if not bool(row.get("in_play")):
        return None
    elapsed = row.get("elapsed_min")
    if pd.notna(elapsed) and float(elapsed) > float(cfg.get("max_elapsed_min", 75)):
        return None

    dom = _dominance_row(row)
    prev_dom = _dominance_row(prev_row) if prev_row is not None else None
    if dom is None or prev_dom is None:
        return None

    velocity = dom - prev_dom
    min_delta = float(cfg.get("min_pressure_delta", 8.0))
    min_dom = float(cfg.get("min_dominance", 12.0))
    steam_pct = float(cfg.get("steam_pct", 0.03))

    prev_odd = prev_row.get("back_home") if prev_row is not None else None
    odd = row.get("back_home")
    if pd.isna(prev_odd) or pd.isna(odd) or float(prev_odd) <= 1.01:
        return None
    odd_move = (float(odd) - float(prev_odd)) / float(prev_odd)

    if dom >= min_dom and velocity >= min_delta and odd_move <= -steam_pct:
        return "BACK"
    if dom <= -min_dom and velocity <= -min_delta and odd_move >= steam_pct:
        return "LAY"
    return None


def _pnl_back(entry: float, exit_odd: float, side: str, commission: float = 0.05) -> float:
    if side == "BACK":
        gross = (exit_odd - entry) / entry
    else:
        gross = (entry - exit_odd) / (exit_odd - 1) if exit_odd > 1.01 else 0.0
    return gross * (1 - commission)


def run_scalping_backtest(
    df: pd.DataFrame,
    *,
    commission: float | None = None,
    horizons: tuple[int, ...] = (10, 30, 60),
) -> ScalpingBacktestResult:
    if df.empty:
        return ScalpingBacktestResult()

    cfg_ps = _pressure_cfg()
    cfg_sc = _scalping_cfg()
    commission = commission if commission is not None else float(cfg_sc.get("commission", 0.05))
    tp = float(cfg_sc.get("take_profit_pct", 0.015))
    sl = float(cfg_sc.get("stop_loss_pct", 0.02))
    timeout = int(cfg_sc.get("timeout_seconds", 60))

    work = df.copy()
    work["timestamp"] = pd.to_datetime(work["timestamp"], errors="coerce")
    work = work.sort_values(["home", "away", "timestamp"]).reset_index(drop=True)

    result = ScalpingBacktestResult()
    equity = 0.0
    peak = 0.0
    max_dd = 0.0

    for (_, _), grp in work.groupby(["home", "away"], sort=False):
        grp = grp.reset_index(drop=True)
        for i in range(1, len(grp)):
            row = grp.iloc[i]
            prev = grp.iloc[i - 1]
            side = _signal(row, prev, cfg_ps)
            if not side:
                continue

            entry = float(row["back_home"])
            if entry <= 1.01:
                continue

            exit_odd = None
            exit_reason = "TIMEOUT"
            for j in range(i + 1, len(grp)):
                future = grp.iloc[j]
                dt = (future["timestamp"] - row["timestamp"]).total_seconds()
                if dt > timeout:
                    break
                px = float(future["back_home"])
                if side == "BACK":
                    if px >= entry * (1 + tp):
                        exit_odd, exit_reason = px, "TP"
                        break
                    if px <= entry * (1 - sl):
                        exit_odd, exit_reason = px, "SL"
                        break
                else:
                    if px <= entry * (1 - tp):
                        exit_odd, exit_reason = px, "TP"
                        break
                    if px >= entry * (1 + sl):
                        exit_odd, exit_reason = px, "SL"
                        break
            if exit_odd is None:
                last = grp.iloc[min(i + 1, len(grp) - 1)]
                exit_odd = float(last["back_home"])

            pnl = _pnl_back(entry, float(exit_odd), side, commission)
            result.trades += 1
            result.total_pnl_pct += pnl
            if pnl > 0:
                result.wins += 1
            elif pnl < 0:
                result.losses += 1
            if exit_reason == "TIMEOUT":
                result.timeouts += 1

            equity += pnl
            peak = max(peak, equity)
            max_dd = max(max_dd, peak - equity)

            result.trade_log.append({
                "home": row["home"],
                "away": row["away"],
                "timestamp": row["timestamp"].isoformat(),
                "side": side,
                "entry_odd": entry,
                "exit_odd": float(exit_odd),
                "reason": exit_reason,
                "pnl_pct": round(pnl * 100, 3),
                "dominance": _dominance_row(row),
            })

    result.avg_pnl_pct = (result.total_pnl_pct / result.trades * 100) if result.trades else 0.0
    result.win_rate = (result.wins / result.trades * 100) if result.trades else 0.0
    result.max_drawdown_pct = round(max_dd * 100, 3)

    for h in horizons:
        col = f"delta_back_home_{h}s"
        if col not in work.columns:
            continue
        subset = work[work[col].notna()].copy()
        if subset.empty:
            continue
        sim_pnl = []
        for i in range(1, len(subset)):
            row = subset.iloc[i]
            prev = subset.iloc[i - 1]
            side = _signal(row, prev, cfg_ps)
            if not side:
                continue
            delta = float(row[col])
            pnl = delta / float(row["back_home"]) if side == "BACK" else -delta / float(row["back_home"])
            sim_pnl.append(pnl * (1 - commission))
        result.by_horizon[h] = {
            "signals": len(sim_pnl),
            "avg_pnl_pct": round(sum(sim_pnl) / len(sim_pnl) * 100, 3) if sim_pnl else 0.0,
            "win_rate": round(sum(1 for x in sim_pnl if x > 0) / len(sim_pnl) * 100, 1) if sim_pnl else 0.0,
        }

    return result
