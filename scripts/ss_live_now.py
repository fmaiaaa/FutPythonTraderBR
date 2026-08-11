"""Diagnóstico rápido — stats SofaScore dos jogos ao vivo FPT."""
from __future__ import annotations

import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

os.environ.setdefault("FPT_PERSIST_LOCAL", "1")
os.environ.setdefault("FPT_DATA_ROOT", r"D:\FutPythonTraderBR\data")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fpt.integrations.sofascore import SofaScoreClient
from fpt.integrations.sofascore.parser import parse_event_statistics
from fpt.live.match_status import parse_kickoff_dt
from fpt.live.monitor import merge_calendar_states, load_latest_snapshot
from fpt.live.pressure import apply_pressure
from fpt.live.sofascore_enricher import SofaScoreEnricher

BR = ZoneInfo("America/Sao_Paulo")


def _print_game(label: str, home: str, away: str, score, minute, ss: dict, ph, pa) -> None:
    print(f"=== {label}: {home} x {away} | {score} | {minute}'")
    print(f"Pressao {ph} / {pa}")
    print(
        f"Posse {ss.get('ss_possession_home')} / {ss.get('ss_possession_away')} | "
        f"Chutes {ss.get('ss_shots_home')} / {ss.get('ss_shots_away')} | "
        f"No gol {ss.get('ss_sot_home')} / {ss.get('ss_sot_away')} | "
        f"xG {ss.get('ss_xg_home')} / {ss.get('ss_xg_away')}"
    )


def main() -> None:
    now = datetime.now(BR)
    print("NOW", now.strftime("%Y-%m-%d %H:%M BRT"))
    states = merge_calendar_states(load_latest_snapshot())
    live = [s for s in states if s.in_play or s.status in ("LIVE", "HT")]
    enricher = SofaScoreEnricher()
    enriched = 0
    for s in live:
        ko = parse_kickoff_dt(s.kickoff or "")
        md = ko.date().isoformat() if ko else now.date().isoformat()
        enricher.enrich(s, md)
        ss = s.sofascore_stats or {}
        if s.sofascore_event_id:
            enriched += 1
        _print_game("FPT LIVE", s.home, s.away, s.score_display, s.elapsed_min, ss, s.pressure_home, s.pressure_away)

    if enriched:
        return

    print("--- Nenhum FPT com stats completas; melhor jogo SS ao vivo ---")
    client = SofaScoreClient()
    best = None
    best_score = -1.0
    for e in client.live_events():
        try:
            st = parse_event_statistics(client.statistics(e.event_id), e.event_id)
            apply_pressure(st, None)
            score = float(st.possession_home or 0) + float(st.shots_on_target_home or 0) * 5
            score += float(st.xg_home or 0) * 10
            if score > best_score:
                best_score = score
                best = (e, st)
        except Exception:
            continue
    if not best:
        print("Sem stats SofaScore disponiveis agora.")
        return
    e, st = best
    ss = st.to_flat_dict()
    _print_game(
        "SS LIVE",
        e.home,
        e.away,
        f"{e.score_home}-{e.score_away}",
        e.minute,
        ss,
        st.pressure_home,
        st.pressure_away,
    )


if __name__ == "__main__":
    main()
