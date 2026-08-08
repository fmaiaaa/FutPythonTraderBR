"""Agenda cruzada — times em múltiplos campeonatos simultaneamente."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class ScheduleContext:
    home_days_rest: float | None
    away_days_rest: float | None
    home_games_7d: int
    away_games_7d: int
    home_games_14d: int
    away_games_14d: int
    home_games_21d: int
    away_games_21d: int
    home_prev_league: str | None
    away_prev_league: str | None
    home_cross_comp_4d: bool  # jogou outro campeonato há ≤4 dias
    away_cross_comp_4d: bool
    home_next_days: float | None
    away_next_days: float | None
    home_congestion_score: float
    away_congestion_score: float

    def to_features(self, prefix_h: str = "h_", prefix_a: str = "a_") -> dict[str, float]:
        return {
            f"{prefix_h}days_rest": self.home_days_rest or 7.0,
            f"{prefix_a}days_rest": self.away_days_rest or 7.0,
            f"{prefix_h}games_7d": self.home_games_7d,
            f"{prefix_a}games_7d": self.away_games_7d,
            f"{prefix_h}games_14d": self.home_games_14d,
            f"{prefix_a}games_14d": self.away_games_14d,
            f"{prefix_h}games_21d": self.home_games_21d,
            f"{prefix_a}games_21d": self.away_games_21d,
            f"{prefix_h}cross_comp_4d": float(self.home_cross_comp_4d),
            f"{prefix_a}cross_comp_4d": float(self.away_cross_comp_4d),
            f"{prefix_h}congestion": self.home_congestion_score,
            f"{prefix_a}congestion": self.away_congestion_score,
            f"{prefix_h}next_days": self.home_next_days or 7.0,
            f"{prefix_a}next_days": self.away_next_days or 7.0,
            f"rest_diff": (self.home_days_rest or 7) - (self.away_days_rest or 7),
            f"congestion_diff": self.home_congestion_score - self.away_congestion_score,
        }

    def notes(self, home: str, away: str) -> list[str]:
        notes = []
        if self.home_cross_comp_4d and self.home_prev_league:
            notes.append(f"{home}: jogou {self.home_prev_league} há {self.home_days_rest:.0f}d (outro camp.)")
        if self.away_cross_comp_4d and self.away_prev_league:
            notes.append(f"{away}: jogou {self.away_prev_league} há {self.away_days_rest:.0f}d (outro camp.)")
        if self.home_games_14d >= 5:
            notes.append(f"{home}: {self.home_games_14d} jogos em 14 dias (calendário pesado)")
        if self.away_games_14d >= 5:
            notes.append(f"{away}: {self.away_games_14d} jogos em 14 dias (calendário pesado)")
        return notes


def _parse_dates(df: pd.DataFrame) -> pd.Series:
    return pd.to_datetime(df["Date"], errors="coerce", dayfirst=True)


def build_team_calendar(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Calendário unificado por time (todos campeonatos)."""
    df = df.copy()
    df["_dt"] = _parse_dates(df)
    df = df.dropna(subset=["_dt", "Home", "Away"])
    rows = []
    for _, r in df.iterrows():
        base = {"date": r["_dt"], "league": r.get("League_Slug") or r.get("League", ""),
                "league_name": r.get("League_Name") or r.get("Div", ""), "match_id": r.get("Match_ID")}
        rows.append({**base, "team": r["Home"], "opponent": r["Away"], "venue": "H",
                     "goals_for": r.get("Home_Score"), "goals_against": r.get("Away_Score")})
        rows.append({**base, "team": r["Away"], "opponent": r["Home"], "venue": "A",
                     "goals_for": r.get("Away_Score"), "goals_against": r.get("Home_Score")})
    cal = pd.DataFrame(rows).sort_values(["team", "date"])
    return {team: g.reset_index(drop=True) for team, g in cal.groupby("team")}


def schedule_context(
    calendars: dict[str, pd.DataFrame],
    home: str,
    away: str,
    match_date: pd.Timestamp,
    current_league: str | None = None,
) -> ScheduleContext:
    def _ctx(team: str) -> dict:
        cal = calendars.get(team)
        if cal is None or cal.empty:
            return {"days_rest": None, "games_7d": 0, "games_14d": 0, "games_21d": 0,
                    "prev_league": None, "cross_comp_4d": False, "next_days": None, "congestion": 0.0}
        past = cal[cal["date"] < match_date]
        future = cal[cal["date"] > match_date]
        days_rest = (match_date - past.iloc[-1]["date"]).days if len(past) else None
        prev_league = past.iloc[-1]["league_name"] if len(past) else None
        prev_league_slug = past.iloc[-1]["league"] if len(past) else None
        cross = bool(
            days_rest is not None and days_rest <= 4
            and prev_league_slug and current_league
            and str(prev_league_slug) != str(current_league)
        )
        w7 = past[past["date"] >= match_date - pd.Timedelta(days=7)]
        w14 = past[past["date"] >= match_date - pd.Timedelta(days=14)]
        w21 = past[past["date"] >= match_date - pd.Timedelta(days=21)]
        next_days = (future.iloc[0]["date"] - match_date).days if len(future) else None
        congestion = len(w14) * 0.4 + len(w7) * 0.6
        if days_rest is not None and days_rest <= 3:
            congestion += 1.5
        if cross:
            congestion += 1.0
        return {
            "days_rest": float(days_rest) if days_rest is not None else None,
            "games_7d": len(w7), "games_14d": len(w14), "games_21d": len(w21),
            "prev_league": prev_league, "cross_comp_4d": cross,
            "next_days": float(next_days) if next_days is not None else None,
            "congestion": congestion,
        }

    h, a = _ctx(home), _ctx(away)
    return ScheduleContext(
        home_days_rest=h["days_rest"], away_days_rest=a["days_rest"],
        home_games_7d=h["games_7d"], away_games_7d=a["games_7d"],
        home_games_14d=h["games_14d"], away_games_14d=a["games_14d"],
        home_games_21d=h["games_21d"], away_games_21d=a["games_21d"],
        home_prev_league=h["prev_league"], away_prev_league=a["prev_league"],
        home_cross_comp_4d=h["cross_comp_4d"], away_cross_comp_4d=a["cross_comp_4d"],
        home_next_days=h["next_days"], away_next_days=a["next_days"],
        home_congestion_score=h["congestion"], away_congestion_score=a["congestion"],
    )
