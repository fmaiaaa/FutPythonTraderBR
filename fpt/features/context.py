"""Features de contexto do jogo (horário, temporada, forma recente)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def _parse_time_hour(time_val) -> float | None:
    if time_val is None or (isinstance(time_val, float) and np.isnan(time_val)):
        return None
    s = str(time_val).strip()
    if not s or s.lower() in ("nan", "none"):
        return None
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return pd.to_datetime(s, format=fmt).hour + pd.to_datetime(s, format=fmt).minute / 60
        except (ValueError, TypeError):
            continue
    try:
        dt = pd.to_datetime(s, errors="coerce")
        if pd.notna(dt):
            return dt.hour + dt.minute / 60
    except Exception:
        pass
    return None


def match_context_features(row: pd.Series, dt: pd.Timestamp | None = None) -> dict[str, float]:
    """Horário, dia da semana, fase da temporada (proxy por mês)."""
    dt = dt or pd.to_datetime(row.get("Date"), errors="coerce", dayfirst=True)
    feats: dict[str, float] = {}
    if pd.isna(dt):
        return feats

    hour = _parse_time_hour(row.get("Time"))
    if hour is not None:
        feats["ctx_kickoff_hour"] = hour
        feats["ctx_night_game"] = float(hour >= 21 or hour <= 1)
        feats["ctx_afternoon"] = float(14 <= hour <= 18)
    feats["ctx_weekday"] = float(dt.weekday())
    feats["ctx_weekend"] = float(dt.weekday() >= 5)
    feats["ctx_month"] = float(dt.month)
    # proxy clima BR: jogos noturnos/inverno sul
    feats["ctx_winter_month"] = float(dt.month in (6, 7, 8))
    return feats


def season_period_features(
    df_hist: pd.DataFrame,
    home: str,
    away: str,
    match_date: pd.Timestamp,
    season_col: str = "Season",
) -> dict[str, float]:
    """
    Estatísticas só da temporada atual (periodo corrente).
    Usa coluna Season quando disponível; senão últimos 120 dias.
    """
    hist = df_hist.copy()
    hist["_dt"] = pd.to_datetime(hist["Date"], errors="coerce", dayfirst=True)
    hist = hist[hist["_dt"] < match_date]

    season_val = None
    # tenta inferir season do último jogo de qualquer time
    for team in (home, away):
        sub = hist[(hist["Home"] == team) | (hist["Away"] == team)]
        if not sub.empty and season_col in sub.columns:
            season_val = sub.iloc[-1].get(season_col)
            if season_val is not None and str(season_val) not in ("nan", ""):
                break

    if season_val is not None and season_col in hist.columns:
        period = hist[hist[season_col].astype(str) == str(season_val)]
    else:
        cutoff = match_date - pd.Timedelta(days=120)
        period = hist[hist["_dt"] >= cutoff]

    def team_stats(team: str, prefix: str) -> dict[str, float]:
        tg = period[(period["Home"] == team) | (period["Away"] == team)]
        if tg.empty:
            return {f"{prefix}season_ppg": 1.0, f"{prefix}season_gf_pg": 1.2, f"{prefix}season_ga_pg": 1.2,
                    f"{prefix}season_n": 0}
        pts, gf, ga, n = 0, 0.0, 0.0, 0
        for _, r in tg.iterrows():
            hs, aws = r.get("Home_Score"), r.get("Away_Score")
            if pd.isna(hs) or pd.isna(aws):
                continue
            n += 1
            hs, aws = int(hs), int(aws)
            if r["Home"] == team:
                gf += hs
                ga += aws
                pts += 3 if hs > aws else (1 if hs == aws else 0)
            else:
                gf += aws
                ga += hs
                pts += 3 if aws > hs else (1 if hs == aws else 0)
        n = max(n, 1)
        return {
            f"{prefix}season_ppg": pts / n,
            f"{prefix}season_gf_pg": gf / n,
            f"{prefix}season_ga_pg": ga / n,
            f"{prefix}season_n": len(tg),
        }

    h = team_stats(home, "h_")
    a = team_stats(away, "a_")
    out = {**h, **a}
    out["season_ppg_diff"] = h["h_season_ppg"] - a["a_season_ppg"]
    out["season_gf_diff"] = h["h_season_gf_pg"] - a["a_season_gf_pg"]
    return out


def discipline_proxy_features(df_hist: pd.DataFrame, home: str, away: str, n: int = 5) -> dict[str, float]:
    """Proxy desfalques/disciplina: cartões vermelhos recentes."""
    feats: dict[str, float] = {}
    for team, prefix in ((home, "h"), (away, "a")):
        sub = df_hist[
            ((df_hist["Home"] == team) | (df_hist["Away"] == team))
        ].tail(n)
        reds = 0
        for _, r in sub.iterrows():
            if r["Home"] == team:
                rc = r.get("Red_Cards_Home_FT")
            else:
                rc = r.get("Red_Cards_Away_FT")
            try:
                if rc is not None and float(rc) > 0:
                    reds += 1
            except (TypeError, ValueError):
                pass
        feats[f"{prefix}_recent_red_games"] = reds
    feats["discipline_diff"] = feats.get("h_recent_red_games", 0) - feats.get("a_recent_red_games", 0)
    return feats
