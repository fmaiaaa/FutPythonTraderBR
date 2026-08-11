"""Tempo do scan completo."""
import os
import time

os.environ.setdefault("FPT_DATA_ROOT", r"D:\FutPythonTraderBR\data")
os.environ.setdefault("BETFAIR_ENABLED", "true")

from fpt.pipeline import load_merged
from fpt.live.monitor import LiveMonitor

df = load_merged()
mon = LiveMonitor()
t0 = time.perf_counter()
states = mon.scan(df)
dt = time.perf_counter() - t0
n_bf = sum(1 for s in states if any(s.odds.get(k, {}).get("back") for k in ("Casa", "Empate", "Visitante")))
print(f"scan={dt:.1f}s games={len(states)} betfair={n_bf} alerts={sum(len(s.alerts) for s in states)}")
for s in states[:3]:
    o = s.odds
    print(f"  {s.home} x {s.away} | back {o['Casa'].get('back')}/{o['Empate'].get('back')}/{o['Visitante'].get('back')} | {s.best_action}")
