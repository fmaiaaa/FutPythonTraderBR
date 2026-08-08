"""Calendario unificado — jogos futuros via FPT jogos-do-dia."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd

from .client import DATA
from .downloader import fetch_jogos_do_dia
from .features.schedule import build_team_calendar, schedule_context
from .markets import JOGOS_DIA_MARKETS


def _parse_day(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def saturday_sunday_window(today: date | None = None) -> tuple[date, date]:
    """Sabado + domingo alvo. Rotina sabado 7h: hoje (sab) + amanha (dom)."""
    today = today or date.today()
    if today.weekday() == 5:
        return today, today + timedelta(days=1)
    if today.weekday() == 6:
        return today - timedelta(days=1), today
    days_to_sat = (5 - today.weekday()) % 7
    saturday = today + timedelta(days=days_to_sat)
    return saturday, saturday + timedelta(days=1)


def weekend_window(today: date | None = None) -> tuple[date, date]:
    return saturday_sunday_window(today)


def fetch_range(start: str | date, end: str | date) -> pd.DataFrame:
    s = _parse_day(str(start)) if isinstance(start, str) else start
    e = _parse_day(str(end)) if isinstance(end, str) else end
    frames = []
    d = s
    while d <= e:
        try:
            df = fetch_jogos_do_dia(d.isoformat())
            if not df.empty:
                df["_fetch_date"] = d.isoformat()
                frames.append(df)
        except Exception as ex:
            print(f"  aviso {d}: {ex}")
        d += timedelta(days=1)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    if "Id" in out.columns:
        out = out.drop_duplicates(subset=["Id"], keep="last")
    return out


def normalize_jogos(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    out["Date"] = pd.to_datetime(out["Date"], dayfirst=True, errors="coerce")
    rename = {
        "Odd_H_FT": "Odd_1_FT", "Odd_D_FT": "Odd_X_FT", "Odd_A_FT": "Odd_2_FT",
        "Odd_H_HT": "Odd_1_HT", "Odd_D_HT": "Odd_X_HT", "Odd_A_HT": "Odd_2_HT",
    }
    for old, new in rename.items():
        if old in out.columns and new not in out.columns:
            out[new] = out[old]
    out["is_brazil"] = out["League"].astype(str).str.contains(
        r"brazil|brasil|serie a|serie b|serie c|serie d|copa do brasil",
        case=False, na=False,
    ) & ~out["League"].astype(str).str.contains(r"women|wom\b", case=False, na=False)
    out["weekday"] = out["Date"].dt.day_name()
    return out


def build_calendar(
    start: str | date | None = None,
    end: str | date | None = None,
    brazil_only: bool = False,
    save: bool = True,
) -> pd.DataFrame:
    if start is None or end is None:
        start, end = saturday_sunday_window()
    print(f"Calendario FPT: {start} -> {end}")
    raw = fetch_range(start, end)
    cal = normalize_jogos(raw)
    if brazil_only and not cal.empty:
        cal = cal[cal["is_brazil"]].copy()
    if save and not cal.empty:
        path = DATA / "calendar" / f"cal_{start}_{end}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        cal.to_parquet(path, index=False)
        cal.to_csv(path.with_suffix(".csv"), index=False, encoding="utf-8-sig")
        print(f"Salvo: {path} ({len(cal)} jogos)")
    return cal


def enrich_with_schedule(cal: pd.DataFrame, hist: pd.DataFrame) -> pd.DataFrame:
    if cal.empty:
        return cal
    calendars = build_team_calendar(hist)
    notes_col = []
    for _, row in cal.iterrows():
        dt = pd.to_datetime(row["Date"])
        ctx = schedule_context(calendars, row["Home"], row["Away"], dt, row.get("League"))
        notes_col.append(" | ".join(ctx.notes(row["Home"], row["Away"])))
    out = cal.copy()
    out["schedule_notes"] = notes_col
    return out


def list_market_odds(row: pd.Series) -> dict[str, float]:
    odds = {}
    for m in JOGOS_DIA_MARKETS:
        v = row.get(m.odd_col)
        try:
            if v is not None and float(v) > 1.01:
                odds[m.id] = float(v)
        except (TypeError, ValueError):
            pass
    return odds
