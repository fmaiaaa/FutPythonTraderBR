"""Testes — limite de exposição correlacionada por jogo."""
from __future__ import annotations

from fpt.live.entry_exposure import (
    OpenExposure,
    check_entry_exposure,
    correlation_group,
    groups_conflict,
)


def _cfg() -> dict:
    return {
        "entry_exposure": {
            "enabled": True,
            "max_entries_per_match": 2,
            "max_per_correlation_group": 1,
        },
    }


def test_correlation_group_home_lay_away():
    assert correlation_group("home_win_ft", "BACK") == "favor_home"
    assert correlation_group("away_win_ft", "LAY") == "favor_home"


def test_groups_conflict_home_vs_away():
    assert groups_conflict("favor_home", "favor_away")
    assert not groups_conflict("favor_home", "low_goals")


def test_blocks_analogous_under_markets():
    existing = [
        OpenExposure("A", "B", "under25_ft", "BACK", entry_type="pre_live"),
    ]
    ok, reason = check_entry_exposure("A", "B", "under15_ft", "BACK", existing, _cfg())
    assert not ok
    assert reason.startswith("exposicao_analogica:")


def test_blocks_home_and_lay_away_same_thesis():
    existing = [
        OpenExposure("A", "B", "home_win_ft", "BACK", entry_type="pre_live"),
    ]
    ok, reason = check_entry_exposure("A", "B", "away_win_ft", "LAY", existing, _cfg())
    assert not ok
    assert reason.startswith("exposicao_analogica:")


def test_allows_different_groups_within_limit():
    existing = [
        OpenExposure("A", "B", "home_win_ft", "BACK", entry_type="pre_live"),
    ]
    ok, _ = check_entry_exposure("A", "B", "under25_ft", "BACK", existing, _cfg())
    assert ok


def test_blocks_max_entries_per_match():
    existing = [
        OpenExposure("A", "B", "home_win_ft", "BACK"),
        OpenExposure("A", "B", "under25_ft", "BACK"),
    ]
    ok, reason = check_entry_exposure("A", "B", "draw_ft", "BACK", existing, _cfg())
    assert not ok
    assert reason == "max_entradas_jogo"
