#!/usr/bin/env python3
"""FutPythonTrader BR — campeonatos masculinos + trading quantitativo."""
import sys
from datetime import date
from pathlib import Path

from fpt.leagues import BRAZIL_MALE_LEAGUES
from fpt.catalog import load_catalog, count_bases, iter_bases
from fpt.calendar import build_calendar, weekend_window
from fpt.weekend import run_weekend_pipeline
from fpt.downloader import (
    download_all_brazil_male, download_league_season, download_catalog,
    download_incremental_weekly, merge_all, fetch_jogos_do_dia,
)
from fpt.pipeline import run_daily_operation, load_merged
from fpt.operation import league_summary, analyze_matchup
from fpt.trading.engine import build_recommendation, scan_day, format_report
from fpt.models.train import train_models
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
  fim-de-semana        Rotina completa: dados + calendário + odds API + stakes
  agendar              Instala tarefa Windows (quarta 10h)
  merge                Consolida em data/merged/
  jogos [data]         Jogos do dia
  operacao [data]      Relatório clássico
  resumo / analise     Stats e forma

TRADING (pré-jogo → saída HT, ML + ¼ Kelly, φ dinâmico):
  treinar              Treina modelos ML (HistGradientBoosting + calibração)
  scan [data]          Varre jogos do dia — entradas com valor
  avaliar <mand> <vis> [odd] [home|draw|away]
                       Saída completa: prob, odd justa, φ, odd mín, lucro, % banca
  backtest [liga] [phi]
  otimizar-phi [liga]

  dashboard            Painel Streamlit

Configure .env: FPT_API_KEY=...  (futpythontrader.com.br/dashboard)

Pipeline: Modelo Poisson → odd justa → φ → contexto → Modelo HT → ¼Kelly → ENTER/SKIP
Modo atual: simulação (odds FPT). Betfair: stub em fpt/trading/market_betfair.py
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
    br = cal[cal["is_brazil"]] if "is_brazil" in cal.columns else cal
    print(f"Total: {len(cal)} | BR: {len(br)}")
    if not br.empty:
        print(br[["Date", "Time", "League", "Home", "Away"]].head(20).to_string())


def cmd_fim_de_semana(args):
    no_train = "--no-train" in args
    no_odds = "--no-odds-api" in args
    run_weekend_pipeline(retrain=not no_train, use_odds_api=not no_odds)


def cmd_agendar(_):
    import subprocess
    ps1 = Path(__file__).parent / "scripts" / "install_schedule.ps1"
    subprocess.run(["powershell", "-ExecutionPolicy", "Bypass", "-File", str(ps1)], check=True)


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
    df = load_merged()
    meta = train_models(df)
    print("\nTreino concluído:")
    for k, v in meta.items():
        if k != "feature_names":
            print(f"  {k}: {v}")


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


def cmd_dashboard(_):
    import subprocess
    app = Path(__file__).parent / "dashboard.py"
    subprocess.Popen([sys.executable, "-m", "streamlit", "run", str(app)])


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
    "agendar": cmd_agendar,
    "merge": cmd_merge,
    "jogos": cmd_jogos,
    "operacao": cmd_operacao,
    "resumo": cmd_resumo,
    "analise": cmd_analise,
    "scan": cmd_scan,
    "avaliar": cmd_avaliar,
    "treinar": cmd_treinar,
    "backtest": cmd_backtest,
    "otimizar-phi": cmd_otimizar_phi,
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
