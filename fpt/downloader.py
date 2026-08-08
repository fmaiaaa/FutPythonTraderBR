from __future__ import annotations

import io
import json
import time
from datetime import date
from pathlib import Path

import pandas as pd
import requests

from .client import DATA, download_url, load_api_key
from .catalog import iter_bases, load_catalog, count_bases
from .leagues import BRAZIL_MALE_LEAGUES

TIMEOUT = 120


def _fetch_csv(url: str) -> pd.DataFrame:
    r = requests.get(url, timeout=TIMEOUT)
    if r.status_code == 401:
        raise PermissionError("API Key inválida ou expirada.")
    if r.status_code == 403:
        raise PermissionError("Acesso negado — verifique assinatura FPT.")
    r.raise_for_status()
    return pd.read_csv(io.StringIO(r.text))


def download_league_season(
    country: str,
    league_slug: str,
    season: str,
    league_name: str = "",
    save: bool = True,
) -> pd.DataFrame:
    api_key = load_api_key()
    url = download_url(country, league_slug, season, api_key)
    df = _fetch_csv(url)
    df["Country"] = country
    df["League_Slug"] = league_slug
    df["League_Name"] = league_name or league_slug
    df["Season"] = season
    if save:
        out_dir = DATA / "raw" / country / league_slug
        out_dir.mkdir(parents=True, exist_ok=True)
        df.to_csv(out_dir / f"{season}.csv", index=False, encoding="utf-8-sig")
    return df


def download_all_brazil_male(pause_sec: float = 0.8) -> dict[str, int]:
    stats: dict[str, int] = {}
    errors: list[str] = []
    for slug, meta in BRAZIL_MALE_LEAGUES.items():
        for season in meta["seasons"]:
            key = f"brazil/{slug}/{season}"
            try:
                df = download_league_season("brazil", slug, season, meta["name"])
                stats[key] = len(df)
                print(f"OK {key}: {len(df)}")
            except Exception as e:
                errors.append(f"{key}: {e}")
                print(f"ERRO {key}: {e}")
            time.sleep(pause_sec)
    _write_errors(errors)
    return stats


def download_catalog(
    country: str | None = None,
    current_season_only: bool = False,
    pause_sec: float = 0.8,
    max_bases: int | None = None,
) -> dict[str, int]:
    """Baixa catálogo global FPT (ou filtrado por país)."""
    catalog = load_catalog()
    stats: dict[str, int] = {}
    errors: list[str] = []
    n = 0
    for c, slug, season, meta in iter_bases(catalog, country):
        if current_season_only and season != meta["seasons"][0]:
            continue
        key = f"{c}/{slug}/{season}"
        try:
            df = download_league_season(c, slug, season, meta["name"])
            stats[key] = len(df)
            print(f"OK {key}: {len(df)}")
        except Exception as e:
            errors.append(f"{key}: {e}")
            print(f"ERRO {key}: {e}")
        n += 1
        if max_bases and n >= max_bases:
            break
        time.sleep(pause_sec)
    _write_errors(errors)
    return stats


def download_incremental_weekly() -> dict[str, int]:
    """Atualização semanal: watchlist (13 ligas) temporada atual + BR histórico."""
    from .catalog import load_catalog
    from .leagues import WATCHLIST_CATALOG

    catalog = load_catalog()
    stats: dict[str, int] = {}
    errors: list[str] = []
    print("=== Watchlist (temporada atual) ===")
    for country, slug, name in WATCHLIST_CATALOG:
        meta = catalog.get(country, {}).get(slug)
        if not meta:
            print(f"  aviso: {country}/{slug} nao no catalogo")
            continue
        season = meta["seasons"][0]
        key = f"{country}/{slug}/{season}"
        try:
            df = download_league_season(country, slug, season, meta.get("name", name))
            stats[key] = len(df)
            print(f"OK {key}: {len(df)}")
        except Exception as e:
            errors.append(f"{key}: {e}")
            print(f"ERRO {key}: {e}")
        time.sleep(0.6)
    _write_errors(errors)
    if not stats:
        raise RuntimeError(
            "Nenhuma liga da watchlist foi baixada. "
            + ("Erros: " + "; ".join(errors[:5]) if errors else "Verifique FPT_API_KEY e assinatura FPT.")
        )
    return stats


def merge_all(glob_country: str | None = None) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    raw = DATA / "raw"
    if not raw.exists():
        raise FileNotFoundError("Nenhum dado em data/raw")
    for csv in raw.rglob("*.csv"):
        if glob_country and glob_country not in str(csv):
            continue
        df = pd.read_csv(csv, low_memory=False)
        frames.append(df)
    if not frames:
        raise FileNotFoundError("CSVs vazios")
    total = pd.concat(frames, ignore_index=True)
    if "Match_ID" in total.columns:
        total = total.drop_duplicates(subset=["Match_ID"], keep="last")
    out_dir = DATA / "merged"
    out_dir.mkdir(parents=True, exist_ok=True)
    _safe_to_parquet(total, out_dir / "global_all.parquet")
    total.to_csv(out_dir / "global_all.csv", index=False, encoding="utf-8-sig")
    # compat legado BR
    br_mask = pd.Series(True, index=total.index)
    if "Country" in total.columns:
        br_mask &= total["Country"].astype(str).str.lower().eq("brazil")
    elif "League_Slug" in total.columns:
        br_mask &= total["League_Slug"].astype(str).str.contains(
            "serie-a|serie-b|serie-c|serie-d|copa-betano", case=False, na=False
        )
    br = total[br_mask]
    if len(br):
        _safe_to_parquet(br, out_dir / "brazil_male_all.parquet")
        br.to_csv(out_dir / "brazil_male_all.csv", index=False, encoding="utf-8-sig")
    return total


def fetch_jogos_do_dia(day: str | None = None) -> pd.DataFrame:
    from .client import jogos_do_dia_url

    day = day or date.today().isoformat()
    url = jogos_do_dia_url(day)
    df = _fetch_csv(url)
    out = DATA / "daily" / f"jogos_{day}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False, encoding="utf-8-sig")
    return df


def _write_errors(errors: list[str]):
    if errors:
        DATA.mkdir(parents=True, exist_ok=True)
        (DATA / "download_errors.txt").write_text("\n".join(errors), encoding="utf-8")


def _safe_to_parquet(df: pd.DataFrame, path: Path) -> None:
    """Parquet exige tipos homogêneos — colunas object viram string."""
    try:
        df.to_parquet(path, index=False)
    except Exception:
        df2 = df.copy()
        for col in df2.select_dtypes(include=["object"]).columns:
            df2[col] = df2[col].astype(str)
        df2.to_parquet(path, index=False)
