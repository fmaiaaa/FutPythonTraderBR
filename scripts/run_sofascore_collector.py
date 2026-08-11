"""Coleta SofaScore + odds 24/7 — processo CMD separado do dashboard."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fpt.live.collector import LiveDataCollector  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="Coleta minuto a minuto 24/7 (watchlist completa)")
    p.add_argument("--interval", type=int, default=60, help="Segundos entre ticks (default 60)")
    args = p.parse_args()

    print("=" * 50)
    print(" FPT — Coleta SofaScore + odds (24/7)")
    print(" Campeonatos: watchlist (14 ligas)")
    print(" Ctrl+C para parar")
    print("=" * 50)

    LiveDataCollector().run_forever(interval_seconds=args.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
