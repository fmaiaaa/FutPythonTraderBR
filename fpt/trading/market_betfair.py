from __future__ import annotations

"""
Integração Betfair — STUB para quando você tiver API Key.

Como obter acesso:
1. Crie conta em https://www.betfair.com/br/ (ou .com)
2. Registre app em https://developer.betfair.com/
   - App Key "Delayed" (grátis, odds com delay) ou "Live" (requer aprovação)
3. Gere certificado SSL (.crt + .key) para login não-interativo
4. pip install betfairlightweight

Variáveis .env:
  BETFAIR_USERNAME=
  BETFAIR_PASSWORD=
  BETFAIR_APP_KEY=
  BETFAIR_CERT_PATH=  # pasta com client-2048.crt e client-2048.key

Documentação: https://docs.developer.betfair.com/
Mercados BR: liquidez menor que PL — testar com listMarketCatalogue filtrando competition BR.
"""

import os
from pathlib import Path

from .market_sim import MarketOdds, MarketProvider


class BetfairMarket(MarketProvider):
    def __init__(self):
        self.username = os.environ.get("BETFAIR_USERNAME", "")
        self.password = os.environ.get("BETFAIR_PASSWORD", "")
        self.app_key = os.environ.get("BETFAIR_APP_KEY", "")
        self.cert_path = os.environ.get("BETFAIR_CERT_PATH", "")
        self._client = None

    @property
    def configured(self) -> bool:
        return bool(self.username and self.password and self.app_key and self.cert_path)

    def connect(self):
        if not self.configured:
            raise RuntimeError(
                "Betfair não configurada. Preencha BETFAIR_* no .env — veja fpt/trading/market_betfair.py"
            )
        try:
            from betfairlightweight import APIClient
        except ImportError as e:
            raise ImportError("pip install betfairlightweight") from e

        cert_dir = Path(self.cert_path)
        self._client = APIClient(
            self.username,
            self.password,
            app_key=self.app_key,
            certs=str(cert_dir),
        )
        self._client.login()
        return self._client

    def get_odds(self, home: str, away: str, **kwargs) -> MarketOdds:
        if self._client is None:
            self.connect()
        # TODO: listar mercado Match Odds, buscar runner por nome do time
        raise NotImplementedError(
            "Betfair live ainda não implementado. Use modo simulação (FPT odds) por enquanto."
        )

    def list_brazil_competitions(self) -> list[dict]:
        """Helper futuro — listar competições BR na exchange."""
        if self._client is None:
            self.connect()
        return self._client.betting.list_event_types(filter={"textQuery": "Brazil"})  # type: ignore
