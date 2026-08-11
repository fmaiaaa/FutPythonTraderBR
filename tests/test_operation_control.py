from __future__ import annotations

import json
from pathlib import Path

import pytest

from fpt.live.operation_control import (
    pending_reset_path,
    reset_initial_bankroll,
    reset_open_entries,
)
from fpt.live.paper_db import get_state, list_paper_trades, record_paper_entry
from fpt.live.trade_positions import PositionManager


@pytest.fixture
def live_data(tmp_path, monkeypatch):
    monkeypatch.setenv("FPT_PERSIST_LOCAL", "1")
    monkeypatch.setenv("FPT_DATA_ROOT", str(tmp_path))
    for mod in (
        "fpt.client",
        "fpt.live.paper_db",
        "fpt.live.trade_positions",
        "fpt.live.scalping",
        "fpt.live.operation_control",
    ):
        monkeypatch.setattr(f"{mod}.DATA", tmp_path)
    monkeypatch.setattr("fpt.live.trade_positions.POSITIONS_FILE", tmp_path / "live" / "managed_positions.json")
    (tmp_path / "live").mkdir(parents=True, exist_ok=True)
    return tmp_path


def test_reset_open_entries_clears_positions_and_executed(live_data):
    pm = PositionManager()
    from fpt.live.models import LiveAlert

    alert = LiveAlert(
        alert_id="a1",
        alert_type="ENTER",
        severity="low",
        home="A",
        away="B",
        league="TEST",
        market="home_win_ft",
        message="test",
        prob_est=0.5,
        odd_back=2.0,
        odd_lay=2.1,
        odd_min=2.0,
        edge_pp=1.0,
        stake_pct=0.02,
        stake_valor=2.0,
        stake_back_pct=0.02,
        stake_lay_pct=0.0,
        market_id="1",
        selection_id=1,
        recommended_side="BACK",
        score="0-0",
        in_play=False,
    )
    pm.register_entry(alert, side="BACK", stake_amount=2.0)
    assert len(pm.open_positions) == 1

    record_paper_entry(
        position_id="pos-test",
        alert_id="a1",
        home="A",
        away="B",
        market="home_win_ft",
        alert_type="ENTER",
        side="BACK",
        stake_amount=2.0,
        stake_pct=0.02,
        entry_odd=2.0,
    )
    executed = live_data / "live" / "executed_alerts.json"
    executed.write_text(json.dumps({"ids": ["x1", "x2"]}), encoding="utf-8")

    info = reset_open_entries()
    assert info["positions_cleared"] >= 1
    assert info["paper_cancelled"] == 1
    assert len(PositionManager().open_positions) == 0
    assert list_paper_trades(open_only=True) == []
    assert json.loads(executed.read_text())["ids"] == []
    assert pending_reset_path().exists()


def test_reset_initial_bankroll(live_data):
    record_paper_entry(
        position_id="pos-test",
        alert_id="a1",
        home="A",
        away="B",
        market="home_win_ft",
        alert_type="ENTER",
        side="BACK",
        stake_amount=2.0,
        stake_pct=0.02,
        entry_odd=2.0,
    )
    state = reset_initial_bankroll()
    assert state["bankroll"] == state["initial_bankroll"]
    assert get_state()["n_trades_open"] == 0
