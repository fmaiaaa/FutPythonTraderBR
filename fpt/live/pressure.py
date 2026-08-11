from __future__ import annotations

"""Índice de pressão live — reescalonado 0–100 com referências fixas (comparável entre jogos)."""

from dataclasses import dataclass

from ..integrations.sofascore.models import SofaScoreLiveStats

# Referências fixas — mesmo critério em todos os jogos (valores ≈ partida forte / elite).
REFERENCE = {
    "sot_per_min": 0.12,       # ~11 SOT / 90 min
    "shots_per_min": 0.22,     # ~20 chutes / 90
    "box_per_min": 0.16,       # chutes na área / min
    "corners_per_min": 0.11,   # escanteios / min
    "big_per_min": 0.06,       # chances claras / min
    "xg_per_90": 2.50,         # xG acumulado projetado p/ 90 min
    "possession_span": 50.0,   # 50%→0, 100%→1 na posse ofensiva
    "momentum": 25.0,          # gráfico SofaScore (positivo casa / negativo visitante)
}

# Pesos — soma = 1.0 → score final já é 0–100 sem corte arbitrário no total.
WEIGHTS = {
    "sot": 0.22,
    "shots": 0.14,
    "box": 0.10,
    "corners": 0.10,
    "big": 0.14,
    "xg": 0.18,
    "possession": 0.07,
    "momentum": 0.05,
}


@dataclass
class PressureSnapshot:
    home: float
    away: float
    dominance: float  # home - away
    velocity_home: float | None = None
    velocity_away: float | None = None


def _per_minute(value: float | int | None, minute: int | None) -> float:
    if value is None:
        return 0.0
    m = max(int(minute or 1), 1)
    return float(value) / m


def _ratio(value: float, reference: float) -> float:
    """Normaliza componente: 0 = nada, 1 = atinge referência elite, >1 saturado em 1."""
    if reference <= 0 or value <= 0:
        return 0.0
    return min(1.0, value / reference)


def _xg_pace_90(xg: float | None, minute: int | None) -> float:
    if xg is None or xg <= 0:
        return 0.0
    m = max(int(minute or 1), 1)
    return float(xg) * 90.0 / m


def _possession_offensive(possession: float | None) -> float:
    if possession is None:
        return 0.0
    return min(1.0, max(0.0, (float(possession) - 50.0) / REFERENCE["possession_span"]))


def _momentum_side(momentum: float | None, *, home: bool) -> float:
    if momentum is None:
        return 0.0
    m = float(momentum)
    raw = m if home else -m
    return _ratio(max(0.0, raw), REFERENCE["momentum"])


def _side_score(
    *,
    minute: int | None,
    sot: int | None,
    shots: int | None,
    xg: float | None,
    corners: int | None,
    big: int | None,
    box_shots: int | None,
    possession: float | None,
    momentum: float | None,
    home: bool,
) -> float:
    ref = REFERENCE
    w = WEIGHTS
    score = 0.0
    score += w["sot"] * _ratio(_per_minute(sot, minute), ref["sot_per_min"])
    score += w["shots"] * _ratio(_per_minute(shots, minute), ref["shots_per_min"])
    score += w["box"] * _ratio(_per_minute(box_shots, minute), ref["box_per_min"])
    score += w["corners"] * _ratio(_per_minute(corners, minute), ref["corners_per_min"])
    score += w["big"] * _ratio(_per_minute(big, minute), ref["big_per_min"])
    score += w["xg"] * _ratio(_xg_pace_90(xg, minute), ref["xg_per_90"])
    score += w["possession"] * _possession_offensive(possession)
    score += w["momentum"] * _momentum_side(momentum, home=home)
    return round(score * 100.0, 2)


def compute_pressure(
    stats: SofaScoreLiveStats,
    prev: SofaScoreLiveStats | None = None,
) -> PressureSnapshot:
    """Pressão 0–100 por time — média ponderada de componentes normalizados por referência fixa."""
    minute = stats.minute or 1
    mom = stats.graph_momentum

    home = _side_score(
        minute=minute,
        sot=stats.shots_on_target_home,
        shots=stats.shots_home,
        xg=stats.xg_home,
        corners=stats.corners_home,
        big=stats.big_chances_home,
        box_shots=stats.shots_inside_box_home,
        possession=stats.possession_home,
        momentum=mom,
        home=True,
    )
    away = _side_score(
        minute=minute,
        sot=stats.shots_on_target_away,
        shots=stats.shots_away,
        xg=stats.xg_away,
        corners=stats.corners_away,
        big=stats.big_chances_away,
        box_shots=stats.shots_inside_box_away,
        possession=stats.possession_away,
        momentum=mom,
        home=False,
    )

    vel_h = vel_a = None
    if prev is not None and prev.pressure_home is not None and prev.pressure_away is not None:
        vel_h = round(home - prev.pressure_home, 2)
        vel_a = round(away - prev.pressure_away, 2)

    return PressureSnapshot(
        home=home,
        away=away,
        dominance=round(home - away, 2),
        velocity_home=vel_h,
        velocity_away=vel_a,
    )


def apply_pressure(stats: SofaScoreLiveStats, prev: SofaScoreLiveStats | None = None) -> SofaScoreLiveStats:
    p = compute_pressure(stats, prev)
    stats.pressure_home = p.home
    stats.pressure_away = p.away
    return stats
