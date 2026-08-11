"""Controles operacionais — reset de banca, entradas e sinal ao robô em execução."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ..client import DATA
from ..storage import persist_data_locally
from .paper_db import cancel_open_paper_trades, reset_paper_bankroll
from .minute_store import clear_bankroll_minutes
from .scalping import clear_scalp_positions
from .trade_positions import clear_managed_positions

BR = ZoneInfo("America/Sao_Paulo")


def pending_reset_path() -> Path:
    return DATA / "live" / "pending_reset.json"


def scan_heartbeat_path() -> Path:
    return DATA / "live" / "scan_heartbeat.json"


def executed_alerts_path() -> Path:
    return DATA / "live" / "executed_alerts.json"


def _now() -> str:
    return datetime.now(BR).isoformat(timespec="seconds")


def write_scan_heartbeat(*, phase: str, n_games: int | None = None, n_done: int | None = None) -> None:
    if not persist_data_locally():
        return
    path = scan_heartbeat_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"ts": _now(), "phase": phase}
    if n_games is not None:
        payload["n_games"] = n_games
    if n_done is not None:
        payload["n_done"] = n_done
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def read_scan_heartbeat() -> dict:
    path = scan_heartbeat_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _clear_executed_alerts_file() -> None:
    path = executed_alerts_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"updated": _now(), "ids": []}, ensure_ascii=False),
        encoding="utf-8",
    )


def _signal_operator(action: str) -> None:
    path = pending_reset_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"action": action, "ts": _now()}, ensure_ascii=False),
        encoding="utf-8",
    )


def consume_pending_reset() -> str | None:
    path = pending_reset_path()
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        action = str(payload.get("action") or "")
    except (json.JSONDecodeError, OSError):
        action = "entries"
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
    return action or None


def reset_initial_bankroll() -> dict:
    """Zera histórico paper e restaura saldo inicial (config/live.yaml)."""
    state = reset_paper_bankroll()
    clear_managed_positions()
    clear_scalp_positions()
    cancel_open_paper_trades()
    clear_bankroll_minutes()
    _clear_executed_alerts_file()
    _signal_operator("bankroll")
    return state


def reset_open_entries() -> dict:
    """Fecha posições em disco, cancela trades paper abertos e libera novas entradas."""
    n_managed = clear_managed_positions()
    n_scalp = clear_scalp_positions()
    n_paper = cancel_open_paper_trades()
    _clear_executed_alerts_file()
    _signal_operator("entries")
    return {
        "positions_cleared": n_managed + n_scalp,
        "managed": n_managed,
        "scalp": n_scalp,
        "paper_cancelled": n_paper,
    }
