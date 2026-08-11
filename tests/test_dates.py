from __future__ import annotations

import pandas as pd

from fpt.calendar import normalize_jogos
from fpt.dates import apply_fetch_date, parse_fpt_date


def test_iso_date_not_swapped():
    ts = parse_fpt_date("2026-08-09")
    assert ts.date().isoformat() == "2026-08-09"


def test_dayfirst_still_works_for_br_format():
    ts = parse_fpt_date("09/08/2026")
    assert ts.date().isoformat() == "2026-08-09"


def test_normalize_jogos_iso_dates():
    raw = pd.DataFrame(
        {
            "Date": ["2026-08-09", "2026-08-10"],
            "Home": ["A", "B"],
            "Away": ["C", "D"],
            "League": ["TEST", "TEST"],
        }
    )
    raw["_fetch_date"] = ["2026-08-09", "2026-08-10"]
    out = normalize_jogos(raw)
    dates = out["Date"].dt.date.astype(str).tolist()
    assert dates == ["2026-08-09", "2026-08-10"]


def test_apply_fetch_date_fixes_corrupted_iso():
    df = pd.DataFrame(
        {
            "Date": ["2026-08-09", "2026-08-10"],
            "_fetch_date": ["2026-08-09", "2026-08-10"],
        }
    )
    df["Date"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
    fixed = apply_fetch_date(df)
    assert fixed.dt.date.astype(str).tolist() == ["2026-08-09", "2026-08-10"]
