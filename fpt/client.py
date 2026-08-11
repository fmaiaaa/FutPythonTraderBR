from __future__ import annotations

import os
from pathlib import Path

from .paths import ENV_PATH, ROOT, data_root, ensure_data_dirs

DATA = data_root()
ensure_data_dirs()

BASE_URL = "https://futpythontrader.com.br/api/download"
JOGOS_URL = "https://futpythontrader.com.br/api/jogos-do-dia"


def load_api_key() -> str:
    key = os.environ.get("FPT_API_KEY", "")
    if not key and ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("FPT_API_KEY=") and not line.endswith("="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
                break
    if not key or key == "COLE_SUA_API_KEY_AQUI":
        raise ValueError(
            "Configure FPT_API_KEY em .env — pegue no dashboard após login: "
            "https://futpythontrader.com.br/dashboard"
        )
    return key


def download_url(country: str, league: str, season: str, api_key: str | None = None) -> str:
    key = api_key or load_api_key()
    return f"{BASE_URL}/{country}/{league}/{season}?api_key={key}"


def jogos_do_dia_url(day: str, api_key: str | None = None, fmt: str = "csv") -> str:
    key = api_key or load_api_key()
    return f"{JOGOS_URL}?date={day}&format={fmt}&api_key={key}"
