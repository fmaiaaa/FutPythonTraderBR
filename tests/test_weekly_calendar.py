from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from fpt.live.weekly_calendar import (
    ScalpSlot,
    _save_daily_refresh_state,
    _window_bounds,
    active_scalp_slots,
    operating_week,
    should_run_daily_refresh,
    week_sun_sat,
)

BR = ZoneInfo("America/Sao_Paulo")


def test_week_sun_sat():
    thu = date(2026, 8, 6)
    sun, sat = week_sun_sat(thu)
    assert sun == date(2026, 8, 2)
    assert sat == date(2026, 8, 8)


def test_should_run_daily_refresh_after_23h(monkeypatch, tmp_path):
    monkeypatch.setattr("fpt.live.weekly_calendar.DATA", tmp_path)
    monkeypatch.setattr("fpt.live.weekly_calendar.WEEKLY_DIR", tmp_path / "calendar" / "weekly")
    monkeypatch.setattr("fpt.live.weekly_calendar.DAILY_REFRESH_STATE", tmp_path / "calendar" / "weekly" / "daily_refresh.json")
    before = datetime(2026, 8, 9, 22, 30, tzinfo=BR)
    after = datetime(2026, 8, 9, 23, 5, tzinfo=BR)
    assert should_run_daily_refresh(before) is False
    assert should_run_daily_refresh(after) is True


def test_daily_refresh_runs_once_per_day(monkeypatch, tmp_path):
    monkeypatch.setattr("fpt.live.weekly_calendar.DATA", tmp_path)
    monkeypatch.setattr("fpt.live.weekly_calendar.WEEKLY_DIR", tmp_path / "calendar" / "weekly")
    monkeypatch.setattr("fpt.live.weekly_calendar.DAILY_REFRESH_STATE", tmp_path / "calendar" / "weekly" / "daily_refresh.json")
    monkeypatch.setattr("fpt.live.weekly_calendar.persist_data_locally", lambda: True)
    now = datetime(2026, 8, 9, 23, 10, tzinfo=BR)
    _save_daily_refresh_state(target_day=now.date() + __import__("datetime").timedelta(days=1), run_date=now.date())
    assert should_run_daily_refresh(now) is False


def test_operating_week_on_saturday():
    sat = date(2026, 8, 8)
    sun, end = operating_week(sat)
    assert sun == date(2026, 8, 9)
    assert end == date(2026, 8, 15)


def test_window_bounds_includes_injury_time():
    cfg = {"pre_kickoff_minutes": 5, "match_duration_minutes": 105, "injury_extra_minutes": 15}
    ko = datetime(2026, 8, 9, 18, 0, tzinfo=BR)
    start, end = _window_bounds(ko, cfg)
    assert (ko - start).total_seconds() == 5 * 60
    assert (end - ko).total_seconds() == 120 * 60


def test_active_scalp_slots(monkeypatch):
    ko = datetime(2026, 8, 9, 18, 0, tzinfo=BR)
    start, end = _window_bounds(ko, {"pre_kickoff_minutes": 5, "match_duration_minutes": 105, "injury_extra_minutes": 15})
    slot = ScalpSlot(
        game_id="1",
        home="A",
        away="B",
        league="TEST",
        match_date="2026-08-09",
        kickoff=ko.strftime("%d/%m/%Y %H:%M"),
        kickoff_dt=ko.isoformat(timespec="minutes"),
        scalp_start=start.isoformat(timespec="minutes"),
        scalp_end=end.isoformat(timespec="minutes"),
    )
    monkeypatch.setattr("fpt.live.weekly_calendar.load_weekly_slots", lambda: [slot])
    now = ko + __import__("datetime").timedelta(minutes=30)
    assert len(active_scalp_slots(now)) == 1
    assert len(active_scalp_slots(ko - __import__("datetime").timedelta(hours=2))) == 0
