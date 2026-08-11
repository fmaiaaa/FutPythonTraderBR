from datetime import datetime
from zoneinfo import ZoneInfo

from fpt.calendar import normalize_jogos
from fpt.downloader import fetch_jogos_do_dia
from fpt.live.match_status import parse_kickoff_dt, resolve_match_status
from fpt.live.monitor import LiveMonitor, _parse_kickoff

BR = ZoneInfo("America/Sao_Paulo")
now = datetime.now(BR)
print("Agora BRT:", now.strftime("%d/%m/%Y %H:%M"))

df = fetch_jogos_do_dia(datetime.now().date().isoformat())
if not df.empty:
    cal = normalize_jogos(df)
    mask = cal["League"].astype(str).str.contains("NETHERLANDS|PORTUGAL|BRAZIL|ENGLAND", na=False)
    for _, row in cal[mask].head(12).iterrows():
        ko = _parse_kickoff(row)
        ko_dt = parse_kickoff_dt(ko)
        r = resolve_match_status(kickoff_dt=ko_dt, betfair_in_play=True, now=now)
        print(
            f"{row.get('Home')} x {row.get('Away')} | raw={row.get('Date')} | ko={ko} | "
            f"{r.status} live={r.in_play}"
        )

print("--- scan LIVE ---")
states = LiveMonitor().scan(None)
for s in [x for x in states if x.in_play][:12]:
    ko_dt = parse_kickoff_dt(s.kickoff)
    mins = (now - ko_dt).total_seconds() / 60 if ko_dt else None
    print(
        f"{s.home} x {s.away} | ko={s.kickoff} | +{mins:.0f}min | {s.status} | "
        f"elapsed={s.elapsed_min} | {s.odds_source}"
    )
