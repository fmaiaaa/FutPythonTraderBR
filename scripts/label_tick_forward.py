"""Rotula ticks com retorno forward de odds (+10/+30/+60s) para backtest scalping."""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from fpt.live.betfair_logger import load_ticks
from fpt.live.tick_labels import label_ticks


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--csv", type=Path, help="CSV de ticks (default: todos via load_ticks)")
    p.add_argument("-o", "--output", type=Path, required=True)
    args = p.parse_args()

    if args.csv:
        df = pd.read_csv(args.csv, encoding="utf-8-sig")
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    else:
        df = load_ticks()

    labeled = label_ticks(df)
    labeled.to_csv(args.output, index=False, encoding="utf-8-sig")
    print(f"Salvo {len(labeled)} linhas em {args.output}")


if __name__ == "__main__":
    main()
