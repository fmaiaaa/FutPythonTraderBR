"""Rotina de fim de semana — calendario, odds, stakes."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd

from .calendar import build_calendar, enrich_with_schedule, list_market_odds, weekend_window
from .client import DATA
from .downloader import download_incremental_weekly, merge_all
from .markets import JOGOS_DIA_MARKETS, TRADING_MARKETS
from .models.train import train_models
from .pipeline import load_merged
from .trading.engine import build_recommendation
from .trading.market_sim import MarketOdds
from .trading.the_odds_api import enrich_calendar_with_odds_api, remaining_budget


def _load_hist() -> pd.DataFrame:
    try:
        return load_merged()
    except FileNotFoundError:
        p = DATA / "merged" / "global_all.parquet"
        if p.exists():
            return pd.read_parquet(p)
        raise


def row_to_market_odds(row: pd.Series) -> MarketOdds:
    """Odds FPT do calendario; The Odds API como override se disponivel."""
    h = _f(row.get("Odd_1_FT") or row.get("Odd_H_FT"))
    d = _f(row.get("Odd_X_FT") or row.get("Odd_D_FT"))
    a = _f(row.get("Odd_2_FT") or row.get("Odd_A_FT"))
    if _f(row.get("odds_api_home")):
        h = _f(row.get("odds_api_home")) or h
    if _f(row.get("odds_api_draw")):
        d = _f(row.get("odds_api_draw")) or d
    if _f(row.get("odds_api_away")):
        a = _f(row.get("odds_api_away")) or a
    src = "fpt+odds_api" if row.get("odds_api_home") else "fpt_jogos_dia"
    return MarketOdds(home=h, draw=d, away=a, source=src)


def _f(v):
    try:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        x = float(v)
        return x if x > 1.01 else None
    except (TypeError, ValueError):
        return None


def scan_weekend(
    cal: pd.DataFrame,
    hist: pd.DataFrame,
    brazil_only: bool = True,
    bankroll: float | None = None,
) -> list[dict]:
    from .trading.config import load_config

    bankroll = bankroll or load_config()["trading"]["bankroll"]
    sub = cal[cal["is_brazil"]] if brazil_only and "is_brazil" in cal.columns else cal
    entries = []

    for _, row in sub.iterrows():
        home, away = str(row["Home"]), str(row["Away"])
        if home in ("nan", "") or away in ("nan", ""):
            continue
        match_date = str(row["Date"])[:10]
        odds = row_to_market_odds(row)
        all_market_odds = list_market_odds(row)

        for mkt in TRADING_MARKETS:
            rec = build_recommendation(
                hist, home, away, market=mkt, market_odds=odds,
                match_date=match_date, bankroll=bankroll,
            )
            entries.append({
                "date": match_date,
                "time": row.get("Time"),
                "league": row.get("League"),
                "home": home,
                "away": away,
                "market": mkt,
                "action": rec.action,
                "prob": rec.probabilidade_estimada,
                "odd_justa": rec.odd_justa,
                "phi": rec.phi_seguranca,
                "odd_min": rec.odd_minima_entrada,
                "odd_mercado": rec.odd_mercado,
                "edge_pp": rec.edge_pp,
                "lucro_est_pct": rec.lucro_estimado_pct,
                "pct_banca": rec.pct_banca,
                "stake": rec.stake_valor,
                "confianca": rec.confianca,
                "odds_source": odds.source,
                "schedule_notes": " | ".join(rec.schedule_notes),
                "all_markets_count": len(all_market_odds),
            })
    return entries


def format_weekend_report(entries: list[dict], meta: dict) -> str:
    enters = [e for e in entries if e["action"] == "ENTER"]
    lines = [
        "=" * 70,
        f"RELATORIO FIM DE SEMANA — {meta.get('start')} a {meta.get('end')}",
        f"Jogos no calendario: {meta.get('n_games')} | Entradas: {len(enters)}",
        f"The Odds API creditos restantes: {meta.get('odds_api_remaining', 'N/A')}",
        "=" * 70,
        "",
    ]
    for e in sorted(enters, key=lambda x: -(x.get("edge_pp") or 0)):
        lines += [
            f"{e['date']} {e.get('time','')} | {e['league']}",
            f"  {e['home']} x {e['away']}  [{e['market']}]",
            f"  Prob={e['prob']:.1%} | Justa={e['odd_justa']:.2f} | phi={e['phi']:.3f} | Min={e['odd_min']:.2f}",
            f"  Mercado={e['odd_mercado']} | Edge={e['edge_pp']}p.p. | LucroHT={e['lucro_est_pct']:+.2f}%",
            f"  Stake={e['pct_banca']:.2%} (R$ {e['stake']:.2f}) | Conf={e['confianca']:.0f}",
            f"  Fonte odds: {e['odds_source']}",
        ]
        if e.get("schedule_notes"):
            lines.append(f"  Agenda: {e['schedule_notes']}")
        lines.append("")
    if not enters:
        lines.append("Nenhuma entrada recomendada neste fim de semana.")
    return "\n".join(lines)


def run_weekend_pipeline(
    update_data: bool = True,
    retrain: bool = True,
    use_odds_api: bool = True,
    brazil_only: bool = True,
) -> dict:
    start, end = weekend_window()
    meta = {"start": str(start), "end": str(end)}

    if update_data:
        print("\n[1/6] Atualizando bases FPT...")
        download_incremental_weekly()
        merge_all()
        meta["data_updated"] = True

    hist = _load_hist()

    print("\n[2/6] Montando calendario (hoje -> domingo)...")
    cal = build_calendar(start, end, brazil_only=False)
    cal = enrich_with_schedule(cal, hist)
    meta["n_games"] = len(cal)
    if brazil_only:
        cal_br = cal[cal["is_brazil"]].copy() if "is_brazil" in cal.columns else cal
    else:
        cal_br = cal
    meta["n_games_br"] = len(cal_br)

    if use_odds_api:
        print("\n[3/6] The Odds API (prioridade fim de semana BR)...")
        cal = enrich_calendar_with_odds_api(cal_br if brazil_only else cal, hist)
        meta["odds_api_remaining"] = remaining_budget()
    else:
        cal = cal_br
        print("\n[3/6] The Odds API desligada")

    if retrain:
        print("\n[4/6] Re-treinando modelos...")
        br_hist = hist
        if "Country" in hist.columns:
            br_hist = hist[hist["Country"].astype(str).str.contains("brazil", case=False, na=False)]
        if len(br_hist) < 500:
            br_hist = hist
        meta["train"] = train_models(br_hist)
    else:
        print("\n[4/6] Treino ignorado (retrain=False)")

    print("\n[5/6] Calculando entradas e stakes...")
    from .features.builder import clear_feature_cache
    clear_feature_cache()
    entries = scan_weekend(cal, hist, brazil_only=brazil_only)

    print("\n[6/7] Gerando relatorio...")
    report = format_weekend_report(entries, meta)
    out_dir = DATA / "weekend"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_txt = out_dir / f"weekend_{start}_{end}.txt"
    out_json = out_dir / f"weekend_{start}_{end}.json"
    out_pdf = out_dir / f"FutPythonTrader_{start}_{end}.pdf"
    out_txt.write_text(report, encoding="utf-8")
    out_json.write_text(json.dumps({"meta": meta, "entries": entries}, indent=2, default=str), encoding="utf-8")
    pd.DataFrame(entries).to_csv(out_txt.with_suffix(".csv"), index=False, encoding="utf-8-sig")

    print("\n[7/7] Gerando PDF e Google Drive...")
    from .report.pdf_weekend import generate_weekend_pdf
    from .integrations.google_drive import upload_file

    generate_weekend_pdf(entries, meta, out_pdf)
    drive_id = upload_file(out_pdf)
    meta["pdf_path"] = str(out_pdf)
    meta["drive_file_id"] = drive_id

    print(report)
    print(f"\nSalvo: {out_txt} | PDF: {out_pdf}")
    return {"meta": meta, "entries": entries, "report_path": str(out_txt), "pdf_path": str(out_pdf)}
