from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ..client import DATA
from ..integrations.sofascore import SofaScoreClient, SofaScoreError
from ..integrations.sofascore.match import find_event
from ..integrations.sofascore.models import SofaScoreEvent, SofaScoreLiveStats
from ..integrations.sofascore.parser import parse_event_statistics, parse_graph
from ..storage import persist_data_locally
from .models import LiveMatchState
from .pressure import apply_pressure

BR = ZoneInfo("America/Sao_Paulo")
SNAPSHOT_ROOT = DATA / "sofascore" / "snapshots"


def _merge_ss_meta(state: LiveMatchState, event: SofaScoreEvent) -> None:
    ss = dict(state.sofascore_stats or {})
    ss["ss_status_type"] = event.status_type
    if event.minute is not None:
        ss["ss_minute"] = event.minute
    state.sofascore_stats = ss


class SofaScoreEnricher:
    """Enriquece estados live com stats SofaScore (posse, chutes, xG, pressão)."""

    def __init__(self, cfg: dict | None = None):
        from .config import load_live_config

        self.cfg = cfg or load_live_config()
        ss = self.cfg.get("sofascore", {})
        self.enabled = bool(ss.get("enabled", False))
        self.fetch_in_play_only = bool(ss.get("fetch_in_play_only", True))
        self._client: SofaScoreClient | None = None
        self._events_by_date: dict[str, list[SofaScoreEvent]] = {}
        self._prev_stats: dict[int, SofaScoreLiveStats] = {}
        self._last_error: str | None = None

    @property
    def client(self) -> SofaScoreClient:
        if self._client is None:
            ss = self.cfg.get("sofascore", {})
            self._client = SofaScoreClient(
                timeout=float(ss.get("timeout", 15)),
                retries=int(ss.get("retries", 3)),
                min_interval=float(ss.get("min_interval_seconds", 0.4)),
            )
        return self._client

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def _load_events(self, match_date: str) -> list[SofaScoreEvent]:
        if match_date in self._events_by_date:
            return self._events_by_date[match_date]

        by_id: dict[int, SofaScoreEvent] = {}
        sched_err: str | None = None

        try:
            for e in self.client.scheduled_events(match_date):
                by_id[e.event_id] = e
        except SofaScoreError as ex:
            sched_err = str(ex)

        try:
            for e in self.client.live_events():
                by_id[e.event_id] = e
        except SofaScoreError as ex:
            self._last_error = str(ex)
            if not by_id:
                return []

        self._events_by_date[match_date] = list(by_id.values())
        self._last_error = sched_err if sched_err and not by_id else None
        return self._events_by_date[match_date]

    def _fetch_live_stats(self, event: SofaScoreEvent, minute: int | None) -> SofaScoreLiveStats | None:
        try:
            stats_payload = self.client.statistics(event.event_id)
            stats = parse_event_statistics(stats_payload, event.event_id)
            stats.minute = minute
            graph_payload = self.client.graph(event.event_id)
            stats.graph_momentum = parse_graph(graph_payload, minute)
            prev = self._prev_stats.get(event.event_id)
            apply_pressure(stats, prev)
            self._prev_stats[event.event_id] = stats
            self._last_error = None
            return stats
        except SofaScoreError as ex:
            self._last_error = str(ex)
            return None

    def _apply_event_status(self, state: LiveMatchState, event: SofaScoreEvent) -> None:
        state.sofascore_event_id = event.event_id
        _merge_ss_meta(state, event)

        if event.is_finished:
            state.in_play = False
            state.status = "FT"
        elif event.is_halftime:
            state.in_play = True
            state.status = "HT"
        elif event.is_live:
            state.in_play = True
            state.status = "LIVE"
        else:
            state.in_play = False
            if state.status in ("LIVE", "HT"):
                state.status = "PRE"

        if event.score_home is not None:
            state.score_home = event.score_home
        if event.score_away is not None:
            state.score_away = event.score_away
        if event.minute is not None:
            state.elapsed_min = event.minute

    def enrich(self, state: LiveMatchState, match_date: str) -> LiveMatchState:
        if not self.enabled:
            return state

        events = self._load_events(match_date)
        if not events:
            return state

        event = find_event(state.home, state.away, events)
        if not event:
            return state

        self._apply_event_status(state, event)

        if event.is_finished:
            return state

        if self.fetch_in_play_only and not event.is_live:
            return state

        stats = self._fetch_live_stats(event, state.elapsed_min)
        if not stats:
            stats = SofaScoreLiveStats(event_id=event.event_id, minute=event.minute or state.elapsed_min)

        state.sofascore_stats = stats.to_flat_dict()
        state.sofascore_stats["ss_status_type"] = event.status_type
        state.pressure_home = stats.pressure_home
        state.pressure_away = stats.pressure_away
        state.graph_momentum = stats.graph_momentum
        if stats.minute is not None:
            state.elapsed_min = stats.minute
        self._persist_snapshot(state, stats, match_date)
        return state

    def _persist_snapshot(
        self,
        state: LiveMatchState,
        stats: SofaScoreLiveStats,
        match_date: str,
    ) -> None:
        if not persist_data_locally():
            return
        ss_cfg = self.cfg.get("sofascore", {})
        if not ss_cfg.get("log_snapshots", True):
            return
        out_dir = SNAPSHOT_ROOT / match_date[:7]
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"ss_{match_date}.jsonl"
        row = {
            "timestamp": datetime.now(BR).isoformat(timespec="seconds"),
            "home": state.home,
            "away": state.away,
            "match_date": match_date,
            **stats.to_flat_dict(),
        }
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def enrich_batch(self, states: list[LiveMatchState], match_dates: dict[str, str]) -> list[LiveMatchState]:
        if not self.enabled:
            return states
        out: list[LiveMatchState] = []
        for s in states:
            key = f"{s.home}|{s.away}"
            md = match_dates.get(key, date.today().isoformat())
            out.append(self.enrich(s, md))
        return out
