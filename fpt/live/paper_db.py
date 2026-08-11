"""Banca fictícia (paper) — SQLite com evolução da banca."""
from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

from ..client import DATA
from ..storage import persist_data_locally
from .config import load_live_config

BR = ZoneInfo("America/Sao_Paulo")
PAPER_DB = DATA / "live" / "paper_trading.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS paper_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    bankroll REAL NOT NULL,
    initial_bankroll REAL NOT NULL,
    max_stake_pct REAL NOT NULL DEFAULT 0.02,
    commission REAL NOT NULL DEFAULT 0.05,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id TEXT UNIQUE NOT NULL,
    position_id TEXT,
    alert_id TEXT,
    ts TEXT NOT NULL,
    closed_ts TEXT,
    home TEXT,
    away TEXT,
    market TEXT,
    alert_type TEXT,
    entry_side TEXT NOT NULL,
    exit_side TEXT,
    entry_odd REAL NOT NULL,
    exit_odd REAL,
    stake_amount REAL NOT NULL,
    stake_pct REAL,
    pnl REAL,
    bankroll_after REAL,
    status TEXT NOT NULL DEFAULT 'OPEN',
    notes TEXT
);

CREATE TABLE IF NOT EXISTS paper_bankroll_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    bankroll REAL NOT NULL,
    event TEXT,
    trade_id TEXT,
    pnl REAL
);

CREATE INDEX IF NOT EXISTS idx_paper_trades_status ON paper_trades(status);
CREATE INDEX IF NOT EXISTS idx_paper_trades_position ON paper_trades(position_id);
CREATE INDEX IF NOT EXISTS idx_paper_history_ts ON paper_bankroll_history(ts);
"""


def _paper_cfg() -> dict:
    cfg = load_live_config()
    paper = cfg.get("paper", {})
    exec_cfg = cfg.get("execution", {})
    live = cfg.get("live", {})
    return {
        "initial_bankroll": float(
            paper.get("initial_bankroll")
            or live.get("bankroll")
            or 100.0
        ),
        "max_stake_pct": float(
            paper.get("max_stake_pct")
            or exec_cfg.get("max_stake_pct")
            or 0.02
        ),
        "commission": float(paper.get("commission", 0.05)),
    }


@contextmanager
def _conn():
    if not persist_data_locally():
        raise RuntimeError("Persistência local desabilitada")
    PAPER_DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(PAPER_DB)
    con.row_factory = sqlite3.Row
    try:
        con.executescript(_SCHEMA)
        yield con
        con.commit()
    finally:
        con.close()


def _now() -> str:
    return datetime.now(BR).isoformat(timespec="seconds")


def init_paper_db(force_reset: bool = False) -> dict:
    """Inicializa ou retorna estado da banca paper."""
    cfg = _paper_cfg()
    with _conn() as con:
        row = con.execute("SELECT * FROM paper_state WHERE id = 1").fetchone()
        if row is None or force_reset:
            if force_reset:
                con.execute("DELETE FROM paper_trades")
                con.execute("DELETE FROM paper_bankroll_history")
                con.execute("DELETE FROM paper_state")
            ts = _now()
            con.execute(
                """
                INSERT INTO paper_state (id, bankroll, initial_bankroll, max_stake_pct, commission, updated_at)
                VALUES (1, ?, ?, ?, ?, ?)
                """,
                (cfg["initial_bankroll"], cfg["initial_bankroll"], cfg["max_stake_pct"], cfg["commission"], ts),
            )
            con.execute(
                "INSERT INTO paper_bankroll_history (ts, bankroll, event, trade_id, pnl) VALUES (?, ?, ?, ?, ?)",
                (ts, cfg["initial_bankroll"], "INIT", None, 0.0),
            )
            return get_paper_summary(con)
        return get_paper_summary(con)


def get_state() -> dict:
    init_paper_db()
    with _conn() as con:
        return get_paper_summary(con)


def get_paper_summary(con: sqlite3.Connection | None = None) -> dict:
    if con is None:
        with _conn() as c:
            return get_paper_summary(c)

    row = con.execute("SELECT * FROM paper_state WHERE id = 1").fetchone()
    if row is None:
        return init_paper_db()

    bankroll = float(row["bankroll"])
    initial = float(row["initial_bankroll"])
    open_rows = con.execute(
        "SELECT stake_amount, entry_side, entry_odd FROM paper_trades WHERE status = 'OPEN'"
    ).fetchall()
    exposure = sum(_trade_exposure(r["entry_side"], float(r["stake_amount"]), float(r["entry_odd"])) for r in open_rows)
    open_count = len(open_rows)
    closed = con.execute(
        "SELECT COALESCE(SUM(pnl), 0) AS total_pnl, COUNT(*) AS n FROM paper_trades WHERE status = 'CLOSED'"
    ).fetchone()

    return {
        "bankroll": bankroll,
        "initial_bankroll": initial,
        "available_bankroll": round(max(0.0, bankroll - exposure), 2),
        "exposure": round(exposure, 2),
        "max_stake_pct": float(row["max_stake_pct"]),
        "commission": float(row["commission"]),
        "pnl_total": round(float(closed["total_pnl"] or 0), 2),
        "roi_pct": round((bankroll - initial) / initial * 100, 2) if initial > 0 else 0.0,
        "n_trades_closed": int(closed["n"] or 0),
        "n_trades_open": open_count,
        "updated_at": row["updated_at"],
    }


def cap_stake_pct(stake_pct: float) -> float:
    cfg = _paper_cfg()
    return min(float(stake_pct), cfg["max_stake_pct"])


def get_available_bankroll() -> float:
    return float(get_state()["available_bankroll"])


def _trade_exposure(side: str, stake: float, odd: float) -> float:
    side = side.upper()
    if side == "BACK":
        return stake
    return stake * max(odd - 1.0, 0.01)


def compute_close_pnl(
    entry_side: str,
    entry_stake: float,
    entry_odd: float,
    exit_odd: float,
    commission: float | None = None,
) -> tuple[float, float]:
    """Fecha com ordem oposta (greening). Retorna (pnl, exit_stake)."""
    commission = commission if commission is not None else _paper_cfg()["commission"]
    entry_side = entry_side.upper()
    exit_stake = round(entry_stake * entry_odd / exit_odd, 2)

    if entry_side == "BACK":
        pnl_win = entry_stake * (entry_odd - 1) * (1 - commission) - exit_stake * (exit_odd - 1)
        pnl_lose = -entry_stake + exit_stake * (1 - commission)
    else:
        pnl_win = -entry_stake * (entry_odd - 1) + exit_stake * (exit_odd - 1) * (1 - commission)
        pnl_lose = entry_stake * (1 - commission) - exit_stake

    pnl = round((pnl_win + pnl_lose) / 2, 2)
    return pnl, exit_stake


def record_paper_entry(
    *,
    position_id: str,
    alert_id: str,
    home: str,
    away: str,
    market: str,
    alert_type: str,
    side: str,
    stake_amount: float,
    stake_pct: float,
    entry_odd: float,
) -> dict:
    init_paper_db()
    trade_id = f"pt-{uuid.uuid4().hex[:12]}"
    ts = _now()
    side = side.upper()
    stake_pct = cap_stake_pct(stake_pct)

    with _conn() as con:
        summary = get_paper_summary(con)
        if stake_amount > summary["available_bankroll"] + 0.01:
            return {"ok": False, "error": "Banca paper insuficiente para stake"}

        con.execute(
            """
            INSERT INTO paper_trades (
                trade_id, position_id, alert_id, ts, home, away, market, alert_type,
                entry_side, entry_odd, stake_amount, stake_pct, status, bankroll_after
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?)
            """,
            (
                trade_id, position_id, alert_id, ts, home, away, market, alert_type,
                side, entry_odd, stake_amount, stake_pct, summary["bankroll"],
            ),
        )
        con.execute(
            "INSERT INTO paper_bankroll_history (ts, bankroll, event, trade_id, pnl) VALUES (?, ?, ?, ?, ?)",
            (ts, summary["bankroll"], f"ENTRY {side}", trade_id, 0.0),
        )

    return {"ok": True, "trade_id": trade_id}


def settle_paper_exit(
    *,
    position_id: str,
    exit_side: str,
    exit_odd: float,
    alert_type: str = "AUTO_EXIT",
) -> dict | None:
    init_paper_db()
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM paper_trades WHERE position_id = ? AND status = 'OPEN' ORDER BY id DESC LIMIT 1",
            (position_id,),
        ).fetchone()
        if row is None:
            return None

        state = con.execute("SELECT * FROM paper_state WHERE id = 1").fetchone()
        commission = float(state["commission"])
        entry_side = row["entry_side"]
        entry_stake = float(row["stake_amount"])
        entry_odd = float(row["entry_odd"])
        pnl, exit_stake = compute_close_pnl(entry_side, entry_stake, entry_odd, exit_odd, commission)

        new_bankroll = round(float(state["bankroll"]) + pnl, 2)
        ts = _now()
        con.execute(
            """
            UPDATE paper_trades SET
                status = 'CLOSED', closed_ts = ?, exit_side = ?, exit_odd = ?,
                pnl = ?, bankroll_after = ?, notes = ?
            WHERE trade_id = ?
            """,
            (ts, exit_side.upper(), exit_odd, pnl, new_bankroll, alert_type, row["trade_id"]),
        )
        con.execute(
            "UPDATE paper_state SET bankroll = ?, updated_at = ? WHERE id = 1",
            (new_bankroll, ts),
        )
        con.execute(
            "INSERT INTO paper_bankroll_history (ts, bankroll, event, trade_id, pnl) VALUES (?, ?, ?, ?, ?)",
            (ts, new_bankroll, f"EXIT {alert_type}", row["trade_id"], pnl),
        )

    return {"trade_id": row["trade_id"], "pnl": pnl, "bankroll": new_bankroll}


def snapshot_bankroll(event: str = "TICK") -> None:
    summary = get_state()
    with _conn() as con:
        con.execute(
            "INSERT INTO paper_bankroll_history (ts, bankroll, event, trade_id, pnl) VALUES (?, ?, ?, ?, ?)",
            (_now(), summary["bankroll"], event, None, 0.0),
        )


def list_paper_trades(limit: int = 100, *, open_only: bool = False) -> list[dict]:
    init_paper_db()
    with _conn() as con:
        q = "SELECT * FROM paper_trades"
        if open_only:
            q += " WHERE status = 'OPEN'"
        q += " ORDER BY id DESC LIMIT ?"
        return [dict(r) for r in con.execute(q, (limit,)).fetchall()]


def bankroll_history(limit: int = 500) -> list[dict]:
    init_paper_db()
    with _conn() as con:
        rows = con.execute(
            "SELECT ts, bankroll, event, trade_id, pnl FROM paper_bankroll_history ORDER BY id ASC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def reset_paper_bankroll() -> dict:
    return init_paper_db(force_reset=True)


def cancel_open_paper_trades() -> int:
    """Cancela trades OPEN sem alterar banca (libera exposição)."""
    init_paper_db()
    ts = _now()
    with _conn() as con:
        rows = con.execute("SELECT trade_id FROM paper_trades WHERE status = 'OPEN'").fetchall()
        for row in rows:
            con.execute(
                """
                UPDATE paper_trades
                SET status = 'CANCELLED', closed_ts = ?, notes = 'RESET_ENTRADAS'
                WHERE trade_id = ?
                """,
                (ts, row["trade_id"]),
            )
        if rows:
            con.execute(
                "INSERT INTO paper_bankroll_history (ts, bankroll, event, trade_id, pnl) VALUES (?, ?, ?, ?, ?)",
                (ts, get_paper_summary(con)["bankroll"], "RESET_CANCEL_OPEN", None, 0.0),
            )
        return len(rows)
