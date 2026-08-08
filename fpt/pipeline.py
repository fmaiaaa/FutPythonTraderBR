from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from .downloader import fetch_jogos_do_dia, merge_all
from .client import DATA
from .operation import analyze_matchup, filter_brazil_today, league_summary
from .leagues import BRAZIL_MALE_LEAGUES


def load_merged() -> pd.DataFrame:
    p = DATA / "merged" / "brazil_male_all.parquet"
    if p.exists():
        return pd.read_parquet(p)
    csv = DATA / "merged" / "brazil_male_all.csv"
    if csv.exists():
        return pd.read_csv(csv, low_memory=False)
    raise FileNotFoundError("Dataset não encontrado. Rode: python main.py download-all")


def run_daily_operation(day: str | None = None) -> dict:
    """Operação diária: jogos do dia + análise com base histórica BR masculina."""
    day = day or date.today().isoformat()
    hist = load_merged()
    jogos = fetch_jogos_do_dia(day)
    br = filter_brazil_today(jogos)

    analyses = []
    home_col = next((c for c in br.columns if c.lower() in ("home", "mandante", "time_mandante")), None)
    away_col = next((c for c in br.columns if c.lower() in ("away", "visitante", "time_visitante")), None)

    if home_col and away_col:
        for _, row in br.iterrows():
            home, away = str(row[home_col]), str(row[away_col])
            if home == "nan" or away == "nan":
                continue
            analyses.append(analyze_matchup(hist, home, away))

    report = {
        "date": day,
        "jogos_total": len(jogos),
        "jogos_brazil": len(br),
        "analyses": analyses,
        "league_stats": {
            slug: league_summary(hist, slug).to_dict("records")[0]
            for slug in BRAZIL_MALE_LEAGUES
            if not league_summary(hist, slug).empty
        },
    }

    out = DATA / "daily" / f"operacao_{day}.txt"
    lines = [
        f"=== Operação FutPythonTrader BR — {day} ===",
        f"Jogos do dia (total): {report['jogos_total']}",
        f"Jogos Brasil: {report['jogos_brazil']}",
        "",
        "--- Resumo por campeonato (histórico) ---",
    ]
    for slug, st in report["league_stats"].items():
        name = BRAZIL_MALE_LEAGUES[slug]["name"]
        lines.append(f"{name}: média {st.get('media_gols')} gols | Over2.5 {st.get('over25_pct')}%")
    lines.append("")
    lines.append("--- Análises jogos BR hoje ---")
    for a in analyses:
        lines.append(f"\n{a['home']} x {a['away']}")
        lines.append(f"  Foco: {a['suggested_focus']}")
        hf, af = a["home_form"], a["away_form"]
        if hf:
            lines.append(f"  {a['home']}: {hf.get('wins')}V/{hf.get('draws')}E/{hf.get('losses')}D | Over2.5 {hf.get('over25_rate')}%")
        if af:
            lines.append(f"  {a['away']}: {af.get('wins')}V/{af.get('draws')}E/{af.get('losses')}D | Over2.5 {af.get('over25_rate')}%")
        if a.get("h2h"):
            lines.append(f"  H2H: {a['h2h']}")

    out.write_text("\n".join(lines), encoding="utf-8")
    report["report_path"] = str(out)
    return report
