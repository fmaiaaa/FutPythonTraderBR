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
    "sofascore": {
        "enabled": False,
        "fetch_in_play_only": True,
        "log_snapshots": True,
        "timeout": 15,
        "retries": 3,
        "min_interval_seconds": 0.4,
    },
    "scalping": {
        "enabled": True,
        "stake_pct": 0.005,
        "take_profit_pct": 0.015,
        "stop_loss_pct": 0.02,
        "timeout_seconds": 60,
        "target_horizon_seconds": 30,
        "commission": 0.05,
        "auto_open_on_signal": False,
        "auto_execute_scalp": False,
    },
    "collection": {
        "run_with_app": True,
        "interval_seconds": 60,
        "default_duration_minutes": 300,
        "record_all_watchlist": True,
        "record_all_fpt": True,
        "fetch_lineups_once": True,
        "fetch_shotmap": True,
        "fetch_incidents": True,
    },
    "leagues": {
        "filter_mode": "ranked_fpt",
        "require_fpt_base": True,
        "ranking": {
            "tier1_kelly_multiplier": 0.25,
            "tier3_kelly_multiplier": 0.05,
        },
    },
    "coverage": {
        "pre_live_require_fpt": True,
        "pre_live_require_betfair": True,
        "in_live_require_betfair": True,
        "in_live_require_sofascore": True,
    },
    "models": {
        "in_live_pressure_ml": False,
    },
    "execution": {
        "enabled": False,
        "paper_mode": True,
        "auto_execute": False,
        "max_stake_pct": 0.02,
        "min_stake_brl": 2.0,
        "require_exchange": True,
    },
    "paper": {
        "initial_bankroll": 100.0,
        "max_stake_pct": 0.02,
        "commission": 0.05,
    },
    "autonomous": {
        "refresh_seconds": 30,
        "full_scan_interval_seconds": 900,
        "collect_data": True,
        "use_betfair_balance": True,
        "balance_reserve_pct": 0.05,
        "auto_exit": True,
        "exit_rules": {
            "exit_at_ht": True,
            "lay_exit_on_team_goal": True,
            "back_draw_exit_on_goal": True,
            "exit_on_any_goal": False,
            "max_goals_before_exit": None,
        },
    },
    "pro_tempo": {
        "classic_prematch_only": True,
    },
    "pro_tempo_strategies": {},
    "scalping_strategies": {},
    "pressure_odds": {
        "enabled": True,
        "require_pressure": True,
        "blend_weight": 0.35,
        "xg_weight": 0.15,
        "dominance_scale": 2.0,
        "min_edge_pp": 0.5,
    },
    "exchange_execution": {
        "enabled": True,
        "use_mid_for_edge": True,
        "require_spread_ok": True,
        "scalp_min_margin_pp": 0.3,
    },
    "dashboard": {
        "refresh_seconds": 15,
    },
    "weekly_calendar": {
        "fetch_on_weekday": 5,
        "daily_refresh_hour": 23,
        "daily_refresh_enabled": True,
        "pre_kickoff_minutes": 5,
        "match_duration_minutes": 105,
        "injury_extra_minutes": 15,
    },
}


def load_live_config() -> dict:
    cfg: dict = {}
    for key, default in _DEFAULTS.items():
        if key == "autonomous":
            cfg[key] = {
                **dict(default),
                "exit_rules": dict(default["exit_rules"]),
            }
        elif isinstance(default, dict):
            cfg[key] = dict(default)
        else:
            cfg[key] = default
    cfg["strategies"] = {}

    if LIVE_CONFIG.exists():
        raw = yaml.safe_load(LIVE_CONFIG.read_text(encoding="utf-8")) or {}
        for key, val in raw.items():
            if not isinstance(val, dict):
                continue
            if key not in cfg:
                cfg[key] = {}
            if key == "autonomous" and "exit_rules" in val:
                cfg["autonomous"].update({k: v for k, v in val.items() if k != "exit_rules"})
                cfg["autonomous"].setdefault("exit_rules", {})
                cfg["autonomous"]["exit_rules"].update(val["exit_rules"])
            else:
                cfg[key].update(val)

    # Streamlit Cloud: execução paper ativa por padrão
    if os.environ.get("FPT_STREAMLIT_CLOUD") == "1":
        cfg["execution"]["enabled"] = True
        cfg["execution"]["paper_mode"] = os.environ.get("EXECUTION_PAPER_MODE", "true").lower() in (
            "1", "true", "yes",
        )

    from .runtime_profile import apply_runtime_profile

    return apply_runtime_profile(cfg)
