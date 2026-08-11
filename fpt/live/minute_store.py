"""Timeline minuto a minuto — banca paper + stats SofaScore por jogo (SQLite)."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ..client import DATA
from ..storage import persist_data_locally

BR = ZoneInfo("America/Sao_Paulo")
MINUTE_DB = DATA / "live" / "minute_timeline.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS bankroll_minute (
    minute_ts TEXT PRIMARY KEY,
    bankroll REAL NOT NULL,
    exposure REAL NOT NULL,
    available REAL NOT NULL,
    n_positions INTEGER NOT NULL DEFAULT 0,
    recorded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS match_minute (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    minute_ts TEXT NOT NULL,
    home TEXT NOT NULL,
    away TEXT NOT NULL,
    league TEXT,
    match_date TEXT,
    event_id INTEGER,
    status TEXT,
    in_play INTEGER,
    elapsed_min INTEGER,
    score_home INTEGER,
    score_away INTEGER,
    back_home REAL,
    lay_home REAL,
    stats_json TEXT,
    recorded_at TEXT NOT NULL,
    UNIQUE(minute_ts, home, away)
);

CREATE INDEX IF NOT EXISTS idx_match_minute_ts ON match_minute(minute_ts);
CREATE INDEX IF NOT EXISTS idx_match_minute_game ON match_minute(home, away, minute_ts);
CREATE INDEX IF NOT EXISTS idx_bankroll_minute_ts ON bankroll_minute(minute_ts);
"""


def minute_timeline_path() -> Path:
    return MINUTE_DB


def truncate_to_minute(dt: datetime | None = None) -> str:
    dt = (dt or datetime.now(BR)).astimezone(BR).replace(second=0, microsecond=0)
    return dt.isoformat(timespec="seconds")


@contextmanager
def _conn():
    if not persist_data_locally():
        raise RuntimeError("Persistência local desabilitada")
    MINUTE_DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(MINUTE_DB)
    con.row_factory = sqlite3.Row
    try:
        con.executescript(_SCHEMA)
        yield con
        con.commit()
    finally:
        con.close()


def _now() -> str:
    return datetime.now(BR).isoformat(timespec="seconds")


def record_bankroll_minute(*, n_positions: int = 0) -> bool:
    """Grava saldo paper no minuto corrente (1 linha por minuto)."""
    from .paper_db import get_state

    summary = get_state()
    minute_ts = truncate_to_minute()
    with _conn() as con:
        con.execute(
            """
            INSERT INTO bankroll_minute (
                minute_ts, bankroll, exposure, available, n_positions, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(minute_ts) DO UPDATE SET
                bankroll = excluded.bankroll,
                exposure = excluded.exposure,
                available = excluded.available,
                n_positions = excluded.n_positions,
                recorded_at = excluded.recorded_at
            """,
            (
                minute_ts,
                float(summary["bankroll"]),
                float(summary["exposure"]),
                float(summary["available_bankroll"]),
                int(n_positions),
                _now(),
            ),
        )
    return True


def record_match_minutes_from_states(states: list) -> int:
    """Grava snapshot SofaScore/odds por jogo no minuto corrente."""
    if not states:
        return 0
    minute_ts = truncate_to_minute()
    recorded_at = _now()
    n = 0
    with _conn() as con:
        for state in states:
            ss = dict(getattr(state, "sofascore_stats", None) or {})
            odds = getattr(state, "odds", None) or {}
            casa = odds.get("Casa") or {}
            row = (
                minute_ts,
                getattr(state, "home", ""),
                getattr(state, "away", ""),
                getattr(state, "league", ""),
                _match_date_from_kickoff(getattr(state, "kickoff", "")),
                _int_or_none(getattr(state, "sofascore_event_id", None)),
                getattr(state, "status", ""),
                1 if getattr(state, "in_play", False) else 0,
                _int_or_none(getattr(state, "elapsed_min", None)),
                _int_or_none(getattr(state, "score_home", None)),
                _int_or_none(getattr(state, "score_away", None)),
                _float_or_none(casa.get("back")),
                _float_or_none(casa.get("lay")),
                json.dumps(ss, ensure_ascii=False) if ss else None,
                recorded_at,
            )
            con.execute(
                """
                INSERT INTO match_minute (
                    minute_ts, home, away, league, match_date, event_id, status, in_play,
                    elapsed_min, score_home, score_away, back_home, lay_home, stats_json, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(minute_ts, home, away) DO UPDATE SET
                    league = excluded.league,
                    match_date = excluded.match_date,
                    event_id = excluded.event_id,
                    status = excluded.status,
                    in_play = excluded.in_play,
                    elapsed_min = excluded.elapsed_min,
                    score_home = excluded.score_home,
                    score_away = excluded.score_away,
                    back_home = excluded.back_home,
                    lay_home = excluded.lay_home,
                    stats_json = excluded.stats_json,
                    recorded_at = excluded.recorded_at
                """,
                row,
            )
            n += 1
    return n


def bankroll_minute_history(*, limit: int = 2000, day: date | None = None) -> list[dict]:
    day = day or date.today()
    prefix = day.isoformat()
    with _conn() as con:
        rows = con.execute(
            """
            SELECT minute_ts, bankroll, exposure, available, n_positions, recorded_at
            FROM bankroll_minute
            WHERE minute_ts LIKE ?
            ORDER BY minute_ts ASC
            LIMIT ?
            """,
            (f"{prefix}%", limit),
        ).fetchall()
    return [dict(r) for r in rows]


def match_minute_count(*, day: date | None = None) -> int:
    day = day or date.today()
    with _conn() as con:
        row = con.execute(
            "SELECT COUNT(*) AS n FROM match_minute WHERE minute_ts LIKE ?",
            (f"{day.isoformat()}%",),
        ).fetchone()
    return int(row["n"] if row else 0)


def clear_bankroll_minutes() -> None:
    with _conn() as con:
        con.execute("DELETE FROM bankroll_minute")


def _int_or_none(val) -> int | None:
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _float_or_none(val) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _match_date_from_kickoff(kickoff: str) -> str | None:
    if not kickoff or kickoff == "—":
        return date.today().isoformat()
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S"):
        try:
            return datetime.strptime(kickoff[:16], fmt).date().isoformat()
        except ValueError:
            continue
    return date.today().isoformat()
