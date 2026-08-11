from __future__ import annotations

from typing import Any


def parse_lineups(payload: dict[str, Any]) -> dict[str, Any]:
    """Extrai formação e contagem de titulares/reservas."""
    home = payload.get("home") or {}
    away = payload.get("away") or {}
    return {
        "ss_formation_home": str(home.get("formation") or ""),
        "ss_formation_away": str(away.get("formation") or ""),
        "ss_lineup_home_starters": len(home.get("players") or []),
        "ss_lineup_away_starters": len(away.get("players") or []),
        "ss_lineup_confirmed": bool(home.get("players") and away.get("players")),
    }


def parse_incidents_summary(payload: dict[str, Any]) -> dict[str, Any]:
    incidents = payload.get("incidents") or []
    goals_h = goals_a = cards_h = cards_a = 0
    for inc in incidents:
        is_home = bool(inc.get("isHome"))
        itype = str(inc.get("incidentType") or "")
        iclass = str(inc.get("incidentClass") or "")
        if itype == "goal" or iclass in ("regular", "penalty"):
            if is_home:
                goals_h += 1
            else:
                goals_a += 1
        elif itype == "card" or iclass in ("yellow", "red", "yellowRed"):
            if is_home:
                cards_h += 1
            else:
                cards_a += 1
    return {
        "ss_incidents_goals_home": goals_h,
        "ss_incidents_goals_away": goals_a,
        "ss_incidents_cards_home": cards_h,
        "ss_incidents_cards_away": cards_a,
        "ss_incidents_total": len(incidents),
    }


def parse_shotmap_summary(payload: dict[str, Any]) -> dict[str, Any]:
    shots = payload.get("shotmap") or payload.get("shots") or []
    if isinstance(shots, dict):
        shots = shots.get("shots") or []
    on_h = on_a = total = 0
    xg_h = xg_a = 0.0
    for s in shots:
        total += 1
        is_home = bool(s.get("isHome"))
        if is_home:
            on_h += 1
            xg_h += float(s.get("xg") or s.get("expectedGoals") or 0)
        else:
            on_a += 1
            xg_a += float(s.get("xg") or s.get("expectedGoals") or 0)
    return {
        "ss_shotmap_total": total,
        "ss_shotmap_home": on_h,
        "ss_shotmap_away": on_a,
        "ss_shotmap_xg_home": round(xg_h, 3),
        "ss_shotmap_xg_away": round(xg_a, 3),
    }
