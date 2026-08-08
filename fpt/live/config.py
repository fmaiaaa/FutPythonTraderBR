from __future__ import annotations

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
LIVE_CONFIG = ROOT / "config" / "live.yaml"

_DEFAULTS = {
    "live": {
        "refresh_seconds": 45,
        "lookahead_days": 1,
        "bankroll": 1000.0,
        "min_edge_pp": 1.0,
        "min_confidence": 40,
        "watch_near_value_pct": 2.0,
        "alert_cooldown_seconds": 300,
        "log_alerts": True,
        "markets": ["home_win_ft", "draw_ft", "away_win_ft"],
    },
    "strategies": {},
    "betfair": {"prefer_over_fpt": True, "min_liquidity": 1000.0},
    "execution": {
        "enabled": False,
        "paper_mode": True,
        "auto_execute": False,
        "min_stake_brl": 2.0,
    },
}


def load_live_config() -> dict:
    cfg = {
        "live": dict(_DEFAULTS["live"]),
        "strategies": {},
        "betfair": dict(_DEFAULTS["betfair"]),
        "execution": dict(_DEFAULTS["execution"]),
    }
    if LIVE_CONFIG.exists():
        raw = yaml.safe_load(LIVE_CONFIG.read_text(encoding="utf-8")) or {}
        for key in ("live", "strategies", "betfair", "execution"):
            if key in raw and isinstance(raw[key], dict):
                cfg[key].update(raw[key])

    # Streamlit Cloud: execução paper ativa por padrão
    if os.environ.get("FPT_STREAMLIT_CLOUD") == "1":
        cfg["execution"]["enabled"] = True
        cfg["execution"]["paper_mode"] = os.environ.get("EXECUTION_PAPER_MODE", "true").lower() in (
            "1", "true", "yes",
        )
    return cfg
