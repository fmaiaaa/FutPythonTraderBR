from __future__ import annotations

"""Coleta minuto a minuto — odds Betfair + stats/escalações SofaScore."""

import csv
import json
import os
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from ..client import DATA
from ..integrations.sofascore import SofaScoreClient, SofaScoreError
from ..integrations.sofascore.lineups import (
    parse_incidents_summary,
    parse_lineups,
    parse_shotmap_summary,
)
from ..integrations.sofascore.match import find_event
from ..integrations.sofascore.models import SofaScoreEvent
from ..integrations.sofascore.parser import parse_event_statistics, parse_graph
from ..live.betfair_logger import COLUMNS as TICK_COLUMNS
from ..live.config import load_live_config
from ..live.monitor import LiveMonitor
from ..live.pressure import apply_pressure
from ..pipeline import load_merged
from ..storage import persist_data_locally

BR = ZoneInfo("America/Sao_Paulo")
COLLECTION_ROOT = DATA / "live_collection"


def collection_day_dir(d: date | None = None) -> Path:
    d = d or date.today()
    out = COLLECTION_ROOT / d.strftime("%Y-%m") / d.isoformat()
    out.mkdir(parents=True, exist_ok=True)
    return out


COLLECTION_EXTRA_COLUMNS = [
    "ss_formation_home",
    "ss_formation_away",
    "ss_lineup_home_starters",
    "ss_lineup_away_starters",
    "ss_lineup_confirmed",
    "ss_incidents_goals_home",
    "ss_incidents_goals_away",
    "ss_incidents_cards_home",
    "ss_incidents_cards_away",
    "ss_incidents_total",
    "ss_shotmap_total",
    "ss_shotmap_home",
    "ss_shotmap_away",
    "ss_shotmap_xg_home",
    "ss_shotmap_xg_away",
    "pressure_delta_home",
    "pressure_delta_away",
    "odd_move_home_pct",
    "collection_tick",
]

ALL_COLUMNS = list(dict.fromkeys(TICK_COLUMNS + COLLECTION_EXTRA_COLUMNS))

_bg_instance: LiveDataCollector | None = None
_bg_thread: threading.Thread | None = None
_bg_lock = threading.Lock()


def ensure_collector_background() -> "LiveDataCollector":
    """Inicia thread de coleta enquanto o app Streamlit estiver aberto."""
    col = LiveDataCollector.get()
    if not col.col_cfg.get("run_with_app", True):
        return col
    with _bg_lock:
        global _bg_thread
        if _bg_thread and _bg_thread.is_alive():
            return col
        col._bg_running = True
        _bg_thread = threading.Thread(
            target=col._background_loop, daemon=True, name="fpt-collector",
        )
        _bg_thread.start()
    return col


class LiveDataCollector:
    """Loop de coleta para CI — grava ticks enriquecidos minuto a minuto."""

    _bg_instance: "LiveDataCollector | None" = None

    def __init__(self):
        self.cfg = load_live_config()
        self.col_cfg = self.cfg.get("collection", {})
        self.interval = int(self.col_cfg.get("interval_seconds", 60))
        self._monitor = LiveMonitor()
        self._ss: SofaScoreClient | None = None
        self._lineups_cache: dict[int, dict] = {}
        self._prev_pressure: dict[str, dict[str, float]] = {}
        self._prev_odds_home: dict[str, float] = {}
        self._tick_count = 0
        self._errors: list[str] = []
        self._robot_collects = False
        self._last_collect_ts: str | None = None
        self._last_collect_rows = 0
        self._bg_running = False

    @classmethod
    def get(cls) -> "LiveDataCollector":
        """Instância compartilhada (app + robô)."""
        global _bg_instance
        with _bg_lock:
            if _bg_instance is None:
                _bg_instance = cls()
                cls._bg_instance = _bg_instance
            return _bg_instance

    @classmethod
    def ensure_background(cls) -> "LiveDataCollector":
        """Alias — preferir ``ensure_collector_background()`` no módulo."""
        return ensure_collector_background()

    @property
    def background_active(self) -> bool:
        return self._bg_running and _bg_thread is not None and _bg_thread.is_alive()

    @property
    def last_collect_ts(self) -> str | None:
        return self._last_collect_ts

    @property
    def last_collect_rows(self) -> int:
        return self._last_collect_rows

    def set_robot_collects(self, active: bool) -> None:
        """Robô ativo coleta no próprio ciclo — evita tick duplicado."""
        self._robot_collects = active

    def _background_loop(self) -> None:
        while self._bg_running:
            t0 = time.time()
            if not self._robot_collects:
                try:
                    n = self.collect_tick()
                    self._last_collect_rows = n
                    self._last_collect_ts = datetime.now(BR).isoformat(timespec="seconds")
                except Exception as ex:
                    self._errors.append(str(ex))
            elapsed = time.time() - t0
            time.sleep(max(1.0, self.interval - elapsed))

    @property
    def ss_client(self) -> SofaScoreClient:
        if self._ss is None:
            ss = self.cfg.get("sofascore", {})
            self._ss = SofaScoreClient(
                timeout=float(ss.get("timeout", 15)),
                retries=int(ss.get("retries", 3)),
                min_interval=float(ss.get("min_interval_seconds", 0.5)),
            )
        return self._ss

    def _fetch_ss_extras(self, event_id: int) -> dict:
        out: dict = {}
        client = self.ss_client
        col = self.col_cfg
        try:
            if col.get("fetch_lineups_once", True) and event_id not in self._lineups_cache:
                payload = client.lineups(event_id)
                self._lineups_cache[event_id] = parse_lineups(payload)
                raw_path = collection_day_dir() / "lineups"
                raw_path.mkdir(exist_ok=True)
                (raw_path / f"{event_id}.json").write_text(
                    json.dumps(payload, ensure_ascii=False), encoding="utf-8",
                )
            if event_id in self._lineups_cache:
                out.update(self._lineups_cache[event_id])
        except SofaScoreError as ex:
            self._errors.append(f"lineups {event_id}: {ex}")

        if col.get("fetch_incidents", True):
            try:
                out.update(parse_incidents_summary(client.incidents(event_id)))
            except SofaScoreError as ex:
                self._errors.append(f"incidents {event_id}: {ex}")

        if col.get("fetch_shotmap", True):
            try:
                out.update(parse_shotmap_summary(client.shotmap(event_id)))
            except SofaScoreError as ex:
                self._errors.append(f"shotmap {event_id}: {ex}")

        return out

    def _enrich_state_row(self, state, match_date: str) -> dict:
        from ..live.betfair_logger import state_to_row

        row = state_to_row(state, ts=datetime.now(BR))
        row["collection_tick"] = self._tick_count
        match_key = f"{state.home}|{state.away}"

        prev_p = self._prev_pressure.get(match_key, {})
        if state.pressure_home is not None:
            row["pressure_delta_home"] = (
                state.pressure_home - prev_p.get("home", state.pressure_home)
                if prev_p else 0.0
            )
            row["pressure_delta_away"] = (
                state.pressure_away - prev_p.get("away", state.pressure_away)
                if prev_p else 0.0
            )
            self._prev_pressure[match_key] = {
                "home": state.pressure_home,
                "away": state.pressure_away,
            }

        back = row.get("back_home")
        prev_odd = self._prev_odds_home.get(match_key)
        if back and prev_odd and prev_odd > 1.01:
            row["odd_move_home_pct"] = round((float(back) - prev_odd) / prev_odd, 5)
        if back:
            self._prev_odds_home[match_key] = float(back)

        if state.sofascore_event_id and self.cfg.get("sofascore", {}).get("enabled", True):
            try:
                eid = int(state.sofascore_event_id)
                row.update(self._fetch_ss_extras(eid))
            except (TypeError, ValueError):
                pass

        for col in ALL_COLUMNS:
            row.setdefault(col, None)
        return row

    def _append_rows(self, rows: list[dict], d: date) -> Path:
        path = collection_day_dir(d) / f"ticks_minute_{d.isoformat()}.csv"
        write_header = not path.exists()
        with path.open("a", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=ALL_COLUMNS, extrasaction="ignore")
            if write_header:
                writer.writeheader()
            writer.writerows(rows)
        return path

    def _write_manifest(self, d: date, *, duration_min: int, ticks: int) -> None:
        manifest = {
            "date": d.isoformat(),
            "updated": datetime.now(BR).isoformat(timespec="seconds"),
            "ticks": ticks,
            "duration_minutes": duration_min,
            "interval_seconds": self.interval,
            "errors": self._errors[-20:],
            "betfair_ok": self._monitor.betfair_ok,
        }
        path = collection_day_dir(d) / "manifest.json"
        path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    def run(
        self,
        duration_minutes: int | None = None,
        *,
        interval_seconds: int | None = None,
    ) -> dict:
        if not persist_data_locally():
            import os
            os.environ["FPT_PERSIST_LOCAL"] = "1"

        duration_minutes = duration_minutes or int(
            self.col_cfg.get("default_duration_minutes", 300)
        )
        if interval_seconds:
            self.interval = interval_seconds

        df_hist = None
        try:
            df_hist = load_merged()
        except FileNotFoundError:
            pass

        end_ts = time.time() + duration_minutes * 60
        total_rows = 0
        d = date.today()

        print(f"[collector] inicio — {duration_minutes}min, intervalo {self.interval}s")
        while time.time() < end_ts:
            self._tick_count += 1
            t0 = time.time()
            try:
                states = self._monitor.scan(df_hist)
                rows = []
                for s in states:
                    if not s.in_play and self.cfg.get("sofascore", {}).get("fetch_in_play_only", True):
                        continue
                    md = d.isoformat()
                    rows.append(self._enrich_state_row(s, md))
                if rows:
                    self._append_rows(rows, d)
                    total_rows += len(rows)
                    print(f"  tick {self._tick_count}: {len(rows)} jogos in-play, total linhas {total_rows}")
                else:
                    print(f"  tick {self._tick_count}: nenhum jogo in-play")
            except Exception as ex:
                self._errors.append(str(ex))
                print(f"  tick {self._tick_count} ERRO: {ex}")

            elapsed = time.time() - t0
            sleep_for = max(0, self.interval - elapsed)
            if time.time() + sleep_for >= end_ts:
                break
            time.sleep(sleep_for)

        self._write_manifest(d, duration_min=duration_minutes, ticks=self._tick_count)
        summary = {
            "ticks": self._tick_count,
            "rows": total_rows,
            "date": d.isoformat(),
            "path": str(collection_day_dir(d)),
            "errors": len(self._errors),
        }
        print(f"[collector] fim — {summary}")
        return summary

    def run_forever(self, interval_seconds: int | None = None) -> None:
        """Loop 24/7 — processo CMD separado (SofaScore + odds)."""
        import os
        from .process_status import write_collector_status

        if not persist_data_locally():
            os.environ["FPT_PERSIST_LOCAL"] = "1"
        if interval_seconds:
            self.interval = interval_seconds

        d = date.today()
        print(f"[collector] 24/7 — intervalo {self.interval}s | watchlist completa")
        write_collector_status(running=True, pid=os.getpid())

        try:
            while True:
                t0 = time.time()
                err: str | None = None
                n_rows = 0
                write_collector_status(
                    running=True,
                    pid=os.getpid(),
                    ticks=self._tick_count,
                    last_ts=self._last_collect_ts,
                    phase="scanning",
                )
                try:
                    n_rows = self.collect_tick()
                    self._last_collect_rows = n_rows
                    self._last_collect_ts = datetime.now(BR).isoformat(timespec="seconds")
                except Exception as ex:
                    err = str(ex)
                    self._errors.append(err)
                    print(f"  tick {self._tick_count} ERRO: {ex}")

                self._write_manifest(d, duration_min=0, ticks=self._tick_count)
                write_collector_status(
                    running=True,
                    pid=os.getpid(),
                    ticks=self._tick_count,
                    last_rows=n_rows,
                    last_ts=self._last_collect_ts,
                    error=err,
                )
                elapsed = time.time() - t0
                if n_rows:
                    print(f"  tick {self._tick_count}: {n_rows} jogos | total ticks {self._tick_count}")
                time.sleep(max(1.0, self.interval - elapsed))
        except KeyboardInterrupt:
            print("\n[collector] interrompido pelo usuário")
        finally:
            write_collector_status(
                running=False,
                pid=os.getpid(),
                ticks=self._tick_count,
                last_rows=self._last_collect_rows,
                last_ts=self._last_collect_ts,
            )

    def collect_tick(self, states: list | None = None) -> int:
        """Um tick de coleta (para robô autônomo). Retorna linhas gravadas."""
        if not persist_data_locally():
            os.environ["FPT_PERSIST_LOCAL"] = "1"

        self._tick_count += 1
        if states is None:
            df_hist = None
            try:
                df_hist = load_merged()
            except FileNotFoundError:
                pass
            from .weekly_calendar import active_scalp_slots

            active = active_scalp_slots()
            if active:
                keys = {s.key for s in active}
                states = self._monitor.scan_scalp(df_hist, slot_keys=keys)
            else:
                states = self._states_for_collection(df_hist)
                if not states:
                    self._last_collect_rows = 0
                    self._last_collect_ts = datetime.now(BR).isoformat(timespec="seconds")
                    return 0

        d = date.today()
        rows = []
        record_all = self.col_cfg.get("record_all_fpt", self.col_cfg.get("record_all_watchlist", True))
        ss_in_play_only = self.cfg.get("sofascore", {}).get("fetch_in_play_only", True)
        for s in states:
            if not s.in_play and not record_all and ss_in_play_only:
                continue
            rows.append(self._enrich_state_row(s, d.isoformat()))
        if rows:
            self._append_rows(rows, d)
        self._last_collect_rows = len(rows)
        self._last_collect_ts = datetime.now(BR).isoformat(timespec="seconds")
        try:
            from .minute_store import record_match_minutes_from_states

            record_match_minutes_from_states(states)
        except Exception as ex:
            self._errors.append(f"minute_store: {ex}")
        return len(rows)

    def _states_for_collection(self, df_hist: pd.DataFrame | None) -> list:
        """Fora da janela scalp: coleta jogos ao vivo do snapshot + SofaScore."""
        from .match_status import parse_kickoff_dt
        from .monitor import load_latest_snapshot, merge_calendar_states
        from .sofascore_enricher import SofaScoreEnricher

        states = merge_calendar_states(load_latest_snapshot())
        live = [
            s for s in states
            if s.in_play or s.status in ("LIVE", "HT", "LIVE?")
        ]
        if not live:
            return []

        enricher = SofaScoreEnricher(self.cfg)
        if enricher.enabled:
            for s in live:
                ko = parse_kickoff_dt(s.kickoff or "")
                md = ko.date().isoformat() if ko else date.today().isoformat()
                try:
                    enricher.enrich(s, md)
                except Exception:
                    continue
        return live


def list_collection_dates() -> list[date]:
    dates: list[date] = []
    if not COLLECTION_ROOT.exists():
        return dates
    for month_dir in COLLECTION_ROOT.iterdir():
        if not month_dir.is_dir():
            continue
        for day_dir in month_dir.iterdir():
            if not day_dir.is_dir():
                continue
            try:
                dates.append(date.fromisoformat(day_dir.name))
            except ValueError:
                pass
    return sorted(set(dates))
