"""Status de processos CMD — lidos pelo dashboard Streamlit."""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ..client import DATA

BR = ZoneInfo("America/Sao_Paulo")
OPERATOR_STATUS = DATA / "live" / "operator_status.json"
COLLECTOR_STATUS = DATA / "live" / "collector_status.json"


def write_operator_status(
    last_result,
    *,
    running: bool,
    error: str | None = None,
    pid: int | None = None,
    phase: str | None = None,
) -> None:
    payload = {
        "updated": datetime.now(BR).isoformat(timespec="seconds"),
        "running": running,
        "pid": pid,
        "error": error,
    }
    if phase:
        payload["phase"] = phase
    if last_result is not None:
        payload.update({
            "ts": last_result.ts,
            "balance": last_result.balance,
            "n_games": last_result.n_games,
            "n_live": last_result.n_live,
            "n_entries": last_result.n_entries,
            "n_exits": last_result.n_exits,
            "n_errors": last_result.n_errors,
        })
        if not phase:
            payload["phase"] = "idle"
    OPERATOR_STATUS.parent.mkdir(parents=True, exist_ok=True)
    OPERATOR_STATUS.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def read_operator_status() -> dict:
    if not OPERATOR_STATUS.exists():
        return {"running": False}
    try:
        return json.loads(OPERATOR_STATUS.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"running": False}


def write_collector_status(
    *,
    running: bool,
    ticks: int = 0,
    last_rows: int = 0,
    last_ts: str | None = None,
    error: str | None = None,
    pid: int | None = None,
    phase: str | None = None,
) -> None:
    payload = {
        "updated": datetime.now(BR).isoformat(timespec="seconds"),
        "running": running,
        "pid": pid,
        "ticks": ticks,
        "last_rows": last_rows,
        "last_ts": last_ts,
        "error": error,
    }
    if phase:
        payload["phase"] = phase
    COLLECTOR_STATUS.parent.mkdir(parents=True, exist_ok=True)
    COLLECTOR_STATUS.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def read_collector_status() -> dict:
    if COLLECTOR_STATUS.exists():
        try:
            return json.loads(COLLECTOR_STATUS.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    d = date.today()
    manifest = DATA / "live_collection" / d.strftime("%Y-%m") / d.isoformat() / "manifest.json"
    if manifest.exists():
        try:
            m = json.loads(manifest.read_text(encoding="utf-8"))
            return {
                "running": False,
                "ticks": m.get("ticks", 0),
                "last_ts": m.get("updated"),
                "interval_seconds": m.get("interval_seconds"),
            }
        except (json.JSONDecodeError, OSError):
            pass
    return {"running": False}


def snapshot_meta() -> dict:
    from .operation_control import read_scan_heartbeat

    today = date.today().isoformat()
    path = DATA / "live" / today[:7] / f"snapshot_{today}.json"
    heartbeat = read_scan_heartbeat()
    if not path.exists():
        return {"path": str(path), "exists": False, "heartbeat": heartbeat}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {
            "path": str(path),
            "exists": True,
            "updated": payload.get("updated"),
            "n_matches": len(payload.get("matches") or []),
            "mtime": datetime.fromtimestamp(path.stat().st_mtime, BR).isoformat(timespec="seconds"),
            "heartbeat": heartbeat,
        }
    except (json.JSONDecodeError, OSError):
        return {"path": str(path), "exists": True, "updated": None, "heartbeat": heartbeat}
