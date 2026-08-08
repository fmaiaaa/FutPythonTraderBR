"""Rotina de fim de semana — calendario, odds, stakes."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd

from .calendar import build_calendar, enrich_with_schedule, list_market_odds, weekend_window
from .client import DATA
from .downloader import download_incremental_weekly, merge_all
from .leagues import filter_watchlist, league_sort_key
from .markets import JOGOS_DIA_MARKETS, market_by_id
from .models.train import train_models
from .pipeline import load_merged
from .trading.engine import build_market_reference, scan_match_all_markets
from .trading.market_sim import MarketOdds
from .trading.config import load_config
from .trading.the_odds_api import enrich_calendar_with_odds_api, remaining_budget


def weekend_report_dir(saturday) -> Path:
    """data/weekend/YYYY-MM/YYYY-MM-DD/ — sabado como ancora do fim de semana."""
    from datetime import date as date_cls

    if isinstance(saturday, str):
        saturday = date_cls.fromisoformat(saturday[:10])
    month = saturday.strftime("%Y-%m")
    day = saturday.isoformat()
    return DATA / "weekend" / month / day


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
    brazil_only: bool = False,
    bankroll: float | None = None,
) -> list[dict]:
    from .trading.config import load_config

    bankroll = bankroll or load_config()["trading"]["bankroll"]
    sub = cal if not cal.empty else cal
    if not sub.empty and "watchlist_league" not in sub.columns:
        sub = filter_watchlist(sub)
    if brazil_only and "is_brazil" in sub.columns:
        sub = sub[sub["is_brazil"]]
    entries = []

    for _, row in sub.iterrows():
        home, away = str(row["Home"]), str(row["Away"])
        if home in ("nan", "") or away in ("nan", ""):
            continue
        match_date = str(row["Date"])[:10]
        recs = scan_match_all_markets(hist, home, away, row, match_date, bankroll)

        for rec in recs:
            mdef = market_by_id(rec.market)
            entries.append({
                "date": match_date,
                "time": row.get("Time"),
                "league": row.get("watchlist_league") or row.get("League"),
                "home": home,
                "away": away,
                "market": rec.market,
                "market_label": mdef.label if mdef else rec.market,
                "market_group": mdef.group if mdef else "",
                "action": rec.action,
                "prob": rec.probabilidade_estimada,
                "p_lucro_ht": rec.p_lucro_ht,
                "odd_justa": rec.odd_justa,
                "back_justa": rec.back_justa,
                "lay_justa": rec.lay_justa,
                "lay_max": rec.lay_max,
                "phi": rec.phi_seguranca,
                "odd_min": rec.odd_minima_entrada,
                "back_min": rec.odd_minima_entrada,
                "odd_mercado": rec.odd_mercado,
                "edge_pp": rec.edge_pp,
                "lucro_est_pct": rec.lucro_estimado_pct,
                "pct_banca": rec.stake_back_pct,
                "stake_back_pct": rec.stake_back_pct,
                "stake_lay_pct": rec.stake_lay_pct,
                "stake": rec.stake_valor,
                "stake_motivo": rec.stake_motivo,
                "confianca": rec.confianca,
                "odds_source": "fpt_jogos_dia",
                "schedule_notes": " | ".join(rec.schedule_notes),
            })
    return entries


def format_weekend_report(entries: list[dict], meta: dict) -> str:
    lines = [
        "=" * 70,
        f"RELATORIO FIM DE SEMANA — {meta.get('start')} a {meta.get('end')}",
        f"Jogos watchlist: {meta.get('n_games_watchlist', meta.get('n_games', 0))} | "
        f"Linhas mercado: {len(entries)}",
        "Estrategia: entrada pre-jogo (1X2 FT) -> saida no intervalo | odd justa, phi, min, stake",
        "=" * 70,
        "",
    ]

    by_match: dict[tuple, list] = {}
    for e in entries:
        key = (e["date"], e["home"], e["away"])
        by_match.setdefault(key, []).append(e)

    match_keys = sorted(
        by_match.keys(),
        key=lambda k: league_sort_key(
            by_match[k][0].get("league", ""),
            str(by_match[k][0].get("time", "")),
            str(k[0]),
        ),
    )

    for key in match_keys:
        evs = by_match[key]
        head = evs[0]
        lines += [
            f"{head['date']} {head.get('time', '')} | {head['league']}",
            f"  {head['home']} x {head['away']}",
            f"  {'Mercado':<18} {'Prob':>6} {'P(HT)':>6} {'BackJ':>6} {'LayJ':>6} {'phi':>5} "
            f"{'BkMin':>6} {'Bk%':>6} {'Lay%':>6}",
        ]
        for e in sorted(evs, key=lambda x: x.get("market", "")):
            lines.append(
                f"  {e.get('market_label', e['market']):<18} "
                f"{e['prob']:>6.1%} {e.get('p_lucro_ht', 0):>6.1%} "
                f"{e.get('back_justa', e['odd_justa']):>6.2f} {e.get('lay_justa', 0):>6.2f} "
                f"{e['phi']:>5.3f} {e.get('back_min', e['odd_min']):>6.2f} "
                f"{e.get('stake_back_pct', e.get('pct_banca', 0)):>6.2%} "
                f"{e.get('stake_lay_pct', 0):>6.2%}"
                + (f"  [{e['stake_motivo']}]" if e.get('stake_motivo') and e.get('stake_back_pct', 0) <= 0 and e.get('stake_lay_pct', 0) <= 0 else "")
            )
        if head.get("schedule_notes"):
            lines.append(f"  Agenda: {head['schedule_notes']}")
        lines.append("")

    if not entries:
        lines.append("Nenhum jogo na watchlist neste fim de semana.")
    return "\n".join(lines)


def run_weekend_pipeline(
    update_data: bool = True,
    retrain: bool = True,
    use_odds_api: bool = False,
    brazil_only: bool = False,
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
    cal = filter_watchlist(cal)
    cal = enrich_with_schedule(cal, hist)
    meta["n_games"] = len(cal)
    meta["n_games_watchlist"] = len(cal)

    if use_odds_api:
        print("\n[3/6] The Odds API (prioridade fim de semana)...")
        cal = enrich_calendar_with_odds_api(cal, hist)
        meta["odds_api_remaining"] = remaining_budget()
    else:
        print("\n[3/6] The Odds API desligada")

    if retrain:
        print("\n[4/6] Re-treinando modelos (ensemble)...")
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
    out_dir = weekend_report_dir(start)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_txt = out_dir / f"weekend_{start}_{end}.txt"
    out_json = out_dir / f"weekend_{start}_{end}.json"
    out_pdf = out_dir / f"FutPythonTrader_{start}_{end}.pdf"  # legado; PDFs por liga abaixo
    out_txt.write_text(report, encoding="utf-8")
    out_json.write_text(json.dumps({"meta": meta, "entries": entries}, indent=2, default=str), encoding="utf-8")
    pd.DataFrame(entries).to_csv(out_txt.with_suffix(".csv"), index=False, encoding="utf-8-sig")

    print("\n[7/7] Gerando PDFs por campeonato e Google Drive...")
    from .report.pdf_weekend import generate_weekend_pdfs_by_league
    from .integrations.google_drive import upload_file, upload_weekend_folder

    pdf_paths = generate_weekend_pdfs_by_league(entries, meta, out_dir)
    drive_manifest = upload_weekend_folder(out_dir, str(start))
    drive_ids = [u["file_id"] for u in drive_manifest.get("uploaded", []) if u.get("file_id")]

    from .storage import is_github_actions
    if is_github_actions():
        from .integrations.google_drive import upload_models_bundle, upload_merged_bundle
        models_info = upload_models_bundle()
        merged_info = upload_merged_bundle()
        if models_info:
            meta.setdefault("models_drive", models_info)
            print(f"Modelos no Drive: {models_info.get('web_view_link', models_info.get('file_id'))}")
        if merged_info:
            meta.setdefault("merged_drive", merged_info)
            print(f"Dados merged no Drive: {merged_info.get('web_view_link', merged_info.get('file_id'))}")
    meta["pdf_paths"] = [str(p) for p in pdf_paths]
    meta["drive_file_ids"] = drive_ids
    meta["drive_links"] = drive_manifest.get("uploaded", [])
    meta["drive_manifest"] = str(out_dir / "drive_links.json")
    drive_id = drive_ids[0] if drive_ids else None

    if retrain and meta.get("train"):
        print("\n[7b/7] PDF avaliacao do modelo...")
        from .models.evaluate import evaluate_holdout, save_evaluation
        from .report.pdf_model_eval import generate_model_eval_pdf
        eval_result = evaluate_holdout(hist)
        save_evaluation(eval_result)
        eval_pdf = out_dir / f"ModeloEval_{start}.pdf"
        generate_model_eval_pdf(eval_result, eval_pdf, meta=meta["train"])
        upload_file(eval_pdf, history_date=str(start))
        meta["model_eval_pdf"] = str(eval_pdf)
    meta["pdf_path"] = meta.get("pdf_paths", [str(out_pdf)])[0] if meta.get("pdf_paths") else str(out_pdf)
    meta["drive_file_id"] = drive_id

    print(report)
    print(f"\nSalvo: {out_txt} | PDFs: {len(meta.get('pdf_paths', []))} campeonatos")
    return {
        "meta": meta, "entries": entries, "report_path": str(out_txt),
        "pdf_path": meta.get("pdf_path"), "pdf_paths": meta.get("pdf_paths", []),
    }
