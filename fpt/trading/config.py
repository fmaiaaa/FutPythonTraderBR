from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "trading.yaml"

_DEFAULT = {
    "trading": {
        "phi": 1.08,
        "kelly_fraction": 0.25,
        "max_risk_per_trade": 0.01,
        "commission": 0.05,
        "min_confidence": 40,
        "bankroll": 1000.0,
    },
    "ht_exit": {
        "home_leading": 0.62,
        "draw": 0.90,
        "home_losing": 1.38,
        "away_leading": 0.62,
        "away_losing": 1.38,
    },
    "model": {
        "form_games": 10,
        "min_games_team": 8,
        "ht_goal_share": 0.43,
        "home_advantage": 1.12,
    },
    "context": {
        "form_weight": 0.15,
        "motivation_weight": 0.10,
        "rest_weight": 0.05,
        "max_adjustment": 0.12,
    },
}


def load_config() -> dict:
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open(encoding="utf-8") as f:
            return yaml.safe_load(f) or _DEFAULT
    return _DEFAULT
