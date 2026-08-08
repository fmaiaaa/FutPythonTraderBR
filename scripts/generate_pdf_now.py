#!/usr/bin/env python3
"""Gera PDF watchlist a partir do calendario em cache (sem re-download)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd

from fpt.calendar import enrich_with_schedule, weekend_window
from fpt.client import DATA
from fpt.leagues import filter_watchlist
from fpt.pipeline import load_merged
from fpt.report.pdf_weekend import generate_weekend_pdfs_by_league
from fpt.weekend import format_weekend_report, scan_weekend, weekend_report_dir
from fpt.integrations.google_drive import upload_file


def main():
    start, end = weekend_window()
    cal_path = DATA / "calendar" / f"cal_{start}_{end}.parquet"
    if not cal_path.exists():
        cal_path = DATA / "calendar" / f"cal_{start}_{end}.csv"
        cal = pd.read_csv(cal_path)
    else:
        cal = pd.read_parquet(cal_path)

    hist = load_merged()
    cal = filter_watchlist(cal)
    cal = enrich_with_schedule(cal, hist)
    print(f"Jogos watchlist: {len(cal)}")

    entries = scan_weekend(cal, hist)
    meta = {"start": str(start), "end": str(end), "n_games_watchlist": len(cal)}
    print(f"Linhas pre-jogo: {len(entries)}")

    out_dir = weekend_report_dir(start)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_txt = out_dir / f"weekend_{start}_{end}.txt"
    report = format_weekend_report(entries, meta)
    out_txt.write_text(report, encoding="utf-8")
    pdf_paths = generate_weekend_pdfs_by_league(entries, meta, out_dir)
    print(f"PDFs gerados: {len(pdf_paths)}")
    for p in pdf_paths:
        print(f"  {p}")
        upload_file(p, history_date=str(start))


if __name__ == "__main__":
    main()
