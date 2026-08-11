from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from fpt.live.minute_store import (
    bankroll_minute_history,
    match_minute_count,
    minute_timeline_path,
    record_bankroll_minute,
    record_match_minutes_from_states,
    truncate_to_minute,
)
from fpt.live.models import LiveMatchState

BR = ZoneInfo("America/Sao_Paulo")


@pytest.fixture
def minute_db(tmp_path, monkeypatch):
    monkeypatch.setenv("FPT_PERSIST_LOCAL", "1")
    db = tmp_path / "live" / "minute_timeline.db"
    for mod in ("fpt.client", "fpt.live.minute_store", "fpt.live.paper_db"):
        monkeypatch.setattr(f"{mod}.DATA", tmp_path)
    monkeypatch.setattr("fpt.live.paper_db.PAPER_DB", tmp_path / "live" / "paper_trading.db")
    monkeypatch.setattr("fpt.live.paper_db.persist_data_locally", lambda: True)
    monkeypatch.setattr(
        "fpt.live.paper_db._paper_cfg",
        lambda: {"initial_bankroll": 100.0, "max_stake_pct": 0.02, "commission": 0.05},
    )
    monkeypatch.setattr("fpt.live.minute_store.MINUTE_DB", db)
    monkeypatch.setattr("fpt.live.minute_store.persist_data_locally", lambda: True)
    from fpt.live.paper_db import init_paper_db

    init_paper_db()
    return tmp_path


def test_record_bankroll_and_match_minutes(minute_db):
    state = LiveMatchState(
        home="Flamengo",
        away="Vasco",
        league="BRAZIL 1",
        league_label="Brasileirão",
        kickoff="09/08/2026 18:30",
        status="LIVE",
        in_play=True,
        elapsed_min=55,
        score_home=1,
        score_away=0,
        sofascore_event_id=12345,
        sofascore_stats={
            "ss_possession_home": 58,
            "ss_possession_away": 42,
            "ss_xg_home": 1.2,
            "ss_xg_away": 0.7,
        },
        odds={"Casa": {"back": 1.85, "lay": 1.86}},
    )
    n = record_match_minutes_from_states([state])
    assert n == 1
    record_bankroll_minute(n_positions=2)

    hist = bankroll_minute_history()
    assert len(hist) == 1
    assert hist[0]["bankroll"] == 100.0
    assert hist[0]["n_positions"] == 2
    assert match_minute_count() == 1
    assert minute_timeline_path().name == "minute_timeline.db"


def test_truncate_to_minute():
    dt = datetime(2026, 8, 9, 21, 48, 32, tzinfo=BR)
    assert truncate_to_minute(dt) == "2026-08-09T21:48:00-03:00"
