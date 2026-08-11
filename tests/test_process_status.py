"""Testes — status de processos e modo headless."""
from __future__ import annotations

from unittest.mock import patch

from fpt.live.process_status import (
    read_collector_status,
    read_operator_status,
    snapshot_meta,
    write_collector_status,
    write_operator_status,
)
from fpt.live.autonomous import TickResult, AutonomousOperator


def test_write_read_operator_status(tmp_path, monkeypatch):
    status_file = tmp_path / "operator_status.json"
    monkeypatch.setattr("fpt.live.process_status.OPERATOR_STATUS", status_file)

    tr = TickResult(
        ts="2026-08-09T10:00:00",
        balance=500.0,
        n_games=12,
        n_live=3,
        n_entries=1,
        n_exits=0,
        n_errors=0,
    )
    write_operator_status(tr, running=True, pid=1234)
    st = read_operator_status()
    assert st["running"] is True
    assert st["n_games"] == 12
    assert st["balance"] == 500.0


def test_scanning_phase_not_overwritten_by_last_result(tmp_path, monkeypatch):
    status_file = tmp_path / "operator_status.json"
    monkeypatch.setattr("fpt.live.process_status.OPERATOR_STATUS", status_file)
    tr = TickResult(
        ts="2026-08-09T10:00:00",
        balance=500.0,
        n_games=12,
        n_live=3,
        n_entries=1,
        n_exits=0,
        n_errors=0,
    )
    write_operator_status(tr, running=True, pid=1234, phase="scanning")
    st = read_operator_status()
    assert st["phase"] == "scanning"


def test_write_read_collector_status(tmp_path, monkeypatch):
    status_file = tmp_path / "collector_status.json"
    monkeypatch.setattr("fpt.live.process_status.COLLECTOR_STATUS", status_file)

    write_collector_status(running=True, ticks=5, last_rows=8, pid=5678)
    st = read_collector_status()
    assert st["running"] is True
    assert st["ticks"] == 5
    assert st["last_rows"] == 8


def test_snapshot_meta_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("fpt.live.process_status.DATA", tmp_path)
    meta = snapshot_meta()
    assert meta["exists"] is False


def test_run_betfair_operator_one_tick(tmp_path, monkeypatch):
    status_file = tmp_path / "operator_status.json"
    monkeypatch.setattr("fpt.live.process_status.OPERATOR_STATUS", status_file)

    op = AutonomousOperator()
    tick_result = TickResult(
        ts="2026-08-09T10:00:00",
        balance=100.0,
        n_games=5,
        n_live=1,
        n_entries=0,
        n_exits=0,
        n_errors=0,
    )

    with patch.object(op, "tick", return_value=tick_result):
        op._running = True
        op._last_result = tick_result
        write_operator_status(tick_result, running=True)
        op._running = False
        write_operator_status(tick_result, running=False)

    st = read_operator_status()
    assert st["running"] is False
    assert st["n_games"] == 5
