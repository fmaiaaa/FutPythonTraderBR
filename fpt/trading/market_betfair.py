from __future__ import annotations

"""
Integração Betfair Exchange BR — odds live (back/lay) via certificado.
"""

import os
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from ..integrations.betfair import get_betfair_client
from .market_sim import ExchangeSide, MarketOdds, MarketProvider

BR = ZoneInfo("America/Sao_Paulo")


def _norm(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9 ]", "", s)
    return re.sub(r"\s+", " ", s)


def _match_names(fpt_home: str, fpt_away: str, event_name: str) -> bool:
    """Fuzzy match FPT ↔ Betfair."""
    name = _norm(event_name)
    h = _norm(fpt_home)
    a = _norm(fpt_away)
    h_tok = h.split()[0] if h else ""
    a_tok = a.split()[0] if a else ""
    if not h_tok or not a_tok:
        return False
    return h_tok in name and a_tok in name


def parsed_to_market_odds(parsed: dict) -> MarketOdds:
    sides = parsed.get("sides", {})
    exchange: dict[str, ExchangeSide] = {}
    home_b = draw_b = away_b = None
    for key, data in sides.items():
        ex = ExchangeSide(
            back=data.get("back"),
            lay=data.get("lay"),
            back_size=data.get("back_size"),
            lay_size=data.get("lay_size"),
        )
        exchange[key] = ex
        if key == "home":
            home_b = ex.back
        elif key == "draw":
            draw_b = ex.back
        elif key == "away":
            away_b = ex.back
    return MarketOdds(
        home=home_b,
        draw=draw_b,
        away=away_b,
        source="betfair_br",
        exchange=exchange,
        market_id=parsed.get("market_id"),
        event_id=parsed.get("event_id"),
        in_play=bool(parsed.get("in_play")),
        status=parsed.get("status"),
        total_matched=parsed.get("total_matched"),
        score_home=parsed.get("score_home"),
        score_away=parsed.get("score_away"),
        elapsed_min=parsed.get("elapsed_min"),
    )


class BetfairMarket(MarketProvider):
    def __init__(self):
        self._bf = get_betfair_client()
        self.enabled = os.environ.get("BETFAIR_ENABLED", "").lower() in ("1", "true", "yes")

    @property
    def configured(self) -> bool:
        return self._bf.configured

    def connect(self):
        return self._bf.login()

    def get_odds(self, home: str, away: str, **kwargs) -> MarketOdds:
        if not self.configured:
            raise RuntimeError("Betfair nao configurada — veja docs/betfair/README.md")
        parsed = self.get_parsed_match(home, away)
        if not parsed:
            raise LookupError(f"Mercado nao encontrado: {home} x {away}")
        return parsed_to_market_odds(parsed)

    def get_parsed_match(self, home: str, away: str) -> dict | None:
        raw = self._bf.find_match_odds(home, away)
        if not raw:
            return None
        return self._bf.parse_match_odds(raw["catalogue"], raw["book"])

    def fetch_odds_for_games(
        self,
        games: list[tuple[str, str]],
        days_ahead: int = 1,
    ) -> list[dict]:
        """Odds Betfair apenas para jogos da watchlist (evita baixar mercado global)."""
        if not games:
            return []
        self.connect()
        today = datetime.now(BR).date()
        start = datetime(today.year, today.month, today.day, tzinfo=BR).astimezone(timezone.utc)
        end = start + timedelta(days=days_ahead + 1)
        events = self._bf.list_events(
            "1",
            market_start_from=start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            market_start_to=end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        matched_ids: list[str] = []
        seen: set[str] = set()
        for home, away in games:
            for ev in events:
                eid = ev["event"]["id"]
                if eid in seen:
                    continue
                if _match_names(home, away, ev.get("event", {}).get("name", "")):
                    matched_ids.append(eid)
                    seen.add(eid)
                    break
        return self._bf.fetch_match_odds_batch(matched_ids)

    def fetch_weekend_odds(self, days_ahead: int = 1) -> list[dict]:
        """Compat — preferir fetch_odds_for_games com lista FPT."""
        self.connect()
        today = datetime.now(BR).date()
        start = datetime(today.year, today.month, today.day, tzinfo=BR).astimezone(timezone.utc)
        end = start + timedelta(days=days_ahead + 1)
        events = self._bf.list_events(
            "1",
            market_start_from=start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            market_start_to=end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        if not events:
            return []
        eids = [e["event"]["id"] for e in events[:40]]
        return self._bf.fetch_match_odds_batch(eids)

    def match_fpt_to_betfair(
        self,
        home: str,
        away: str,
        betfair_events: list[dict],
    ) -> dict | None:
        for parsed in betfair_events:
            if _match_names(home, away, parsed.get("event_name", "")):
                return parsed
        return None
