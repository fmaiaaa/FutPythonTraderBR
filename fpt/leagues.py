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

# Ordem no PDF: BR → Libertadores → Sul-Americana → top europeias
LEAGUE_SORT_ORDER: dict[str, int] = {
    "Brasileirão Série A": 1,
    "Brasileirão Série B": 2,
    "Copa do Brasil": 3,
    "Copa Libertadores": 10,
    "Copa Sudamericana": 11,
    "Champions League": 12,
    "Premier League": 20,
    "LaLiga": 21,
    "Serie A Itália": 22,
    "Bundesliga": 23,
    "Ligue 1": 24,
    "Eredivisie": 25,
    "Liga Portugal": 26,
    "Liga Argentina": 27,
}


def league_sort_key(league_label: str, time_str: str = "", date_str: str = "") -> tuple:
    order = LEAGUE_SORT_ORDER.get(league_label, 99)
    return (order, date_str or "", str(time_str or ""))


# Cores oficiais / caracteristicas por campeonato (PDF e destaques)
LEAGUE_THEME: dict[str, dict[str, str]] = {
    "Brasileirão Série A": {"primary": "#009739", "secondary": "#FFDF00", "accent": "#002776", "dark": "#004D25"},
    "Brasileirão Série B": {"primary": "#006B2A", "secondary": "#C8E6C9", "accent": "#1B5E20", "dark": "#003D16"},
    "Copa do Brasil": {"primary": "#FFDF00", "secondary": "#009739", "accent": "#002776", "dark": "#B8860B"},
    "Copa Libertadores": {"primary": "#C9A227", "secondary": "#003087", "accent": "#FFFFFF", "dark": "#8B6914"},
    "Copa Sudamericana": {"primary": "#003087", "secondary": "#00A3E0", "accent": "#C9A227", "dark": "#001F54"},
    "Champions League": {"primary": "#0E1E5B", "secondary": "#8B5CF6", "accent": "#00D4FF", "dark": "#060E2E"},
    "Premier League": {"primary": "#3D195B", "secondary": "#00FF85", "accent": "#FFFFFF", "dark": "#240E38"},
    "LaLiga": {"primary": "#EE324E", "secondary": "#FFB500", "accent": "#1A1A2E", "dark": "#B8183A"},
    "Serie A Itália": {"primary": "#008FD7", "secondary": "#FFFFFF", "accent": "#003366", "dark": "#006299"},
    "Bundesliga": {"primary": "#D20515", "secondary": "#FFFFFF", "accent": "#1A1A1A", "dark": "#9B0410"},
    "Ligue 1": {"primary": "#091C3E", "secondary": "#DAFF00", "accent": "#FFFFFF", "dark": "#050E22"},
    "Eredivisie": {"primary": "#E03228", "secondary": "#FFFFFF", "accent": "#1A237E", "dark": "#A8241C"},
    "Liga Portugal": {"primary": "#006600", "secondary": "#FF0000", "accent": "#FFD700", "dark": "#004400"},
    "Liga Argentina": {"primary": "#75AADB", "secondary": "#FFFFFF", "accent": "#003087", "dark": "#4A86AC"},
}

DEFAULT_THEME = {"primary": "#37474F", "secondary": "#78909C", "accent": "#1565C0", "dark": "#263238"}


def league_theme(league_label: str) -> dict[str, str]:
    return LEAGUE_THEME.get(league_label or "", DEFAULT_THEME.copy())


def league_file_slug(league_label: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", league_label or "liga")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_").lower()
    return s or "liga"


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
