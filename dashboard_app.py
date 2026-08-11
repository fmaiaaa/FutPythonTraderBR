"""
FPT Dashboard — somente leitura (rápido).

Operação e coleta rodam em processos CMD separados:
  scripts/start_coleta.bat   — SofaScore + odds 24/7
  scripts/start_operacao.bat — Betfair 24/7
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import os

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from fpt.client import DATA
from fpt.leagues import WATCHLIST_CATALOG
from fpt.live.display_labels import (
    format_operation,
    market_label,
    operation_type_label,
)
from fpt.live.config import load_live_config
from fpt.live.autonomous import load_robot_log
from fpt.live.models import LiveMatchState
from fpt.live.runtime_profile import active_profile_name, profile_summary
from fpt.live.monitor import load_latest_snapshot, merge_calendar_states
from fpt.live.process_status import (
    read_collector_status,
    read_operator_status,
    snapshot_meta,
)
from fpt.live.operation_control import (
    read_scan_heartbeat,
    reset_initial_bankroll,
    reset_open_entries,
)
from fpt.live.weekly_calendar import active_scalp_slots, load_weekly_meta, WEEKLY_DIR
from fpt.live.paper_db import get_state, list_paper_trades, bankroll_history
from fpt.live.minute_store import (
    bankroll_minute_history,
    match_minute_count,
    minute_timeline_path,
)
from fpt.live.scalping import ScalpingEngine
from fpt.live.trade_positions import PositionManager
from fpt.paths import data_root, ensure_data_dirs

BR = ZoneInfo("America/Sao_Paulo")

_MKT_SIDE = [
    ("home_win_ft", "Casa"),
    ("draw_ft", "Empate"),
    ("away_win_ft", "Visitante"),
]

if not os.environ.get("FPT_PERSIST_LOCAL"):
    os.environ["FPT_PERSIST_LOCAL"] = "1"
ensure_data_dirs()


def _fmt_ts_short(ts: str | None) -> str:
    if not ts:
        return "—"
    s = str(ts)
    if "T" in s:
        return s.split("T")[-1][:8]
    return s[:8]


def _parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts))
        if dt.tzinfo is None:
            return dt.replace(tzinfo=BR)
        return dt.astimezone(BR)
    except ValueError:
        return None


def _process_cycle_label(st: dict) -> str:
    ts = _fmt_ts_short(st.get("ts") or st.get("updated") or st.get("last_ts"))
    if st.get("phase") == "scanning":
        return f"{ts} (scan…)" if ts != "—" else "scan em andamento…"
    return ts


def _latest_data_ts(snap_meta: dict, op_st: dict, heartbeat: dict) -> tuple[str, float | None]:
    """Melhor timestamp disponível + idade em minutos."""
    now = datetime.now(BR)
    scanning = (
        op_st.get("phase") == "scanning"
        or heartbeat.get("phase") == "scanning"
    )
    best: datetime | None = None
    candidates = [
        op_st.get("updated") if scanning else None,
        heartbeat.get("ts"),
        op_st.get("ts"),
        op_st.get("updated"),
        snap_meta.get("updated"),
        snap_meta.get("mtime"),
    ]
    for raw in candidates:
        dt = _parse_ts(raw)
        if dt and (best is None or dt > best):
            best = dt
    if best is None:
        return "—", None
    age_min = max(0.0, (now - best).total_seconds() / 60.0)
    return best.strftime("%H:%M:%S"), round(age_min, 1)


def _format_entry_rows(trades: list[dict]) -> list[dict]:
    """Entradas paper — jogo, operação (mercado+lado), odds, stake e resultado."""
    rows = []
    for t in trades:
        pnl = t.get("pnl")
        if t.get("status") == "OPEN":
            lucro = "—"
        elif pnl is not None:
            lucro = f"{float(pnl):+.2f}"
        else:
            lucro = "—"
        rows.append({
            "Jogo": f"{t.get('home', '?')} x {t.get('away', '?')}",
            "Modo": operation_type_label(t.get("alert_type")),
            "Mercado": market_label(t.get("market")),
            "Lado": str(t.get("entry_side", "")).upper() or "—",
            "Posição": format_operation(t.get("entry_side"), t.get("market")),
            "Status": str(t.get("status", "")),
            "Odd entrada": f"{float(t['entry_odd']):.2f}",
            "Odd saída": f"{float(t['exit_odd']):.2f}" if t.get("exit_odd") else "—",
            "Stake R$": f"{float(t['stake_amount']):.2f}",
            "Lucro R$": lucro,
        })
    return rows


def _collect_open_positions() -> list[dict]:
    """Lista unificada de posições abertas (managed + scalp + paper)."""
    rows: list[dict] = []
    seen: set[str] = set()

    def _add(home: str, away: str, operation: str, **extra) -> None:
        key = f"{home}|{away}|{operation}|{extra.get('modo', '')}"
        if key in seen:
            return
        seen.add(key)
        rows.append({"home": home, "away": away, "operation": operation, **extra})

    for pos in PositionManager().open_positions:
        _add(
            pos.home, pos.away,
            format_operation(pos.side, pos.market),
            market=market_label(pos.market),
            side=str(pos.side).upper(),
            modo=operation_type_label(entry_type=pos.entry_type),
            jogo=f"{pos.home} x {pos.away}",
            odd=f"{pos.entry_odd:.2f}",
            stake=f"R$ {pos.stake_amount:.2f}",
            tipo=pos.entry_type,
        )
    for pos in ScalpingEngine().open_positions:
        _add(
            pos.home, pos.away,
            format_operation(pos.side, pos.market),
            market=market_label(pos.market),
            side=str(pos.side).upper(),
            modo="Scalping",
            jogo=f"{pos.home} x {pos.away}",
            odd=f"{pos.entry_odd:.2f}",
            stake="—",
            tipo="scalp",
        )
    for t in list_paper_trades(300, open_only=True):
        _add(
            str(t.get("home", "")),
            str(t.get("away", "")),
            format_operation(t.get("entry_side"), t.get("market")),
            market=market_label(t.get("market")),
            side=str(t.get("entry_side", "")).upper() or "—",
            modo=operation_type_label(t.get("alert_type")),
            jogo=f"{t.get('home', '?')} x {t.get('away', '?')}",
            odd=f"{float(t['entry_odd']):.2f}",
            stake=f"R$ {float(t['stake_amount']):.2f}",
            tipo="paper",
        )
    return rows


def _refresh_live_sofascore(states: list[LiveMatchState]) -> None:
    """Atualiza stats SofaScore para jogos ao vivo (aba In-Live)."""
    from datetime import date

    from fpt.live.match_status import parse_kickoff_dt
    from fpt.live.sofascore_enricher import SofaScoreEnricher

    enricher = SofaScoreEnricher()
    if not enricher.enabled:
        return
    live = [
        s for s in states
        if s.in_play or s.status in ("LIVE", "HT", "LIVE?")
    ]
    for s in live:
        ko = parse_kickoff_dt(s.kickoff or "")
        md = ko.date().isoformat() if ko else date.today().isoformat()
        try:
            enricher.enrich(s, md)
        except Exception:
            continue


def _load_states() -> tuple[list[LiveMatchState], dict]:
    """Carrega snapshot em disco — enriquece SofaScore dos jogos ao vivo."""
    meta = snapshot_meta()
    states = merge_calendar_states(load_latest_snapshot())
    _refresh_live_sofascore(states)
    return states, meta


def _rec_for_side(state: LiveMatchState, market: str) -> dict | None:
    for r in state.recommendations or []:
        if r.get("market") == market:
            return r
    return None


def _fmt_model_odds(state: LiveMatchState, field: str) -> str:
    parts = []
    for mkt, _ in _MKT_SIDE:
        rec = _rec_for_side(state, mkt)
        val = rec.get(field) if rec else None
        parts.append(f"{val:.2f}" if val else "—")
    return "/".join(parts)


def _fmt_odds(state: LiveMatchState, side: str) -> str:
    parts = []
    for mkt, label in _MKT_SIDE:
        v = state.odds.get(label, {}).get(side)
        if not v:
            rec = _rec_for_side(state, mkt)
            if rec:
                v = rec.get("odd_lay" if side == "lay" else "odd_back")
        parts.append(f"{v:.2f}" if v else "—")
    return "/".join(parts)


def _fmt_edge(state: LiveMatchState) -> str:
    parts = []
    for mkt, _ in _MKT_SIDE:
        rec = _rec_for_side(state, mkt)
        edge = rec.get("edge_pp") if rec else None
        parts.append(f"{edge:+.1f}" if edge is not None else "—")
    return "/".join(parts)


def resolve_pressure(state: LiveMatchState) -> tuple[float | None, float | None]:
    """Pressão H/A — campos do state ou fallback em sofascore_stats."""
    if state.pressure_home is not None and state.pressure_away is not None:
        return state.pressure_home, state.pressure_away
    ss = state.sofascore_stats or {}
    h = ss.get("ss_pressure_home")
    a = ss.get("ss_pressure_away")
    if h is not None and a is not None:
        return float(h), float(a)
    return None, None


def _fmt_pressure(state: LiveMatchState) -> str:
    h, a = resolve_pressure(state)
    if h is None or a is None:
        return "—"
    return f"{h:.0f}/{a:.0f}"


def _ss_pair(state: LiveMatchState, key_home: str, key_away: str) -> str:
    ss = state.sofascore_stats or {}
    h, a = ss.get(key_home), ss.get(key_away)
    if h is None and a is None:
        return "—"
    return f"{h if h is not None else '—'}/{a if a is not None else '—'}"


def _scan_progress_label(op_st: dict, heartbeat: dict) -> str:
    hb_done = heartbeat.get("n_done")
    hb_total = heartbeat.get("n_games")
    if hb_done and hb_total:
        return f"Scan: {hb_done}/{hb_total} jogos (snapshot parcial a cada 20)"
    if op_st.get("phase") == "scanning" or heartbeat.get("phase") == "scanning":
        return "Scan em andamento — aguarde alguns minutos (221 jogos)"
    return ""


def _refresh_context() -> dict:
    states, snap_meta = _load_states()
    op_st = read_operator_status()
    col_st = read_collector_status()
    heartbeat = read_scan_heartbeat()
    now_brt = datetime.now(BR).strftime("%H:%M:%S")
    cycle_ts, data_age_min = _latest_data_ts(snap_meta, op_st, heartbeat)
    return {
        "states": states,
        "snap_meta": snap_meta,
        "op_st": op_st,
        "col_st": col_st,
        "heartbeat": heartbeat,
        "now_brt": now_brt,
        "cycle_ts": cycle_ts,
        "data_age_min": data_age_min,
        "scan_note": _scan_progress_label(op_st, heartbeat),
    }


def _draw_sidebar(ctx: dict, cfg: dict) -> None:
    exec_cfg = cfg.get("execution", {})
    op_st = ctx["op_st"]
    col_st = ctx["col_st"]
    heartbeat = ctx["heartbeat"]
    scan_note = ctx["scan_note"]

    st.subheader("Processos CMD")
    if op_st.get("running"):
        st.success("🟢 Operação Betfair: ATIVA")
        st.caption(f"PID {op_st.get('pid', '—')} | ciclo {_process_cycle_label(op_st)}")
        if scan_note:
            st.caption(scan_note)
        elif op_st.get("phase") == "scanning" or heartbeat.get("phase") == "scanning":
            st.caption("Varrendo jogos — dados parciais aparecem durante o scan.")
    else:
        st.warning("⚫ Operação Betfair: parada")
        st.caption("Execute: `scripts\\start_operacao.bat`")

    if col_st.get("running"):
        st.success("🟢 Coleta SofaScore: ATIVA")
        st.caption(
            f"PID {col_st.get('pid', '—')} | ticks {col_st.get('ticks', 0)} | "
            f"último {_process_cycle_label(col_st)}"
        )
        if col_st.get("phase") == "scanning":
            st.caption("Coletando dados — pode levar alguns minutos com 200+ jogos.")
    else:
        st.warning("⚫ Coleta: parada")
        st.caption("Execute: `scripts\\start_coleta.bat`")

    st.divider()
    mode_label = "REAL 💰" if not exec_cfg.get("paper_mode", True) else "PAPER 📝"
    st.markdown(f"**Modo config:** {mode_label}")

    if exec_cfg.get("paper_mode", True):
        paper = get_state()
        st.metric("Banca paper", f"R$ {paper['bankroll']:,.2f}")
        st.caption(
            f"Inicial R$ {paper['initial_bankroll']:.2f} | "
            f"P&L {paper['pnl_total']:+.2f} ({paper['roi_pct']:+.1f}%) | "
            f"Disp. R$ {paper['available_bankroll']:.2f}"
        )
        st.divider()
        st.markdown("**Controles paper**")
        if st.button(
            "💰 Resetar saldo inicial",
            width="stretch",
            key="btn_reset_bankroll",
            help="Zera histórico, restaura R$ inicial e limpa posições",
        ):
            reset_initial_bankroll()
            st.success("Saldo inicial restaurado e entradas zeradas.")
            st.rerun()
        if st.button(
            "🚪 Resetar entradas",
            width="stretch",
            key="btn_reset_entries",
            help="Fecha posições abertas e permite novas entradas",
        ):
            info = reset_open_entries()
            st.success(
                f"Entradas resetadas: {info['positions_cleared']} posições, "
                f"{info['paper_cancelled']} trades paper cancelados."
            )
            st.rerun()
        st.caption("O robô em execução aplica o reset no próximo ciclo (~30s).")
    elif op_st.get("balance") is not None:
        st.metric("Saldo (último ciclo)", f"R$ {op_st['balance']:,.2f}")

    st.divider()
    st.markdown("**Campeonatos (watchlist)**")
    for _country, _slug, label in WATCHLIST_CATALOG:
        st.caption(f"• {label}")

    if st.button("🔄 Recarregar agora", width="stretch", key="btn_reload"):
        st.rerun()


def _draw_main(ctx: dict, cfg: dict, refresh_sec: int) -> None:
    states = ctx["states"]
    snap_meta = ctx["snap_meta"]
    op_st = ctx["op_st"]
    heartbeat = ctx["heartbeat"]
    now_brt = ctx["now_brt"]
    cycle_ts = ctx["cycle_ts"]
    data_age_min = ctx["data_age_min"]

    hb_done = heartbeat.get("n_done")
    hb_total = heartbeat.get("n_games")
    if hb_done and hb_total and int(hb_total) > 0:
        st.progress(
            min(int(hb_done) / int(hb_total), 1.0),
            text=f"Scan completo: {hb_done}/{hb_total} jogos processados",
        )

    st.title("📊 FPT Dashboard")
    st.caption(
        f"Dados em `{data_root()}` | Atualização a cada {refresh_sec}s | "
        "Operação 24/7 — todos os dias"
    )

    updated = snap_meta.get("updated") or snap_meta.get("mtime", "—")
    n_games = op_st.get("n_games") or len(states)
    n_live = op_st.get("n_live") or sum(1 for s in states if s.in_play and s.status not in ("FT", "CLOSED"))
    n_entries = op_st.get("n_entries", 0)
    n_exits = op_st.get("n_exits", 0)
    last_ts = _fmt_ts_short(op_st.get("ts")) or cycle_ts

    c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
    c1.metric("Jogos", n_games)
    c2.metric("Ao vivo", n_live)
    c3.metric("Entradas (ciclo)", n_entries)
    c4.metric("Saídas (ciclo)", n_exits)
    c5.metric("Posições", len(PositionManager().open_positions) + len(ScalpingEngine().open_positions))
    c6.metric("Último ciclo", cycle_ts)
    c7.metric("Agora (BRT)", now_brt)

    age_note = ""
    hb_done = heartbeat.get("n_done")
    hb_total = heartbeat.get("n_games")
    if op_st.get("phase") == "scanning" or heartbeat.get("phase") == "scanning":
        if hb_done and hb_total:
            age_note = f" | Scan em andamento: {hb_done}/{hb_total} jogos"
        else:
            age_note = " | Scan em andamento"
    elif data_age_min is not None and data_age_min >= 2:
        age_note = f" | Snapshot com ~{data_age_min:.0f} min de atraso"

    if not states:
        st.info(
            "Nenhum snapshot ainda. Inicie **`start_operacao.bat`** (gera snapshot a cada ciclo) "
            "ou **`start_coleta.bat`** para coleta de dados."
        )
        return

    n_with_odds = sum(
        1 for s in states
        if any(s.odds.get(k, {}).get("back") for k in ("Casa", "Empate", "Visitante"))
    )
    n_with_model = sum(1 for s in states if s.recommendations)
    prof = profile_summary(active_profile_name())
    n_scalp = len(active_scalp_slots())
    wk = load_weekly_meta()
    n_snap = snap_meta.get("n_matches")
    snap_note = f" | snapshot disco: {n_snap}" if n_snap else ""
    st.caption(
        f"Perfil: **{prof}** | {len(states)} jogos | com odds: **{n_with_odds}** | com modelo: **{n_with_model}** | "
        f"Scalp ativo agora: **{n_scalp}** | "
        f"Calendário semanal: `{WEEKLY_DIR}` ({wk.get('week_start', '—')} → {wk.get('week_end', '—')}) | "
        f"Ciclo operador: {last_ts}{age_note}{snap_note} | "
        f"Arquivo: `{snap_meta.get('path', '—')}`"
    )

    tab_games, tab_live, tab_robot, tab_paper = st.tabs([
        "📊 Jogos do dia",
        "🔴 In-Live",
        "⚡ Robô & Entradas",
        "📝 Paper — Evolução",
    ])

    with tab_games:
        _tab_games(states)
    with tab_live:
        _tab_inlive(states)
    with tab_robot:
        _tab_robot(cfg)
    with tab_paper:
        _tab_paper(cfg)


def _fmt_action(state: LiveMatchState) -> str:
    if state.best_action and state.best_action not in ("—", ""):
        mkt = market_label(state.best_market) if state.best_market else ""
        return f"{state.best_action} {mkt}".strip()
    best_rec = None
    best_score = -999.0
    for r in state.recommendations or []:
        edge = r.get("edge_pp")
        sb = float(r.get("stake_back_pct") or 0)
        sl = float(r.get("stake_lay_pct") or 0)
        score = None
        if edge is not None:
            try:
                score = float(edge)
            except (TypeError, ValueError):
                score = None
        if score is None:
            score = max(sb, sl) * 100.0
        if score is None or score <= best_score:
            continue
        best_score = score
        best_rec = r
    if best_rec:
        side = "BACK"
        if float(best_rec.get("stake_lay_pct") or 0) > float(best_rec.get("stake_back_pct") or 0):
            side = "LAY"
        return format_operation(side, best_rec.get("market"))
    return "—"


def _tab_games(states: list[LiveMatchState]):
    st.header("Jogos do dia — calendário e odds")
    st.caption("Odds e modelo FPT. Estatísticas in-live ficam na aba **In-Live**; suas entradas na aba **Robô & Entradas**.")

    rows = []
    for s in states:
        rows.append({
            "Status": "🔴 LIVE" if s.in_play else s.status,
            "Liga": s.league_label,
            "Jogo": f"{s.home} x {s.away}",
            "Horário": s.kickoff or "—",
            "Mod. back min (φ) H/E/A": _fmt_model_odds(s, "odd_minima_entrada"),
            "Merc. back H/E/A": _fmt_odds(s, "back"),
            "Mod. lay máx (φ) H/E/A": _fmt_model_odds(s, "lay_max"),
            "Merc. lay H/E/A": _fmt_odds(s, "lay"),
            "Edge pp H/E/A": _fmt_edge(s),
            "Prob H/E/A": (
                f"{s.prob_home:.0%}/{s.prob_draw:.0%}/{s.prob_away:.0%}"
                if s.prob_home is not None else "—"
            ),
            "Ação sugerida": _fmt_action(s),
        })
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


def _tab_inlive(states: list[LiveMatchState]):
    st.header("In-Live — estatísticas ao vivo")
    live = [
        s for s in states
        if (s.in_play or s.status in ("LIVE", "HT", "LIVE?"))
        and s.status not in ("FT", "CLOSED", "PRE")
    ]
    if not live:
        st.info("Nenhum jogo ao vivo no snapshot atual.")
        return

    st.subheader(f"Jogos ao vivo ({len(live)})")
    st.dataframe(
        pd.DataFrame([
            {
                "Liga": s.league_label,
                "Jogo": f"{s.home} x {s.away}",
                "Placar": s.score_display,
                "Min": s.elapsed_min if s.elapsed_min is not None else "—",
                "Pressão H/A": _fmt_pressure(s),
                "Posse H/A": _ss_pair(s, "ss_possession_home", "ss_possession_away"),
                "Chutes H/A": _ss_pair(s, "ss_shots_home", "ss_shots_away"),
                "No gol H/A": _ss_pair(s, "ss_sot_home", "ss_sot_away"),
                "Escanteios H/A": _ss_pair(s, "ss_corners_home", "ss_corners_away"),
                "xG H/A": _ss_pair(s, "ss_xg_home", "ss_xg_away"),
                "Momentum": f"{s.graph_momentum:+.0f}" if s.graph_momentum else "—",
            }
            for s in live
        ]),
        width="stretch",
        hide_index=True,
    )

    st.subheader("Detalhe por jogo")
    for s in live:
        with st.expander(
            f"🔴 {s.league_label}: {s.home} x {s.away} — {s.score_display} ({s.elapsed_min or '?'}')",
            expanded=len(live) <= 3,
        ):
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Horário", s.kickoff or "—")
            c2.metric("Minuto", s.elapsed_min or "—")
            ph, pa = resolve_pressure(s)
            c3.metric(
                "Pressão H/A",
                f"{ph:.0f} / {pa:.0f}" if ph is not None and pa is not None else "—",
            )
            c4.metric("Momentum", f"{s.graph_momentum:+.0f}" if s.graph_momentum else "—")
            c5.metric("Matched", f"{s.total_matched:,.0f}" if s.total_matched else "—")

            cmp_rows = []
            for mkt, label in _MKT_SIDE:
                rec = _rec_for_side(s, mkt)
                cmp_rows.append({
                    "Seleção": label,
                    "P modelo": f"{rec.get('probabilidade_estimada', 0):.1%}" if rec else "—",
                    "Back min (φ)": f"{rec.get('odd_minima_entrada', 0):.2f}" if rec else "—",
                    "Back mercado": f"{s.odds.get(label, {}).get('back', 0):.2f}" if s.odds.get(label, {}).get("back") else "—",
                    "Lay máx (φ)": f"{rec.get('lay_max', 0):.2f}" if rec else "—",
                    "Lay mercado": f"{s.odds.get(label, {}).get('lay', 0):.2f}" if s.odds.get(label, {}).get("lay") else "—",
                    "Edge pp": f"{rec.get('edge_pp', 0):+.1f}" if rec and rec.get("edge_pp") is not None else "—",
                })
            st.dataframe(pd.DataFrame(cmp_rows), hide_index=True, width='stretch')

            stats = s.sofascore_stats or {}
            if stats:
                labels = {
                    "ss_possession_home": "Posse mandante %",
                    "ss_possession_away": "Posse visitante %",
                    "ss_shots_home": "Chutes mandante",
                    "ss_shots_away": "Chutes visitante",
                    "ss_sot_home": "No gol mandante",
                    "ss_sot_away": "No gol visitante",
                    "ss_corners_home": "Escanteios mandante",
                    "ss_corners_away": "Escanteios visitante",
                    "ss_xg_home": "xG mandante",
                    "ss_xg_away": "xG visitante",
                }
                stat_rows = [
                    {"Stat": labels.get(k, k), "Valor": v}
                    for k, v in sorted(stats.items())
                    if v is not None and k in labels
                ]
                st.dataframe(pd.DataFrame(stat_rows), hide_index=True, width='stretch')


def _format_open_entry_rows() -> list[dict]:
    """Entradas abertas unificadas (managed + scalp + paper)."""
    return [
        {
            "Jogo": p["jogo"],
            "Modo": p["modo"],
            "Mercado": p["market"],
            "Lado": p["side"],
            "Posição": p["operation"],
            "Odd": p["odd"],
            "Stake": p["stake"],
            "Origem": p.get("tipo", "—"),
        }
        for p in _collect_open_positions()
    ]


def _tab_robot(cfg: dict):
    st.header("Entradas e robô")
    exec_cfg = cfg.get("execution", {})
    st.caption(f"Log: `{DATA / 'live'}` | Operação contínua — use `start_operacao.bat`")

    open_rows = _format_open_entry_rows()
    st.subheader(f"Entradas abertas ({len(open_rows)})")
    if open_rows:
        st.dataframe(
            pd.DataFrame(open_rows),
            width="stretch",
            hide_index=True,
        )
    else:
        st.info("Nenhuma entrada aberta no momento.")

    st.subheader("Histórico de entradas (paper)")
    trades = list_paper_trades(100)
    if trades:
        st.dataframe(
            pd.DataFrame(_format_entry_rows(trades)),
            width="stretch",
            hide_index=True,
        )
    else:
        st.caption("Nenhuma entrada registrada ainda.")

    if exec_cfg.get("paper_mode", True):
        open_trades = [t for t in trades if t.get("status") == "OPEN"]
        n_open = len(open_trades) + len(PositionManager().open_positions) + len(ScalpingEngine().open_positions)
        if n_open:
            st.caption(f"{n_open} posição(ões) ainda aberta(s) — lucro aparece após a saída.")

    st.subheader("Log do robô")
    logs = load_robot_log(30)
    if logs:
        for entry in logs:
            st.text(f"{entry.get('ts', '')} — {entry.get('msg', '')}")
    else:
        st.caption("Inicie `start_operacao.bat` para ver o log.")


def _tab_paper(cfg: dict):
    st.header("Banca fictícia — evolução")
    exec_cfg = cfg.get("execution", {})
    if not exec_cfg.get("paper_mode", True):
        st.warning("Modo REAL ativo em config/live.yaml. Ative `paper_mode: true` para simulação.")
        return

    paper = get_state()
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Banca atual", f"R$ {paper['bankroll']:.2f}")
    c2.metric("Inicial", f"R$ {paper['initial_bankroll']:.2f}")
    c3.metric("P&L total", f"R$ {paper['pnl_total']:+.2f}")
    c4.metric("ROI", f"{paper['roi_pct']:+.1f}%")
    c5.metric("Abertas", paper["n_trades_open"])

    st.caption(
        f"Teto stake: {paper['max_stake_pct']:.1%} | "
        f"Exposição aberta: R$ {paper['exposure']:.2f} | "
        f"Disponível: R$ {paper['available_bankroll']:.2f} | "
        f"DB: `data/live/paper_trading.db`"
    )

    hist = bankroll_history()
    minute_hist = bankroll_minute_history()
    db_path = minute_timeline_path()
    n_match_rows = match_minute_count()

    st.subheader("Saldo por minuto")
    st.caption(
        f"Base unificada (banca + SofaScore por jogo): `{db_path}` | "
        f"{n_match_rows} linhas de jogos hoje na tabela `match_minute`"
    )
    if len(minute_hist) > 1:
        df_min = pd.DataFrame(minute_hist)
        df_min["label"] = df_min["minute_ts"].astype(str).str.replace("T", " ").str[:16]
        st.line_chart(df_min.set_index("minute_ts")["bankroll"])
        st.dataframe(
            df_min[["label", "bankroll", "exposure", "available", "n_positions"]].rename(
                columns={
                    "label": "Minuto",
                    "bankroll": "Saldo R$",
                    "exposure": "Exposição R$",
                    "available": "Disponível R$",
                    "n_positions": "Posições",
                }
            ),
            width="stretch",
            hide_index=True,
        )
    else:
        st.info(
            "Saldo por minuto aparece após alguns ciclos do robô (`start_operacao.bat`) "
            "ou da coleta (`start_coleta.bat`)."
        )

    st.subheader("Curva da banca (eventos)")
    if len(hist) > 1:
        df_hist = pd.DataFrame(hist)
        st.line_chart(df_hist.set_index("ts")["bankroll"])
    else:
        st.info("Sem histórico de eventos ainda. Inicie `start_operacao.bat` para registrar operações fictícias.")

    st.subheader("Entradas")
    trades = list_paper_trades(100)
    if trades:
        st.dataframe(
            pd.DataFrame(_format_entry_rows(trades)),
            width="stretch",
            hide_index=True,
        )
    else:
        st.caption("Nenhuma entrada registrada ainda.")

    st.divider()
    st.subheader("Controles")
    c_reset1, c_reset2 = st.columns(2)
    with c_reset1:
        if st.button("💰 Resetar saldo inicial", type="secondary"):
            reset_initial_bankroll()
            st.success("Saldo inicial restaurado (config/live.yaml) e entradas zeradas.")
            st.rerun()
    with c_reset2:
        if st.button("🚪 Resetar entradas (sair de tudo)", type="secondary"):
            info = reset_open_entries()
            st.success(
                f"Posições fechadas: {info['positions_cleared']} | "
                f"Trades paper cancelados: {info['paper_cancelled']}"
            )
            st.rerun()
    st.caption(
        "Saldo inicial: zera histórico e restaura a banca configurada. "
        "Entradas: fecha posições abertas e libera novas oportunidades no próximo ciclo do robô."
    )


def _schedule_page_reload(seconds: int) -> None:
    """Recarrega a página inteira — evita erro removeChild do React (fragments/autorefresh)."""
    if seconds <= 0:
        return
    components.html(
        f"<script>window.setTimeout(function(){{window.parent.location.reload();}}, {seconds * 1000});</script>",
        height=0,
        width=0,
    )


def main():
    cfg = load_live_config()
    dash_cfg = cfg.get("dashboard", {})
    refresh_sec = int(dash_cfg.get("refresh_seconds", 15))

    st.set_page_config(
        page_title="FPT Dashboard",
        page_icon="📊",
        layout="wide",
    )

    ctx = _refresh_context()
    with st.sidebar:
        _draw_sidebar(ctx, cfg)
    _draw_main(ctx, cfg, refresh_sec)
    _schedule_page_reload(refresh_sec)


if __name__ == "__main__":
    main()
