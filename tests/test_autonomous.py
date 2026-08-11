"""Testes operação autônoma."""
from __future__ import annotations

import pandas as pd

from fpt.live.models import LiveAlert, LiveMatchState
from fpt.live.trade_positions import ManagedPosition, PositionManager, _should_exit


def _alert(**kw) -> LiveAlert:
    defaults = dict(
        alert_id="t1", alert_type="ENTER", severity="high",
        home="Flamengo", away="Palmeiras", league="BRA", market="away_win_ft",
        message="test", prob_est=0.2, odd_back=4.0, odd_lay=4.1, odd_min=3.5,
        edge_pp=2.0, stake_pct=0.03, stake_valor=30.0,
        stake_back_pct=0.0, stake_lay_pct=0.03,
        market_id="1.1", selection_id=99, recommended_side="LAY",
        score="0-0", in_play=False,
    )
    defaults.update(kw)
    return LiveAlert(**defaults)


def test_lay_exit_on_underdog_goal():
    pos = ManagedPosition(
        position_id="p1", home="Flamengo", away="Criciuma", league="BRA",
        market="away_win_ft", side="LAY", entry_type="pre_live",
        entry_score_home=0, entry_score_away=0,
        market_id="1", selection_id=1, stake_amount=10.0, entry_odd=5.0,
        entry_ts="2026-08-08T15:00:00",
    )
    rules = {"lay_exit_on_team_goal": True, "exit_at_ht": False}
    assert _should_exit(pos, 0, 1, 1, 30, True, rules) == "GOAL_LAY_AWAY"


def test_back_draw_exit_on_goal():
    pos = ManagedPosition(
        position_id="p2", home="A", away="B", league="X",
        market="draw_ft", side="BACK", entry_type="pre_live",
        entry_score_home=0, entry_score_away=0,
        market_id="1", selection_id=1, stake_amount=10.0, entry_odd=3.5,
        entry_ts="2026-08-08T15:00:00",
    )
    rules = {"back_draw_exit_on_goal": True, "exit_at_ht": False}
    assert _should_exit(pos, 1, 0, 1, 20, True, rules) == "DRAW_BROKEN"


def test_exit_at_ht():
    pos = ManagedPosition(
        position_id="p3", home="A", away="B", league="X",
        market="home_win_ft", side="LAY", entry_type="pre_live",
        entry_score_home=0, entry_score_away=0,
        market_id="1", selection_id=1, stake_amount=10.0, entry_odd=2.0,
        entry_ts="2026-08-08T15:00:00",
    )
    rules = {"exit_at_ht": True}
    assert _should_exit(pos, 0, 0, 0, 45, True, rules) == "HT"


def test_max_goals_exit():
    pos = ManagedPosition(
        position_id="p4", home="A", away="B", league="X",
        market="draw_ft", side="BACK", entry_type="pre_live",
        entry_score_home=0, entry_score_away=0,
        market_id="1", selection_id=1, stake_amount=10.0, entry_odd=3.0,
        entry_ts="2026-08-08T15:00:00", max_goals_before_exit=1,
    )
    rules = {"exit_at_ht": False}
    assert _should_exit(pos, 1, 0, 1, 10, True, rules) == "GOALS_LIMIT"


def test_position_manager_evaluate():
    pm = PositionManager()
    pm._open.clear()
    pm.register_entry(_alert(market="away_win_ft", score="0-0"), side="LAY", stake_amount=5.0)
    state = LiveMatchState(
        home="Flamengo", away="Palmeiras", league="BRA", league_label="BRA",
        kickoff="08/08 16:00", status="LIVE", in_play=True,
        score_home=0, score_away=1, elapsed_min=35,
        odds={"Visitante": {"back": 3.0, "lay": 3.1}},
    )
    pairs = pm.evaluate_exits([state])
    assert len(pairs) >= 1
