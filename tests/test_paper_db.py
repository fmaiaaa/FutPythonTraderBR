"""Testes — banca paper SQLite."""
from __future__ import annotations

from fpt.live.paper_db import (
    cap_stake_pct,
    compute_close_pnl,
    get_state,
    init_paper_db,
    record_paper_entry,
    reset_paper_bankroll,
    settle_paper_exit,
)


def test_cap_stake_pct():
    assert cap_stake_pct(0.05) == 0.02
    assert cap_stake_pct(0.01) == 0.01


def test_compute_close_pnl_back():
    pnl, exit_stake = compute_close_pnl("BACK", 2.0, 3.0, 2.8, commission=0.05)
    assert exit_stake > 0
    assert isinstance(pnl, float)


def test_paper_entry_and_exit(tmp_path, monkeypatch):
    db = tmp_path / "paper_trading.db"
    monkeypatch.setattr("fpt.live.paper_db.PAPER_DB", db)
    monkeypatch.setattr("fpt.live.paper_db.persist_data_locally", lambda: True)
    monkeypatch.setattr(
        "fpt.live.paper_db._paper_cfg",
        lambda: {"initial_bankroll": 100.0, "max_stake_pct": 0.02, "commission": 0.05},
    )

    reset_paper_bankroll()
    st = get_state()
    assert st["bankroll"] == 100.0

    rec = record_paper_entry(
        position_id="pos-test1",
        alert_id="a1",
        home="Flamengo",
        away="Palmeiras",
        market="draw_ft",
        alert_type="ENTER",
        side="BACK",
        stake_amount=2.0,
        stake_pct=0.02,
        entry_odd=3.5,
    )
    assert rec["ok"] is True

    settled = settle_paper_exit(
        position_id="pos-test1",
        exit_side="LAY",
        exit_odd=3.2,
        alert_type="AUTO_EXIT",
    )
    assert settled is not None
    assert "pnl" in settled

    final = get_state()
    assert final["n_trades_closed"] == 1
    assert final["n_trades_open"] == 0
