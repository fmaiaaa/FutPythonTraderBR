from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from fpt.live.match_status import (
    betfair_market_is_live,
    filter_operational_states,
    format_kickoff,
    is_operational_state,
    kickoff_from_open_date,
    parse_kickoff_dt,
    refresh_state_status,
    resolve_match_status,
    try_fix_swapped_day_month,
)
from fpt.live.models import LiveMatchState

BR = ZoneInfo("America/Sao_Paulo")


def test_finished_ss_overrides_betfair_live():
    ko = datetime(2026, 8, 9, 16, 0, tzinfo=BR)
    now = datetime(2026, 8, 9, 18, 0, tzinfo=BR)
    r = resolve_match_status(
        kickoff_dt=ko,
        betfair_in_play=True,
        ss_status_type="finished",
        now=now,
    )
    assert r.in_play is False
    assert r.status == "FT"


def test_stale_midnight_kickoff_marks_ft_after_window():
    """Calendário 09/08/2026 00:00 (9 ago) — jogo já terminou."""
    ko = parse_kickoff_dt("09/08/2026 00:00")
    now = datetime(2026, 8, 9, 15, 33, tzinfo=BR)
    r = resolve_match_status(kickoff_dt=ko, betfair_in_play=True, now=now)
    assert r.in_play is False
    assert r.status == "FT"


def test_wrong_parsed_date_future_still_ft_via_ss():
    ko = parse_kickoff_dt("08/09/2026 00:00")  # 8 set — parse errado do CSV
    now = datetime(2026, 8, 9, 15, 33, tzinfo=BR)
    r = resolve_match_status(
        kickoff_dt=ko,
        betfair_in_play=True,
        ss_status_type="finished",
        now=now,
    )
    assert r.status == "FT"


def test_betfair_closed_not_live():
    parsed = {
        "in_play": True,
        "status": "CLOSED",
        "sides": {"home": {"status": "WINNER"}, "draw": {"status": "LOSER"}, "away": {"status": "LOSER"}},
    }
    assert betfair_market_is_live(parsed) is False


def test_betfair_settled_runners_not_live():
    parsed = {
        "in_play": True,
        "status": "OPEN",
        "sides": {
            "home": {"status": "WINNER"},
            "draw": {"status": "LOSER"},
            "away": {"status": "LOSER"},
        },
    }
    assert betfair_market_is_live(parsed) is False


def test_kickoff_from_open_date_brt():
    dt = kickoff_from_open_date("2026-08-09T19:00:00.000Z")
    assert dt is not None
    assert format_kickoff(dt) == "09/08/2026 16:00"


def test_refresh_state_status_fixes_ambiguous_future_kickoff():
    st = LiveMatchState(
        home="Cruzeiro",
        away="Mirassol",
        league="BRAZIL 1",
        league_label="Brasileirão",
        kickoff="08/09/2026 00:00",
        status="LIVE",
        in_play=True,
        odds_source="fpt_row",
    )
    now = datetime(2026, 8, 9, 15, 33, tzinfo=BR)
    refresh_state_status(st, now=now)
    assert st.kickoff == "09/08/2026 00:00"
    assert st.in_play is False
    assert st.status == "FT"


def test_prematch_before_kickoff():
    ko = datetime(2026, 8, 9, 20, 0, tzinfo=BR)
    now = datetime(2026, 8, 9, 18, 0, tzinfo=BR)
    r = resolve_match_status(kickoff_dt=ko, betfair_in_play=False, now=now)
    assert r.status == "PRE"
    assert r.in_play is False


def test_stale_betfair_in_play_marks_ft_after_wall_clock():
    """17:30 kickoff, 19:10 agora — Betfair ainda in_play com minuto 2."""
    ko = datetime(2026, 8, 9, 17, 30, tzinfo=BR)
    now = datetime(2026, 8, 9, 19, 10, tzinfo=BR)
    r = resolve_match_status(
        kickoff_dt=ko,
        betfair_in_play=True,
        elapsed_bf=2,
        now=now,
    )
    assert r.in_play is False
    assert r.status == "FT"
    assert r.elapsed_min is not None and r.elapsed_min >= 80


def test_stale_betfair_elapsed_reconciled_from_kickoff():
    ko = datetime(2026, 8, 9, 17, 45, tzinfo=BR)
    now = datetime(2026, 8, 9, 19, 12, tzinfo=BR)
    r = resolve_match_status(
        kickoff_dt=ko,
        betfair_in_play=True,
        elapsed_bf=2,
        now=now,
    )
    assert r.elapsed_min is not None
    assert r.elapsed_min >= 65
    assert r.elapsed_min <= 85


def test_swapped_day_month_fixes_september_parse():
    ko = parse_kickoff_dt("08/09/2026 11:00")
    fixed = try_fix_swapped_day_month(ko)
    assert fixed is not None
    assert fixed.month == 8 and fixed.day == 9


def test_finished_yesterday_not_operational_on_next_day():
    st = LiveMatchState(
        home="Cruzeiro",
        away="Mirassol",
        league="BRAZIL 1",
        league_label="Brasileirão",
        kickoff="09/08/2026 11:00",
        status="FT",
        in_play=False,
    )
    now = datetime(2026, 8, 10, 0, 30, tzinfo=BR)
    assert is_operational_state(st, now=now) is False
    assert filter_operational_states([st], now=now) == []


def test_wrong_future_kickoff_yesterday_not_operational():
    """08/09/2026 (8 set) no dia 10/08 — após swap vira 9 ago encerrado."""
    st = LiveMatchState(
        home="Cruzeiro",
        away="Mirassol",
        league="BRAZIL 1",
        league_label="Brasileirão",
        kickoff="08/09/2026 11:00",
        status="PRE",
        in_play=False,
    )
    now = datetime(2026, 8, 10, 0, 30, tzinfo=BR)
    refresh_state_status(st, now=now)
    assert st.kickoff == "09/08/2026 11:00"
    assert st.status == "FT"
    assert is_operational_state(st, now=now) is False
