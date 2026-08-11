from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from ..calendar import normalize_jogos
from ..client import DATA
from ..downloader import fetch_jogos_do_dia
from ..dates import apply_fetch_date, match_date_iso, parse_fpt_date
from ..league_filter import filter_calendar
from ..leagues import filter_watchlist, watchlist_label
from ..pipeline import load_merged
from ..storage import persist_data_locally
from ..trading.market_betfair import BetfairMarket, _build_parsed_lookup, parsed_to_market_odds
from ..trading.market_sim import SimulatedMarket
from .betfair_logger import log_states
from .match_status import (
    betfair_market_is_live,
    filter_operational_states,
    format_kickoff,
    kickoff_from_open_date,
    parse_kickoff_dt,
    refresh_state_status,
    resolve_match_status,
)
from .config import load_live_config
from .models import LiveAlert, LiveMatchState
from .pro_tempo import pick_best_action
from .sofascore_enricher import SofaScoreEnricher
from .scalping import ScalpingEngine
from .scalping_strategies import is_scalp_entry
from .strategies import evaluate_match_strategies

BR = ZoneInfo("America/Sao_Paulo")
_SNAPSHOT_BATCH = 20


def _state_has_odds(state: LiveMatchState) -> bool:
    return any(state.odds.get(k, {}).get("back") for k in ("Casa", "Empate", "Visitante"))


def _parse_kickoff(row: pd.Series) -> str:
    date_part = parse_fpt_date(row.get("Date"))
    time_raw = row.get("Time")
    if time_raw is not None and not (isinstance(time_raw, float) and pd.isna(time_raw)):
        ts = pd.to_datetime(str(time_raw).strip(), format="%H:%M", errors="coerce")
        if ts is not None and not pd.isna(ts) and not pd.isna(date_part):
            date_part = date_part.replace(hour=int(ts.hour), minute=int(ts.minute), second=0, microsecond=0)

    fetch_d = row.get("_fetch_date")
    if fetch_d is not None and not (isinstance(fetch_d, float) and pd.isna(fetch_d)):
        fd = pd.to_datetime(fetch_d, errors="coerce")
        if not pd.isna(fd):
            if pd.isna(date_part):
                date_part = fd
            else:
                date_part = date_part.replace(
                    year=int(fd.year),
                    month=int(fd.month),
                    day=int(fd.day),
                )
    if pd.isna(date_part):
        return "—"
    if date_part.tzinfo is None:
        date_part = date_part.tz_localize(BR)
    else:
        date_part = date_part.tz_convert(BR)
    return date_part.strftime("%d/%m/%Y %H:%M")


def _match_date_iso(row: pd.Series) -> str:
    return match_date_iso(row)


def _match_status(in_play: bool, score_home, score_away, kickoff_str: str) -> str:
    """Legado — preferir resolve_match_status."""
    resolved = resolve_match_status(
        kickoff_dt=parse_kickoff_dt(kickoff_str),
        betfair_in_play=in_play,
    )
    return resolved.status


class LiveMonitor:
    """Monitor in-time: placares Betfair + odds + alertas do modelo."""

    def __init__(self):
        self.cfg = load_live_config()
        self._bf = BetfairMarket()
        self._sofascore = SofaScoreEnricher(self.cfg)
        self._scalping = ScalpingEngine()
        self._prev_odds: dict[str, dict[str, float]] = {}
        self._prev_pressure: dict[str, dict[str, float]] = {}
        self._prev_live: dict[str, dict[str, float]] = {}
        self._alert_history: dict[str, float] = {}
        self._last_scan: datetime | None = None
        self._states: list[LiveMatchState] = []
        self._all_alerts: list[LiveAlert] = []

    @property
    def betfair_ok(self) -> bool:
        return self._bf.configured

    def _cooldown_ok(self, alert_id: str) -> bool:
        cd = self.cfg["live"].get("alert_cooldown_seconds", 300)
        last = self._alert_history.get(alert_id, 0)
        return time.time() - last >= cd

    def _register_alerts(self, alerts: list[LiveAlert]) -> list[LiveAlert]:
        fresh = []
        for a in alerts:
            if self._cooldown_ok(a.alert_id):
                self._alert_history[a.alert_id] = time.time()
                fresh.append(a)
        if fresh and self.cfg["live"].get("log_alerts", True):
            self._persist_alerts(fresh)
        self._all_alerts = fresh + self._all_alerts
        self._all_alerts = self._all_alerts[:200]
        return fresh

    def _persist_alerts(self, alerts: list[LiveAlert]):
        if not persist_data_locally():
            return
        today = date.today().isoformat()
        out_dir = DATA / "live" / today[:7]
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"alerts_{today}.jsonl"
        with path.open("a", encoding="utf-8") as f:
            for a in alerts:
                f.write(json.dumps(a.to_dict(), ensure_ascii=False) + "\n")

    def _load_calendar_daily(self) -> pd.DataFrame:
        live = self.cfg["live"]
        today = date.today()
        start = today - timedelta(days=live.get("lookback_days", 0))
        end = today + timedelta(days=live.get("lookahead_days", 1))
        frames = []
        d = start
        while d <= end:
            cached = DATA / "daily" / f"jogos_{d.isoformat()}.csv"
            try:
                if cached.exists() and cached.stat().st_mtime > time.time() - 3600:
                    df = pd.read_csv(cached)
                else:
                    df = fetch_jogos_do_dia(d.isoformat())
                if not df.empty:
                    df["_fetch_date"] = d.isoformat()
                    frames.append(df)
            except Exception as ex:
                print(f"  aviso calendario {d}: {ex}")
            d += timedelta(days=1)
        if not frames:
            return pd.DataFrame()
        out = pd.concat(frames, ignore_index=True)
        if "Id" in out.columns:
            out = out.drop_duplicates(subset=["Id"], keep="last")
        out = normalize_jogos(out)
        lg_cfg = self.cfg.get("leagues", {})
        mode = lg_cfg.get("filter_mode", "ranked_fpt")
        require_base = bool(lg_cfg.get("require_fpt_base", True))
        return filter_calendar(out, mode=mode, require_fpt_base=require_base)

    def _load_calendar(self) -> pd.DataFrame:
        """Calendário operacional: CSV diário (hoje±janela) tem prioridade sobre semanal."""
        daily = self._load_calendar_daily()
        if not daily.empty:
            return daily

        from .weekly_calendar import load_weekly_dataframe

        weekly = load_weekly_dataframe()
        if weekly.empty:
            return daily

        live = self.cfg["live"]
        today = date.today()
        start = today - timedelta(days=live.get("lookback_days", 0))
        end = today + timedelta(days=live.get("lookahead_days", 1))
        dates = apply_fetch_date(weekly).dt.date
        weekly = weekly.loc[(dates >= start) & (dates <= end)].copy()
        lg_cfg = self.cfg.get("leagues", {})
        return filter_calendar(
            weekly,
            mode=lg_cfg.get("filter_mode", "all_fpt"),
            require_fpt_base=bool(lg_cfg.get("require_fpt_base", False)),
        )

    def _calendar_for_scalp(self, slot_keys: set[str]) -> pd.DataFrame:
        from .weekly_calendar import load_weekly_dataframe

        cal = load_weekly_dataframe()
        if cal.empty:
            cal = self._load_calendar_daily()
        if cal.empty or not slot_keys:
            return pd.DataFrame()
        home_col = next((c for c in cal.columns if c.lower() in ("home", "mandante")), "Home")
        away_col = next((c for c in cal.columns if c.lower() in ("away", "visitante")), "Away")
        mask = []
        for _, row in cal.iterrows():
            h, a = str(row[home_col]), str(row[away_col])
            mask.append(f"{h}|{a}" in slot_keys)
        return cal.loc[mask].copy() if any(mask) else pd.DataFrame()

    def _build_state_from_row(
        self,
        row: pd.Series,
        *,
        home_col: str,
        away_col: str,
        df_hist: pd.DataFrame,
        sim: SimulatedMarket,
        betfair_events: list[dict],
        bf_lookup: dict[str, dict],
        mode: str,
        bankroll: float,
        min_liq: float,
        enrich_sofascore: bool,
        register_alerts: bool,
    ) -> LiveMatchState | None:
        home, away = str(row[home_col]), str(row[away_col])
        if home in ("nan", "") or away in ("nan", ""):
            return None

        league = str(row.get("League", ""))
        league_label = str(row.get("watchlist_league") or watchlist_label(league) or league)
        league_slug = str(row.get("League_Slug", "")) if "League_Slug" in row.index else None
        kickoff = _parse_kickoff(row)
        match_date_str = _match_date_iso(row)
        match_key = f"{home}|{away}"

        market_odds = None
        parsed_bf = None
        if betfair_events:
            parsed_bf = self._bf.match_fpt_to_betfair(home, away, betfair_events, lookup=bf_lookup)
            if parsed_bf:
                tm = parsed_bf.get("total_matched") or 0
                if tm >= min_liq or min_liq <= 0:
                    market_odds = parsed_to_market_odds(parsed_bf)
                    ko_bf = kickoff_from_open_date(parsed_bf.get("open_date"))
                    if ko_bf is not None:
                        kickoff = format_kickoff(ko_bf)

        if market_odds is None:
            if any(c in row.index for c in ("Odd_1_FT", "Odd_H_FT")):
                market_odds = sim.odds_from_row(row)
            else:
                market_odds = sim.get_odds(home, away, league_slug=league_slug)

        bf_live = betfair_market_is_live(parsed_bf) if parsed_bf else bool(market_odds.in_play)
        kickoff_dt = parse_kickoff_dt(kickoff)
        prev = self._prev_odds.get(match_key, {})
        prev_pressure = self._prev_pressure.get(match_key)
        prev_live = self._prev_live.get(match_key)

        partial = LiveMatchState(
            home=home, away=away, league=league, league_label=league_label,
            kickoff=kickoff, status="PRE",
            in_play=bf_live,
            elapsed_min=market_odds.elapsed_min,
            score_home=market_odds.score_home,
            score_away=market_odds.score_away,
        )
        clock_live = False
        if kickoff_dt is not None:
            now_bf = datetime.now(BR)
            clock_live = (
                kickoff_dt - timedelta(minutes=5) <= now_bf <= kickoff_dt + timedelta(minutes=115)
            )
        if enrich_sofascore and self._sofascore.enabled and (mode == "scalp" or bf_live or clock_live):
            try:
                prev_fetch_only = self._sofascore.fetch_in_play_only
                if mode == "scalp":
                    self._sofascore.fetch_in_play_only = False
                partial = self._sofascore.enrich(partial, match_date_str)
                self._sofascore.fetch_in_play_only = prev_fetch_only
            except Exception as ex:
                print(f"  aviso SofaScore {home} x {away}: {ex}")

        ss = partial.sofascore_stats or {}
        bf_mkt = ""
        if parsed_bf:
            bf_mkt = str(parsed_bf.get("status") or market_odds.status or "").upper()
        elif market_odds and market_odds.status:
            bf_mkt = str(market_odds.status).upper()
        resolved = resolve_match_status(
            kickoff_dt=kickoff_dt,
            betfair_in_play=bf_live,
            betfair_market_status=bf_mkt or None,
            betfair_settled=bf_mkt in {"CLOSED", "SETTLED"},
            ss_status_type=ss.get("ss_status_type"),
            ss_minute=partial.elapsed_min,
            elapsed_bf=market_odds.elapsed_min,
        )
        partial.in_play = resolved.in_play
        partial.status = resolved.status

        in_play = resolved.in_play
        sh = partial.score_home if partial.score_home is not None else market_odds.score_home
        sa = partial.score_away if partial.score_away is not None else market_odds.score_away
        elapsed = resolved.elapsed_min if resolved.elapsed_min is not None else partial.elapsed_min
        if elapsed is None:
            elapsed = market_odds.elapsed_min
        status = resolved.status
        score = f"{sh}-{sa}" if sh is not None and sa is not None else "—"

        recs, alerts = evaluate_match_strategies(
            df_hist, home, away, league, league_slug, match_date_str,
            market_odds, bankroll=bankroll, prev_odds=prev,
            in_play=in_play, score=score,
            pressure_home=partial.pressure_home,
            pressure_away=partial.pressure_away,
            prev_pressure=prev_pressure,
            prev_live=prev_live,
            elapsed_min=elapsed,
            row=row,
            sofascore_stats=partial.sofascore_stats,
            graph_momentum=partial.graph_momentum,
            market_id=partial.market_id or market_odds.market_id,
            sofascore_event_id=partial.sofascore_event_id,
        )
        if mode == "scalp":
            alerts = [
                a for a in alerts
                if is_scalp_entry(a.alert_type) or a.alert_type in ("SCALP_EXIT", "HT_EXIT")
            ]
        else:
            alerts = [a for a in alerts if not is_scalp_entry(a.alert_type)]
        fresh_alerts = self._register_alerts(alerts) if register_alerts else alerts

        if partial.pressure_home is not None and partial.pressure_away is not None:
            self._prev_pressure[match_key] = {
                "home": partial.pressure_home,
                "away": partial.pressure_away,
            }
            ss = partial.sofascore_stats or {}
            self._prev_live[match_key] = {
                "xg_home": float(ss.get("ss_xg_home") or 0),
                "xg_away": float(ss.get("ss_xg_away") or 0),
                "pressure_home": partial.pressure_home,
                "pressure_away": partial.pressure_away,
            }

        self._prev_odds[match_key] = {
            m: market_odds.get(m) for m in ("home_win_ft", "draw_ft", "away_win_ft")
            if market_odds.get(m)
        }

        odds_table: dict[str, dict] = {}
        for side, key in [("Casa", "home"), ("Empate", "draw"), ("Visitante", "away")]:
            ex = market_odds.get_exchange(key)
            odds_table[side] = {
                "back": ex.back if ex else None,
                "lay": ex.lay if ex else None,
                "selection_id": ex.selection_id if ex else None,
            }

        best_action, best_market, confidence, _entry_side = pick_best_action(recs, fresh_alerts)
        kelly_quarter = 0.0
        stake_back_pct = 0.0
        stake_lay_pct = 0.0
        prob_h = prob_d = prob_a = None
        for r in recs:
            if r.get("prob_home"):
                prob_h, prob_d, prob_a = r["prob_home"], r["prob_draw"], r["prob_away"]
            sb = float(r.get("stake_back_pct") or r.get("pct_banca") or 0)
            sl = float(r.get("stake_lay_pct") or 0)
            kq = float(r.get("kelly_quarto") or 0)
            stake_back_pct = max(stake_back_pct, sb)
            stake_lay_pct = max(stake_lay_pct, sl)
            kelly_quarter = max(kelly_quarter, kq)
        if best_action == "—" and fresh_alerts:
            a0 = fresh_alerts[0]
            best_action = a0.alert_type
            best_market = a0.market

        return LiveMatchState(
            home=home, away=away, league=league, league_label=league_label,
            kickoff=kickoff, status=status,
            score_home=sh, score_away=sa,
            elapsed_min=elapsed,
            in_play=in_play,
            market_id=market_odds.market_id,
            event_id=market_odds.event_id,
            total_matched=market_odds.total_matched,
            odds_source=market_odds.source,
            odds_updated_at=datetime.now(BR).strftime("%H:%M:%S"),
            prob_home=prob_h, prob_draw=prob_d, prob_away=prob_a,
            odds=odds_table,
            recommendations=recs,
            alerts=fresh_alerts,
            best_action=best_action,
            best_market=best_market,
            confidence=confidence,
            kelly_quarter=kelly_quarter,
            stake_back_pct=stake_back_pct,
            stake_lay_pct=stake_lay_pct,
            sofascore_event_id=partial.sofascore_event_id,
            sofascore_stats=partial.sofascore_stats,
            pressure_home=partial.pressure_home,
            pressure_away=partial.pressure_away,
            graph_momentum=partial.graph_momentum,
        )

    def _build_light_state_from_row(
        self,
        row: pd.Series,
        *,
        home_col: str,
        away_col: str,
        sim: SimulatedMarket,
    ) -> LiveMatchState | None:
        """Estado rápido para dashboard — odds FPT, sem modelo/Betfair/SofaScore."""
        home, away = str(row[home_col]), str(row[away_col])
        if home in ("nan", "") or away in ("nan", ""):
            return None

        league = str(row.get("League", ""))
        league_label = str(row.get("watchlist_league") or watchlist_label(league) or league)
        kickoff = _parse_kickoff(row)
        league_slug = str(row.get("League_Slug", "")) if "League_Slug" in row.index else None

        if any(c in row.index for c in ("Odd_1_FT", "Odd_H_FT")):
            market_odds = sim.odds_from_row(row)
        else:
            market_odds = sim.get_odds(home, away, league_slug=league_slug)

        odds_table: dict[str, dict] = {}
        raw_back = {"Casa": market_odds.home, "Empate": market_odds.draw, "Visitante": market_odds.away}
        for side, key in [("Casa", "home"), ("Empate", "draw"), ("Visitante", "away")]:
            ex = market_odds.get_exchange(key)
            odds_table[side] = {
                "back": ex.back if ex else raw_back[side],
                "lay": ex.lay if ex else None,
                "selection_id": ex.selection_id if ex else None,
            }

        implied = []
        for side in ("Casa", "Empate", "Visitante"):
            b = odds_table[side].get("back")
            implied.append(1.0 / b if b and b > 1.01 else None)
        total = sum(x for x in implied if x)
        if total > 0:
            prob_h, prob_d, prob_a = [(x / total if x else None) for x in implied]
        else:
            prob_h = prob_d = prob_a = None

        kickoff_dt = parse_kickoff_dt(kickoff)
        resolved = resolve_match_status(kickoff_dt=kickoff_dt, betfair_in_play=False)

        return LiveMatchState(
            home=home,
            away=away,
            league=league,
            league_label=league_label,
            kickoff=kickoff,
            status=resolved.status,
            in_play=resolved.in_play,
            elapsed_min=resolved.elapsed_min,
            odds_source=market_odds.source or "fpt_row",
            odds_updated_at=datetime.now(BR).strftime("%H:%M:%S"),
            prob_home=prob_h,
            prob_draw=prob_d,
            prob_away=prob_a,
            odds=odds_table,
        )

    def scan_full(self, df_hist: pd.DataFrame | None = None) -> list[LiveMatchState]:
        return self.scan(df_hist, mode="full")

    def scan_scalp(self, df_hist: pd.DataFrame | None = None, slot_keys: set[str] | None = None) -> list[LiveMatchState]:
        return self.scan(df_hist, mode="scalp", slot_keys=slot_keys)

    def scan(
        self,
        df_hist: pd.DataFrame | None = None,
        *,
        mode: str = "full",
        slot_keys: set[str] | None = None,
    ) -> list[LiveMatchState]:
        from .operation_control import write_scan_heartbeat

        tag = "scalp" if mode == "scalp" else "full"
        write_scan_heartbeat(phase="start", n_games=0)
        df_hist = df_hist if df_hist is not None else load_merged()

        if mode == "scalp":
            cal = self._calendar_for_scalp(slot_keys or set())
        else:
            cal = self._load_calendar()
        if cal.empty:
            self._last_scan = datetime.now(BR)
            write_scan_heartbeat(phase="done", n_games=0)
            return [] if mode == "scalp" else self._states

        write_scan_heartbeat(phase="scanning", n_games=len(cal))

        home_col = next((c for c in cal.columns if c.lower() in ("home", "mandante")), "Home")
        away_col = next((c for c in cal.columns if c.lower() in ("away", "visitante")), "Away")

        betfair_events: list[dict] = []
        game_pairs = [
            (str(row[home_col]), str(row[away_col]))
            for _, row in cal.iterrows()
            if str(row[home_col]) not in ("nan", "") and str(row[away_col]) not in ("nan", "")
        ]
        if self.betfair_ok and game_pairs:
            try:
                betfair_events = self._bf.fetch_odds_for_games(
                    game_pairs,
                    days_ahead=self.cfg["live"].get("lookahead_days", 1),
                )
            except Exception as ex:
                print(f"  aviso Betfair: {ex}")

        bf_lookup = _build_parsed_lookup(betfair_events, game_pairs) if betfair_events else {}
        sim = SimulatedMarket(df_hist)
        bankroll = self.cfg["live"].get("bankroll", 1000.0)
        min_liq = self.cfg.get("betfair", {}).get("min_liquidity", 0)
        ss_cfg = self.cfg.get("sofascore", {})
        enrich_ss = bool(
            self._sofascore.enabled
            and (
                mode == "scalp"
                or ss_cfg.get("enrich_full_scan", False)
                or ss_cfg.get("enrich_live_in_full_scan", True)
            )
        )

        states: list[LiveMatchState] = []
        total = len(cal)

        for idx, (_, row) in enumerate(cal.iterrows(), start=1):
            state = self._build_state_from_row(
                row,
                home_col=home_col,
                away_col=away_col,
                df_hist=df_hist,
                sim=sim,
                betfair_events=betfair_events,
                bf_lookup=bf_lookup,
                mode=mode,
                bankroll=bankroll,
                min_liq=min_liq,
                enrich_sofascore=enrich_ss,
                register_alerts=True,
            )
            if state is None:
                continue
            states.append(state)

            if mode == "full" and idx % _SNAPSHOT_BATCH == 0:
                self._persist_snapshot(states)
                write_scan_heartbeat(phase="scanning", n_games=total, n_done=len(states))

        scalp_exits = self._scalping.evaluate_exits(states)
        if scalp_exits:
            self._register_alerts(scalp_exits)
            for s in states:
                for ex in scalp_exits:
                    if ex.home == s.home and ex.away == s.away:
                        s.alerts = [ex] + s.alerts

        if self.cfg.get("scalping", {}).get("auto_open_on_signal", False):
            for s in states:
                for a in s.alerts:
                    if is_scalp_entry(a.alert_type):
                        self._scalping.open_from_alert(a)

        states.sort(key=lambda s: (0 if s.in_play else 1, s.kickoff))
        live_cfg = self.cfg.get("live", {})
        states = filter_operational_states(
            states,
            lookback_days=int(live_cfg.get("lookback_days", 0)),
            lookahead_days=int(live_cfg.get("lookahead_days", 1)),
        )
        self._last_scan = datetime.now(BR)
        if mode == "full":
            self._states = states
            self._persist_snapshot(states)
        else:
            self._persist_scalp_snapshot(states)
        write_scan_heartbeat(phase="done", n_games=len(states))
        if mode == "full" and self.cfg.get("live", {}).get("log_betfair_ticks", True):
            log_states(states, ts=self._last_scan)
        return states

    def _persist_scalp_snapshot(self, states: list[LiveMatchState]):
        if not persist_data_locally():
            return
        today = date.today().isoformat()
        out_dir = DATA / "live" / today[:7]
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"snapshot_scalp_{today}.json"
        payload = {
            "updated": datetime.now(BR).isoformat(timespec="seconds"),
            "matches": [s.to_dict() for s in states],
        }
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def _persist_snapshot(self, states: list[LiveMatchState]):
        if not persist_data_locally():
            return
        today = date.today().isoformat()
        out_dir = DATA / "live" / today[:7]
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"snapshot_{today}.json"
        payload = {
            "updated": datetime.now(BR).isoformat(timespec="seconds"),
            "matches": [s.to_dict() for s in states],
        }
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    @property
    def last_scan(self) -> datetime | None:
        return self._last_scan

    @property
    def states(self) -> list[LiveMatchState]:
        return self._states

    @property
    def recent_alerts(self) -> list[LiveAlert]:
        return self._all_alerts


def run_live_scan(df_hist: pd.DataFrame | None = None) -> list[LiveMatchState]:
    return LiveMonitor().scan(df_hist)


def load_latest_snapshot() -> list[LiveMatchState]:
    """Último snapshot persistido — carrega UI instantaneamente."""
    if not persist_data_locally():
        return []
    today = date.today().isoformat()
    path = DATA / "live" / today[:7] / f"snapshot_{today}.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    states: list[LiveMatchState] = []
    for m in payload.get("matches") or []:
        odds = m.get("odds") or {}
        score_home = m.get("score_home")
        score_away = m.get("score_away")
        if score_home is None and score_away is None:
            sc = str(m.get("score") or "")
            if "-" in sc and sc != "—":
                parts = sc.split("-", 1)
                try:
                    score_home = int(parts[0].strip())
                    score_away = int(parts[1].strip())
                except ValueError:
                    pass
        states.append(LiveMatchState(
            home=m.get("home", ""),
            away=m.get("away", ""),
            league=m.get("league", ""),
            league_label=m.get("league_label", ""),
            kickoff=m.get("kickoff", ""),
            status=m.get("status", "UNKNOWN"),
            score_home=score_home,
            score_away=score_away,
            elapsed_min=m.get("elapsed_min"),
            in_play=bool(m.get("in_play")),
            market_id=m.get("market_id"),
            event_id=m.get("event_id"),
            total_matched=m.get("total_matched"),
            odds_source=m.get("odds_source", "none"),
            odds_updated_at=m.get("odds_updated_at", ""),
            prob_home=m.get("prob_home"),
            prob_draw=m.get("prob_draw"),
            prob_away=m.get("prob_away"),
            odds=odds,
            recommendations=m.get("recommendations") or [],
            best_action=m.get("best_action", "—"),
            best_market=m.get("best_market", ""),
            confidence=float(m.get("confidence") or 0),
            kelly_quarter=float(m.get("kelly_quarter") or 0),
            stake_back_pct=float(m.get("stake_back_pct") or 0),
            stake_lay_pct=float(m.get("stake_lay_pct") or 0),
            sofascore_event_id=m.get("sofascore_event_id"),
            sofascore_stats=m.get("sofascore_stats") or {},
            pressure_home=m.get("pressure_home"),
            pressure_away=m.get("pressure_away"),
            graph_momentum=m.get("graph_momentum"),
        ))
    for st in states:
        refresh_state_status(st)
    live_cfg = load_live_config().get("live", {})
    return filter_operational_states(
        states,
        lookback_days=int(live_cfg.get("lookback_days", 0)),
        lookahead_days=int(live_cfg.get("lookahead_days", 1)),
    )


def merge_calendar_states(states: list[LiveMatchState]) -> list[LiveMatchState]:
    """Completa jogos faltantes com odds FPT (rápido). Modelo/Betfair vêm do scan."""
    monitor = LiveMonitor()
    cal = monitor._load_calendar_daily()
    if cal.empty:
        return states

    try:
        df_hist = load_merged()
    except FileNotFoundError:
        df_hist = pd.DataFrame()

    sim = SimulatedMarket(df_hist)
    home_col = next((c for c in cal.columns if c.lower() in ("home", "mandante")), "Home")
    away_col = next((c for c in cal.columns if c.lower() in ("away", "visitante")), "Away")

    by_key = {f"{s.home}|{s.away}": s for s in states}
    live_cfg = monitor.cfg.get("live", {})
    lookback = int(live_cfg.get("lookback_days", 0))
    today = date.today()
    earliest = today - timedelta(days=lookback)
    for _, row in cal.iterrows():
        home, away = str(row[home_col]), str(row[away_col])
        if home in ("nan", "") or away in ("nan", ""):
            continue
        try:
            row_day = date.fromisoformat(_match_date_iso(row))
        except ValueError:
            row_day = today
        if row_day < earliest:
            continue
        key = f"{home}|{away}"
        existing = by_key.get(key)
        built = monitor._build_light_state_from_row(
            row, home_col=home_col, away_col=away_col, sim=sim,
        )
        if built is None:
            continue
        if existing:
            if existing.recommendations:
                if not _state_has_odds(existing) and built:
                    existing.odds = built.odds
                    existing.odds_source = built.odds_source
                    existing.odds_updated_at = built.odds_updated_at
                    if existing.prob_home is None:
                        existing.prob_home = built.prob_home
                        existing.prob_draw = built.prob_draw
                        existing.prob_away = built.prob_away
                continue
            if _state_has_odds(existing):
                continue
        by_key[key] = built

    merged = list(by_key.values())
    merged.sort(key=lambda s: (0 if s.in_play else 1, s.kickoff or ""))
    return filter_operational_states(
        merged,
        lookback_days=lookback,
        lookahead_days=int(live_cfg.get("lookahead_days", 1)),
    )

