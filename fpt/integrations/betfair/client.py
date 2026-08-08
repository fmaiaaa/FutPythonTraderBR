"""
Cliente Betfair BR — login por certificado + JSON-RPC.

Baseado em: https://github.com/AraujoDavies/api-betfair-tutorial
Endpoints regulamentados: identitysso-cert.betfair.bet.br / api.betfair.bet.br
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import requests

from ...client import ENV_PATH

# URLs Betfair Brasil (pós-regulamentação)
LOGIN_URL = "https://identitysso-cert.betfair.bet.br/api/certlogin"
API_URL = "https://api.betfair.bet.br/exchange/betting/json-rpc/v1"

_client: "BetfairClient | None" = None


def _load_env(name: str) -> str:
    val = os.environ.get(name, "")
    if val or not ENV_PATH.exists():
        return val
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(f"{name}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


@dataclass
class BetfairConfig:
    username: str
    password: str
    app_key: str
    cert_dir: Path
    cert_file: str = "client-2048.crt"
    key_file: str = "client-2048.key"

    @classmethod
    def from_env(cls) -> "BetfairConfig":
        cert_path = _load_env("BETFAIR_CERT_PATH") or str(Path(__file__).resolve().parents[3] / "certs")
        return cls(
            username=_load_env("BETFAIR_USERNAME") or _load_env("EMAIL"),
            password=_load_env("BETFAIR_PASSWORD") or _load_env("SENHA"),
            app_key=_load_env("BETFAIR_APP_KEY") or _load_env("APP_KEY"),
            cert_dir=Path(cert_path),
        )

    @property
    def configured(self) -> bool:
        if not all([self.username, self.password, self.app_key]):
            return False
        return (self.cert_dir / self.cert_file).exists() and (self.cert_dir / self.key_file).exists()

    @property
    def cert_tuple(self) -> tuple[str, str]:
        return (
            str(self.cert_dir / self.cert_file),
            str(self.cert_dir / self.key_file),
        )


class BetfairClient:
    def __init__(self, config: BetfairConfig | None = None):
        self.config = config or BetfairConfig.from_env()
        self._session_token: str | None = None

    @property
    def configured(self) -> bool:
        return self.config.configured

    def login(self, force: bool = False) -> str:
        if self._session_token and not force:
            return self._session_token
        if not self.configured:
            raise RuntimeError(
                "Betfair nao configurada. Preencha BETFAIR_USERNAME, BETFAIR_PASSWORD, "
                "BETFAIR_APP_KEY no .env e coloque client-2048.crt/.key em certs/"
            )
        payload = f"username={self.config.username}&password={self.config.password}"
        headers = {
            "X-Application": self.config.app_key,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        resp = requests.post(
            LOGIN_URL,
            data=payload,
            cert=self.config.cert_tuple,
            headers=headers,
            timeout=30,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Betfair login falhou HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        status = data.get("loginStatus", "")
        if status != "SUCCESS":
            raise RuntimeError(f"Betfair loginStatus={status}")
        self._session_token = data["sessionToken"]
        return self._session_token

    def call(self, method: str, params: dict, req_id: int = 1) -> dict:
        """Chamada JSON-RPC Sports API."""
        token = self.login()
        body = json.dumps({
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": req_id,
        })
        headers = {
            "X-Application": self.config.app_key,
            "X-Authentication": token,
            "Content-Type": "application/json",
        }
        req = urllib.request.Request(API_URL, body.encode("utf-8"), headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as ex:
            raise RuntimeError(f"Betfair API HTTP {ex.code}: {ex.read().decode('utf-8', errors='replace')[:300]}") from ex
        if "error" in raw:
            raise RuntimeError(f"Betfair API error: {raw['error']}")
        return raw.get("result", raw)

    # --- Helpers ---

    def list_event_types(self) -> list[dict]:
        return self.call("SportsAPING/v1.0/listEventTypes", {"filter": {}})

    def list_events(
        self,
        event_type_id: str = "1",
        text_query: str = "",
        competition_ids: list[str] | None = None,
        market_start_from: str | None = None,
        market_start_to: str | None = None,
    ) -> list[dict]:
        filt: dict = {"eventTypeIds": [event_type_id]}
        if text_query:
            filt["textQuery"] = text_query
        if competition_ids:
            filt["competitionIds"] = competition_ids
        if market_start_from or market_start_to:
            filt["marketStartTime"] = {}
            if market_start_from:
                filt["marketStartTime"]["from"] = market_start_from
            if market_start_to:
                filt["marketStartTime"]["to"] = market_start_to
        return self.call("SportsAPING/v1.0/listEvents", {"filter": filt})

    def list_market_catalogue(
        self,
        event_ids: list[str] | None = None,
        market_type: str = "MATCH_ODDS",
        max_results: int = 50,
    ) -> list[dict]:
        filt: dict = {"marketTypeCodes": [market_type]}
        if event_ids:
            filt["eventIds"] = event_ids
        return self.call(
            "SportsAPING/v1.0/listMarketCatalogue",
            {
                "filter": filt,
                "maxResults": str(max_results),
                "marketProjection": ["RUNNER_DESCRIPTION", "EVENT", "MARKET_START_TIME"],
            },
        )

    def list_market_book(self, market_ids: list[str]) -> list[dict]:
        if not market_ids:
            return []
        return self.call(
            "SportsAPING/v1.0/listMarketBook",
            {"marketIds": market_ids, "priceProjection": {"priceData": ["EX_BEST_OFFERS"]}},
        )

    def list_scores(self, market_ids: list[str]) -> list[dict]:
        if not market_ids:
            return []
        return self.call("SportsAPING/v1.0/listScores", {"marketIds": market_ids})

    @staticmethod
    def best_back_lay(runner: dict) -> tuple[float | None, float | None, float | None, float | None]:
        ex = runner.get("ex", {})
        backs = ex.get("availableToBack", [])
        lays = ex.get("availableToLay", [])
        bb = backs[0]["price"] if backs else None
        bs = backs[0].get("size") if backs else None
        bl = lays[0]["price"] if lays else None
        ls = lays[0].get("size") if lays else None
        return bb, bl, bs, ls

    @staticmethod
    def runner_side_key(event_name: str, runner_name: str) -> str:
        lname = runner_name.lower()
        if "draw" in lname or lname == "the draw":
            return "draw"
        if " v " in event_name:
            home, away = [p.strip() for p in event_name.split(" v ", 1)]
            if runner_name == home or home.lower() in lname:
                return "home"
            if runner_name == away or away.lower() in lname:
                return "away"
        return runner_name.lower().replace(" ", "_")

    def parse_match_odds(self, catalogue: dict, book: dict, score: dict | None = None) -> dict:
        """Normaliza catálogo + book + score em estrutura interna."""
        event = catalogue.get("event", {})
        event_name = event.get("name", "")
        runners_by_id = {r["selectionId"]: r for r in book.get("runners", [])}
        sides: dict[str, dict] = {}
        for runner in catalogue.get("runners", []):
            sid = runner["selectionId"]
            rb = runners_by_id.get(sid, {})
            bb, bl, bs, ls = self.best_back_lay(rb)
            key = self.runner_side_key(event_name, runner.get("runnerName", ""))
            sides[key] = {
                "runner": runner.get("runnerName"),
                "selection_id": sid,
                "back": bb,
                "lay": bl,
                "back_size": bs,
                "lay_size": ls,
                "status": rb.get("status"),
            }
        out = {
            "event_id": event.get("id"),
            "event_name": event_name,
            "market_id": catalogue.get("marketId"),
            "market_name": catalogue.get("marketName"),
            "open_date": event.get("openDate"),
            "in_play": book.get("inplay", False),
            "status": book.get("status"),
            "total_matched": book.get("totalMatched"),
            "sides": sides,
        }
        if score:
            sc = score.get("score", {})
            out["score_home"] = sc.get("home", {}).get("score")
            out["score_away"] = sc.get("away", {}).get("score")
            out["elapsed_min"] = score.get("timeElapsed")
        return out

    def place_orders(
        self,
        market_id: str,
        instructions: list[dict],
        customer_ref: str | None = None,
    ) -> dict:
        """Envia ordens LIMIT (BACK/LAY) via Sports API."""
        if not market_id or not instructions:
            raise ValueError("market_id e instructions obrigatórios")
        params: dict = {
            "marketId": market_id,
            "instructions": instructions,
        }
        if customer_ref:
            params["customerRef"] = customer_ref[:32]
        return self.call("SportsAPING/v1.0/placeOrders", params)

    @staticmethod
    def build_limit_instruction(
        selection_id: int,
        side: str,
        size: float,
        price: float,
        persistence: str = "LAPSE",
    ) -> dict:
        return {
            "selectionId": int(selection_id),
            "handicap": 0,
            "side": side.upper(),
            "orderType": "LIMIT",
            "limitOrder": {
                "size": round(float(size), 2),
                "price": round(float(price), 2),
                "persistenceType": persistence,
            },
        }

    def fetch_match_odds_batch(self, event_ids: list[str]) -> list[dict]:
        """Match Odds + book + placar para vários eventos."""
        if not event_ids:
            return []
        cats = self.list_market_catalogue(event_ids, "MATCH_ODDS", max(len(event_ids) * 2, 10))
        if not cats:
            return []
        market_ids = [c["marketId"] for c in cats]
        books = {b["marketId"]: b for b in self.list_market_book(market_ids)}
        scores = {s["marketId"]: s for s in self.list_scores(market_ids)}
        out = []
        for cat in cats:
            mid = cat["marketId"]
            book = books.get(mid)
            if not book:
                continue
            out.append(self.parse_match_odds(cat, book, scores.get(mid)))
        return out

    def find_match_odds(self, home: str, away: str) -> dict | None:
        """Busca mercado Match Odds por nomes aproximados dos times."""
        home_l, away_l = home.lower(), away.lower()
        events = self.list_events("1", text_query=home.split()[0] if home else "")
        for ev in events:
            name = ev.get("event", {}).get("name", "").lower()
            if home_l[:4] in name and away_l[:4] in name:
                eid = ev["event"]["id"]
                cats = self.list_market_catalogue([eid], "MATCH_ODDS", 5)
                if not cats:
                    continue
                market_id = cats[0]["marketId"]
                books = self.list_market_book([market_id])
                if books:
                    scores = self.list_scores([market_id])
                    sc = scores[0] if scores else None
                    return {
                        "catalogue": cats[0],
                        "book": books[0],
                        "parsed": self.parse_match_odds(cats[0], books[0], sc),
                    }
        return None


def get_betfair_client() -> BetfairClient:
    global _client
    if _client is None:
        _client = BetfairClient()
    return _client
