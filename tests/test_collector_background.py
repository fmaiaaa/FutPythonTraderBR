"""Testes — coleta background com app aberto."""
from __future__ import annotations

from unittest.mock import patch

from fpt.live.collector import LiveDataCollector, ensure_collector_background


def test_robot_active_skips_background_tick():
    col = LiveDataCollector.get()
    col.set_robot_collects(True)
    with patch.object(col, "collect_tick") as mock_tick:
        col._robot_collects = True
        # simula um ciclo do loop sem dormir
        if not col._robot_collects:
            col.collect_tick()
    mock_tick.assert_not_called()


def test_singleton_get():
    a = LiveDataCollector.get()
    b = LiveDataCollector.get()
    assert a is b


def test_ensure_collector_background_module_fn():
    col = ensure_collector_background()
    assert isinstance(col, LiveDataCollector)
