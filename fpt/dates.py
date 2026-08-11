"""Parsing de datas FPT — ISO (YYYY-MM-DD) e dd/mm/yyyy."""
from __future__ import annotations

from datetime import date

import pandas as pd


def parse_fpt_date(value) -> pd.Timestamp:
    """Parse uma data FPT sem inverter mês/dia em strings ISO."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return pd.NaT
    if isinstance(value, pd.Timestamp):
        return value
    if isinstance(value, date) and not isinstance(value, pd.Timestamp):
        return pd.Timestamp(value)
    s = str(value).strip()
    if not s or s.lower() == "nan":
        return pd.NaT
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return pd.to_datetime(s[:10], format="%Y-%m-%d", errors="coerce")
    return pd.to_datetime(s, dayfirst=True, errors="coerce")


def parse_fpt_date_series(series: pd.Series) -> pd.Series:
    if series.empty:
        return series
    if pd.api.types.is_datetime64_any_dtype(series):
        return pd.to_datetime(series, errors="coerce")
    return series.map(parse_fpt_date)


def apply_fetch_date(df: pd.DataFrame, date_col: str = "Date") -> pd.Series:
    """Corrige a parte calendário usando _fetch_date (dia real do download FPT)."""
    dates = parse_fpt_date_series(df[date_col])
    if "_fetch_date" not in df.columns:
        return dates
    fetch = pd.to_datetime(df["_fetch_date"], errors="coerce")
    mask = fetch.notna() & dates.notna()
    if not mask.any():
        return dates
    time_part = dates - dates.dt.normalize()
    corrected = fetch.dt.normalize() + time_part
    return dates.where(~mask, corrected)


def match_date_iso(row: pd.Series, *, fallback: date | None = None) -> str:
    fetch_d = row.get("_fetch_date")
    if fetch_d is not None and not (isinstance(fetch_d, float) and pd.isna(fetch_d)):
        fd = pd.to_datetime(fetch_d, errors="coerce")
        if not pd.isna(fd):
            return fd.date().isoformat()
    dt = parse_fpt_date(row.get("Date"))
    if not pd.isna(dt):
        return dt.date().isoformat()
    return (fallback or date.today()).isoformat()
