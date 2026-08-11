"""Diagnóstico rápido por etapa."""
import os
import time

os.environ.setdefault("FPT_DATA_ROOT", r"D:\FutPythonTraderBR\data")
os.environ.setdefault("BETFAIR_ENABLED", "true")

def step(name, fn):
    t0 = time.perf_counter()
    try:
        r = fn()
        dt = time.perf_counter() - t0
        print(f"OK  {name}: {dt:.1f}s -> {r}")
        return r
    except Exception as ex:
        dt = time.perf_counter() - t0
        print(f"ERR {name}: {dt:.1f}s -> {ex}")
        return None

from fpt.pipeline import load_merged
from fpt.live.monitor import LiveMonitor
from fpt.trading.market_betfair import BetfairMarket

df = step("load_merged", load_merged)
print(f"    rows={len(df) if df is not None else 0}")

mon = LiveMonitor()
cal = step("calendar", mon._load_calendar)
print(f"    games={len(cal) if cal is not None and not cal.empty else 0}")

if cal is not None and not cal.empty:
    home_col = next((c for c in cal.columns if c.lower() in ("home", "mandante")), "Home")
    away_col = next((c for c in cal.columns if c.lower() in ("away", "visitante")), "Away")
    pairs = [
        (str(r[home_col]), str(r[away_col]))
        for _, r in cal.head(5).iterrows()
    ]
    bf = BetfairMarket()
    if bf.configured:
        step("betfair_batch_5", lambda: bf.fetch_odds_for_games(pairs, days_ahead=1))

step("scan_3_games", lambda: mon.scan(df.head(0) if df is not None else None) if False else None)
