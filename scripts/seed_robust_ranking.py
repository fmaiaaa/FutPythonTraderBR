"""Gera ranking.json com tier 1 para as 14 ligas da watchlist."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fpt.league_ranking import RANKING_FILE, save_league_rankings, _default_rankings


def main() -> int:
    ranks = _default_rankings()
    out = {k: v for k, v in ranks.items() if not k.startswith("_")}
    save_league_rankings(out)
    print(f"Ranking robusto salvo: {RANKING_FILE}")
    print(f"Ligas tier 1: {len(out) // 2}")  # slug + label keys
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
