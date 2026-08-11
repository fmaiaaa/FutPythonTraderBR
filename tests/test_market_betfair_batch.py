from __future__ import annotations

from fpt.trading.market_betfair import (
    _collect_events_for_games,
    _match_event_ids,
    _query_tokens,
)


class _FakeBf:
    def __init__(self, responses: dict[str, list[dict]]):
        self.responses = responses
        self.calls: list[str] = []

    def list_events(self, _etype, text_query="", **kwargs):
        self.calls.append(text_query)
        return list(self.responses.get(text_query, []))


def test_query_tokens_from_home_and_away():
    toks = _query_tokens([("Flamengo RJ", "Palmeiras SP"), ("Santos", "Corinthians")])
    assert "flamengo" in toks
    assert "palmeiras" in toks
    assert "santos" in toks
    assert "corinthians" in toks


def test_collect_events_uses_tokens_not_global():
    events = [
        {"event": {"id": "1", "name": "Flamengo v Palmeiras"}},
    ]
    bf = _FakeBf({"flamengo": events, "palmeiras": events})
    out = _collect_events_for_games(
        bf,
        [("Flamengo", "Palmeiras")],
        market_start_from="2026-08-10T00:00:00Z",
        market_start_to="2026-08-11T00:00:00Z",
    )
    assert len(out) == 1
    assert "flamengo" in bf.calls
    assert "palmeiras" in bf.calls


def test_match_event_ids_token_index():
    events = [{"event": {"id": "99", "name": "Benfica v Porto"}}]
    ids = _match_event_ids([("Benfica", "Porto")], events)
    assert ids == ["99"]
