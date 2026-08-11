"""Filtro de calendário — watchlist, todas ligas FPT com base, ou ranking."""
from __future__ import annotations

import re
from functools import lru_cache

import pandas as pd

from .league_ranking import LeagueRank, load_league_rankings
from .leagues import filter_watchlist, is_watchlist_league, watchlist_label

_EXCLUDE_LEAGUE = re.compile(
    r"women|wom\b|\bW\b|\sW\s|u19|u20|u21|u23|youth|juvenil|reserv",
    re.I,
)


def is_excluded_league(league: str) -> bool:
    if not league or str(league).lower() in ("nan", "none", ""):
        return True
    return bool(_EXCLUDE_LEAGUE.search(str(league)))


@lru_cache(maxsize=1)
def known_league_slugs_from_merged() -> frozenset[str]:
    from .pipeline import load_merged

    try:
        df = load_merged(prefer="global")
    except FileNotFoundError:
        return frozenset()
    if "League_Slug" not in df.columns:
        return frozenset()
    slugs = df["League_Slug"].dropna().astype(str).str.strip()
    return frozenset(s for s in slugs.unique() if s and s.lower() != "nan")


def league_slug_from_row(row: pd.Series) -> str | None:
    if "League_Slug" in row.index:
        slug = row.get("League_Slug")
        if slug is not None and str(slug).strip() and str(slug).lower() != "nan":
            return str(slug).strip()
    return None


def has_fpt_base(row: pd.Series, known_slugs: frozenset[str] | None = None) -> bool:
    known = known_slugs if known_slugs is not None else known_league_slugs_from_merged()
    slug = league_slug_from_row(row)
    if slug and slug in known:
        return True
    for col in ("Odd_1_FT", "Odd_H_FT"):
        if col in row.index:
            try:
                v = float(row[col])
                if v > 1.01:
                    return True
            except (TypeError, ValueError):
                pass
    return False


def filter_calendar(
    df: pd.DataFrame,
    *,
    mode: str = "ranked_fpt",
    require_fpt_base: bool = True,
    rankings: dict[str, LeagueRank] | None = None,
) -> pd.DataFrame:
    if df.empty:
        return df

    mode = (mode or "ranked_fpt").lower()
    if mode in ("watchlist", "robust"):
        out = filter_watchlist(df)
        if mode != "robust" or out.empty:
            return out
        ranks = rankings or load_league_rankings()

        def _robust_allowed(row: pd.Series) -> bool:
            slug = league_slug_from_row(row) or ""
            league = str(row.get("League", ""))
            label = watchlist_label(league) if is_watchlist_league(league) else league
            for key in (slug, label, league):
                if not key:
                    continue
                rk = ranks.get(key)
                if rk and rk.tier == 1 and rk.can_operate:
                    return True
            return False

        return out[out.apply(_robust_allowed, axis=1)].copy()

    out = df.copy()
    if "League" in out.columns:
        out = out[~out["League"].astype(str).map(is_excluded_league)]

    known = known_league_slugs_from_merged()
    if require_fpt_base and known:
        mask = out.apply(lambda r: has_fpt_base(r, known), axis=1)
        out = out[mask].copy()

    if mode == "all_fpt":
        if "watchlist_league" not in out.columns and "League" in out.columns:
            out["watchlist_league"] = out["League"].astype(str).map(
                lambda x: watchlist_label(x) or str(x).strip()
            )
        return out

    ranks = rankings or load_league_rankings()
    if not ranks:
        if "watchlist_league" not in out.columns and "League" in out.columns:
            out["watchlist_league"] = out["League"].astype(str).map(
                lambda x: watchlist_label(x) or str(x).strip()
            )
        return out

    def _allowed(row: pd.Series) -> bool:
        slug = league_slug_from_row(row) or ""
        league = str(row.get("League", ""))
        label = watchlist_label(league) if is_watchlist_league(league) else league
        for key in (slug, label, league):
            if not key:
                continue
            rk = ranks.get(key)
            if rk and rk.can_operate:
                return True
        if slug and slug in known:
            rk = ranks.get("_default_probation")
            return rk.can_operate if rk else True
        return False

    out = out[out.apply(_allowed, axis=1)].copy()
    if "watchlist_league" not in out.columns and "League" in out.columns:
        out["watchlist_league"] = out["League"].astype(str).map(
            lambda x: watchlist_label(x) or str(x).strip()
        )
    return out
