from __future__ import annotations

import pandas as pd
import pytest

from fpt.report.revenue_metrics import max_losing_streak, max_winning_streak, compute_revenue_stats
from fpt.report.revenue_evolution import build_combined_report, build_scalping_report
from fpt.models.evaluate import EquityCurve


def test_losing_streak():
    assert max_losing_streak([True, False, False, False, True, False]) == 3
    assert max_winning_streak([True, True, False, True, True, True]) == 3


def test_scalping_report_empty_ticks():
    rep = build_scalping_report(ticks=pd.DataFrame())
    assert rep.method == "scalping"
    assert rep.stats["n_trades"] == 0
    assert "Sem ticks" in rep.note


def test_combined_report_merges():
    pre = build_scalping_report(ticks=pd.DataFrame())
    pre.method = "pre_live"
    pre.trades = pd.DataFrame([{
        "timestamp": pd.Timestamp("2026-01-01"),
        "date": pd.Timestamp("2026-01-01"),
        "ht_return_pct": 0.05,
        "pnl_pct": 0.05,
        "win": True,
        "method": "pre_live",
        "entered_model": True,
        "entry_odd": 2.0,
        "p_ht": 0.6,
        "back_min": 1.8,
    }])
    pre.equity = EquityCurve(series=pd.Series([0.0, 5.0], index=pd.to_datetime(["2025-12-31", "2026-01-01"])))
    scalp = build_scalping_report(ticks=pd.DataFrame())
    combined = build_combined_report(pre, scalp, bankroll=1000.0)
    assert combined.method == "combined"
    assert combined.stats["n_pre_live"] == 1


def test_generate_revenue_pdf(tmp_path):
    from fpt.report.pdf_revenue import generate_revenue_pdf
    from fpt.report.revenue_evolution import RevenueReport

    eq = EquityCurve(
        series=pd.Series(
            [0.0, 2.0, 4.0, 3.0, 6.0],
            index=pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05"]),
        ),
        final_pct=6.0,
        max_drawdown_pct=-1.0,
        n_trades=4,
    )
    trades = pd.DataFrame({
        "win": [True, True, False, True],
        "pnl_pct": [0.02, 0.02, -0.01, 0.03],
    })
    stats = compute_revenue_stats(eq, trades, pnl_col="pnl_pct")
    stats["label"] = "Teste"
    rep = RevenueReport(method="pre_live", title="Teste", equity=eq, trades=trades, stats=stats)
    out = tmp_path / "test_revenue.pdf"
    generate_revenue_pdf(rep, out, saturday="2026-01-04")
    assert out.exists()
    assert out.stat().st_size > 1000
