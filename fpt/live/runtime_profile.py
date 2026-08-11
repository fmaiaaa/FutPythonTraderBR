"""Perfis de operação — escolha no .bat (watchlist vs todas as ligas)."""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ..client import DATA

BR = ZoneInfo("America/Sao_Paulo")
PROFILE_FILE = DATA / "live" / "runtime_profile.json"

PROFILES: dict[str, dict] = {
    "robust": {
        "label": "Robusto — 14 ligas tier 1 com base FPT validada (recomendado)",
        "leagues": {
            "filter_mode": "robust",
            "require_fpt_base": True,
            "operate_min_tier": 1,
            "watchlist_only": True,
        },
        "coverage": {
            "pre_live_require_fpt": True,
            "pre_live_require_betfair": True,
            "in_live_require_betfair": True,
            "in_live_require_sofascore": True,
        },
        "execution": {"require_exchange": True},
        "betfair": {"prefer_over_fpt": True},
        "pro_tempo": {"classic_prematch_only": True},
        "exchange_execution": {"enabled": True, "require_spread_ok": True},
    },
    "watchlist": {
        "label": "Watchlist (14 ligas principais)",
        "leagues": {
            "filter_mode": "ranked_fpt",
            "require_fpt_base": True,
        },
        "coverage": {
            "pre_live_require_fpt": True,
            "pre_live_require_betfair": True,
            "in_live_require_betfair": True,
            "in_live_require_sofascore": True,
        },
        "execution": {"require_exchange": True},
        "betfair": {"prefer_over_fpt": True},
        "pro_tempo": {"classic_prematch_only": True},
        "exchange_execution": {"enabled": True, "require_spread_ok": True},
    },
    "all_leagues": {
        "label": "Todas as ligas FPT (pré-live FPT+Betfair | scalping SS+Betfair)",
        "leagues": {
            "filter_mode": "all_fpt",
            "require_fpt_base": False,
        },
        "coverage": {
            "pre_live_require_fpt": True,
            "pre_live_require_betfair": True,
            "in_live_require_betfair": True,
            "in_live_require_sofascore": True,
        },
        "execution": {"require_exchange": True},
        "betfair": {"prefer_over_fpt": True, "min_liquidity": 500.0},
        "pro_tempo": {"classic_prematch_only": True},
        "exchange_execution": {"enabled": True, "require_spread_ok": True},
        "sofascore": {"fetch_all_scheduled": True},
        "collection": {"record_all_fpt": True},
    },
}


def active_profile_name() -> str:
    env = os.environ.get("FPT_PROFILE", "").strip().lower()
    if env in PROFILES:
        return env
    if PROFILE_FILE.exists():
        try:
            raw = json.loads(PROFILE_FILE.read_text(encoding="utf-8"))
            name = str(raw.get("profile", "")).lower()
            if name in PROFILES:
                return name
        except json.JSONDecodeError:
            pass
    return "robust"


def save_profile(name: str) -> Path:
    name = name.lower()
    if name not in PROFILES:
        raise ValueError(f"Perfil desconhecido: {name}")
    PROFILE_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "profile": name,
        "label": PROFILES[name]["label"],
        "updated": datetime.now(BR).isoformat(timespec="seconds"),
    }
    PROFILE_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return PROFILE_FILE


def apply_runtime_profile(cfg: dict) -> dict:
    name = active_profile_name()
    prof = PROFILES.get(name, PROFILES["robust"])
    for section, values in prof.items():
        if section == "label":
            continue
        if not isinstance(values, dict):
            continue
        cfg.setdefault(section, {})
        if isinstance(cfg[section], dict):
            cfg[section].update(values)
    cfg["_runtime_profile"] = name
    cfg["_runtime_profile_label"] = prof.get("label", name)
    return cfg


def profile_summary(name: str | None = None) -> str:
    name = name or active_profile_name()
    prof = PROFILES.get(name, PROFILES["robust"])
    return prof.get("label", name)
