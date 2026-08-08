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


def _h2h_features(df_hist: pd.DataFrame, home: str, away: str, n: int = 5) -> dict[str, float]:
    mask = ((df_hist["Home"] == home) & (df_hist["Away"] == away)) | (
        (df_hist["Home"] == away) & (df_hist["Away"] == home)
    )
    sub = df_hist.loc[mask].tail(n)
    if sub.empty:
        return {"h2h_n": 0, "h2h_home_win_rate": 0.33, "h2h_avg_goals": 2.5, "h2h_over25": 0.5}
    home_w = 0
    goals = []
    for _, r in sub.iterrows():
        hs, aws = _safe_float(r["Home_Score"]), _safe_float(r["Away_Score"])
        if hs is None or aws is None:
            continue
        goals.append(hs + aws)
        if r["Home"] == home and hs > aws:
            home_w += 1
        elif r["Away"] == home and aws > hs:
            home_w += 1
    ng = max(len(goals), 1)
    return {
        "h2h_n": len(sub),
        "h2h_home_win_rate": home_w / ng,
        "h2h_avg_goals": float(np.mean(goals)) if goals else 2.5,
        "h2h_over25": sum(1 for g in goals if g > 2) / ng,
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

        # diffs forma geral
        h5 = hs.rolling(5)
        a5 = as_.rolling(5)
        for k in ("ppg", "goals_for", "goals_against", "xg_ft", "win_rate"):
            if f"h_{k}_5" in feats or k in h5:
                hk = feats.get(f"h_{k}_5", h5.get(k.replace("xg_ft", "xg_ft"), 0))
                ak = feats.get(f"a_{k}_5", a5.get(k.replace("xg_ft", "xg_ft"), 0))
                feats[f"diff_{k}_5"] = (hk or 0) - (ak or 0)

        feats["_schedule_notes"] = sched.notes(home, away)
        return feats

    def update_states(self, row: pd.Series):
        for team, venue in [(row["Home"], "H"), (row["Away"], "A")]:
            self._state(team).games.append(_extract_team_game_row(row, team, venue))

    def build_training_matrix(
        self,
        min_history: int = 100,
        progress_every: int = 500,
    ) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
        """Gera X, y_outcome (0=H,1=D,2=A), y_ht_profit para mercado home."""
        self.team_states = {}
        rows, y_out, y_ht = [], [], []

        for i, row in self.df.iterrows():
            if i < min_history:
                self.update_states(row)
                continue
            if pd.isna(row.get("Home_Score")) or pd.isna(row.get("Away_Score")):
                continue
            feats = self.build_row_features(row, self.df.iloc[:i])
            feats.pop("_schedule_notes", None)
            rows.append(feats)

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
        return X, pd.Series(y_out, name="outcome"), pd.Series(y_ht, name="ht_profit_home")


_fb_cache: dict[int, "FeatureBuilder"] = {}


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


def clear_feature_cache():
    _fb_cache.clear()


def build_single_match_features(
    df: pd.DataFrame,
    home: str,
    away: str,
    match_date: str | None = None,
    league_slug: str | None = None,
    market_odds: dict | None = None,
) -> tuple[dict[str, float], list[str]]:
    """Features para um jogo futuro (todos os dados anteriores à data)."""
    df = df.copy()
    df["_dt"] = pd.to_datetime(df["Date"], errors="coerce", dayfirst=True)
    if match_date:
        cutoff = pd.to_datetime(match_date)
        hist = df[df["_dt"] < cutoff]
    else:
        hist = df

    pseudo = {
        "Home": home, "Away": away,
        "Date": match_date or df["_dt"].max(),
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

    fb = get_feature_builder(hist if len(hist) else df)
    row = pd.Series(pseudo)
    feats = fb.build_row_features(row, hist if len(hist) else df)
    notes = feats.pop("_schedule_notes", [])
    return feats, notes
