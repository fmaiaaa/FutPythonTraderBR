"""PDF de avaliacao do modelo — metricas e curvas de receita (tempo × % banca)."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..models.evaluate import ModelEvaluationResult
from ..client import DATA
from .chart_equity import chart_equity_triple

MODEL_DIR = DATA / "models"
CONTENT_W = A4[0] - 3 * cm

STAKE_COLORS = {
    "model": ("#1A237E", "#C62828"),
    "fixed_0.2%": ("#2E7D32", "#558B2F"),
    "fixed_0.5%": ("#00695C", "#00897B"),
    "fixed_1.0%": ("#F57F17", "#FF8F00"),
    "fixed_2.0%": ("#EF6C00", "#E65100"),
    "fixed_5.0%": ("#C62828", "#B71C1C"),
    "fixed_10.0%": ("#6A1B9A", "#4A148C"),
}


def _centered_image(path: Path, width: float, height: float) -> Table:
    img = Image(str(path), width=width, height=height)
    t = Table([[img]], colWidths=[CONTENT_W])
    t.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER")]))
    return t


def _centered_para(text: str, style) -> Table:
    p = Paragraph(text, style)
    t = Table([[p]], colWidths=[CONTENT_W])
    t.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER")]))
    return t


def _save_fig(fig, path: Path) -> None:
    fig.tight_layout()
    fig.savefig(path, dpi=140, bbox_inches="tight", facecolor="#FAFAFA")
    plt.close(fig)


def _chart_calibration(trades, path: Path) -> None:
    if trades.empty or "p_home" not in trades.columns:
        return
    y = (trades["y_true"] == 0).astype(int).values
    p = trades["p_home"].values
    bins = np.linspace(0, 1, 11)
    obs, pred = [], []
    for lo, hi in zip(bins[:-1], bins[1:]):
        m = (p >= lo) & (p < hi)
        if m.sum() < 5:
            continue
        obs.append(y[m].mean())
        pred.append(p[m].mean())
    fig, ax = plt.subplots(figsize=(6, 4.5), facecolor="#FAFAFA")
    ax.plot([0, 1], [0, 1], color="#78909C", linestyle="--", linewidth=1)
    ax.scatter(pred, obs, c="#1A237E", s=50, edgecolors="white", linewidths=0.8, zorder=3)
    ax.plot(pred, obs, c="#1A237E", alpha=0.5)
    ax.set_xlabel("Prob. predita (mandante)", fontsize=9)
    ax.set_ylabel("Freq. observada", fontsize=9)
    ax.set_title("Calibracao — mandante FT (holdout 30%)", fontname="Times New Roman", fontsize=12, fontweight="bold")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.grid(True, alpha=0.35)
    _save_fig(fig, path)


def _chart_errors(meta: dict, path: Path) -> None:
    mot = meta.get("metrics_outcome_test", {})
    mht = meta.get("metrics_ht_test", {})
    labels = ["Acc", "LogLoss×10", "ECE H", "MAE H", "AUC HT", "ECE HT", "MAE HT"]
    vals = [
        mot.get("accuracy", 0) * 100,
        mot.get("logloss", 0) * 10,
        mot.get("ece_home", 0) * 100,
        mot.get("mae_home", 0) * 100,
        mht.get("auc", 0) * 100,
        mht.get("ece", 0) * 100,
        mht.get("mae", 0) * 100,
    ]
    fig, ax = plt.subplots(figsize=(7.5, 4), facecolor="#FAFAFA")
    bars = ax.bar(labels, vals, color=["#1A237E"] * 4 + ["#2E7D32"] * 3, alpha=0.88, edgecolor="white")
    ax.set_title("Metricas no holdout (30%)", fontname="Times New Roman", fontsize=12, fontweight="bold")
    ax.set_ylabel("Valor", fontsize=9)
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=22, ha="right", fontsize=8)
    _save_fig(fig, path)


def _stake_label(key: str) -> str:
    if key == "model":
        return "Stake sugerida (¼ Kelly)"
    return f"Stake fixa {key.replace('fixed_', '')} da banca inicial"


def generate_model_eval_pdf(
    result: ModelEvaluationResult,
    out_path: Path,
    meta: dict | None = None,
) -> Path:
    meta_path = MODEL_DIR / "meta.json"
    meta = meta or (json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {})

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(out_path), pagesize=A4,
        rightMargin=1.5 * cm, leftMargin=1.5 * cm,
        topMargin=1.5 * cm, bottomMargin=1.5 * cm,
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "t", parent=styles["Heading1"], fontSize=18, textColor=colors.HexColor("#1A237E"),
        alignment=TA_CENTER, fontName="Times-Bold", spaceAfter=8,
    )
    h2 = ParagraphStyle(
        "h2", parent=styles["Heading2"], fontSize=12, spaceAfter=10,
        fontName="Times-Roman", textColor=colors.HexColor("#37474F"), alignment=TA_CENTER,
    )
    sub = ParagraphStyle("sub", parent=styles["Normal"], fontSize=9, alignment=TA_CENTER, textColor=colors.HexColor("#546E7A"))

    story = []
    story.append(Spacer(1, 0.5 * cm))
    story.append(_centered_para("FutPythonTrader", title))
    story.append(_centered_para("Relatorio de Avaliacao do Modelo", h2))
    story.append(_centered_para(
        f"{datetime.now().strftime('%d/%m/%Y %H:%M')} · Ensemble RF + HistGBM + GBM · Holdout 30%",
        sub,
    ))
    story.append(Spacer(1, 0.4 * cm))

    mot = meta.get("metrics_outcome_test", {})
    mht = meta.get("metrics_ht_test", {})
    mrows = [
        ["Metrica", "1X2 Outcome", "Lucro HT"],
        ["MAE", f"{mot.get('mae_home', 0):.4f}", f"{mht.get('mae', 0):.4f}"],
        ["ECE", f"{mot.get('ece_home', 0):.4f}", f"{mht.get('ece', 0):.4f}"],
        ["Brier", f"{mot.get('brier_home', 0):.4f}", f"{mht.get('brier', 0):.4f}"],
        ["Acc / AUC", f"{mot.get('accuracy', 0):.1%}", f"{mht.get('auc', 0):.3f}"],
    ]
    tm = Table(mrows, colWidths=[5 * cm, 5 * cm, 5 * cm], hAlign="CENTER")
    tm.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1A237E")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CFD8DC")),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F5F5")]),
    ]))
    story.append(tm)
    story.append(Spacer(1, 0.35 * cm))

    summ = result.summary
    brow = [["Cenario", "Retorno final", "Max DD", "Trades", "Falencias"]]
    for k in ["model"] + sorted([x for x in summ if x.startswith("fixed_")], key=lambda x: float(x.replace("fixed_", "").replace("%", ""))):
        if k not in summ or not isinstance(summ[k], dict):
            continue
        s = summ[k]
        brow.append([
            _stake_label(k),
            f"{s.get('final_pct', s.get('roi_pct', 0)):+.1f}%",
            f"{s.get('max_drawdown_pct', 0):.1f} p.p.",
            str(s.get("n_trades", "—")),
            str(s.get("bankruptcies", 0)),
        ])
    bt = Table(brow, colWidths=[5.5 * cm, 2.8 * cm, 2.5 * cm, 2 * cm, 2.2 * cm], hAlign="CENTER")
    bt.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2E7D32")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]))
    story.append(bt)

    chart_dir = out_path.parent / "_charts_model"
    chart_dir.mkdir(parents=True, exist_ok=True)
    p_err = chart_dir / "errors.png"
    _chart_errors(meta, p_err)
    if not result.trades.empty:
        _chart_calibration(result.trades, chart_dir / "calib.png")

    story.append(PageBreak())
    story.append(_centered_para("Diagnostico do Modelo", h2))
    story.append(Spacer(1, 0.2 * cm))
    story.append(_centered_image(p_err, 15 * cm, 6.5 * cm))
    if (chart_dir / "calib.png").exists():
        story.append(Spacer(1, 0.3 * cm))
        story.append(_centered_image(chart_dir / "calib.png", 12 * cm, 8 * cm))

    stake_keys = ["model"] + sorted(
        [k for k in result.equity_curves if k.startswith("fixed_")],
        key=lambda x: float(x.replace("fixed_", "").replace("%", "")),
    )
    for sk in stake_keys:
        ec = result.equity_curves.get(sk)
        if ec is None or len(ec.series) < 2:
            continue
        col, acc = STAKE_COLORS.get(sk, ("#1A237E", "#C62828"))
        chart_path = chart_dir / f"equity_{sk.replace('%', 'pct')}.png"
        chart_equity_triple(
            ec.series, _stake_label(sk), chart_path,
            color=col, accent=acc, bankruptcy_dates=ec.bankruptcies,
        )
        story.append(PageBreak())
        story.append(_centered_para(f"Evolucao da Banca — {_stake_label(sk)}", h2))
        note = ""
        if ec.bankruptcies:
            note = f"Falencia em: {', '.join(ec.bankruptcies)}"
        elif ec.final_pct <= -50:
            note = "Queda severa — risco elevado"
        if note:
            story.append(_centered_para(note, sub))
        story.append(Spacer(1, 0.15 * cm))
        story.append(_centered_image(chart_path, 16 * cm, 19 * cm))

    doc.build(story)
    print(f"PDF modelo: {out_path}")
    return out_path
