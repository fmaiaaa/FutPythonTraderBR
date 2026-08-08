from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from ..calendar import normalize_jogos
from ..client import DATA
from ..downloader import fetch_jogos_do_dia
from ..leagues import filter_watchlist, watchlist_label
from ..pipeline import load_merged
from ..trading.market_betfair import BetfairMarket, parsed_to_market_odds
from ..trading.market_sim import SimulatedMarket
from .config import load_live_config
from .models import LiveAlert, LiveMatchState
from .betfair_logger import log_states
from .strategies import evaluate_match_strategies

BR = ZoneInfo("America/Sao_Paulo")


def _parse_kickoff(row: pd.Series) -> str:
    dt = pd.to_datetime(row.get("Date"), dayfirst=True, errors="coerce")
    if pd.isna(dt):
        return "—"
    if dt.tzinfo is None:
        dt = dt.tz_localize(BR)
    else:
        dt = dt.tz_convert(BR)
    return dt.strftime("%d/%m/%Y %H:%M")


def _match_status(in_play: bool, score_home, score_away, kickoff_str: str) -> str:
    if in_play:
        return "LIVE"
    now = datetime.now(BR)
    try:
        ko = datetime.strptime(kickoff_str, "%d/%m/%Y %H:%M").replace(tzinfo=BR)
        if now < ko:
            return "PRE"
        if now >= ko + timedelta(hours=2, minutes=30):
            return "FT"
        return "LIVE?"
    except ValueError:
        return "UNKNOWN"


class LiveMonitor:
    """Monitor in-time: placares Betfair + odds + alertas do modelo."""

    def __init__(self):
        self.cfg = load_live_config()
        self._bf = BetfairMarket()
        self._prev_odds: dict[str, dict[str, float]] = {}
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
        today = date.today().isoformat()
        out_dir = DATA / "live" / today[:7]
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"alerts_{today}.jsonl"
        with path.open("a", encoding="utf-8") as f:
            for a in alerts:
                f.write(json.dumps(a.to_dict(), ensure_ascii=False) + "\n")

    def _load_calendar(self) -> pd.DataFrame:
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
        return filter_watchlist(out)

    def scan(self, df_hist: pd.DataFrame | None = None) -> list[LiveMatchState]:
        df_hist = df_hist if df_hist is not None else load_merged()
        cal = self._load_calendar()
        if cal.empty:
            self._states = []
            self._last_scan = datetime.now(BR)
            return self._states

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

        sim = SimulatedMarket(df_hist)
        bankroll = self.cfg["live"].get("bankroll", 1000.0)
        min_liq = self.cfg.get("betfair", {}).get("min_liquidity", 0)

        states: list[LiveMatchState] = []

        for _, row in cal.iterrows():
            home, away = str(row[home_col]), str(row[away_col])
            if home in ("nan", "") or away in ("nan", ""):
                continue

            league = str(row.get("League", ""))
            league_label = str(row.get("watchlist_league") or watchlist_label(league) or league)
            league_slug = str(row.get("League_Slug", "")) if "League_Slug" in row.index else None
            kickoff = _parse_kickoff(row)
            match_date = pd.to_datetime(row.get("Date"), dayfirst=True, errors="coerce")
            match_date_str = match_date.date().isoformat() if not pd.isna(match_date) else date.today().isoformat()

            # Odds: Betfair > FPT row > simulado
            market_odds = None
            parsed_bf = None
            if betfair_events:
                parsed_bf = self._bf.match_fpt_to_betfair(home, away, betfair_events)
                if parsed_bf:
                    tm = parsed_bf.get("total_matched") or 0
                    if tm >= min_liq or min_liq <= 0:
                        market_odds = parsed_to_market_odds(parsed_bf)

            if market_odds is None:
                if "Odd_1_FT" in row.index:
                    market_odds = sim.odds_from_row(row)
                else:
                    market_odds = sim.get_odds(home, away, league_slug=league_slug)

            in_play = bool(market_odds.in_play)
            sh, sa = market_odds.score_home, market_odds.score_away
            status = _match_status(in_play, sh, sa, kickoff)
            score = market_odds.score_display if sh is not None else "—"

            match_key = f"{home}|{away}"
            prev = self._prev_odds.get(match_key, {})

            recs, alerts = evaluate_match_strategies(
                df_hist, home, away, league, league_slug, match_date_str,
                market_odds, bankroll=bankroll, prev_odds=prev,
                in_play=in_play, score=score,
            )
            fresh_alerts = self._register_alerts(alerts)

            # Atualiza prev odds
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

            best_action = "—"
            best_market = ""
            confidence = 0.0
            prob_h = prob_d = prob_a = None
            for r in recs:
                if r.get("prob_home"):
                    prob_h, prob_d, prob_a = r["prob_home"], r["prob_draw"], r["prob_away"]
                if r.get("action") == "ENTER":
                    best_action = "ENTER"
                    best_market = r.get("market_label", r.get("market", ""))
                    confidence = r.get("confianca", 0)
                    break
            if best_action == "—" and fresh_alerts:
                best_action = fresh_alerts[0].alert_type
                best_market = fresh_alerts[0].market

            state = LiveMatchState(
                home=home, away=away, league=league, league_label=league_label,
                kickoff=kickoff, status=status,
                score_home=sh, score_away=sa,
                elapsed_min=market_odds.elapsed_min,
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
            )
            states.append(state)

        states.sort(key=lambda s: (0 if s.in_play else 1, s.kickoff))
        self._states = states
        self._last_scan = datetime.now(BR)
        self._persist_snapshot(states)
        if self.cfg.get("live", {}).get("log_betfair_ticks", True):
            log_states(states, ts=self._last_scan)
        return states

    def _persist_snapshot(self, states: list[LiveMatchState]):
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
