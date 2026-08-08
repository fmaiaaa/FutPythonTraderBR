# Campeonatos e ligas monitoradas
# Fonte FPT jogos-do-dia: coluna "League" (ex: BRAZIL 1, ENGLAND 1)

from __future__ import annotations

import re

BRAZIL_MALE_LEAGUES = {
    "serie-a-betano": {
        "name": "Brasileirão Série A",
        "seasons": ["2026", "2025", "2024", "2023", "2022", "2021"],
    },
    "serie-b": {
        "name": "Brasileirão Série B",
        "seasons": ["2026", "2025", "2024", "2023", "2022", "2021"],
    },
    "copa-betano-do-brasil": {
        "name": "Copa do Brasil",
        "seasons": ["2026", "2025", "2024", "2023", "2022", "2021"],
    },
}

COUNTRY = "brazil"

# Watchlist — liga principal por país + BR B + copas + Champions
WATCHLIST_CATALOG: list[tuple[str, str, str]] = [
    ("brazil", "serie-a-betano", "Brasileirão Série A"),
    ("brazil", "serie-b", "Brasileirão Série B"),
    ("brazil", "copa-betano-do-brasil", "Copa do Brasil"),
    ("south-america", "copa-libertadores", "Copa Libertadores"),
    ("south-america", "copa-sudamericana", "Copa Sudamericana"),
    ("europe", "champions-league", "Champions League"),
    ("spain", "laliga", "LaLiga"),
    ("italy", "serie-a", "Serie A Itália"),
    ("netherlands", "eredivisie", "Eredivisie"),
    ("germany", "bundesliga", "Bundesliga"),
    ("france", "ligue-1", "Ligue 1"),
    ("portugal", "liga-portugal", "Liga Portugal"),
    ("england", "premier-league", "Premier League"),
    ("argentina", "torneo-betano", "Liga Argentina"),
]

WATCHLIST_LEAGUE_PATTERNS: list[tuple[str, str]] = [
    ("Brasileirão Série A", r"^BRAZIL\s+1$"),
    ("Brasileirão Série B", r"^BRAZIL\s+2$"),
    ("Copa do Brasil", r"^BRAZIL\s+CUP$|COPA\s+DO\s+BRASIL"),
    ("Copa Libertadores", r"LIBERTAD"),
    ("Copa Sudamericana", r"SUDAMER"),
    ("Champions League", r"CHAMPIONS\s+LEAGUE|CHAMPIONS\s+LEAGUE"),
    ("LaLiga", r"^SPAIN\s+1$"),
    ("Serie A Itália", r"^ITALY\s+1$"),
    ("Eredivisie", r"^NETHERLANDS\s+1$"),
    ("Bundesliga", r"^GERMANY\s+1$"),
    ("Ligue 1", r"^FRANCE\s+1$"),
    ("Liga Portugal", r"^PORTUGAL\s+1$"),
    ("Premier League", r"^ENGLAND\s+1$"),
    ("Liga Argentina", r"^ARGENTINA\s+1$"),
]

_COMPILED = [(label, re.compile(pat, re.I)) for label, pat in WATCHLIST_LEAGUE_PATTERNS]


def is_watchlist_league(league: str) -> bool:
    if not league or str(league).lower() in ("nan", "none"):
        return False
    s = str(league).strip()
    if re.search(r"women|wom\b|\bW\b\s*$", s, re.I):
        return False
    return any(rx.search(s) for _, rx in _COMPILED)


def watchlist_label(league: str) -> str | None:
    s = str(league).strip()
    for label, rx in _COMPILED:
        if rx.search(s):
            return label
    return None


def filter_watchlist(df):
    """Filtra DataFrame de jogos para ligas da watchlist."""
    if df.empty or "League" not in df.columns:
        return df
    mask = df["League"].astype(str).map(is_watchlist_league)
    out = df[mask].copy()
    if not out.empty:
        out["watchlist_league"] = out["League"].astype(str).map(watchlist_label)
    return out
