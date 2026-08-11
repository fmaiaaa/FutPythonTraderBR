"""Limite de exposição correlacionada por jogo — evita entradas análogas.

Mesma tese em mercados diferentes (ex.: BACK mandante + LAY visitante, ou
vários unders) conta como uma exposição só.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..markets import JOGOS_DIA_MARKETS
from .team_utils import teams_match

# (side, market_id) → grupo de correlação
_CORRELATION_GROUPS: dict[str, frozenset[tuple[str, str]]] = {
    "favor_home": frozenset({
        ("BACK", "home_win_ft"),
        ("BACK", "home_win_ht"),
        ("LAY", "away_win_ft"),
        ("LAY", "away_win_ht"),
        ("BACK", "dc_1x"),
    }),
    "favor_away": frozenset({
        ("BACK", "away_win_ft"),
        ("BACK", "away_win_ht"),
        ("LAY", "home_win_ft"),
        ("LAY", "home_win_ht"),
        ("BACK", "dc_x2"),
    }),
    "favor_draw": frozenset({
        ("BACK", "draw_ft"),
        ("BACK", "draw_ht"),
    }),
    "low_goals": frozenset(
        {("BACK", m.id) for m in JOGOS_DIA_MARKETS if m.id.startswith("under")}
        | {("LAY", m.id) for m in JOGOS_DIA_MARKETS if m.id.startswith("over")}
    ),
    "high_goals": frozenset(
        {("BACK", m.id) for m in JOGOS_DIA_MARKETS if m.id.startswith("over")}
        | {("LAY", m.id) for m in JOGOS_DIA_MARKETS if m.id.startswith("under")}
    ),
    "btts_yes": frozenset({("BACK", "btts_yes")}),
    "btts_no": frozenset({("BACK", "btts_no"), ("LAY", "btts_yes")}),
}

_CONFLICTING_GROUP_PAIRS: frozenset[tuple[str, str]] = frozenset({
    ("favor_home", "favor_away"),
    ("favor_draw", "favor_home"),
    ("favor_draw", "favor_away"),
    ("low_goals", "high_goals"),
    ("btts_yes", "btts_no"),
})

_SIDE_MARKET_TO_GROUP: dict[tuple[str, str], str] = {}
for _gid, _members in _CORRELATION_GROUPS.items():
    for _pair in _members:
        _SIDE_MARKET_TO_GROUP[_pair] = _gid


@dataclass(frozen=True)
class OpenExposure:
    home: str
    away: str
    market: str
    side: str
    entry_type: str = "unknown"
    source: str = "unknown"


def exposure_cfg(cfg: dict) -> dict:
    return cfg.get("entry_exposure", {})


def correlation_group(market: str, side: str) -> str | None:
    key = (str(side or "").upper(), str(market or "").lower())
    return _SIDE_MARKET_TO_GROUP.get(key)


def groups_conflict(group_a: str, group_b: str) -> bool:
    if group_a == group_b:
        return True
    return (group_a, group_b) in _CONFLICTING_GROUP_PAIRS or (group_b, group_a) in _CONFLICTING_GROUP_PAIRS


def load_open_exposures() -> list[OpenExposure]:
    """Posições abertas: managed + scalp + paper."""
    out: list[OpenExposure] = []

    from .trade_positions import PositionManager

    for pos in PositionManager().open_positions:
        out.append(OpenExposure(
            home=pos.home,
            away=pos.away,
            market=pos.market,
            side=pos.side,
            entry_type=pos.entry_type,
            source="managed",
        ))

    from .scalping import ScalpingEngine

    for pos in ScalpingEngine().open_positions:
        out.append(OpenExposure(
            home=pos.home,
            away=pos.away,
            market=pos.market,
            side=pos.side,
            entry_type="scalp",
            source="scalp",
        ))

    try:
        from .paper_db import list_paper_trades

        for t in list_paper_trades(500, open_only=True):
            out.append(OpenExposure(
                home=str(t.get("home", "")),
                away=str(t.get("away", "")),
                market=str(t.get("market", "")),
                side=str(t.get("entry_side", "")).upper(),
                entry_type=str(t.get("alert_type", "paper")),
                source="paper",
            ))
    except Exception:
        pass

    return out


def match_exposures(
    home: str,
    away: str,
    exposures: list[OpenExposure],
) -> list[OpenExposure]:
    return [e for e in exposures if teams_match(home, away, e.home, e.away)]


def check_entry_exposure(
    home: str,
    away: str,
    market: str,
    side: str,
    exposures: list[OpenExposure],
    cfg: dict,
) -> tuple[bool, str]:
    """Retorna (ok, motivo) — bloqueia entradas análogas no mesmo jogo."""
    ecfg = exposure_cfg(cfg)
    if not ecfg.get("enabled", True):
        return True, ""

    side_u = str(side or "").upper()
    market_id = str(market or "").lower()
    if not side_u or not market_id:
        return True, ""

    on_match = match_exposures(home, away, exposures)
    max_match = int(ecfg.get("max_entries_per_match", 2))
    if len(on_match) >= max_match:
        return False, "max_entradas_jogo"

    new_group = correlation_group(market_id, side_u)
    if new_group is None:
        # Mercado fora do mapa — limita repetição exata market+side
        for e in on_match:
            if e.market.lower() == market_id and e.side.upper() == side_u:
                return False, "entrada_duplicada"
        return True, ""

    max_per_group = int(ecfg.get("max_per_correlation_group", 1))
    same_group = 0
    for e in on_match:
        g = correlation_group(e.market, e.side)
        if g is None:
            continue
        if g == new_group:
            same_group += 1
            if same_group >= max_per_group:
                return False, f"exposicao_analogica:{new_group}"
        elif groups_conflict(g, new_group):
            return False, f"exposicao_conflito:{g}_vs_{new_group}"

    return True, ""


def exposure_block_message(reason: str) -> str:
    labels = {
        "max_entradas_jogo": "limite de entradas no jogo",
        "entrada_duplicada": "mesma operação já aberta",
    }
    if reason in labels:
        return labels[reason]
    if reason.startswith("exposicao_analogica:"):
        return f"exposição análoga ({reason.split(':', 1)[1]})"
    if reason.startswith("exposicao_conflito:"):
        return f"exposição conflitante ({reason.split(':', 1)[1]})"
    return reason or "exposição bloqueada"
