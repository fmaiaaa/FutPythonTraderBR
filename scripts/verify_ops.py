"""Verifica componentes críticos."""
import os

os.environ.setdefault("FPT_DATA_ROOT", r"D:\FutPythonTraderBR\data")
os.environ.setdefault("BETFAIR_ENABLED", "true")

from pathlib import Path
from fpt.integrations.betfair.client import get_betfair_client
from fpt.integrations.sofascore import SofaScoreClient
from fpt.live.executor import BetfairExecutor
from fpt.client import DATA

print("=== D: dados ===")
for p in ["merged/brazil_male_all.parquet", "models/model_outcome.joblib"]:
    fp = DATA / p
    print(f"  {p}: {'OK' if fp.exists() else 'MISSING'} ({fp.stat().st_size if fp.exists() else 0} bytes)")

print("\n=== Betfair ===")
bf = get_betfair_client()
bf.login()
print(f"  login: OK")
print(f"  saldo: R$ {bf.available_balance():,.2f}")
ex = BetfairExecutor()
print(f"  executor enabled: {ex.enabled} paper={ex.paper_mode}")

print("\n=== SofaScore ===")
ss = SofaScoreClient(timeout=15, retries=2, min_interval=0.4)
live = ss.live_events()
print(f"  live_events: {len(live)} jogos")
if live:
    e = live[0]
    print(f"  sample: {e.home} x {e.away} id={e.event_id}")
