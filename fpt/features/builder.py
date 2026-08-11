"""Feature engineering completo a partir do histórico FPT."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .columns import (
    LEAGUE_TIER, ODDS_1X2, ODDS_1X2_HT, ODDS_BTTS, ODDS_DC, ODDS_OU_FT, ODDS_OU_HT,
    STAT_FT_AWAY_PREFIX, STAT_FT_HOME_PREFIX, STAT_HT_AWAY_PREFIX, STAT_HT_HOME_PREFIX,
)
from .schedule import ScheduleContext, build_team_calendar, schedule_context
from .context import discipline_proxy_features, match_context_features, season_period_features
from ..trading.ht_trading import ht_state_label, parse_ht_score


ROLL_WINDOWS = [5, 10, 20]


@dataclass
class TeamState:
    games: list[dict] = field(default_factory=list)

    def rolling(self, n: int, venue: str | None = None) -> dict[str, float]:
        g = self.games
        if venue:
            g = [x for x in g if x.get("venue") == venue]
        g = g[-n:]
        if not g:
            return {}
        keys = [k for k in g[0] if k not in ("venue", "date", "opponent", "league")]
        out = {}
        for k in keys:
            vals = [x[k] for x in g if k in x and x[k] is not None and not (isinstance(x[k], float) and np.isnan(x[k]))]
            if vals:
                out[k] = float(np.mean(vals))
        out["n"] = len(g)
        pts = sum(x.get("pts", 0) for x in g)
        out["ppg"] = pts / max(len(g), 1)
        out["win_rate"] = sum(1 for x in g if x.get("pts") == 3) / max(len(g), 1)
        out["over25_rate"] = sum(1 for x in g if x.get("total_goals", 0) > 2) / max(len(g), 1)
        out["btts_rate"] = sum(1 for x in g if x.get("btts")) / max(len(g), 1)
        return out


def _safe_float(v) -> float | None:
    try:
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _implied_prob(odd: float | None) -> float | None:
    if odd is None or odd <= 1.01:
        return None
    return 1.0 / odd


def _extract_team_game_row(row: pd.Series, team: str, venue: str) -> dict:
    is_home = venue == "H"
    opp = row["Away"] if is_home else row["Home"]
    gf = _safe_float(row["Home_Score"] if is_home else row["Away_Score"])
    ga = _safe_float(row["Away_Score"] if is_home else row["Home_Score"])
    pts = 0
    if gf is not None and ga is not None:
        if gf > ga:
            pts = 3
        elif gf == ga:
            pts = 1
    stat_map = {}
    prefixes = (STAT_FT_HOME_PREFIX, STAT_HT_HOME_PREFIX) if is_home else (STAT_FT_AWAY_PREFIX, STAT_HT_AWAY_PREFIX)
    for col_list in prefixes:
        for col in col_list:
            short = col.replace("_Home_", "_").replace("_Away_", "_").lower()
            stat_map[short] = _safe_float(row.get(col))
    return {
        "date": pd.to_datetime(row["Date"], errors="coerce", dayfirst=True),
        "venue": venue,
        "opponent": opp,
        "league": row.get("League_Slug"),
        "goals_for": gf,
        "goals_against": ga,
        "total_goals": (gf or 0) + (ga or 0),
        "pts": pts,
        "btts": bool(gf and ga and gf > 0 and ga > 0),
        **stat_map,
    }


def _h2h_features(df_hist: pd.DataFrame, home: str, away: str, n: int = 10) -> dict[str, float]:
    mask = ((df_hist["Home"] == home) & (df_hist["Away"] == away)) | (
        (df_hist["Home"] == away) & (df_hist["Away"] == home)
    )
    sub = df_hist.loc[mask].tail(n)
    if sub.empty:
        return {
            "h2h_n": 0, "h2h_home_win_rate": 0.33, "h2h_draw_rate": 0.28,
            "h2h_avg_goals": 2.5, "h2h_over25": 0.5, "h2h_btts": 0.5,
            "h2h_home_gf_pg": 1.2, "h2h_recent_home_win": 0.33,
        }
    home_w = draws = 0
    goals = []
    home_goals = []
    for _, r in sub.iterrows():
        hs, aws = _safe_float(r["Home_Score"]), _safe_float(r["Away_Score"])
        if hs is None or aws is None:
            continue
        goals.append(hs + aws)
        if r["Home"] == home:
            home_goals.append(hs)
            if hs > aws:
                home_w += 1
            elif hs == aws:
                draws += 1
        else:
            home_goals.append(aws)
            if aws > hs:
                home_w += 1
            elif hs == aws:
                draws += 1
    ng = max(len(goals), 1)
    recent = sub.tail(3)
    rh_w = 0
    rn = 0
    for _, r in recent.iterrows():
        hs, aws = _safe_float(r["Home_Score"]), _safe_float(r["Away_Score"])
        if hs is None or aws is None:
            continue
        rn += 1
        if r["Home"] == home and hs > aws:
            rh_w += 1
        elif r["Away"] == home and aws > hs:
            rh_w += 1
    return {
        "h2h_n": len(sub),
        "h2h_home_win_rate": home_w / ng,
        "h2h_draw_rate": draws / ng,
        "h2h_avg_goals": float(np.mean(goals)) if goals else 2.5,
        "h2h_over25": sum(1 for g in goals if g > 2) / ng,
        "h2h_btts": sum(1 for g in goals if g >= 2) / ng if goals else 0.5,
        "h2h_home_gf_pg": float(np.mean(home_goals)) if home_goals else 1.2,
        "h2h_recent_home_win": rh_w / max(rn, 1),
    }


def _odds_features(row: pd.Series) -> dict[str, float]:
    feats = {}
    for col in ODDS_1X2 + ODDS_1X2_HT + ODDS_OU_FT + ODDS_OU_HT + ODDS_BTTS + ODDS_DC:
        if col in row.index:
            v = _safe_float(row[col])
            feats[f"mkt_{col.lower()}"] = v if v else np.nan
            ip = _implied_prob(v)
            if ip:
                feats[f"impl_{col.lower()}"] = ip
    # margem bookmaker 1x2
    o1, ox, o2 = [_safe_float(row.get(c)) for c in ODDS_1X2]
    if all(x and x > 1.01 for x in (o1, ox, o2)):
        overround = 1 / o1 + 1 / ox + 1 / o2
        feats["mkt_overround_1x2"] = overround
        feats["impl_home_norm"] = (1 / o1) / overround
        feats["impl_draw_norm"] = (1 / ox) / overround
        feats["impl_away_norm"] = (1 / o2) / overround

    # Betfair exchange (live / enriquecimento)
    for side in ("home", "draw", "away"):
        bb = _safe_float(row.get(f"bf_back_{side}"))
        bl = _safe_float(row.get(f"bf_lay_{side}"))
        if bb and bb > 1.01:
            feats[f"bf_impl_{side}"] = 1 / bb
        if bl and bl > 1.01:
            feats[f"bf_impl_lay_{side}"] = 1 / bl
        if bb and bl and bb > 1.01:
            feats[f"bf_spread_{side}"] = (bl - bb) / bb
    bf_backs = [_safe_float(row.get(f"bf_back_{s}")) for s in ("home", "draw", "away")]
    if all(x and x > 1.01 for x in bf_backs):
        inv = [1 / x for x in bf_backs]
        s = sum(inv)
        feats["bf_overround_back"] = s
        feats["bf_impl_home_norm"] = inv[0] / s
        feats["bf_impl_draw_norm"] = inv[1] / s
        feats["bf_impl_away_norm"] = inv[2] / s
    tm = _safe_float(row.get("bf_total_matched"))
    if tm:
        feats["bf_log_matched"] = float(np.log1p(tm))
    if _safe_float(row.get("bf_in_play")):
        feats["bf_in_play"] = 1.0
    return feats


def _table_proxy(st: TeamState, league: str | None) -> dict[str, float]:
    lg_games = [g for g in st.games if not league or g.get("league") == league]
    pts = sum(g.get("pts", 0) for g in lg_games)
    n = max(len(lg_games), 1)
    gf = sum(g.get("goals_for") or 0 for g in lg_games)
    ga = sum(g.get("goals_against") or 0 for g in lg_games)
    return {"table_ppg": pts / n, "table_gd_pg": (gf - ga) / n, "table_games": len(lg_games)}


class FeatureBuilder:
    def __init__(self, df: pd.DataFrame):
        self.df = df.sort_values("Date").reset_index(drop=True)
        self.calendars = build_team_calendar(df)
        self.team_states: dict[str, TeamState] = {}

    def _state(self, team: str) -> TeamState:
        if team not in self.team_states:
            self.team_states[team] = TeamState()
        return self.team_states[team]

    def build_row_features(
        self,
        row: pd.Series,
        df_hist: pd.DataFrame | None = None,
    ) -> dict[str, float]:
        home, away = row["Home"], row["Away"]
        league = row.get("League_Slug")
        dt = pd.to_datetime(row["Date"], errors="coerce", dayfirst=True)
        hs, as_ = self._state(home), self._state(away)

        feats: dict[str, float] = {
            "league_tier": LEAGUE_TIER.get(str(league), 3),
            "is_copa": float("copa" in str(league or "").lower()),
        }

        for w in ROLL_WINDOWS:
            for prefix, st, ven in [("h", hs, "H"), ("h_away", hs, "A"), ("a", as_, "A"), ("a_home", as_, "H")]:
                r = st.rolling(w, venue=ven)
                for k, v in r.items():
                    feats[f"{prefix}_{k}_{w}"] = v

        for prefix, st, lg in [("h", hs, league), ("a", as_, league)]:
            tb = _table_proxy(st, lg)
            for k, v in tb.items():
                feats[f"{prefix}_{k}"] = v

        sched = schedule_context(self.calendars, home, away, dt, league)
        feats.update(sched.to_features())

        hist = df_hist if df_hist is not None else self.df[self.df["Date"] < row["Date"]]
        feats.update(_h2h_features(hist, home, away))
        feats.update(_odds_features(row))
        feats.update(match_context_features(row, dt))
        feats.update(season_period_features(hist, home, away, dt if pd.notna(dt) else pd.Timestamp.now()))
        feats.update(discipline_proxy_features(hist, home, away))

        # diffs forma geral
        h5 = hs.rolling(5)
        a5 = as_.rolling(5)
        for k in ("ppg", "goals_for", "goals_against", "xg_ft", "win_rate"):
            if f"h_{k}_5" in feats or k in h5:
                hk = feats.get(f"h_{k}_5", h5.get(k.replace("xg_ft", "xg_ft"), 0))
                ak = feats.get(f"a_{k}_5", a5.get(k.replace("xg_ft", "xg_ft"), 0))
                feats[f"diff_{k}_5"] = (hk or 0) - (ak or 0)

        # Fator casa × visitante (mandante em casa vs visitante fora)
        h_home10 = hs.rolling(10, venue="H")
        h_away10 = hs.rolling(10, venue="A")
        a_away10 = as_.rolling(10, venue="A")
        a_home10 = as_.rolling(10, venue="H")
        feats["home_ppg_casa_10"] = h_home10.get("ppg", 1.0)
        feats["away_ppg_fora_10"] = a_away10.get("ppg", 1.0)
        feats["home_gf_casa_10"] = h_home10.get("goals_for", 1.2)
        feats["away_ga_fora_10"] = a_away10.get("goals_against", 1.2)
        feats["home_advantage_ppg"] = feats["home_ppg_casa_10"] - feats["away_ppg_fora_10"]
        feats["home_advantage_attack"] = feats["home_gf_casa_10"] - feats["away_ga_fora_10"]
        feats["home_advantage_combined"] = (
            feats["home_advantage_ppg"] * 0.6 + feats["home_advantage_attack"] * 0.4
        )
        feats["home_win_rate_casa_10"] = h_home10.get("win_rate", 0.33)
        feats["away_win_rate_fora_10"] = a_away10.get("win_rate", 0.33)
        feats["venue_factor"] = feats["home_win_rate_casa_10"] - feats["away_win_rate_fora_10"]

        feats["_schedule_notes"] = sched.notes(home, away)
        return feats

    def update_states(self, row: pd.Series):
        for team, venue in [(row["Home"], "H"), (row["Away"], "A")]:
            self._state(team).games.append(_extract_team_game_row(row, team, venue))

    def build_training_matrix(
        self,
        min_history: int = 100,
        progress_every: int = 500,
        return_indices: bool = False,
    ) -> tuple[pd.DataFrame, pd.Series, pd.Series] | tuple[pd.DataFrame, pd.Series, pd.Series, pd.Series]:
        """Gera X, y_outcome (0=H,1=D,2=A), y_ht_profit para mercado home."""
        self.team_states = {}
        rows, y_out, y_ht, row_indices = [], [], [], []

        for i, row in self.df.iterrows():
            if i < min_history:
                self.update_states(row)
                continue
            if pd.isna(row.get("Home_Score")) or pd.isna(row.get("Away_Score")):
                continue
            feats = self.build_row_features(row, self.df.iloc[:i])
            feats.pop("_schedule_notes", None)
            rows.append(feats)
            row_indices.append(i)

            hs, aws = int(row["Home_Score"]), int(row["Away_Score"])
            if hs > aws:
                y_out.append(0)
            elif hs == aws:
                y_out.append(1)
            else:
                y_out.append(2)

            # target HT trade: back home @ Odd_1_FT, saída proxy no HT
            entry = _safe_float(row.get("Odd_1_FT"))
            if entry and entry > 1.05:
                hg, ag = parse_ht_score(row.get("Min_Goals_Home"), row.get("Min_Goals_Away"))
                state = ht_state_label(hg, ag, "home_win_ft")
                mult = {"home_leading": 0.62, "draw": 0.90, "home_losing": 1.38}.get(state, 1.0)
                exit_odd = entry * mult
                profit = (entry / exit_odd - 1) * 0.90  # ~5% comissão ida+volta
                y_ht.append(1 if profit > 0.02 else 0)
            else:
                y_ht.append(np.nan)

            self.update_states(row)
            if progress_every and i % progress_every == 0:
                print(f"  features: {len(rows)} amostras...")

        X = pd.DataFrame(rows)
        y_out_s = pd.Series(y_out, name="outcome")
        y_ht_s = pd.Series(y_ht, name="ht_profit_home")
        if return_indices:
            return X, y_out_s, y_ht_s, pd.Series(row_indices, name="df_index")
        return X, y_out_s, y_ht_s


_fb_cache: dict[int, "FeatureBuilder"] = {}
_fb_by_cutoff: dict[tuple[int, str], "FeatureBuilder"] = {}


def get_feature_builder(df: pd.DataFrame) -> "FeatureBuilder":
    """Cache do FeatureBuilder por id do dataframe — evita rebuild a cada jogo."""
    key = id(df)
    if key not in _fb_cache:
        hist = df.copy()
        if "Date" in hist.columns:
            hist["_dt"] = pd.to_datetime(hist["Date"], errors="coerce", dayfirst=True)
            hist = hist.sort_values("_dt")
        fb = FeatureBuilder(hist)
        for _, r in hist.iterrows():
            fb.update_states(r)
        _fb_cache[key] = fb
    return _fb_cache[key]


def _feature_builder_for_cutoff(df: pd.DataFrame, match_date: str | None) -> tuple["FeatureBuilder", pd.DataFrame]:
    """FeatureBuilder cacheado por (dataframe, data de corte) — scan live usa o mesmo histórico."""
    md_key = str(match_date or "")
    cache_key = (id(df), md_key)
    dt_series = pd.to_datetime(df["Date"], errors="coerce", dayfirst=True)
    if match_date:
        hist = df.loc[dt_series < pd.to_datetime(match_date)]
    else:
        hist = df
    if cache_key not in _fb_by_cutoff:
        h = hist.copy()
        h["_dt"] = pd.to_datetime(h["Date"], errors="coerce", dayfirst=True)
        h = h.sort_values("_dt").reset_index(drop=True)
        fb = FeatureBuilder(h)
        for _, r in h.iterrows():
            fb.update_states(r)
        _fb_by_cutoff[cache_key] = fb
    return _fb_by_cutoff[cache_key], hist


def clear_feature_cache():
    _fb_cache.clear()
    _fb_by_cutoff.clear()


def build_single_match_features(
    df: pd.DataFrame,
    home: str,
    away: str,
    match_date: str | None = None,
    league_slug: str | None = None,
    market_odds: dict | None = None,
) -> tuple[dict[str, float], list[str]]:
    """Features para um jogo futuro (todos os dados anteriores à data)."""
    fb, hist = _feature_builder_for_cutoff(df, match_date)
    dt_series = pd.to_datetime(df["Date"], errors="coerce", dayfirst=True)

    pseudo = {
        "Home": home, "Away": away,
        "Date": match_date or dt_series.max(),
        "League_Slug": league_slug,
    }
    if market_odds:
        for k, v in market_odds.items():
            pseudo[k] = v
    elif len(hist):
        mask = ((hist["Home"] == home) & (hist["Away"] == away))
        if mask.any() and league_slug and "League_Slug" in hist.columns:
            mask &= hist["League_Slug"] == league_slug
        if mask.any():
            for c in ODDS_1X2 + ODDS_OU_FT + ODDS_BTTS:
                if c in hist.columns:
                    pseudo[c] = hist.loc[mask].iloc[-1][c]

    row = pd.Series(pseudo)
    feats = fb.build_row_features(row, hist if len(hist) else df)
    notes = feats.pop("_schedule_notes", [])
    return feats, notes
