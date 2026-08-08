from __future__ import annotations

import pandas as pd


def _safe_numeric(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def team_form(df: pd.DataFrame, team: str, last_n: int = 5) -> dict:
    """Forma recente de um time (últimos N jogos)."""
    if df.empty or "Home" not in df.columns:
        return {}
    mask = (df["Home"] == team) | (df["Away"] == team)
    sub = df.loc[mask].copy()
    if "Date" in sub.columns:
        sub = sub.sort_values("Date", ascending=False)
    sub = sub.head(last_n)
    goals_for, goals_against, wins, draws, losses = 0, 0, 0, 0, 0
    over25, btts = 0, 0
    for _, row in sub.iterrows():
        h, a = row.get("Home"), row.get("Away")
        hs, aws = row.get("Home_Score"), row.get("Away_Score")
        if pd.isna(hs) or pd.isna(aws):
            continue
        hs, aws = int(hs), int(aws)
        if h == team:
            goals_for += hs
            goals_against += aws
        else:
            goals_for += aws
            goals_against += hs
        if hs == aws:
            draws += 1
        elif (h == team and hs > aws) or (a == team and aws > hs):
            wins += 1
        else:
            losses += 1
        if hs + aws > 2:
            over25 += 1
        if hs > 0 and aws > 0:
            btts += 1
    n = max(len(sub), 1)
    return {
        "team": team,
        "games": len(sub),
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "goals_for_avg": round(goals_for / n, 2),
        "goals_against_avg": round(goals_against / n, 2),
        "over25_rate": round(100 * over25 / n, 1),
        "btts_rate": round(100 * btts / n, 1),
    }


def league_summary(df: pd.DataFrame, league_slug: str | None = None) -> pd.DataFrame:
    sub = df
    if league_slug and "League_Slug" in df.columns:
        sub = df[df["League_Slug"] == league_slug]
    sub = _safe_numeric(sub, ["Home_Score", "Away_Score", "Corners_Home_FT", "Corners_Away_FT"])
    if sub.empty:
        return pd.DataFrame()
    total_goals = sub["Home_Score"] + sub["Away_Score"]
    return pd.DataFrame([{
        "partidas": len(sub),
        "media_gols": round(total_goals.mean(), 2),
        "over25_pct": round(100 * (total_goals > 2).mean(), 1),
        "btts_pct": round(100 * ((sub["Home_Score"] > 0) & (sub["Away_Score"] > 0)).mean(), 1),
        "media_escanteios": round((sub.get("Corners_Home_FT", 0) + sub.get("Corners_Away_FT", 0)).mean(), 1)
        if "Corners_Home_FT" in sub.columns else None,
    }])


def analyze_matchup(df: pd.DataFrame, home: str, away: str) -> dict:
    """Análise pré-jogo entre dois times com base histórica."""
    h_form = team_form(df, home)
    a_form = team_form(df, away)
    h2h = df[((df["Home"] == home) & (df["Away"] == away)) | ((df["Home"] == away) & (df["Away"] == home))]
    h2h = _safe_numeric(h2h, ["Home_Score", "Away_Score"])
    h2h_stats = {}
    if not h2h.empty and "Home_Score" in h2h.columns:
        tg = h2h["Home_Score"] + h2h["Away_Score"]
        h2h_stats = {
            "jogos": len(h2h),
            "media_gols": round(tg.mean(), 2),
            "over25_pct": round(100 * (tg > 2).mean(), 1),
        }
    combined_avg = (h_form.get("goals_for_avg", 0) + a_form.get("goals_for_avg", 0)) / 2
    return {
        "home": home,
        "away": away,
        "home_form": h_form,
        "away_form": a_form,
        "h2h": h2h_stats,
        "suggested_focus": _suggest_market(h_form, a_form, h2h_stats, combined_avg),
    }


def _suggest_market(h_form: dict, a_form: dict, h2h: dict, combined_avg: float) -> str:
    over_h = h_form.get("over25_rate", 0)
    over_a = a_form.get("over25_rate", 0)
    avg_over = (over_h + over_a) / 2
    if h2h.get("over25_pct", 0) >= 60 or avg_over >= 60:
        return "Over 2.5 gols (histórico favorável)"
    if h_form.get("btts_rate", 0) >= 55 and a_form.get("btts_rate", 0) >= 55:
        return "Ambas marcam (BTTS)"
    if combined_avg <= 1.8 and avg_over <= 40:
        return "Under 2.5 gols"
    return "Mercado aberto — analisar odds manualmente"


def filter_brazil_today(jogos: pd.DataFrame) -> pd.DataFrame:
    """Filtra jogos do dia para competições brasileiras."""
    if jogos.empty:
        return jogos
    country_cols = [c for c in jogos.columns if "country" in c.lower() or c.lower() == "country"]
    league_cols = [c for c in jogos.columns if "league" in c.lower() or c.lower() in ("div", "liga")]
    mask = pd.Series(False, index=jogos.index)
    for c in country_cols:
        mask |= jogos[c].astype(str).str.contains("brazil|brasil", case=False, na=False)
    br_leagues = "serie a|serie b|serie c|serie d|copa|brasileir"
    for c in league_cols:
        mask |= jogos[c].astype(str).str.contains(br_leagues, case=False, na=False)
    if not mask.any():
        return jogos  # retorna tudo se não achar coluna país
    return jogos[mask].copy()
