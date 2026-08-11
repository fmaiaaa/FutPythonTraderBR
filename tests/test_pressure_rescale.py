from __future__ import annotations

import json
from pathlib import Path

from fpt.integrations.sofascore.parser import parse_event_statistics
from fpt.live.pressure import REFERENCE, WEIGHTS, compute_pressure

FIXTURES = Path(__file__).parent / "fixtures"


def test_pressure_rescaled_0_100_no_hard_clip():
    raw = json.loads((FIXTURES / "sofascore_statistics_sample.json").read_text(encoding="utf-8"))
    stats = parse_event_statistics(raw, 1)
    stats.minute = 30
    stats.graph_momentum = 10.0
    p = compute_pressure(stats)
    assert 0 <= p.home <= 100
    assert 0 <= p.away <= 100
    assert p.home != 100 or p.away != 100  # sample não é partida extrema nos dois lados


def test_pressure_comparable_across_minutes_same_pace():
    """Mesmo ritmo por minuto → pressão similar (critério uniforme)."""
    base = {
        "shots_on_target_home": 3,
        "shots_home": 6,
        "xg_home": 0.83,
        "corners_home": 2,
        "big_chances_home": 1,
        "shots_inside_box_home": 4,
        "possession_home": 58.0,
        "shots_on_target_away": 2,
        "shots_away": 4,
        "xg_away": 0.55,
        "corners_away": 1,
        "big_chances_away": 0,
        "shots_inside_box_away": 2,
        "possession_away": 42.0,
        "graph_momentum": 5.0,
    }
    from fpt.integrations.sofascore.models import SofaScoreLiveStats

    s30 = SofaScoreLiveStats(event_id=1, minute=30, **base)
    s60 = SofaScoreLiveStats(
        event_id=1,
        minute=60,
        shots_on_target_home=6,
        shots_home=12,
        xg_home=1.66,
        corners_home=4,
        big_chances_home=2,
        shots_inside_box_home=8,
        possession_home=58.0,
        shots_on_target_away=4,
        shots_away=8,
        xg_away=1.10,
        corners_away=2,
        big_chances_away=0,
        shots_inside_box_away=4,
        possession_away=42.0,
        graph_momentum=5.0,
    )
    p30 = compute_pressure(s30)
    p60 = compute_pressure(s60)
    assert abs(p30.home - p60.home) < 8.0
    assert abs(p30.away - p60.away) < 8.0


def test_weights_sum_to_one():
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9


def test_reference_documented():
    assert REFERENCE["xg_per_90"] > 0
    assert REFERENCE["sot_per_min"] > 0
