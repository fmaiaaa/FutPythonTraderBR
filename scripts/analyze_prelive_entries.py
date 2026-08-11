"""Analisa entradas pre-live com odds Betfair back/lay."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fpt.calendar import build_calendar, weekend_window
from fpt.leagues import filter_watchlist
from fpt.live.monitor import run_live_scan
from fpt.pipeline import load_merged
from fpt.trading.engine import build_recommendation
from fpt.trading.market_betfair import BetfairMarket, parsed_to_market_odds


def main():
    start, end = weekend_window()
    cal = filter_watchlist(build_calendar(start, end))
    hist = load_merged()

    bf = BetfairMarket()
    game_pairs = [(str(r["Home"]), str(r["Away"])) for _, r in cal.iterrows()]
    betfair_events = []
    if bf.configured:
        try:
            betfair_events = bf.fetch_odds_for_games(game_pairs, days_ahead=1)
        except Exception as ex:
            print(f"Aviso Betfair: {ex}")

    print(f"=== FIM DE SEMANA {start} a {end} ===")
    print(f"Jogos watchlist: {len(cal)} | Eventos Betfair: {len(betfair_events)}\n")

    enters = []
    watches = []
    near = []

    for _, row in cal.iterrows():
        home, away = str(row["Home"]), str(row["Away"])
        league = str(row.get("watchlist_league") or row.get("League", ""))
        match_date = str(row["Date"])[:10]

        parsed_bf = bf.match_fpt_to_betfair(home, away, betfair_events) if betfair_events else None
        market_odds = parsed_to_market_odds(parsed_bf) if parsed_bf else None

        if not market_odds:
            continue

        bh = market_odds.get("home_win_ft")
        bd = market_odds.get("draw_ft")
        ba = market_odds.get("away_win_ft")
        ex_h = market_odds.get_exchange("home")
        ex_d = market_odds.get_exchange("draw")
        ex_a = market_odds.get_exchange("away")

        for mkt, label, back, lay in [
            ("draw_ft", "Empate", bd, ex_d.lay if ex_d else None),
            ("home_win_ft", "Mandante", bh, ex_h.lay if ex_h else None),
            ("away_win_ft", "Visitante", ba, ex_a.lay if ex_a else None),
        ]:
            rec = build_recommendation(
                hist, home, away, market=mkt, market_odds=market_odds,
                match_date=match_date, bankroll=1000.0,
            )
            entry = {
                "league": league,
                "home": home,
                "away": away,
                "market": label,
                "action": rec.action,
                "side": "BACK" if mkt == "draw_ft" else "LAY",
                "prob": rec.probabilidade_estimada,
                "odd_min": rec.odd_minima_entrada,
                "edge_pp": rec.edge_pp,
                "stake_back": rec.stake_back_pct,
                "stake_lay": rec.stake_lay_pct,
                "back": back,
                "lay": lay,
                "in_play": market_odds.in_play,
            }
            if rec.action == "ENTER" and (
                (mkt == "draw_ft" and rec.stake_back_pct > 0)
                or (mkt != "draw_ft" and rec.stake_lay_pct > 0)
            ):
                enters.append(entry)
            elif mkt == "draw_ft" and back and back >= rec.odd_minima_entrada * 0.98:
                if rec.edge_pp and rec.edge_pp >= 0.5:
                    watches.append(entry)

            # Quase: lay/back perto do mínimo
            if rec.action == "SKIP" and rec.edge_pp and rec.edge_pp > 0:
                price = back if mkt == "draw_ft" else lay
                if price and rec.odd_minima_entrada and price >= rec.odd_minima_entrada * 0.95:
                    near.append(entry)

    print("=== ENTRADAS POSSÍVEIS (ENTER — odd Betfair >= mínima) ===")
    if not enters:
        print("Nenhuma entrada ENTER confirmada com odds Betfair atuais.\n")
    for e in enters:
        print(
            f"{e['league']} | {e['home']} x {e['away']} | {e['market']} {e['side']}\n"
            f"  Back={e['back']} Lay={e['lay']} | Min={e['odd_min']:.2f} | Edge={e['edge_pp']:+.1f}pp | "
            f"Stake B={e['stake_back']:.2%} L={e['stake_lay']:.2%} | in_play={e['in_play']}"
        )

    print("\n=== QUASE VALOR (WATCH — empate perto da odd mínima) ===")
    for e in watches[:20]:
        print(
            f"{e['home']} x {e['away']} | Back empate {e['back']} (min {e['odd_min']:.2f}) | "
            f"edge {e['edge_pp']:+.1f}pp"
        )
    if not watches:
        print("Nenhum WATCH empate.")

    print("\n=== OPORTUNIDADES PRÓXIMAS (edge>0, odd a ~5% do mínimo) ===")
    seen = set()
    for e in sorted(near, key=lambda x: -(x["edge_pp"] or 0))[:25]:
        key = (e["home"], e["away"], e["market"])
        if key in seen:
            continue
        seen.add(key)
        px = e["back"] if e["side"] == "BACK" else e["lay"]
        print(
            f"{e['league']} | {e['home']} x {e['away']} | {e['market']} {e['side']} | "
            f"{'Back' if e['side']=='BACK' else 'Lay'}={px} min={e['odd_min']:.2f} edge={e['edge_pp']:+.1f}pp"
        )

    # Live scan alerts
    print("\n=== ALERTAS LIVE SCAN (modelo + Betfair agora) ===")
    states = run_live_scan(hist)
    alert_enters = [(s, a) for s in states for a in s.alerts if a.alert_type == "ENTER"]
    alert_watches = [(s, a) for s in states for a in s.alerts if a.alert_type == "WATCH"]
    print(f"ENTER: {len(alert_enters)} | WATCH: {len(alert_watches)}")
    for s, a in alert_enters:
        o = s.odds
        print(
            f"{s.league_label} | {s.home} x {s.away} | {a.recommended_side} | {a.message}\n"
            f"  Back H/E/A: {o.get('Casa',{}).get('back')}/{o.get('Empate',{}).get('back')}/{o.get('Visitante',{}).get('back')} | "
            f"Lay: {o.get('Casa',{}).get('lay')}/{o.get('Empate',{}).get('lay')}/{o.get('Visitante',{}).get('lay')}"
        )


if __name__ == "__main__":
    main()
