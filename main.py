#!/usr/bin/env python3
"""FutPythonTrader BR — campeonatos masculinos + trading quantitativo."""
import sys
from datetime import date
from pathlib import Path

from fpt.leagues import BRAZIL_MALE_LEAGUES
from fpt.catalog import load_catalog, count_bases, iter_bases
from fpt.calendar import build_calendar, weekend_window
from fpt.leagues import filter_watchlist
from fpt.weekend import run_weekend_pipeline
from fpt.downloader import (
    download_all_brazil_male, download_league_season, download_catalog,
    download_incremental_weekly, merge_all, fetch_jogos_do_dia,
)
from fpt.pipeline import run_daily_operation, load_merged
from fpt.operation import league_summary, analyze_matchup
from fpt.trading.engine import build_recommendation, scan_day, format_report
from fpt.models.train import train_models
from fpt.models.hierarchical import train_hierarchical_models
from fpt.trading.market_sim import SimulatedMarket
from fpt.trading.backtest import run_backtest, optimize_phi
from fpt.trading.config import load_config
from fpt.trading.context import ContextInput
from fpt.client import DATA


def help_text():
    print("""
FutPythonTrader BR — Operação + Trading Quantitativo

DADOS (FPT API):
  list                 Campeonatos e temporadas
  download-all         Baixa bases BR masculinas
  download-global [pais]  Catálogo global FPT (172 ligas, todas temporadas)
  download-weekly      Atualização semanal (BR full + resto temporada atual)
  calendario [ini] [fim]  Calendário FPT (default: hoje -> domingo)
  fim-de-semana        Rotina completa (somente GitHub Actions)
  merge                Consolida em data/merged/
  jogos [data]         Jogos do dia
  operacao [data]      Relatório clássico
  resumo / analise     Stats e forma

TRADING (pré-jogo → saída HT, ML + ¼ Kelly, φ dinâmico):
  treinar              Treina ensemble ML (RF + HistGBM + GBM + seleção features)
  relatorio-modelo     Treina/avalia holdout 30% + PDF métricas e receita
  scan [data]          Varre jogos do dia — entradas com valor
  avaliar <mand> <vis> [odd] [home|draw|away]
                       Saída completa: prob, odd justa, φ, odd mín, lucro, % banca
  backtest [liga] [phi]
  otimizar-phi [liga]

  betfair login|esportes|odds <mand> <vis>   API Betfair BR (certificado)

  live [scan]          Monitor in-time (CLI scan ou abre painel Streamlit)
  collect-live         Coleta minuto a minuto (odds + SofaScore)
  robo                 App autônomo (Streamlit + atalho área de trabalho)
  finalize-collection  Dataset + treino scalping + upload Drive
  scalping-backtest    Backtest rule-based PRESSURE_STEAM sobre ticks
  sofascore-probe      Testa API SofaScore (requer curl_cffi)
  dashboard            Painel Streamlit (analise manual)

Configure .env: FPT_API_KEY=...  (futpythontrader.com.br/dashboard)
Betfair BR: docs/betfair/README.md — certs/ + BETFAIR_* no .env
""")


def cmd_list(_):
    total = 0
    for slug, meta in BRAZIL_MALE_LEAGUES.items():
        print(f"\n{meta['name']} ({slug})")
        for s in meta["seasons"]:
            print(f"  - {s}")
            total += 1
    print(f"\nTotal: {total} bases")


def cmd_download_all(_):
    print("Baixando bases...")
    stats = download_all_brazil_male()
    print(f"OK: {sum(stats.values())} partidas")
    df = merge_all()
    print(f"Merged: {len(df)} partidas")


def cmd_download(args):
    if len(args) < 3:
        print("Uso: download <pais> <liga> <temporada>")
        return
    country, slug, season = args[0], args[1], args[2]
    df = download_league_season(country, slug, season)
    print(f"OK: {len(df)} partidas")


def cmd_download_global(args):
    country = args[0] if args else None
    n = count_bases(load_catalog()) if not country else sum(1 for _ in iter_bases(country=country))
    print(f"Baixando {n} bases...")
    stats = download_catalog(country=country)
    print(f"OK: {sum(stats.values())} partidas | erros: {len(stats)-sum(1 for v in stats.values() if v)}")
    print(f"Merged global: {len(merge_all())}")


def cmd_download_weekly(_):
    stats = download_incremental_weekly()
    print(f"OK: {sum(stats.values())} partidas")
    print(f"Merged: {len(merge_all())}")


def cmd_calendario(args):
    if len(args) >= 2:
        start, end = args[0], args[1]
    else:
        start, end = weekend_window()
    cal = build_calendar(start, end)
    wl = filter_watchlist(cal)
    print(f"Total FPT: {len(cal)} | Watchlist: {len(wl)}")
    if not wl.empty:
        cols = ["Date", "Time", "watchlist_league", "Home", "Away"]
        cols = [c for c in cols if c in wl.columns]
        print(wl[cols].head(30).to_string())


def cmd_fim_de_semana(args):
    from fpt.storage import is_github_actions

    if not is_github_actions():
        print("Rotina semanal roda apenas no GitHub Actions.")
        print("Dispare: https://github.com/fmaiaaa/FutPythonTraderBR/actions → Relatorio Semanal Sabado")
        sys.exit(1)
    no_train = "--no-train" in args
    no_odds = "--no-odds-api" in args
    run_weekend_pipeline(retrain=not no_train, use_odds_api=not no_odds)


def cmd_merge(_):
    print(f"Merged: {len(merge_all())} partidas")


def cmd_jogos(args):
    day = args[0] if args else date.today().isoformat()
    df = fetch_jogos_do_dia(day)
    print(f"{len(df)} jogos em {day}\n{df.head(10)}")


def cmd_operacao(args):
    r = run_daily_operation(args[0] if args else None)
    print(f"Relatório: {r['report_path']}")


def cmd_resumo(_):
    df = load_merged()
    for slug, meta in BRAZIL_MALE_LEAGUES.items():
        s = league_summary(df, slug)
        if not s.empty:
            r = s.iloc[0]
            print(f"{meta['name']}: {int(r['partidas'])} jogos | Over2.5 {r['over25_pct']}%")


def cmd_analise(args):
    df = load_merged()
    a = analyze_matchup(df, args[0], args[1])
    print(a)


def cmd_scan(args):
    day = args[0] if args else date.today().isoformat()
    df = load_merged()
    signals = scan_day(df, day)
    report = format_report(signals, day)
    out = DATA / "daily" / f"scan_trading_{day}.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(report)
    print(f"\nSalvo: {out}")


def cmd_treinar(_):
    from fpt.models.config import load_model_config

    cfg = load_model_config()
    prefer = "global" if cfg.get("hierarchical", {}).get("enabled", True) else "auto"
    try:
        df = load_merged(prefer=prefer)
    except FileNotFoundError:
        df = load_merged(prefer="auto")
    if cfg.get("hierarchical", {}).get("enabled", True):
        meta = train_hierarchical_models(df)
        print("\nTreino hierárquico concluído (global + ligas):")
        print(f"  ligas treinadas: {len(meta.get('leagues', {}))}")
    else:
        meta = train_models(df)
        print("\nTreino concluído (ensemble RF + HistGBM + GBM):")
    for k, v in meta.items():
        if k not in ("feature_names", "selected_features_sample", "leagues", "global"):
            print(f"  {k}: {v}")


def cmd_relatorio_modelo(args):
    from fpt.models.evaluate import evaluate_holdout, save_evaluation
    from fpt.report.pdf_model_eval import generate_model_eval_pdf
    from fpt.calendar import weekend_window
    from fpt.weekend import weekend_report_dir
    from fpt.integrations.google_drive import upload_file
    import json

    df = load_merged()
    retrain = "--no-train" not in args
    if retrain:
        meta = train_models(df)
    else:
        meta = json.loads((DATA / "models" / "meta.json").read_text(encoding="utf-8"))
    result = evaluate_holdout(df)
    save_evaluation(result)
    start, _ = weekend_window()
    out_dir = weekend_report_dir(start)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_pdf = out_dir / f"ModeloEval_{start}.pdf"
    generate_model_eval_pdf(result, out_pdf, meta=meta)
    upload_file(out_pdf, history_date=str(start))
    s = result.summary.get("model", {})
    print(f"PDF modelo: {out_pdf}")
    print(f"ROI stake modelo: {s.get('roi_pct', 0):+.1f}% | Entradas: {result.metrics.get('n_trades_model', 0)}")


def cmd_avaliar(args):
    if len(args) < 2:
        print("Uso: avaliar <mandante> <visitante> [odd] [home|draw|away]")
        return
    home, away = args[0], args[1]
    odd = float(args[2]) if len(args) > 2 and _is_float(args[2]) else None
    market_arg = args[3] if len(args) > 3 else (args[2] if len(args) > 2 and not _is_float(args[2]) else "home")
    market = {"home": "home_win_ft", "draw": "draw_ft", "away": "away_win_ft"}.get(
        market_arg.lower(), "home_win_ft"
    )

    df = load_merged()
    odds = SimulatedMarket(df).get_odds(home, away)
    if odd and odd > 1.01:
        if market == "home_win_ft":
            odds.home = odd
        elif market == "draw_ft":
            odds.draw = odd
        else:
            odds.away = odd

    rec = build_recommendation(df, home, away, market=market, market_odds=odds)
    print(rec.report())


def cmd_backtest(args):
    df = load_merged()
    league = args[0] if args and args[0] in BRAZIL_MALE_LEAGUES else None
    phi = float(args[1]) if len(args) > 1 and _is_float(args[1]) else load_config()["trading"]["phi"]
    res = run_backtest(df, league_slug=league, phi=phi)
    res.print_summary()
    out = DATA / "backtest" / f"backtest_{league or 'all'}_phi{phi}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    res.trades.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"Trades salvos: {out}")


def cmd_otimizar_phi(args):
    df = load_merged()
    league = args[0] if args and args[0] in BRAZIL_MALE_LEAGUES else None
    grid = optimize_phi(df, league_slug=league)
    print(grid.to_string(index=False))
    out = DATA / "backtest" / f"phi_grid_{league or 'all'}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    grid.to_csv(out, index=False)
    print(f"\nSalvo: {out}")


def cmd_betfair(args):
    from fpt.integrations.betfair import get_betfair_client
    from fpt.trading.market_betfair import BetfairMarket

    sub = (args[0] if args else "login").lower()
    bf = get_betfair_client()

    if sub == "login":
        token = bf.login(force=True)
        print(f"Login OK (token {token[:12]}...)")
        cfg = bf.config
        print(f"Certs: {cfg.cert_dir} | User: {cfg.username[:3]}***")
        return

    if sub == "esportes":
        bf.login()
        for row in bf.list_event_types()[:15]:
            et = row.get("eventType", {})
            print(f"{et.get('id'):>8}  {et.get('name')}")
        return

    if sub == "odds":
        if len(args) < 3:
            print("Uso: betfair odds <mandante> <visitante>")
            return
        home, away = args[1], args[2]
        mkt = BetfairMarket()
        odds = mkt.get_odds(home, away)
        print(f"{home} x {away}  |  H={odds.home}  E={odds.draw}  A={odds.away}  ({odds.source})")
        return

    print("Subcomandos: login | esportes | odds <mand> <vis>")


def cmd_collect_live(args):
    import subprocess
    minutes = int(args[0]) if args else 300
    interval = int(args[1]) if len(args) > 1 else 60
    subprocess.run([
        sys.executable, "scripts/run_live_collector.py",
        "--minutes", str(minutes), "--interval", str(interval),
    ], check=False)


def cmd_finalize_collection(args):
    import subprocess
    cmd = [sys.executable, "scripts/finalize_weekly_collection.py"]
    if args and args[0] == "--upload-drive":
        cmd.append("--upload-drive")
    subprocess.run(cmd, check=False)


def cmd_robo(_):
    import subprocess
    app = Path(__file__).parent / "autonomous_app.py"
    print("Abrindo FPT Robo — http://localhost:8501")
    print(f"Dados: defina FPT_DATA_ROOT ou use D:\\FutPythonTraderBR\\data")
    subprocess.run([
        sys.executable, "-m", "streamlit", "run", str(app),
        "--server.headless", "true",
    ])


def cmd_scalping_backtest(args):
    from fpt.live.betfair_logger import load_ticks
    from fpt.live.scalping_backtest import run_scalping_backtest
    from fpt.live.tick_labels import label_ticks

    ticks = load_ticks()
    if ticks.empty:
        print("Sem ticks em data/betfair/ticks/ — rode o monitor live durante jogos.")
        return
    labeled = label_ticks(ticks)
    out_path = Path("data/betfair/labeled_ticks.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    labeled.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"Ticks rotulados: {out_path} ({len(labeled)} linhas)")

    bt = run_scalping_backtest(labeled)
    print(f"\n=== SCALPING BACKTEST — PRESSURE_STEAM ===")
    print(f"Trades: {bt.trades} | Win rate: {bt.win_rate:.1f}%")
    print(f"PnL total: {bt.total_pnl_pct * 100:.2f}% | Médio/trade: {bt.avg_pnl_pct:.3f}%")
    print(f"Max drawdown: {bt.max_drawdown_pct:.2f}% | Timeouts: {bt.timeouts}")
    if bt.by_horizon:
        print("\nPor horizonte:")
        for h, stats in bt.by_horizon.items():
            print(f"  +{h}s: sinais={stats['signals']} avg_pnl={stats['avg_pnl_pct']:.3f}% win={stats['win_rate']:.1f}%")


def cmd_sofascore_probe(args):
    import subprocess
    script = Path(__file__).parent / "scripts" / "sofascore_probe.py"
    subprocess.run([sys.executable, str(script)] + args)


def cmd_dashboard(_):
    import subprocess
    app = Path(__file__).parent / "dashboard.py"
    subprocess.Popen([sys.executable, "-m", "streamlit", "run", str(app)])


def cmd_live(args):
    sub = (args[0] if args else "app").lower()
    if sub == "scan":
        from fpt.live.monitor import run_live_scan
        from fpt.pipeline import load_merged

        df = load_merged()
        states = run_live_scan(df)
        print(f"=== LIVE SCAN — {len(states)} jogos ===\n")
        for s in states:
            tag = "LIVE" if s.in_play else s.status
            print(f"[{tag}] {s.league_label}: {s.home} x {s.away}  {s.score_display}  @ {s.kickoff}")
            for side in ("Casa", "Empate", "Visitante"):
                o = s.odds.get(side, {})
                print(f"  {side}: back {o.get('back', '—')} / lay {o.get('lay', '—')}")
            if s.prob_home:
                print(f"  Modelo: H{s.prob_home:.0%} E{s.prob_draw:.0%} A{s.prob_away:.0%}")
            for a in s.alerts:
                print(f"  >> {a.alert_type}: {a.message}")
            print()
        return

    import subprocess
    app = Path(__file__).parent / "streamlit_app.py"
    print("Abrindo FPT Live — http://localhost:8501")
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(app)])


def _is_float(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


COMMANDS = {
    "list": cmd_list,
    "download-all": cmd_download_all,
    "download": cmd_download,
    "download-global": cmd_download_global,
    "download-weekly": cmd_download_weekly,
    "calendario": cmd_calendario,
    "fim-de-semana": cmd_fim_de_semana,
    "merge": cmd_merge,
    "jogos": cmd_jogos,
    "operacao": cmd_operacao,
    "resumo": cmd_resumo,
    "analise": cmd_analise,
    "scan": cmd_scan,
    "avaliar": cmd_avaliar,
    "treinar": cmd_treinar,
    "relatorio-modelo": cmd_relatorio_modelo,
    "backtest": cmd_backtest,
    "otimizar-phi": cmd_otimizar_phi,
    "betfair": cmd_betfair,
    "live": cmd_live,
    "collect-live": cmd_collect_live,
    "finalize-collection": cmd_finalize_collection,
    "robo": cmd_robo,
    "scalping-backtest": cmd_scalping_backtest,
    "sofascore-probe": cmd_sofascore_probe,
    "dashboard": cmd_dashboard,
    "help": lambda _: help_text(),
}


def main():
    if len(sys.argv) < 2:
        help_text()
        return
    cmd = sys.argv[1].lower()
    fn = COMMANDS.get(cmd)
    if not fn:
        print(f"Comando desconhecido: {cmd}")
        help_text()
        sys.exit(1)
    fn(sys.argv[2:])


if __name__ == "__main__":
    main()
