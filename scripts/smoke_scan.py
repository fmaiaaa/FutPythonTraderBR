"""Smoke test scan + Betfair odds."""
import os
os.environ.setdefault("FPT_DATA_ROOT", r"D:\FutPythonTraderBR\data")

from fpt.live.monitor import run_live_scan
from fpt.pipeline import load_merged

states = run_live_scan(load_merged())
n_bf = sum(
    1 for s in states
    if any(s.odds.get(k, {}).get("back") for k in ("Casa", "Empate", "Visitante"))
)
print(f"states={len(states)} betfair_odds={n_bf} alerts={sum(len(s.alerts) for s in states)}")
for s in states:
    o = s.odds
    if o.get("Casa", {}).get("back"):
        print(
            f"sample: {s.home} x {s.away} | back H/E/A: "
            f"{o['Casa'].get('back')}/{o['Empate'].get('back')}/{o['Visitante'].get('back')} | "
            f"lay: {o['Casa'].get('lay')}/{o['Empate'].get('lay')}/{o['Visitante'].get('lay')}"
        )
        break
