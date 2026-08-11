from __future__ import annotations

"""Monta dataset rotulado para treino do modelo de scalping."""

import json
from datetime import date
from pathlib import Path

import pandas as pd
import yaml

from ..client import DATA
from ..live.collector import COLLECTION_ROOT, list_collection_dates
from ..live.tick_labels import label_ticks

ROOT = Path(__file__).resolve().parents[2]
SCALPING_CFG = ROOT / "config" / "scalping_model.yaml"
WEEKLY_ROOT = COLLECTION_ROOT / "weekly"


def _load_scalping_cfg() -> dict:
    if not SCALPING_CFG.exists():
        return {}
    return yaml.safe_load(SCALPING_CFG.read_text(encoding="utf-8")) or {}


def load_collection_ticks(
    start: date | None = None,
    end: date | None = None,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    if not COLLECTION_ROOT.exists():
        return pd.DataFrame()

    for month_dir in sorted(COLLECTION_ROOT.iterdir()):
        if not month_dir.is_dir() or month_dir.name == "weekly":
            continue
        for day_dir in sorted(month_dir.iterdir()):
            if not day_dir.is_dir():
                continue
            try:
                d = date.fromisoformat(day_dir.name)
            except ValueError:
                continue
            if start and d < start:
                continue
            if end and d > end:
                continue
            for csv_path in day_dir.glob("ticks_minute_*.csv"):
                df = pd.read_csv(csv_path, encoding="utf-8-sig")
                df["_collection_date"] = d.isoformat()
                frames.append(df)

    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    out["timestamp"] = pd.to_datetime(out["timestamp"], errors="coerce")
    return out.sort_values("timestamp").reset_index(drop=True)


def build_scalping_features(df: pd.DataFrame) -> pd.DataFrame:
    """Adiciona deltas de pressão/odd e rotula forward."""
    if df.empty:
        return df
    cfg = _load_scalping_cfg().get("scalping_model", {})
    horizons = (10, int(cfg.get("forward_seconds", 30)), 60)
    work = label_ticks(df, horizons=horizons)

    work = work.sort_values(["home", "away", "timestamp"]).reset_index(drop=True)
    for col in ("pressure_delta_home", "pressure_delta_away", "odd_move_home_pct"):
        if col not in work.columns:
            work[col] = None

    fwd = int(cfg.get("forward_seconds", 30))
    delta_col = f"delta_back_home_{fwd}s"
    if delta_col in work.columns:
        work["target_move"] = work[delta_col]
        work["target_profitable_back"] = (work[delta_col] > 0).astype(int)
        comm = 0.05
        work["target_pnl_back"] = (work[delta_col] / work["back_home"]) * (1 - comm)
        work["target_profitable_30s"] = (work["target_pnl_back"] > 0).astype(int)
    return work


def save_weekly_dataset(df: pd.DataFrame, week_label: str | None = None) -> Path:
    WEEKLY_ROOT.mkdir(parents=True, exist_ok=True)
    week_label = week_label or date.today().strftime("%Y-W%W")
    out_dir = WEEKLY_ROOT / week_label
    out_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = out_dir / "scalping_dataset.parquet"
    csv_path = out_dir / "scalping_dataset.csv"
    df.to_parquet(parquet_path, index=False)
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    meta = {
        "week": week_label,
        "rows": len(df),
        "matches": int(df[["home", "away"]].drop_duplicates().shape[0]) if not df.empty else 0,
        "columns": list(df.columns),
        "collection_dates": sorted(df["_collection_date"].unique().tolist()) if "_collection_date" in df.columns else [],
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return parquet_path


def build_weekly_scalping_dataset(days_back: int = 14) -> pd.DataFrame:
    dates = list_collection_dates()
    if not dates:
        raw = load_collection_ticks()
    else:
        start = dates[-1] - pd.Timedelta(days=days_back)
        raw = load_collection_ticks(start=start.date() if hasattr(start, "date") else dates[0])
    if raw.empty:
        return raw
    labeled = build_scalping_features(raw)
    save_weekly_dataset(labeled)
    return labeled
