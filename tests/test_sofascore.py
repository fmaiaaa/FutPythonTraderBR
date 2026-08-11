from __future__ import annotations

import json
from pathlib import Path

import pytest

from fpt.integrations.sofascore.match import find_event, match_teams
from fpt.integrations.sofascore.models import SofaScoreEvent
from fpt.integrations.sofascore.parser import parse_event_statistics, parse_graph
from fpt.live.pressure import apply_pressure, compute_pressure

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_match_teams_fuzzy():
    ev = SofaScoreEvent(event_id=1, home="Flamengo", away="Palmeiras")
    assert match_teams("Flamengo RJ", "Palmeiras SP", ev)
    assert not match_teams("Corinthians", "Santos", ev)


def test_match_teams_accent_and_abbreviation():
    ev = SofaScoreEvent(
        event_id=2,
        home="MŠK Považská Bystrica",
        away="FC ViOn Zlaté Moravce",
    )
    assert match_teams("Povazska Bystrica", "Z. Moravce-Vrable", ev)


def test_find_event():
    events = [
        SofaScoreEvent(event_id=10, home="SL Benfica", away="FC Porto"),
        SofaScoreEvent(event_id=11, home="Moreirense", away="FC Vizela"),
    ]
    found = find_event("Benfica", "Porto", events)
    assert found is not None
    assert found.event_id == 10


def test_parse_statistics():
    raw = _load("sofascore_statistics_sample.json")
    stats = parse_event_statistics(raw, 9620324)
    assert stats.possession_home == 55.0
    assert stats.possession_away == 45.0
    assert stats.shots_home == 12
    assert stats.shots_on_target_away == 3
    assert stats.xg_home == 1.42


def test_parse_graph():
    raw = _load("sofascore_graph_sample.json")
    assert parse_graph(raw) == 8.0
    assert parse_graph(raw, minute=2) == -5.0


def test_pressure_increases_with_sot():
    raw = _load("sofascore_statistics_sample.json")
    stats = parse_event_statistics(raw, 1)
    stats.minute = 30
    stats.graph_momentum = 5.0
    apply_pressure(stats)
    p = compute_pressure(stats)
    assert 0 <= p.home <= 100
    assert p.dominance == round(p.home - p.away, 2)

    stats2 = parse_event_statistics(raw, 1)
    stats2.minute = 30
    stats2.graph_momentum = 5.0
    stats2.shots_on_target_home = 8
    apply_pressure(stats2, stats)
    assert stats2.pressure_home >= stats.pressure_home


def test_enricher_load_events_falls_back_to_live(monkeypatch):
    from fpt.integrations.sofascore import SofaScoreError
    from fpt.live.sofascore_enricher import SofaScoreEnricher

    live_ev = SofaScoreEvent(event_id=99, home="PEC Zwolle", away="AFC Ajax", status_type="inprogress")

    class _Client:
        def scheduled_events(self, _day):
            raise SofaScoreError("HTTP Error 404")

        def live_events(self):
            return [live_ev]

    enricher = SofaScoreEnricher({"sofascore": {"enabled": True}})
    enricher._client = _Client()
    events = enricher._load_events("2026-08-09")
    assert len(events) == 1
    assert events[0].event_id == 99
