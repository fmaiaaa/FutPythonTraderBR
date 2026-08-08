#!/usr/bin/env python3
"""Exporta ticks Betfair do dia para Excel (análise de estratégias)."""
from __future__ import annotations

import argparse
from datetime import date

from fpt.live.betfair_logger import export_daily_workbook, list_available_dates, load_ticks


def main():
    p = argparse.ArgumentParser(description="Exporta planilha Betfair (ticks + resumo)")
    p.add_argument("--date", type=str, default="", help="YYYY-MM-DD (default: hoje)")
    p.add_argument("--list", action="store_true", help="Lista dias com ticks")
    args = p.parse_args()

    if args.list:
        for d in list_available_dates():
            n = len(load_ticks(start=d, end=d))
            print(f"{d.isoformat()} — {n} ticks")
        return

    d = date.fromisoformat(args.date) if args.date else date.today()
    path = export_daily_workbook(d)
    if path:
        print(f"Planilha gerada: {path}")
    else:
        print(f"Sem ticks em {d.isoformat()}")


if __name__ == "__main__":
    main()
