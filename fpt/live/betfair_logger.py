"""Persistência de ticks Betfair — planilha para análise de variação de odds."""
from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from ..client import DATA
from .models import LiveMatchState

BR = ZoneInfo("America/Sao_Paulo")
TICKS_ROOT = DATA / "betfair" / "ticks"

COLUMNS = [
    "timestamp",
    "date",
    "time",
    "home",
    "away",
    "league",
    "league_label",
    "status",
    "in_play",
    "elapsed_min",
    "score_home",
    "score_away",
    "score",
    "back_home",
    "back_draw",
    "back_away",
    "lay_home",
    "lay_draw",
    "lay_away",
    "total_matched",
    "market_id",
    "event_id",
    "odds_source",
    "prob_home",
    "prob_draw",
    "prob_away",
    "best_action",
    "best_market",
    "confidence",
]


def _month_dir(d: date | None = None) -> Path:
    d = d or date.today()
    out = TICKS_ROOT / d.strftime("%Y-%m")
    out.mkdir(parents=True, exist_ok=True)
    return out


def _daily_csv_path(d: date | None = None) -> Path:
    d = d or date.today()
    return _month_dir(d) / f"betfair_ticks_{d.isoformat()}.csv"


def _match_key(home: str, away: str) -> str:
    return f"{home}|{away}"


def state_to_row(state: LiveMatchState, ts: datetime | None = None) -> dict:
    ts = ts or datetime.now(BR)
    odds = state.odds or {}
    return {
        "timestamp": ts.isoformat(timespec="seconds"),
        "date": ts.date().isoformat(),
        "time": ts.strftime("%H:%M:%S"),
        "home": state.home,
        "away": state.away,
        "league": state.league,
        "league_label": state.league_label,
        "status": state.status,
        "in_play": state.in_play,
        "elapsed_min": state.elapsed_min,
        "score_home": state.score_home,
        "score_away": state.score_away,
        "score": state.score_display,
        "back_home": odds.get("Casa", {}).get("back"),
        "back_draw": odds.get("Empate", {}).get("back"),
        "back_away": odds.get("Visitante", {}).get("back"),
        "lay_home": odds.get("Casa", {}).get("lay"),
        "lay_draw": odds.get("Empate", {}).get("lay"),
        "lay_away": odds.get("Visitante", {}).get("lay"),
        "total_matched": state.total_matched,
        "market_id": state.market_id,
        "event_id": state.event_id,
        "odds_source": state.odds_source,
        "prob_home": state.prob_home,
        "prob_draw": state.prob_draw,
        "prob_away": state.prob_away,
        "best_action": state.best_action,
        "best_market": state.best_market,
        "confidence": state.confidence,
    }


def log_states(states: list[LiveMatchState], ts: datetime | None = None) -> Path | None:
    """Append ticks de todos os jogos monitorados ao CSV diário."""
    if not states:
        return None
    ts = ts or datetime.now(BR)
    path = _daily_csv_path(ts.date())
    write_header = not path.exists()
    rows = [state_to_row(s, ts) for s in states]
    with path.open("a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerows(rows)
    return path


def load_ticks(
    start: date | None = None,
    end: date | None = None,
    match: str | None = None,
) -> pd.DataFrame:
    """Carrega ticks de um intervalo de datas (CSV diários)."""
    if not TICKS_ROOT.exists():
        return pd.DataFrame(columns=COLUMNS)

    frames: list[pd.DataFrame] = []
    for month_dir in sorted(TICKS_ROOT.iterdir()):
        if not month_dir.is_dir():
            continue
        for csv_path in sorted(month_dir.glob("betfair_ticks_*.csv")):
            day_str = csv_path.stem.replace("betfair_ticks_", "")
            try:
                day = date.fromisoformat(day_str)
            except ValueError:
                continue
            if start and day < start:
                continue
            if end and day > end:
                continue
            df = pd.read_csv(csv_path, encoding="utf-8-sig")
            frames.append(df)

    if not frames:
        return pd.DataFrame(columns=COLUMNS)

    out = pd.concat(frames, ignore_index=True)
    out["timestamp"] = pd.to_datetime(out["timestamp"], errors="coerce")
    if match:
        parts = match.split("|", 1)
        if len(parts) == 2:
            out = out[(out["home"] == parts[0]) & (out["away"] == parts[1])]
        else:
            m = match.lower()
            out = out[
                out["home"].str.lower().str.contains(m, na=False)
                | out["away"].str.lower().str.contains(m, na=False)
            ]
    return out.sort_values("timestamp").reset_index(drop=True)


def export_daily_workbook(d: date | None = None) -> Path | None:
    """Exporta CSV diário + resumo por jogo para Excel (.xlsx)."""
    d = d or date.today()
    csv_path = _daily_csv_path(d)
    if not csv_path.exists():
        return None

    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    if df.empty:
        return None

    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    if hasattr(df["timestamp"].dt, "tz") and df["timestamp"].dt.tz is not None:
        df["timestamp"] = df["timestamp"].dt.tz_localize(None)
    df["match_key"] = df["home"] + " x " + df["away"]

    summary = (
        df.groupby(["match_key", "league_label"], dropna=False)
        .agg(
            ticks=("timestamp", "count"),
            first_ts=("timestamp", "min"),
            last_ts=("timestamp", "max"),
            back_home_min=("back_home", "min"),
            back_home_max=("back_home", "max"),
            back_home_last=("back_home", "last"),
            score_last=("score", "last"),
            elapsed_max=("elapsed_min", "max"),
        )
        .reset_index()
    )

    xlsx_path = _month_dir(d) / f"betfair_analise_{d.isoformat()}.xlsx"
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="ticks", index=False)
        summary.to_excel(writer, sheet_name="resumo_jogos", index=False)
    return xlsx_path


def list_available_dates() -> list[date]:
    dates: list[date] = []
    if not TICKS_ROOT.exists():
        return dates
    for month_dir in TICKS_ROOT.iterdir():
        if not month_dir.is_dir():
            continue
        for csv_path in month_dir.glob("betfair_ticks_*.csv"):
            day_str = csv_path.stem.replace("betfair_ticks_", "")
            try:
                dates.append(date.fromisoformat(day_str))
            except ValueError:
                pass
    return sorted(set(dates))
