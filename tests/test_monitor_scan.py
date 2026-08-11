from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd

from fpt.live.monitor import LiveMonitor


def test_scan_without_betfair_match_does_not_crash():
    """parsed_bf=None + market_odds sim — não chama .get em None."""
    today = date.today().isoformat()
    cal = pd.DataFrame([{
        "Home": "Cruzeiro",
        "Away": "Mirassol",
        "League": "BRAZIL 1",
        "Date": today,
        "_fetch_date": today,
        "Odd_1_FT": 1.61,
        "Odd_X_FT": 3.90,
        "Odd_2_FT": 5.75,
    }])
    monitor = LiveMonitor()
    monitor._bf = MagicMock()
    monitor._bf.configured = False
    monitor._bf.fetch_odds_for_games.return_value = []
    monitor._sofascore.enabled = False

    with patch.object(monitor, "_load_calendar", return_value=cal):
        with patch("fpt.live.monitor.evaluate_match_strategies", return_value=([], [])):
            states = monitor.scan(pd.DataFrame())

    assert len(states) == 1
    assert states[0].home == "Cruzeiro"
