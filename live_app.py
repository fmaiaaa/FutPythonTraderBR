"""
FutPythonTrader — Operação Live (sábado/domingo)

Monitor in-time: placares Betfair, odds back/lay, alertas ML, PDFs do fim de semana,
análise de ticks Betfair e métricas do modelo (ROI, drawdown, receita).
"""
from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from fpt.live.analytics import (
    build_model_dashboard_metrics,
    drawdown_series,
    equity_curve_from_trades,
    load_holdout_summary,
    load_holdout_trades,
    load_ticks,
    odds_by_score_summary,
    odds_evolution_df,
    run_evaluation_if_missing,
)
from fpt.live.betfair_logger import export_daily_workbook, list_available_dates
from fpt.live.config import load_live_config
from fpt.live.models import LiveMatchState
from fpt.live.monitor import LiveMonitor
from fpt.live.reports import find_weekend_reports
from fpt.live.executor import BetfairExecutor, load_recent_executions
from fpt.pipeline import load_merged
from fpt.report.chart_equity import decompose_equity_time

BR = ZoneInfo("America/Sao_Paulo")


def main():
    cfg = load_live_config()
    default_refresh = cfg["live"].get("refresh_seconds", 60)

    st.set_page_config(
        page_title="FPT Live — Operação In-Time",
        page_icon="⚽",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.markdown("""
    <style>
        .live-badge { background:#e53935; color:white; padding:2px 8px; border-radius:4px; font-weight:700; font-size:0.75rem; }
        .pre-badge { background:#546e7a; color:white; padding:2px 8px; border-radius:4px; font-size:0.75rem; }
        .enter-badge { background:#2e7d32; color:white; padding:2px 10px; border-radius:4px; font-weight:700; }
        .watch-badge { background:#f57c00; color:white; padding:2px 10px; border-radius:4px; font-weight:700; }
        .alert-box { border-left:4px solid #2e7d32; padding:8px 12px; margin:4px 0; background:#1a2e1a; }
        .alert-box.watch { border-color:#f57c00; background:#2e2410; }
        .update-ts { color:#90a4ae; font-size:0.85rem; }
        .odds-stale { color:#ff9800; font-weight:600; }
    </style>
    """, unsafe_allow_html=True)

    with st.sidebar:
        st.title("⚽ FPT Live")
        st.caption("Operação in-time — fim de semana")
        page = st.radio(
            "Seção",
            ["Monitor Live", "Análise Betfair", "Modelo & Backtest", "PDFs Fim de Semana"],
            index=0,
        )
        st.divider()
        auto = st.toggle("Auto-atualizar (1 min)", value=True)
        refresh_sec = st.slider("Intervalo (segundos)", 30, 120, default_refresh, 15)
        filter_status = st.multiselect("Status", ["PRE", "LIVE", "FT"], default=["PRE", "LIVE"])
        filter_league = st.text_input("Filtrar liga", "")
        only_alerts = st.checkbox("Só alertas", value=False)
        bankroll = st.number_input("Banca (R$)", 100.0, 100000.0, float(cfg["live"].get("bankroll", 1000)), 100.0)
        cfg["live"]["bankroll"] = bankroll

        if st.button("🔄 Atualizar agora", type="primary", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

        st.divider()
        exec_cfg = load_live_config().get("execution", {})
        st.markdown("**Execução Betfair**")
        if exec_cfg.get("enabled"):
            st.success("Ativa" + (" (PAPER)" if exec_cfg.get("paper_mode", True) else " (REAL)"))
        else:
            st.info("Desabilitada — `execution.enabled: true` em config/live.yaml")
        mon = _get_monitor()
        st.markdown("**Betfair**")
        st.success("Conectado") if mon.betfair_ok else st.warning("Não configurado")

    now = datetime.now(BR)

    if page == "PDFs Fim de Semana":
        _page_pdfs(now)
    elif page == "Análise Betfair":
        _page_betfair_analysis(now)
    elif page == "Modelo & Backtest":
        _page_model_backtest(bankroll)
    else:
        _page_monitor(cfg, auto, refresh_sec, filter_status, filter_league, only_alerts, bankroll, now)


def _page_betfair_analysis(now: datetime):
    st.header("Análise Betfair — Odds × Tempo × Placar")
    st.caption("Ticks salvos automaticamente a cada scan live em `data/betfair/ticks/`")

    dates_avail = list_available_dates()
    if not dates_avail:
        st.info(
            "Nenhum tick registrado ainda. Abra **Monitor Live** durante jogos para acumular dados "
            "ou rode `python main.py live scan`."
        )
        return

    col1, col2, col3 = st.columns(3)
    default_end = dates_avail[-1]
    default_start = max(dates_avail[0], default_end - timedelta(days=7))
    with col1:
        start_d = st.date_input("De", default_start, min_value=dates_avail[0], max_value=default_end)
    with col2:
        end_d = st.date_input("Até", default_end, min_value=dates_avail[0], max_value=default_end)
    with col3:
        if st.button("📊 Exportar Excel do dia", use_container_width=True):
            path = export_daily_workbook(end_d)
            if path and path.exists():
                st.success(f"Planilha: {path}")
            else:
                st.warning("Sem ticks no dia selecionado.")

    ticks = load_ticks(start=start_d, end=end_d)
    if ticks.empty:
        st.warning("Sem dados no intervalo.")
        return

    ticks["timestamp"] = pd.to_datetime(ticks["timestamp"], errors="coerce")
    ticks["match"] = ticks["home"] + " x " + ticks["away"]
    matches = sorted(ticks["match"].unique())

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Ticks", len(ticks))
    c2.metric("Jogos", ticks["match"].nunique())
    c3.metric("Ao vivo (ticks)", int((ticks["in_play"] == True).sum()))  # noqa: E712
    c4.metric("Último tick", ticks["timestamp"].max().strftime("%d/%m %H:%M"))

    sel_match = st.selectbox("Jogo", matches)
    h, a = sel_match.split(" x ", 1)
    match_ticks = ticks[(ticks["home"] == h) & (ticks["away"] == a)]

    st.subheader("Evolução das odds (back/lay)")
    evo = odds_evolution_df(match_ticks)
    if not evo.empty:
        fig = px.line(
            evo,
            x="timestamp",
            y="odd",
            color="selection",
            line_dash="side",
            markers=True,
            title=f"Odds — {sel_match}",
            labels={"odd": "Odd", "timestamp": "Horário"},
        )
        fig.update_layout(height=420, legend=dict(orientation="h"))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Sem odds registradas para este jogo.")

    st.subheader("Odds vs minuto de jogo")
    if "elapsed_min" in match_ticks.columns and match_ticks["back_home"].notna().any():
        fig2 = make_subplots(specs=[[{"secondary_y": True}]])
        for col, name, color in [
            ("back_home", "Back Casa", "#1976d2"),
            ("back_draw", "Back Empate", "#ffa000"),
            ("back_away", "Back Visit.", "#388e3c"),
        ]:
            sub = match_ticks.dropna(subset=[col, "elapsed_min"])
            if not sub.empty:
                fig2.add_trace(
                    go.Scatter(x=sub["elapsed_min"], y=sub[col], name=name, mode="lines+markers", line=dict(color=color)),
                    secondary_y=False,
                )
        sub = match_ticks.dropna(subset=["score_home", "score_away", "elapsed_min"])
        if not sub.empty:
            fig2.add_trace(
                go.Scatter(
                    x=sub["elapsed_min"],
                    y=sub["score_home"] + sub["score_away"],
                    name="Gols total",
                    mode="markers",
                    marker=dict(size=8, color="#e53935"),
                ),
                secondary_y=True,
            )
        fig2.update_xaxes(title_text="Minuto")
        fig2.update_yaxes(title_text="Odd back", secondary_y=False)
        fig2.update_yaxes(title_text="Gols (total)", secondary_y=True)
        fig2.update_layout(height=400, title="Odds × tempo de jogo")
        st.plotly_chart(fig2, use_container_width=True)

    st.subheader("Odds médias por placar (in-play)")
    by_score = odds_by_score_summary(ticks)
    if not by_score.empty:
        st.dataframe(by_score.round(3), use_container_width=True, hide_index=True)
        melt = by_score.melt(
            id_vars=["score", "n"],
            value_vars=["back_home_mean", "back_draw_mean", "back_away_mean"],
            var_name="mercado",
            value_name="odd_media",
        )
        fig3 = px.bar(
            melt,
            x="score",
            y="odd_media",
            color="mercado",
            barmode="group",
            title="Odd back média por placar",
        )
        st.plotly_chart(fig3, use_container_width=True)

    st.subheader("Heatmap — odd back casa × placar × minuto")
    ht = match_ticks.dropna(subset=["elapsed_min", "back_home", "score"]).copy()
    if len(ht) >= 3:
        ht["min_bucket"] = (ht["elapsed_min"] // 15 * 15).astype(int)
        pivot = ht.pivot_table(index="score", columns="min_bucket", values="back_home", aggfunc="mean")
        if not pivot.empty:
            fig4 = px.imshow(pivot, aspect="auto", color_continuous_scale="RdYlGn_r", title="Back Casa")
            st.plotly_chart(fig4, use_container_width=True)

    st.subheader("Planilha bruta (amostra)")
    st.dataframe(match_ticks.tail(50), use_container_width=True, hide_index=True)


def _page_model_backtest(bankroll: float):
    st.header("Modelo ML & Backtest Holdout")
    run_evaluation_if_missing()

    dash = build_model_dashboard_metrics()
    summary = load_holdout_summary()
    trades = load_holdout_trades()

    if not dash.get("roi_pct") and trades.empty:
        st.warning("Sem avaliação. Rode: `python main.py treinar` e `python main.py evaluate`")
        meta_path = Path("data/models/meta.json")
        if meta_path.exists():
            with st.expander("meta.json"):
                st.json(json.loads(meta_path.read_text(encoding="utf-8")))
        return

    st.subheader("Estatísticas do modelo")
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("ROI (modelo)", f"{dash.get('roi_pct', 0):.2f}%")
    m2.metric("Max Drawdown", f"{dash.get('max_drawdown_pct', 0):.2f}%")
    m3.metric("Win rate (entradas)", f"{(dash.get('win_rate_model') or 0):.1%}")
    m4.metric("Acurácia teste", f"{(dash.get('accuracy_test') or 0):.1%}")
    m5.metric("Log-loss teste", f"{dash.get('logloss_test', 0):.3f}" if dash.get("logloss_test") else "—")
    m6.metric("Pseudo-R²", f"{dash.get('pseudo_r2', 0):.3f}" if dash.get("pseudo_r2") is not None else "—")

    m7, m8, m9, m10 = st.columns(4)
    m7.metric("AUC HT", f"{dash.get('auc_ht', 0):.3f}" if dash.get("auc_ht") else "—")
    m8.metric("Brier (casa)", f"{dash.get('brier_test', 0):.3f}" if dash.get("brier_test") else "—")
    m9.metric("ECE (casa)", f"{dash.get('ece_test', 0):.3f}" if dash.get("ece_test") else "—")
    m10.metric("Trades modelo", dash.get("n_trades_model", 0))

    st.caption(
        f"Tipo: {dash.get('model_type', '—')} | "
        f"Amostras teste: {dash.get('n_test_samples', '—')} | "
        f"Features: {dash.get('n_features', '—')}"
    )

    st.subheader("Evolução da receita (holdout 30%)")
    mode = st.radio("Estratégia de stake", ["Modelo (Kelly)", "Fixo 1%"], horizontal=True)
    if not trades.empty:
        eq = equity_curve_from_trades(
            trades,
            bankroll=bankroll,
            mode="model" if mode.startswith("Modelo") else "fixed",
            fixed_pct=0.01,
        )
        if len(eq) >= 2:
            dates = eq["date"].values
            y = eq["equity_pct"].values.astype(float)
            dec = decompose_equity_time(dates, y)

            fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.06,
                                subplot_titles=("Evolução geral", "Tendência (OLS)", "Ciclo (série − tendência)"))
            fig.add_trace(go.Scatter(x=dates, y=y, name="Retorno %", line=dict(color="#1565C0")), row=1, col=1)
            fig.add_hline(y=0, line_dash="dash", line_color="gray", row=1, col=1)
            fig.add_trace(go.Scatter(x=dates, y=y, line=dict(color="#1565C0", width=1), opacity=0.25, showlegend=False), row=2, col=1)
            fig.add_trace(go.Scatter(x=dates, y=dec["trend"], name="Tendência", line=dict(color="#C62828", width=2)), row=2, col=1)
            fig.add_trace(go.Scatter(x=dates, y=dec["cycle"], name="Ciclo", fill="tozeroy", line=dict(color="#546E7A")), row=3, col=1)
            fig.update_layout(height=720, showlegend=True)
            fig.update_yaxes(title_text="% banca", row=1, col=1)
            fig.update_yaxes(title_text="% banca", row=2, col=1)
            fig.update_yaxes(title_text="p.p.", row=3, col=1)
            st.plotly_chart(fig, use_container_width=True)

        dd = drawdown_series(eq)
        fig_dd = px.area(dd, x="date", y="drawdown_pct", title="Drawdown (%)")
        fig_dd.update_layout(height=280)
        st.plotly_chart(fig_dd, use_container_width=True)

    st.subheader("Comparativo de stakes fixos vs modelo")
    metrics = summary.get("metrics", summary)
    rows = []
    for key, val in metrics.items():
        if isinstance(val, dict) and "roi_pct" in val:
            rows.append({"estrategia": key, **val})
    if rows:
        cmp_df = pd.DataFrame(rows)[["estrategia", "roi_pct", "max_drawdown_pct", "n_trades"]]
        fig_cmp = px.bar(
            cmp_df,
            x="estrategia",
            y="roi_pct",
            color="max_drawdown_pct",
            title="ROI por estratégia (holdout)",
            labels={"roi_pct": "ROI %", "max_drawdown_pct": "Max DD %"},
        )
        st.plotly_chart(fig_cmp, use_container_width=True)
        st.dataframe(cmp_df.round(2), use_container_width=True, hide_index=True)

    st.subheader("Calibração — acurácia treino vs teste")
    meta = metrics.get("meta", {})
    if meta.get("metrics_outcome_train") and meta.get("metrics_outcome_test"):
        cal = pd.DataFrame([
            {"split": "Treino (70%)", **meta["metrics_outcome_train"]},
            {"split": "Teste (30%)", **meta["metrics_outcome_test"]},
        ])
        fig_cal = px.bar(cal, x="split", y=["accuracy", "logloss", "brier_home"], barmode="group", title="Métricas outcome")
        st.plotly_chart(fig_cal, use_container_width=True)

    with st.expander("Detalhes meta.json"):
        meta_path = Path("data/models/meta.json")
        if meta_path.exists():
            st.json(json.loads(meta_path.read_text(encoding="utf-8")))


def _page_pdfs(now: datetime):
    st.header("Relatórios PDF — Fim de Semana")
    reports = find_weekend_reports()
    st.caption(f"{reports['start']} → {reports['end']} | Atualizado {now.strftime('%d/%m/%Y %H:%M')}")

    if reports["drive_links"]:
        st.subheader("Google Drive")
        for link in reports["drive_links"]:
            url = link.get("web_view_link") or "#"
            st.markdown(f"- [{link.get('name', 'PDF')}]({url})")
    else:
        st.info(
            "Nenhum PDF no Drive ainda. O **GitHub Actions** gera e envia todo sábado 07:00 (BRT). "
            "[Ver workflows](https://github.com/fmaiaaa/FutPythonTraderBR/actions)"
        )


def _page_monitor(cfg, auto, refresh_sec, filter_status, filter_league, only_alerts, bankroll, now):
    st.header("Operação Live")
    scan_ts = now.strftime("%d/%m/%Y %H:%M:%S")
    st.markdown(
        f'<span class="update-ts">🕐 Relógio: {scan_ts} (Brasília) | '
        f'Odds atualizadas a cada {refresh_sec}s (minuto a minuto)</span>',
        unsafe_allow_html=True,
    )

    monitor = _get_monitor()
    df = _load_df()
    if df is None:
        st.warning("Base histórica ausente. CI ou `python main.py download-all && merge && treinar`")
        st.stop()

    with st.spinner("Betfair + modelo ML..."):
        states = _run_scan(monitor, df)

    global_updated = monitor.last_scan.strftime("%H:%M:%S") if monitor.last_scan else "—"
    st.info(
        f"📊 **Última atualização de odds:** {global_updated} | "
        f"Fonte: Betfair Exchange BR"
    )

    if filter_status:
        states = [s for s in states if s.status in filter_status or (s.in_play and "LIVE" in filter_status)]
    if filter_league:
        fl = filter_league.lower()
        states = [s for s in states if fl in s.league_label.lower() or fl in s.league.lower()]
    if only_alerts:
        states = [s for s in states if s.alerts]

    c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
    c1.metric("Jogos", len(states))
    c2.metric("Ao vivo", sum(1 for s in states if s.in_play))
    c3.metric("Alertas", sum(len(s.alerts) for s in states))
    c4.metric("Entradas", sum(1 for s in states if s.best_action == "ENTER"))
    c5.metric("Max ¼ Kelly", f"{max((s.kelly_quarter for s in states), default=0):.2%}")
    c6.metric("Odds @", global_updated)
    c7.metric("Próx. tick", f"{refresh_sec}s")

    all_alerts = [a for s in states for a in s.alerts]
    exec_cfg = load_live_config().get("execution", {})
    executor = BetfairExecutor()

    if all_alerts:
        st.subheader("🔔 Alertas")
        for a in all_alerts[:15]:
            icon = "🟢" if a.alert_type == "ENTER" else ("🟠" if a.alert_type == "WATCH" else "🔵")
            st.markdown(f"{icon} **{a.alert_type}** — {a.home} x {a.away}: {a.message}")

        if executor.enabled or exec_cfg.get("paper_mode", True):
            st.caption(
                f"Execução: {'PAPER' if executor.paper_mode else 'REAL'} | "
                f"{'automática' if exec_cfg.get('auto_execute') else 'aprovação manual'}"
            )
            for a in all_alerts:
                if a.alert_type not in ("ENTER", "HT_EXIT"):
                    continue
                side = a.recommended_side or ("LAY" if a.alert_type == "HT_EXIT" else "BACK")
                stake = a.stake_back_pct if side == "BACK" else a.stake_lay_pct
                if stake <= 0:
                    continue
                cols = st.columns([3, 1, 1])
                cols[0].markdown(
                    f"**{a.home} x {a.away}** — {side} @ "
                    f"{a.odd_back if side == 'BACK' else a.odd_lay:.2f} | stake **{stake:.2%}**"
                )
                if exec_cfg.get("auto_execute") and a.alert_type == "ENTER":
                    res = executor.execute_alert(a, side=side, bankroll=bankroll, approved=True)
                    cols[1].success(res.get("status", "OK"))
                else:
                    if cols[1].button(f"✅ Executar {side}", key=f"exec_{a.alert_id}"):
                        res = executor.execute_alert(a, side=side, bankroll=bankroll, approved=True)
                        if res.get("status") in ("PLACED", "PAPER"):
                            st.success(res.get("message", "Ordem enviada"))
                        else:
                            st.error(res.get("message", "Falha"))

        recent = load_recent_executions(5)
        if recent:
            with st.expander("Últimas execuções"):
                st.dataframe(pd.DataFrame(recent), use_container_width=True, hide_index=True)

    if not states:
        st.info("Nenhum jogo na watchlist.")
    else:
        rows = []
        for s in states:
            rows.append({
                "": "🔴" if s.in_play else "⏳",
                "Liga": s.league_label,
                "Jogo": f"{s.home} x {s.away}",
                "Placar": s.score_display,
                "Odds @": s.odds_updated_at or global_updated,
                "Back H/E/A": _fmt_odds(s, "back"),
                "Lay H/E/A": _fmt_odds(s, "lay"),
                "Modelo H/E/A": (
                    f"{s.prob_home:.0%}/{s.prob_draw:.0%}/{s.prob_away:.0%}" if s.prob_home else "—"
                ),
                "¼ Kelly": f"{s.kelly_quarter:.2%}" if s.kelly_quarter else "—",
                "Stake B%": f"{s.stake_back_pct:.2%}" if s.stake_back_pct else "—",
                "Stake L%": f"{s.stake_lay_pct:.2%}" if s.stake_lay_pct else "—",
                "Ação": s.best_action,
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        for s in states:
            with st.expander(f"{s.home} x {s.away} — {s.league_label} | {s.score_display}", expanded=bool(s.alerts)):
                st.caption(f"Odds atualizadas às **{s.odds_updated_at}** | Fonte: {s.odds_source}")
                if s.recommendations:
                    st.dataframe(pd.DataFrame([
                        {
                            "Mercado": r.get("market_label"),
                            "Ação": r.get("action"),
                            "P": f"{r.get('probabilidade_estimada', 0):.1%}",
                            "Back mkt": r.get("odd_back"),
                            "Lay mkt": r.get("odd_lay"),
                            "Bk mín": r.get("odd_minima_entrada"),
                            "Ly máx": r.get("lay_max"),
                            "Edge": r.get("edge_pp"),
                            "Kelly cheio": f"{r.get('kelly_cheio', 0):.2%}",
                            "¼ Kelly": f"{r.get('kelly_quarto', 0):.2%}",
                            "% Banca Back": f"{r.get('stake_back_pct', r.get('pct_banca', 0)):.2%}",
                            "% Banca Lay": f"{r.get('stake_lay_pct', 0):.2%}",
                        }
                        for r in s.recommendations
                    ]), hide_index=True)

    if auto:
        time.sleep(refresh_sec)
        st.rerun()


def _fmt_odds(s: LiveMatchState, side: str) -> str:
    parts = []
    for label in ("Casa", "Empate", "Visitante"):
        v = s.odds.get(label, {}).get(side)
        parts.append(f"{v:.2f}" if v else "—")
    return "/".join(parts)


@st.cache_resource
def _get_monitor():
    return LiveMonitor()


@st.cache_data(ttl=55, show_spinner=False)
def _load_df():
    try:
        return load_merged()
    except FileNotFoundError:
        return None


def _run_scan(monitor: LiveMonitor, df):
    return monitor.scan(df)


if __name__ == "__main__":
    main()
