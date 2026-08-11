from __future__ import annotations

"""
Integração Betfair Exchange BR — odds live (back/lay) via certificado.
"""

import os
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from collections import defaultdict

from ..integrations.betfair import get_betfair_client
from .market_sim import ExchangeSide, MarketOdds, MarketProvider

BR = ZoneInfo("America/Sao_Paulo")


def _norm(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9 ]", "", s)
    return re.sub(r"\s+", " ", s)


def _first_token(name: str) -> str:
    parts = _norm(name).split()
    return parts[0] if parts else ""


def _build_parsed_lookup(parsed_events: list[dict], games: list[tuple[str, str]]) -> dict[str, dict]:
    """Mapa home|away → odds Betfair já parseadas (evita loop O(n²) no scan)."""
    if not parsed_events or not games:
        return {}
    norm_events = [(_norm(p.get("event_name", "")), p) for p in parsed_events]
    lookup: dict[str, dict] = {}
    for home, away in games:
        h_tok, a_tok = _first_token(home), _first_token(away)
        if not h_tok or not a_tok:
            continue
        key = f"{home}|{away}"
        if key in lookup:
            continue
        for name, parsed in norm_events:
            if h_tok in name and a_tok in name:
                lookup[key] = parsed
                break
    return lookup


def _match_event_ids(games: list[tuple[str, str]], events: list[dict]) -> list[str]:
    """Associa jogos FPT a eventos Betfair via índice por token (rápido)."""
    if not games or not events:
        return []
    token_map: dict[str, list[int]] = defaultdict(list)
    norm_events: list[tuple[str, str]] = []
    for ev in events:
        eid = ev["event"]["id"]
        name = _norm(ev.get("event", {}).get("name", ""))
        idx = len(norm_events)
        norm_events.append((eid, name))
        for tok in set(name.split()):
            if len(tok) >= 3:
                token_map[tok].append(idx)

    matched_ids: list[str] = []
    seen: set[str] = set()
    for home, away in games:
        h_tok, a_tok = _first_token(home), _first_token(away)
        if not h_tok or not a_tok:
            continue
        candidates = set(token_map.get(h_tok, [])) & set(token_map.get(a_tok, []))
        for idx in candidates:
            eid, name = norm_events[idx]
            if eid in seen:
                continue
            if h_tok in name and a_tok in name:
                matched_ids.append(eid)
                seen.add(eid)
                break
    return matched_ids


def _dedupe_events(events: list[dict]) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for ev in events:
        eid = str(ev.get("event", {}).get("id", ""))
        if not eid or eid in seen:
            continue
        seen.add(eid)
        out.append(ev)
    return out


def _query_tokens(games: list[tuple[str, str]]) -> list[str]:
    tokens: list[str] = []
    seen: set[str] = set()
    for home, away in games:
        for name in (home, away):
            tok = _first_token(name)
            if len(tok) >= 3 and tok not in seen:
                seen.add(tok)
                tokens.append(tok)
    return tokens


def _collect_events_for_games(
    bf,
    games: list[tuple[str, str]],
    *,
    market_start_from: str,
    market_start_to: str,
) -> list[dict]:
    """Evita listEvents global (TOO_MUCH_DATA na Betfair BR)."""
    if not games:
        return []
    merged: dict[str, dict] = {}
    for tok in _query_tokens(games):
        try:
            batch = bf.list_events(
                "1",
                text_query=tok,
                market_start_from=market_start_from,
                market_start_to=market_start_to,
            )
        except Exception as ex:
            if "TOO_MUCH_DATA" in str(ex):
                continue
            raise
        for ev in batch:
            eid = str(ev.get("event", {}).get("id", ""))
            if eid:
                merged[eid] = ev
    return list(merged.values())


def _parsed_event_names(parsed_events: list[dict]) -> set[str]:
    return {_norm(p.get("event_name", "")) for p in parsed_events if p.get("event_name")}


def _fetch_games_fallback(bf, games: list[tuple[str, str]], existing: list[dict]) -> list[dict]:
    """Busca jogo a jogo quando o lote falha ou não casa."""
    have = _parsed_event_names(existing)
    extra: list[dict] = []
    for home, away in games:
        probe = _norm(f"{home} v {away}")
        if any(_first_token(home) in n and _first_token(away) in n for n in have):
            continue
        raw = bf.find_match_odds(home, away)
        if not raw:
            continue
        parsed = raw.get("parsed") or bf.parse_match_odds(raw["catalogue"], raw["book"])
        if parsed:
            extra.append(parsed)
            have.add(_norm(parsed.get("event_name", "")))
    return extra


def _match_names(fpt_home: str, fpt_away: str, event_name: str) -> bool:
    """Fuzzy match FPT ↔ Betfair."""
    name = _norm(event_name)
    h_tok = _first_token(fpt_home)
    a_tok = _first_token(fpt_away)
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
            selection_id=data.get("selection_id"),
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
        """Odds Betfair apenas para jogos FPT — consultas por token (evita TOO_MUCH_DATA)."""
        if not games:
            return []
        self.connect()
        today = datetime.now(BR).date()
        start = datetime(today.year, today.month, today.day, tzinfo=BR).astimezone(timezone.utc)
        end = start + timedelta(days=days_ahead + 1)
        start_iso = start.strftime("%Y-%m-%dT%H:%M:%SZ")
        end_iso = end.strftime("%Y-%m-%dT%H:%M:%SZ")

        events = _collect_events_for_games(
            self._bf,
            games,
            market_start_from=start_iso,
            market_start_to=end_iso,
        )
        matched_ids = _match_event_ids(games, events)
        out: list[dict] = []
        if matched_ids:
            out = self._bf.fetch_match_odds_batch(matched_ids)
        out.extend(_fetch_games_fallback(self._bf, games, out))
        return out

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
        lookup: dict[str, dict] | None = None,
    ) -> dict | None:
        if lookup is not None:
            hit = lookup.get(f"{home}|{away}")
            if hit is not None:
                return hit
        for parsed in betfair_events:
            if _match_names(home, away, parsed.get("event_name", "")):
                return parsed
        return None
