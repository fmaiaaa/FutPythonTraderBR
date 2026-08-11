"""Pulse cloud — scan live + heartbeat + upload snapshot para consulta 24h."""
from __future__ import annotations

import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from ..client import DATA
from ..storage import persist_data_locally

BR = ZoneInfo("America/Sao_Paulo")
PULSE_FILE = DATA / "live" / "cloud_pulse.json"
LIVE_SNAPSHOT_DRIVE_NAME = "fpt-live-snapshot-latest.json"


def _now() -> str:
    return datetime.now(BR).isoformat(timespec="seconds")


def write_cloud_pulse(
    *,
    n_games: int,
    n_live: int = 0,
    profile: str = "robust",
    upload: dict | None = None,
    error: str | None = None,
) -> dict:
    payload = {
        "ts": _now(),
        "profile": profile,
        "n_games": n_games,
        "n_live": n_live,
        "upload": upload or {},
        "error": error,
        "source": os.environ.get("GITHUB_ACTIONS") and "github_actions" or "local",
    }
    if persist_data_locally():
        PULSE_FILE.parent.mkdir(parents=True, exist_ok=True)
        PULSE_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def read_cloud_pulse() -> dict:
    if not PULSE_FILE.exists():
        return {}
    try:
        return json.loads(PULSE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def run_cloud_pulse(*, upload_drive: bool = True) -> dict:
    """Um ciclo completo: scan full (perfil robust) + upload Drive."""
    from .monitor import LiveMonitor
    from .runtime_profile import active_profile_name, save_profile

    profile = os.environ.get("FPT_PROFILE", "").strip().lower() or active_profile_name()
    if profile not in ("robust", "watchlist", "all_leagues"):
        profile = "robust"
    os.environ["FPT_PROFILE"] = profile
    save_profile(profile)

    upload_result = None
    err: str | None = None
    n_games = 0
    n_live = 0
    try:
        mon = LiveMonitor()
        states = mon.scan_full()
        n_games = len(states)
        n_live = sum(1 for s in states if s.in_play)
        if upload_drive:
            from ..integrations.google_drive import upload_live_snapshot_bundle

            upload_result = upload_live_snapshot_bundle()
    except Exception as ex:
        err = str(ex)

    pulse = write_cloud_pulse(
        n_games=n_games,
        n_live=n_live,
        profile=profile,
        upload=upload_result,
        error=err,
    )
    if err:
        raise RuntimeError(err)
    return pulse
