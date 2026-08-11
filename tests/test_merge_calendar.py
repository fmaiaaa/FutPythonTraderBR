from __future__ import annotations

from datetime import date

import pandas as pd
import pytest


def test_merge_calendar_states_includes_fpt_odds(monkeypatch, tmp_path):
    monkeypatch.setenv("FPT_PERSIST_LOCAL", "1")
    monkeypatch.setenv("FPT_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr("fpt.client.DATA", tmp_path)
    monkeypatch.setattr("fpt.live.monitor.DATA", tmp_path)

    today = date.today().isoformat()
    daily = tmp_path / "daily"
    daily.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(
        {
            "Date": [today],
            "Time": ["16:00"],
            "Home": ["Palmeiras"],
            "Away": ["Internacional"],
            "League": ["BRA"],
            "Odd_1_FT": [2.10],
            "Odd_X_FT": [3.20],
            "Odd_2_FT": [3.50],
            "_fetch_date": [today],
        }
    )
    df.to_csv(daily / f"jogos_{today}.csv", index=False)

    monkeypatch.setattr("fpt.live.monitor.load_merged", lambda prefer="auto": pd.DataFrame())

    from fpt.calendar import normalize_jogos
    from fpt.live.monitor import LiveMonitor, merge_calendar_states

    cal = normalize_jogos(df)
    monkeypatch.setattr(LiveMonitor, "_load_calendar_daily", lambda self: cal)

    merged = merge_calendar_states([])
    assert len(merged) == 1
    pal = next(s for s in merged if s.home == "Palmeiras")
    assert pal.odds["Casa"]["back"] == 2.10
    assert pal.prob_home is not None


def test_normalize_jogos_merges_mixed_odd_columns():
    """Dois CSVs: um só Odd_H_FT, outro Odd_1_FT parcial — não perder odds."""
    from fpt.calendar import normalize_jogos

    d9 = pd.DataFrame(
        {
            "Date": ["2026-08-09"],
            "Home": ["A"],
            "Away": ["B"],
            "League": ["TEST"],
            "Odd_H_FT": [2.0],
            "Odd_D_FT": [3.0],
            "Odd_A_FT": [4.0],
        }
    )
    d10 = pd.DataFrame(
        {
            "Date": ["2026-08-10"],
            "Home": ["C"],
            "Away": ["D"],
            "League": ["TEST"],
            "Odd_1_FT": [1.9],
            "Odd_X_FT": [3.1],
            "Odd_2_FT": [4.1],
        }
    )
    out = normalize_jogos(pd.concat([d9, d10], ignore_index=True))
    assert out["Odd_1_FT"].notna().sum() == 2
    assert float(out.iloc[0]["Odd_1_FT"]) == 2.0
    assert float(out.iloc[1]["Odd_1_FT"]) == 1.9
