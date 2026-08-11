"""Resolução de status do jogo — Betfair + SofaScore + relógio."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from .models import LiveMatchState

BR = ZoneInfo("America/Sao_Paulo")

FINISHED_SS = frozenset({
    "finished", "ended", "afterpenalties", "afterextratime",
    "cancelled", "canceled", "postponed", "abandoned", "walkover", "awarded",
})
HALFTIME_SS = frozenset({"halftime", "half_time", "break"})
LIVE_SS = frozenset({"inprogress", "live", "interrupted", "1sthalf", "2ndhalf"})
FINISHED_BF_MARKET = frozenset({"CLOSED", "SETTLED", "CANCELLED"})
SETTLED_RUNNER = frozenset({"WINNER", "LOSER", "REMOVED", "HIDDEN"})


@dataclass(frozen=True)
class ResolvedMatchStatus:
    in_play: bool
    status: str  # PRE | LIVE | HT | FT | CLOSED | UNKNOWN
    elapsed_min: int | None = None


def parse_kickoff_dt(kickoff_str: str) -> datetime | None:
    if not kickoff_str or kickoff_str == "—":
        return None
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S"):
        try:
            return datetime.strptime(kickoff_str, fmt).replace(tzinfo=BR)
        except ValueError:
            continue
    return None


def kickoff_from_open_date(open_date: str | None) -> datetime | None:
    if not open_date:
        return None
    try:
        s = open_date.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt.astimezone(BR)
    except (ValueError, TypeError):
        return None


def format_kickoff(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    return dt.astimezone(BR).strftime("%d/%m/%Y %H:%M")


def betfair_market_is_live(parsed: dict | None) -> bool:
    """In-play real na Betfair — ignora mercado fechado/settled."""
    if not parsed:
        return False
    mkt = str(parsed.get("status") or "").upper()
    if mkt in FINISHED_BF_MARKET:
        return False
    if not parsed.get("in_play"):
        return False
    sides = parsed.get("sides") or {}
    statuses = [str(s.get("status") or "").upper() for s in sides.values()]
    if statuses and all(s in SETTLED_RUNNER for s in statuses if s):
        return False
    return True


def clock_elapsed_min(kickoff_dt: datetime | None, now: datetime | None = None) -> int | None:
    if kickoff_dt is None:
        return None
    now = now or datetime.now(BR)
    return max(0, int((now - kickoff_dt).total_seconds() // 60))


def estimate_match_minute(wall_min: int) -> int:
    """Minuto aproximado do jogo a partir do tempo desde o kickoff (inclui HT ~15 min)."""
    if wall_min <= 47:
        return wall_min
    if wall_min <= 62:
        return 45
    return min(wall_min - 18, 95)


def betfair_elapsed_stale(*, wall_min: int | None, elapsed_bf: int | None) -> bool:
    if wall_min is None:
        return False
    if elapsed_bf is None:
        return wall_min >= 70
    if wall_min >= 70 and elapsed_bf <= 15:
        return True
    return wall_min - elapsed_bf >= 35


def reconcile_elapsed(
    *,
    kickoff_dt: datetime | None,
    ss_minute: int | None,
    elapsed_bf: int | None,
    now: datetime | None = None,
) -> int | None:
    """Prefer minuto SofaScore; se Betfair divergir muito do relógio, estima pelo kickoff."""
    wall = clock_elapsed_min(kickoff_dt, now)
    estimated = estimate_match_minute(wall) if wall is not None else None
    if ss_minute is not None and ss_minute >= 0:
        if wall is None or abs(ss_minute - (estimated or wall)) <= 20:
            return ss_minute
        return max(ss_minute, estimated or wall)
    if elapsed_bf is not None and wall is not None and not betfair_elapsed_stale(wall_min=wall, elapsed_bf=elapsed_bf):
        if abs(elapsed_bf - (estimated or wall)) <= 20:
            return elapsed_bf
    return estimated if estimated is not None else elapsed_bf


def resolve_match_status(
    *,
    kickoff_dt: datetime | None = None,
    betfair_in_play: bool = False,
    betfair_market_status: str | None = None,
    betfair_settled: bool = False,
    ss_status_type: str | None = None,
    ss_minute: int | None = None,
    elapsed_bf: int | None = None,
    now: datetime | None = None,
) -> ResolvedMatchStatus:
    """Combina fontes — nunca deixa FT aparecer como LIVE."""
    now = now or datetime.now(BR)
    ss = (ss_status_type or "").lower()
    bf_mkt = (betfair_market_status or "").upper()
    wall = clock_elapsed_min(kickoff_dt, now)
    elapsed = reconcile_elapsed(
        kickoff_dt=kickoff_dt,
        ss_minute=ss_minute,
        elapsed_bf=elapsed_bf,
        now=now,
    )
    bf_stale = betfair_elapsed_stale(wall_min=wall, elapsed_bf=elapsed_bf)

    if ss in FINISHED_SS or bf_mkt in FINISHED_BF_MARKET or betfair_settled:
        return ResolvedMatchStatus(in_play=False, status="FT", elapsed_min=elapsed)

    # Betfair BR costuma ficar in_play com minuto 1–2 após o apito — confiar no relógio
    if wall is not None and wall >= 105 and bf_stale and ss not in LIVE_SS:
        return ResolvedMatchStatus(in_play=False, status="FT", elapsed_min=elapsed or estimate_match_minute(wall))

    if ss in HALFTIME_SS:
        return ResolvedMatchStatus(in_play=True, status="HT", elapsed_min=elapsed or ss_minute or elapsed_bf or 45)

    if ss in LIVE_SS:
        em = elapsed if elapsed is not None else ss_minute or elapsed_bf
        if em is not None and em >= 95:
            return ResolvedMatchStatus(in_play=False, status="FT", elapsed_min=em)
        return ResolvedMatchStatus(in_play=True, status="LIVE", elapsed_min=em)

    if kickoff_dt is not None:
        if now < kickoff_dt - timedelta(minutes=5):
            return ResolvedMatchStatus(in_play=False, status="PRE", elapsed_min=None)
        if now >= kickoff_dt + timedelta(minutes=115):
            return ResolvedMatchStatus(in_play=False, status="FT", elapsed_min=elapsed or (estimate_match_minute(wall) if wall else None))

    live = False
    if betfair_in_play and bf_mkt not in FINISHED_BF_MARKET and not betfair_settled:
        if bf_stale and wall is not None and wall >= 100 and ss not in LIVE_SS:
            live = False
        elif wall is None or wall < 105:
            live = True

    if live:
        em = elapsed if elapsed is not None else ss_minute or elapsed_bf
        if em is not None and em >= 95:
            return ResolvedMatchStatus(in_play=False, status="FT", elapsed_min=em)
        return ResolvedMatchStatus(in_play=True, status="LIVE", elapsed_min=em)

    if kickoff_dt is not None and now >= kickoff_dt:
        if now >= kickoff_dt + timedelta(minutes=100):
            return ResolvedMatchStatus(in_play=False, status="FT", elapsed_min=elapsed or (estimate_match_minute(wall) if wall else None))
        return ResolvedMatchStatus(
            in_play=True,
            status="LIVE",
            elapsed_min=elapsed or (estimate_match_minute(wall) if wall else None),
        )

    return ResolvedMatchStatus(in_play=False, status="UNKNOWN", elapsed_min=elapsed)


def try_fix_swapped_day_month(ko: datetime) -> datetime | None:
    """Corrige 08/09/2026 (8 set) que deveria ser 09/08/2026 (9 ago)."""
    try:
        return ko.replace(month=ko.day, day=ko.month)
    except ValueError:
        return None


def reconcile_kickoff_dt(ko: datetime | None, *, now: datetime | None = None) -> datetime | None:
    """Ajusta kickoff ambíguo antes de resolver status."""
    if ko is None:
        return None
    now = now or datetime.now(BR)
    if ko.date() <= now.date():
        return ko
    fixed = try_fix_swapped_day_month(ko)
    if fixed is None:
        return ko
    fixed = fixed.replace(
        hour=ko.hour,
        minute=ko.minute,
        second=ko.second,
        microsecond=ko.microsecond,
    )
    if fixed.date() <= now.date() + timedelta(days=2):
        return fixed
    return ko


def is_operational_state(
    state: "LiveMatchState",
    *,
    now: datetime | None = None,
    lookback_days: int = 0,
    lookahead_days: int = 1,
) -> bool:
    """Jogos visíveis no dashboard/scan — exclui encerrados de dias anteriores."""
    now = now or datetime.now(BR)
    ko = reconcile_kickoff_dt(parse_kickoff_dt(getattr(state, "kickoff", "") or ""), now=now)
    if ko is None:
        return True
    today = now.date()
    earliest = today - timedelta(days=max(0, lookback_days))
    latest = today + timedelta(days=max(0, lookahead_days))
    match_day = ko.date()
    if match_day > latest:
        return False
    if match_day >= today:
        return True
    if match_day < earliest:
        return False
    if getattr(state, "in_play", False) and getattr(state, "status", "") in ("LIVE", "HT", "LIVE?"):
        return True
    if getattr(state, "status", "") in ("FT", "CLOSED"):
        return False
    resolved = resolve_match_status(
        kickoff_dt=ko,
        betfair_in_play=bool(getattr(state, "in_play", False)),
        ss_status_type=(getattr(state, "sofascore_stats", None) or {}).get("ss_status_type"),
        ss_minute=getattr(state, "elapsed_min", None),
        now=now,
    )
    return resolved.in_play or resolved.status not in ("FT", "CLOSED")


def filter_operational_states(
    states: list["LiveMatchState"],
    *,
    now: datetime | None = None,
    lookback_days: int = 0,
    lookahead_days: int = 1,
) -> list["LiveMatchState"]:
    return [
        s for s in states
        if is_operational_state(
            s,
            now=now,
            lookback_days=lookback_days,
            lookahead_days=lookahead_days,
        )
    ]


def refresh_state_status(state, *, now: datetime | None = None) -> None:
    """Reavalia status ao carregar snapshot (dashboard / operação)."""
    now = now or datetime.now(BR)
    ss = getattr(state, "sofascore_stats", None) or {}
    ko = parse_kickoff_dt(getattr(state, "kickoff", "") or "")
    ko = reconcile_kickoff_dt(ko, now=now)
    if ko is not None:
        state.kickoff = format_kickoff(ko)
    odds_src = str(getattr(state, "odds_source", "") or "")
    stored_in_play = bool(getattr(state, "in_play", False))
    # Só confia em in_play persistido quando veio da Betfair; demais fontes revalidam por tempo/SS.
    betfair_in_play = stored_in_play if odds_src == "betfair_br" else False

    resolved = resolve_match_status(
        kickoff_dt=ko,
        betfair_in_play=betfair_in_play,
        ss_status_type=ss.get("ss_status_type"),
        ss_minute=ss.get("ss_minute") or getattr(state, "elapsed_min", None),
        elapsed_bf=getattr(state, "elapsed_min", None),
        now=now,
    )
    state.in_play = resolved.in_play
    state.status = resolved.status
    if resolved.elapsed_min is not None:
        state.elapsed_min = resolved.elapsed_min
