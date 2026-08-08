"""
The Odds API — odds live multi-casa (complemento ao FPT).

UTILIDADE vs FPT:
- FPT: historico profundo, xG, stats, 70+ mercados por jogo PASSADO, jogos-do-dia FPT
- The Odds API: odds ATUAIS de varias casas (Pinnacle, Bet365...) para VALIDAR preco live
- Incremento util: SIM — consenso multi-book e linhas sharp para calibrar entrada
- NAO substitui: stats, xG, agenda, backtest historico (FPT e superior)

Plano free: ~500 creditos/mes. 1 request odds = 1 credito por regiao/mercado.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import requests

from ..client import DATA, ENV_PATH

BASE = "https://api.the-odds-api.com/v4"
USAGE_PATH = DATA / "the_odds_usage.json"

# Prioridade ligas BR + europeias top (para contexto adversarios)
SPORT_PRIORITY = [
    "soccer_brazil_campeonato",
    "soccer_brazil_serie_b",
    "soccer_epl",
    "soccer_spain_la_liga",
    "soccer_italy_serie_a",
    "soccer_germany_bundesliga",
    "soccer_france_ligue_one",
    "soccer_uefa_champs_league",
    "soccer_conmebol_copa_libertadores",
]


@dataclass
class OddsApiEvent:
    event_id: str
    home: str
    away: str
    commence: str
    sport: str
    bookmaker: str
    market: str
    outcomes: dict[str, float]


def load_key() -> str:
    key = os.environ.get("THE_ODDS_API_KEY", "")
    if not key and ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            if line.startswith("THE_ODDS_API_KEY=") and "=" in line[17:]:
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
                break
    return key


def _load_usage() -> dict:
    if USAGE_PATH.exists():
        return json.loads(USAGE_PATH.read_text(encoding="utf-8"))
    return {"month": datetime.now().strftime("%Y-%m"), "used": 0, "log": []}


def _save_usage(used: int, endpoint: str):
    u = _load_usage()
    month = datetime.now().strftime("%Y-%m")
    if u.get("month") != month:
        u = {"month": month, "used": 0, "log": []}
    u["used"] = u.get("used", 0) + used
    u["log"] = (u.get("log", []) + [{"ts": datetime.now().isoformat(), "ep": endpoint, "cost": used}])[-200:]
    USAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    USAGE_PATH.write_text(json.dumps(u, indent=2), encoding="utf-8")


def remaining_budget(monthly: int = 500) -> int:
    u = _load_usage()
    if u.get("month") != datetime.now().strftime("%Y-%m"):
        return monthly
    return max(0, monthly - u.get("used", 0))


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _team_match(a: str, b: str) -> bool:
    na, nb = _norm(a), _norm(b)
    return na in nb or nb in na or na[:6] == nb[:6]


class TheOddsApiClient:
    def __init__(self, monthly_budget: int = 500):
        self.key = load_key()
        self.budget = monthly_budget
        self._cache: dict[str, list[dict]] = {}

    @property
    def enabled(self) -> bool:
        return bool(self.key)

    def _get(self, path: str, params: dict | None = None) -> tuple[dict | list, dict]:
        if not self.enabled:
            return [], {}
        if remaining_budget(self.budget) <= 0:
            print("The Odds API: budget mensal esgotado")
            return [], {}
        params = dict(params or {})
        params["apiKey"] = self.key
        r = requests.get(f"{BASE}{path}", params=params, timeout=30)
        headers = {k.lower(): v for k, v in r.headers.items()}
        cost = int(headers.get("x-requests-last", 1))
        _save_usage(cost, path)
        r.raise_for_status()
        return r.json(), headers

    def fetch_sport_odds(
        self,
        sport: str,
        regions: str = "eu,uk",
        markets: str = "h2h,totals",
    ) -> list[dict]:
        cache_key = f"{sport}|{regions}|{markets}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        data, _ = self._get(
            f"/sports/{sport}/odds",
            {"regions": regions, "markets": markets, "oddsFormat": "decimal"},
        )
        if isinstance(data, list):
            self._cache[cache_key] = data
            return data
        return []

    def match_event(self, home: str, away: str, events: list[dict]) -> dict | None:
        for ev in events:
            if _team_match(home, ev.get("home_team", "")) and _team_match(away, ev.get("away_team", "")):
                return ev
        return None

    def best_h2h(self, event: dict, prefer: str = "pinnacle") -> dict[str, float]:
        out: dict[str, float] = {}
        for bm in event.get("bookmakers", []):
            if prefer and bm.get("key") != prefer and out:
                continue
            for mk in bm.get("markets", []):
                if mk.get("key") != "h2h":
                    continue
                for o in mk.get("outcomes", []):
                    name = o.get("name", "")
                    price = float(o.get("price", 0))
                    if price > 1.01:
                        if name == event.get("home_team"):
                            out["home"] = price
                        elif name == event.get("away_team"):
                            out["away"] = price
                        elif name.lower() == "draw":
                            out["draw"] = price
        return out


def prioritize_weekend_games(calendar: "pd.DataFrame", hist: "pd.DataFrame") -> list[dict]:
    """
    Ordena jogos do fim de semana por prioridade para gastar creditos The Odds API.
    1. BR Serie A/B/C/D + Copa
    2. Times com agenda cruzada (2+ jogos em 14d no historico)
    3. Demais BR
    4. Libertadores/Sul-Americana
    5. Top ligas europeias envolvidas
    """
    import pandas as pd
    from ..features.schedule import build_team_calendar, schedule_context

    if calendar.empty:
        return []

    calendars = build_team_calendar(hist) if not hist.empty else {}
    rows = []
    for _, r in calendar.iterrows():
        league = str(r.get("League", ""))
        score = 0
        if re.search(r"brazil|brasil", league, re.I):
            score += 100
        if re.search(r"serie a|serie b", league, re.I):
            score += 50
        if re.search(r"libertadores|sudamericana|copa do brasil", league, re.I):
            score += 40
        dt = pd.to_datetime(r["Date"])
        ctx = schedule_context(calendars, r["Home"], r["Away"], dt)
        if ctx.home_cross_comp_4d or ctx.away_cross_comp_4d:
            score += 30
        if ctx.home_games_14d >= 4 or ctx.away_games_14d >= 4:
            score += 20
        if r.get("weekday") in ("Saturday", "Sunday"):
            score += 10
        rows.append({
            "home": r["Home"], "away": r["Away"], "date": str(r["Date"])[:10],
            "league": league, "priority": score,
        })
    rows.sort(key=lambda x: -x["priority"])
    return rows


def enrich_calendar_with_odds_api(
    calendar: "pd.DataFrame",
    hist: "pd.DataFrame",
    monthly_budget: int = 500,
    max_events: int | None = None,
) -> "pd.DataFrame":
    """Enriquece calendario com odds The Odds API (prioridade fim de semana BR)."""
    import pandas as pd

    client = TheOddsApiClient(monthly_budget)
    if not client.enabled:
        print("THE_ODDS_API_KEY nao configurada — usando apenas odds FPT")
        return calendar

    prioritized = prioritize_weekend_games(calendar, hist)
    if max_events is None:
        max_events = min(len(prioritized), remaining_budget(monthly_budget))

    # buscar odds por esporte (batch) — economiza requests
    sport_events: dict[str, list] = {}
    for sport in SPORT_PRIORITY:
        if remaining_budget(monthly_budget) <= 0:
            break
        sport_events[sport] = client.fetch_sport_odds(sport)

    out = calendar.copy()
    out["odds_api_home"] = None
    out["odds_api_draw"] = None
    out["odds_api_away"] = None
    out["odds_api_book"] = None

    matched = 0
    for item in prioritized[:max_events]:
        if matched >= max_events:
            break
        for sport, events in sport_events.items():
            ev = client.match_event(item["home"], item["away"], events)
            if not ev:
                continue
            h2h = client.best_h2h(ev)
            if not h2h:
                continue
            mask = (out["Home"] == item["home"]) & (out["Away"] == item["away"])
            out.loc[mask, "odds_api_home"] = h2h.get("home")
            out.loc[mask, "odds_api_draw"] = h2h.get("draw")
            out.loc[mask, "odds_api_away"] = h2h.get("away")
            out.loc[mask, "odds_api_book"] = "pinnacle/eu"
            matched += 1
            break

    print(f"The Odds API: {matched} jogos enriquecidos | creditos restantes ~{remaining_budget(monthly_budget)}")
    cache_path = DATA / "calendar" / "odds_api_enriched.parquet"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(cache_path, index=False)
    return out
