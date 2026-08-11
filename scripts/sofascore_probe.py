"""Testa conexão SofaScore — rode durante jogos ou com data histórica."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fpt.integrations.sofascore import SofaScoreClient, SofaScoreError
from fpt.integrations.sofascore.parser import parse_event_statistics, parse_graph


def main() -> int:
    p = argparse.ArgumentParser(description="Probe API SofaScore (não oficial)")
    p.add_argument("--date", default=date.today().isoformat(), help="YYYY-MM-DD")
    p.add_argument("--event-id", type=int, help="Buscar stats/graph de um evento")
    p.add_argument("--live", action="store_true", help="Listar jogos live")
    args = p.parse_args()

    client = SofaScoreClient()
    print(f"transport={client.transport}")

    try:
        if args.live:
            events = client.live_events()
            print(f"live events: {len(events)}")
            for e in events[:10]:
                print(f"  {e.event_id} | {e.home} vs {e.away} | {e.status_type}")
            return 0

        if args.event_id:
            eid = args.event_id
            stats_raw = client.statistics(eid)
            stats = parse_event_statistics(stats_raw, eid)
            graph_raw = client.graph(eid)
            momentum = parse_graph(graph_raw)
            print(json.dumps({
                "event_id": eid,
                "stats": stats.to_flat_dict(),
                "graph_momentum": momentum,
            }, indent=2, ensure_ascii=False))
            return 0

        d = date.fromisoformat(args.date)
        for offset in (0, -1, 1):
            day = (d + timedelta(days=offset)).isoformat()
            events = client.scheduled_events(day)
            print(f"{day}: {len(events)} jogos")
            for e in events[:5]:
                print(f"  {e.event_id} | {e.home} vs {e.away} | {e.status_type}")
        return 0
    except SofaScoreError as ex:
        print(f"ERRO: {ex}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
