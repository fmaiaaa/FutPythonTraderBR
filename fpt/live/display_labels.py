"""Rótulos legíveis para mercado + lado (BACK/LAY) no dashboard."""
from __future__ import annotations

from ..markets import JOGOS_DIA_MARKETS
from .team_utils import teams_match

__all__ = [
    "format_operation",
    "find_operation_for_game",
    "find_entries_for_game",
    "market_label",
    "operation_type_label",
    "summarize_game_entries",
    "teams_match",
]

_MARKET_LABEL: dict[str, str] = {m.id: m.label for m in JOGOS_DIA_MARKETS}

# Aliases curtos para tabela
_MARKET_SHORT: dict[str, str] = {
    "home_win_ft": "Mandante",
    "draw_ft": "Empate",
    "away_win_ft": "Visitante",
    "home_win_ht": "Mandante HT",
    "draw_ht": "Empate HT",
    "away_win_ht": "Visitante HT",
}

# Espelha SCALP_ENTRY_TYPES — evita import circular com scalping_strategies
_SCALP_ALERT_TYPES = frozenset({
    "PRESSURE_STEAM",
    "SCALP_PRESSURE_STEAM",
    "SCALP_STEAM_MOMENTUM",
    "SCALP_PRESSURE_SURGE",
    "SCALP_XG_SPIKE",
    "SCALP_DOMINANCE",
    "SCALP_FADE_STEAM",
})


def market_label(market_id: str | None) -> str:
    if not market_id:
        return "—"
    mid = str(market_id).strip()
    if not mid or mid.lower() == "nan":
        return "—"
    return _MARKET_SHORT.get(mid) or _MARKET_LABEL.get(mid) or mid.replace("_", " ").upper()


def operation_type_label(
    alert_type: str | None = None,
    *,
    entry_type: str | None = None,
) -> str:
    """Pré-live vs scalping (e paper) para colunas do dashboard."""
    raw = (entry_type or alert_type or "").strip()
    low = raw.lower()
    if low == "scalp" or low.startswith("scalp"):
        return "Scalping"
    if low in ("pre_live", "pre-live", "enter"):
        return "Pré-live"
    if low == "paper":
        return "Paper"
    if raw in _SCALP_ALERT_TYPES or raw.upper().startswith("SCALP_"):
        return "Scalping"
    if raw.upper() == "ENTER":
        return "Pré-live"
    return "—"


def find_operation_for_game(
    home: str,
    away: str,
    positions: list[dict],
) -> str:
    for p in positions:
        if teams_match(home, away, p["home"], p["away"]):
            return p["operation"]
    return "—"


def find_entries_for_game(
    home: str,
    away: str,
    positions: list[dict],
) -> list[dict]:
    return [p for p in positions if teams_match(home, away, p["home"], p["away"])]


def _join_unique(values: list[str]) -> str:
    seen: list[str] = []
    for v in values:
        v = (v or "—").strip() or "—"
        if v not in seen:
            seen.append(v)
    return " | ".join(seen) if seen else "—"


def summarize_game_entries(
    home: str,
    away: str,
    positions: list[dict],
) -> dict[str, str]:
    """Operação, mercado e modo (Pré-live/Scalping) para um jogo."""
    matches = find_entries_for_game(home, away, positions)
    if not matches:
        return {"operacao": "—", "mercado": "—", "modo": "—", "lado": "—"}
    return {
        "operacao": _join_unique([p.get("operation", "—") for p in matches]),
        "mercado": _join_unique([p.get("market", "—") for p in matches]),
        "modo": _join_unique([p.get("modo", "—") for p in matches]),
        "lado": _join_unique([p.get("side", "—") for p in matches]),
    }


def format_operation(
    side: str | None,
    market: str | None,
    *,
    alert_type: str | None = None,
) -> str:
    """Ex.: LAY Visitante, BACK Under 2.5 FT, BACK Empate FT."""
    s = (side or "").strip().upper()
    if s not in ("BACK", "LAY"):
        s = ""
    mkt = market_label(market)
    if s and mkt != "—":
        op = f"{s} {mkt}"
    elif s:
        op = s
    elif mkt != "—":
        op = mkt
    else:
        op = "—"
    if alert_type and alert_type not in ("ENTER", "—", ""):
        op = f"{op} ({alert_type})"
    return op
