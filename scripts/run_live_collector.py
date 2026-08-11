"""Coleta live minuto a minuto — uso local ou GitHub Actions."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fpt.live.collector import LiveDataCollector


def main() -> int:
    p = argparse.ArgumentParser(description="Coleta odds + SofaScore minuto a minuto")
    p.add_argument("--minutes", type=int, default=300, help="Duração da sessão (default 5h)")
    p.add_argument("--interval", type=int, default=60, help="Segundos entre ticks")
    p.add_argument("--forever", action="store_true", help="Loop 24/7 (Ctrl+C para parar)")
    args = p.parse_args()

    col = LiveDataCollector()
    if args.forever:
        col.run_forever(interval_seconds=args.interval)
        return 0

    summary = col.run(
        duration_minutes=args.minutes,
        interval_seconds=args.interval,
    )
    print(summary)
    return 0 if summary.get("rows", 0) >= 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
