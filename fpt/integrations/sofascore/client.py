from __future__ import annotations

import secrets
import time
from datetime import date
from typing import Any

from .models import SofaScoreEvent

try:
    from curl_cffi import requests as _http
    _HAS_CURL_CFFI = True
except ImportError:  # pragma: no cover
    import requests as _http  # type: ignore
    _HAS_CURL_CFFI = False


class SofaScoreError(RuntimeError):
    pass


class SofaScoreClient:
    """Cliente HTTP para API não oficial do SofaScore.

    Requer `curl_cffi` para contornar TLS fingerprinting (403 challenge).
    Documentação comunitária: apdmatos/sofascore-api, pseudo-r/Public-Sofascore-API.
    """

    BASE = "https://api.sofascore.com/api/v1"

    def __init__(
        self,
        timeout: float = 15.0,
        retries: int = 3,
        retry_delay: float = 1.5,
        impersonate: str = "chrome120",
        min_interval: float = 0.35,
    ):
        self.timeout = timeout
        self.retries = retries
        self.retry_delay = retry_delay
        self.impersonate = impersonate
        self.min_interval = min_interval
        self._last_request = 0.0
        self._xhr_token = secrets.token_hex(8)

    @property
    def transport(self) -> str:
        return "curl_cffi" if _HAS_CURL_CFFI else "requests"

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
            "Referer": "https://www.sofascore.com/",
            "Origin": "https://www.sofascore.com",
            "X-Requested-With": self._xhr_token,
        }

    def _throttle(self) -> None:
        elapsed = time.time() - self._last_request
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)

    def get_json(self, path: str) -> dict[str, Any]:
        url = path if path.startswith("http") else f"{self.BASE}{path}"
        last_err: Exception | None = None
        delay = self.retry_delay

        for attempt in range(self.retries):
            self._throttle()
            try:
                kwargs: dict[str, Any] = {
                    "headers": self._headers(),
                    "timeout": self.timeout,
                }
                if _HAS_CURL_CFFI:
                    kwargs["impersonate"] = self.impersonate
                resp = _http.get(url, **kwargs)
                self._last_request = time.time()

                if resp.status_code == 403:
                    body = (resp.text or "")[:200]
                    hint = (
                        "Instale curl_cffi: pip install curl_cffi"
                        if not _HAS_CURL_CFFI
                        else "IP pode estar bloqueado — tente proxy residencial"
                    )
                    raise SofaScoreError(f"403 Forbidden ({hint}): {body}")

                resp.raise_for_status()
                return resp.json()
            except SofaScoreError:
                raise
            except Exception as ex:
                last_err = ex
                if attempt + 1 < self.retries:
                    time.sleep(delay)
                    delay *= 1.8
        raise SofaScoreError(f"Falha ao consultar SofaScore: {last_err}")

    def scheduled_events(self, day: date | str) -> list[SofaScoreEvent]:
        d = day.isoformat() if isinstance(day, date) else str(day)
        payload = self.get_json(f"/sport/football/scheduled-events/{d}")
        return [SofaScoreEvent.from_api(e) for e in payload.get("events") or []]

    def live_events(self) -> list[SofaScoreEvent]:
        payload = self.get_json("/sport/football/events/live")
        return [SofaScoreEvent.from_api(e) for e in payload.get("events") or []]

    def event(self, event_id: int) -> dict[str, Any]:
        return self.get_json(f"/event/{event_id}")

    def statistics(self, event_id: int) -> dict[str, Any]:
        return self.get_json(f"/event/{event_id}/statistics")

    def graph(self, event_id: int) -> dict[str, Any]:
        return self.get_json(f"/event/{event_id}/graph")

    def incidents(self, event_id: int) -> dict[str, Any]:
        return self.get_json(f"/event/{event_id}/incidents")

    def lineups(self, event_id: int) -> dict[str, Any]:
        return self.get_json(f"/event/{event_id}/lineups")

    def shotmap(self, event_id: int) -> dict[str, Any]:
        return self.get_json(f"/event/{event_id}/shotmap")

    def average_positions(self, event_id: int) -> dict[str, Any]:
        return self.get_json(f"/event/{event_id}/average-positions")
