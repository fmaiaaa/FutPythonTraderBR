"""Dashboard — Trading ML completo."""
from datetime import date

import pandas as pd
import streamlit as st

from fpt.leagues import BRAZIL_MALE_LEAGUES
from fpt.pipeline import load_merged
from fpt.operation import league_summary
from fpt.trading.engine import build_recommendation, scan_day
from fpt.trading.market_sim import SimulatedMarket
from fpt.trading.config import load_config
from fpt.models.predict import get_predictor
from fpt.models.train import train_models
from fpt.models.calibration import load_calibration

st.set_page_config(page_title="FutPythonTrader BR", layout="wide")
st.title("FutPythonTrader BR — Trading ML")

cfg = load_config()
pred = get_predictor()

tab1, tab2, tab3, tab4, tab5 = st.tabs(
    ["Operação", "Scan Hoje", "Treinar ML", "Calibracao", "Config"]
)

with tab1:
    st.subheader("Avaliar operação (pré-jogo → saída HT)")
    try:
        df = load_merged()
        teams = sorted(set(df["Home"].dropna()) | set(df["Away"].dropna()))
        c1, c2, c3 = st.columns(3)
        home = c1.selectbox("Mandante", teams)
        away = c2.selectbox("Visitante", [t for t in teams if t != home] or teams)
        market = c3.selectbox("Mercado", ["home_win_ft", "draw_ft", "away_win_ft"],
                              format_func=lambda x: {"home_win_ft": "Mandante", "draw_ft": "Empate", "away_win_ft": "Visitante"}[x])
        odd_in = st.number_input("Odd mercado (0 = usar FPT)", 0.0, 50.0, 0.0, 0.01)
        bankroll = st.number_input("Banca", 100.0, 100000.0, float(cfg["trading"]["bankroll"]), 100.0)

        if st.button("Calcular"):
            odds = SimulatedMarket(df).get_odds(home, away)
            if odd_in > 1.01:
                if market == "home_win_ft":
                    odds.home = odd_in
                elif market == "draw_ft":
                    odds.draw = odd_in
                else:
                    odds.away = odd_in
            rec = build_recommendation(df, home, away, market, odds, bankroll=bankroll)

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Probabilidade", f"{rec.probabilidade_estimada:.1%}")
            m2.metric("Odd justa", f"{rec.odd_justa:.2f}")
            m3.metric("φ segurança", f"{rec.phi_seguranca:.3f}")
            m4.metric("Odd mínima", f"{rec.odd_minima_entrada:.2f}")

            m5, m6, m7, m8 = st.columns(4)
            m5.metric("Lucro est. HT", f"{rec.lucro_estimado_pct:+.2f}%")
            m6.metric("¼ Kelly", f"{rec.kelly_quarto:.2%}")
            m7.metric("% Banca", f"{rec.pct_banca:.2%}")
            m8.metric("Stake", f"R$ {rec.stake_valor:.2f}")

            if rec.action == "ENTER":
                st.success("ENTRADA RECOMENDADA")
            else:
                st.warning(f"SKIP — {', '.join(rec.reasons)}")

            st.code(rec.report())

            if rec.schedule_notes:
                st.markdown("**Agenda cruzada**")
                for n in rec.schedule_notes:
                    st.write(f"• {n}")
    except FileNotFoundError as e:
        st.warning(str(e))
        st.code("python main.py download-all && python main.py treinar")

with tab2:
    d = st.date_input("Data", value=date.today())
    if st.button("Scan entradas"):
        try:
            df = load_merged()
            recs = scan_day(df, d.isoformat())
            st.write(f"**{len(recs)} entradas**")
            for r in recs:
                with st.expander(f"{r.home} x {r.away} — stake R${r.stake_valor:.2f}"):
                    st.code(r.report())
        except Exception as e:
            st.error(str(e))

with tab3:
    st.subheader("Treinar modelos robustos")
    st.caption("HistGradientBoosting + calibração isotônica + agenda cruzada + stats FPT")
    if st.button("Treinar agora"):
        with st.spinner("Treinando... pode levar alguns minutos"):
            df = load_merged()
            meta = train_models(df)
        st.success("Modelos salvos!")
        st.json(meta)

with tab4:
    cal = load_calibration()
    st.json(cal)
    st.caption("φ dinâmico usa o erro por faixa de probabilidade (ECE)")

with tab5:
    st.json(cfg)
    st.markdown(f"Modelo carregado: **{'sim' if pred.ready else 'não — rode treinar'}**")
