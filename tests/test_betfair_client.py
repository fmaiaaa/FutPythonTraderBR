"""Testes Betfair BR — listScores opcional (DSC-0021)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from fpt.integrations.betfair.client import BetfairClient, BetfairConfig


def test_list_scores_optional_swallows_dsc_0021():
    client = BetfairClient(BetfairConfig(
        username="u", password="p", app_key="k",
        cert_dir=Path("certs"),
    ))
    with patch.object(client, "list_scores", side_effect=RuntimeError("DSC-0021")):
        assert client.list_scores_optional(["1.1"]) == []


def test_fetch_batch_without_scores():
    client = BetfairClient(BetfairConfig(
        username="u", password="p", app_key="k",
        cert_dir=Path("certs"),
    ))
    cat = [{
        "marketId": "1.1",
        "marketName": "Match Odds",
        "event": {"id": "99", "name": "Home v Away"},
        "runners": [
            {"selectionId": 1, "runnerName": "Home"},
            {"selectionId": 2, "runnerName": "The Draw"},
            {"selectionId": 3, "runnerName": "Away"},
        ],
    }]
    book = {
        "marketId": "1.1",
        "inplay": False,
        "status": "OPEN",
        "totalMatched": 1000.0,
        "runners": [
            {"selectionId": 1, "ex": {"availableToBack": [{"price": 2.0, "size": 10}], "availableToLay": [{"price": 2.02, "size": 10}]}},
            {"selectionId": 2, "ex": {"availableToBack": [{"price": 3.5, "size": 10}], "availableToLay": [{"price": 3.55, "size": 10}]}},
            {"selectionId": 3, "ex": {"availableToBack": [{"price": 4.0, "size": 10}], "availableToLay": [{"price": 4.05, "size": 10}]}},
        ],
    }
    with patch.object(client, "list_market_catalogue", return_value=cat):
        with patch.object(client, "list_market_book", return_value=[book]):
            with patch.object(client, "list_scores_optional", return_value=[]):
                out = client.fetch_match_odds_batch(["99"])
    assert len(out) == 1
    assert out[0]["sides"]["home"]["back"] == 2.0
    assert out[0]["sides"]["home"]["lay"] == 2.02


def test_rpc_retries_on_invalid_session():
    client = BetfairClient(BetfairConfig(
        username="u", password="p", app_key="k",
        cert_dir=Path("certs"),
    ))
    client._session_token = "expired-token"
    calls = {"n": 0}

    def fake_login(force=False):
        calls["n"] += 1
        client._session_token = f"token-{calls['n']}"
        return client._session_token

    class _FakeResp:
        def __init__(self, data):
            self._data = json.dumps(data).encode()

        def read(self):
            return self._data

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    def fake_urlopen(req, timeout=60):
        if calls["n"] <= 1:
            return _FakeResp({
                "jsonrpc": "2.0",
                "error": {
                    "code": -32099,
                    "message": "AANGX-0002",
                    "data": {"AccountAPINGException": {"errorCode": "INVALID_SESSION_INFORMATION"}},
                },
                "id": 1,
            })
        return _FakeResp({"jsonrpc": "2.0", "result": {"availableToBetBalance": 100.0}, "id": 1})

    with patch.object(client, "login", side_effect=fake_login):
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            out = client.account_call("AccountAPING/v1.0/getAccountFunds", {})
    assert out["availableToBetBalance"] == 100.0
    assert calls["n"] >= 2
