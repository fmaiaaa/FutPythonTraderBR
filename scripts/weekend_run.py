#!/usr/bin/env python3
"""Rotina semanal — atualiza dados, calendario, odds API, stakes."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fpt.weekend import run_weekend_pipeline


def main():
    retrain = "--no-train" not in sys.argv
    no_odds_api = "--no-odds-api" in sys.argv
    no_update = "--no-update" in sys.argv
    all_countries = "--all-countries" in sys.argv

    run_weekend_pipeline(
        update_data=not no_update,
        retrain=retrain,
        use_odds_api=not no_odds_api,
        brazil_only=not all_countries,
    )


if __name__ == "__main__":
    main()
