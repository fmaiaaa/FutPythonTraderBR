from fpt.integrations.sofascore.lineups import (
    parse_incidents_summary,
    parse_lineups,
    parse_shotmap_summary,
)


def test_parse_lineups():
    payload = {
        "home": {"formation": "4-3-3", "players": [{"id": 1}, {"id": 2}]},
        "away": {"formation": "4-4-2", "players": [{"id": 3}]},
    }
    out = parse_lineups(payload)
    assert out["ss_formation_home"] == "4-3-3"
    assert out["ss_lineup_home_starters"] == 2
    assert out["ss_lineup_confirmed"] is True


def test_parse_incidents():
    payload = {
        "incidents": [
            {"incidentType": "goal", "isHome": True, "incidentClass": "regular"},
            {"incidentType": "card", "isHome": False, "incidentClass": "yellow"},
        ]
    }
    out = parse_incidents_summary(payload)
    assert out["ss_incidents_goals_home"] == 1
    assert out["ss_incidents_cards_away"] == 1


def test_parse_shotmap():
    payload = {"shotmap": [{"isHome": True, "xg": 0.1}, {"isHome": False, "xg": 0.2}]}
    out = parse_shotmap_summary(payload)
    assert out["ss_shotmap_total"] == 2
    assert out["ss_shotmap_home"] == 1


def test_build_scalping_features():
    import pandas as pd
    from fpt.live.dataset_builder import build_scalping_features

    rows = []
    base = pd.Timestamp("2026-03-15 16:00:00")
    for i in range(5):
        rows.append({
            "timestamp": base + pd.Timedelta(seconds=30 * i),
            "home": "A", "away": "B",
            "back_home": 2.0 - i * 0.01,
            "ss_pressure_home": 40 + i,
            "ss_pressure_away": 35,
        })
    df = build_scalping_features(pd.DataFrame(rows))
    assert "target_profitable_30s" in df.columns or "delta_back_home_30s" in df.columns
