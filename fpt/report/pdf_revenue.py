from __future__ import annotations

"""PDFs de evolução da receita — pré-live, scalping e combinado."""

from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .chart_equity import chart_equity_triple, decompose_equity_time
from .revenue_evolution import RevenueReport, build_all_revenue_reports

CONTENT_W = A4[0] - 3 * cm

METHOD_COLORS = {
    "pre_live": ("#1A237E", "#3949AB"),
    "scalping": ("#E65100", "#FF6D00"),
    "combined": ("#2E7D32", "#43A047"),
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


def generate_revenue_pdf(report: RevenueReport, out_path: Path, saturday: str | None = None) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(out_path), pagesize=A4,
        rightMargin=1.5 * cm, leftMargin=1.5 * cm,
        topMargin=1.5 * cm, bottomMargin=1.5 * cm,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "t", parent=styles["Heading1"], fontSize=17, textColor=colors.HexColor("#1A237E"),
        alignment=TA_CENTER, fontName="Times-Bold", spaceAfter=6,
    )
    h2 = ParagraphStyle(
        "h2", parent=styles["Heading2"], fontSize=12, spaceAfter=8,
        fontName="Times-Roman", textColor=colors.HexColor("#37474F"), alignment=TA_CENTER,
    )
    sub = ParagraphStyle("sub", parent=styles["Normal"], fontSize=9, alignment=TA_CENTER, textColor=colors.HexColor("#546E7A"))
    body = ParagraphStyle("body", parent=styles["Normal"], fontSize=9, alignment=TA_LEFT, textColor=colors.HexColor("#37474F"))

    color, accent = METHOD_COLORS.get(report.method, ("#1A237E", "#C62828"))
    story = []
    story.append(Spacer(1, 0.4 * cm))
    story.append(_centered_para("FutPythonTrader", title_style))
    story.append(_centered_para(report.title, h2))
    story.append(_centered_para(
        f"{datetime.now().strftime('%d/%m/%Y %H:%M')} · Fim de semana {saturday or '—'} · {report.stats.get('label', '')}",
        sub,
    ))
    if report.note:
        story.append(_centered_para(report.note, sub))
    story.append(Spacer(1, 0.3 * cm))

    s = report.stats
    rows = [
        ["Métrica", "Valor"],
        ["ROI (retorno final)", f"{s.get('roi_pct', s.get('final_pct', 0)):+.2f}%"],
        ["Max drawdown", f"{s.get('max_drawdown_pct', 0):.2f} p.p."],
        ["Trades", str(s.get("n_trades", 0))],
        ["Win rate", f"{s.get('win_rate_pct', 0):.1f}%"],
        ["Maior sequência de perdas", str(s.get("max_losing_streak", 0))],
        ["Maior sequência de ganhos", str(s.get("max_winning_streak", 0))],
        ["Volatilidade do ciclo (σ)", f"{s.get('cycle_volatility_pp', 0):.2f} p.p."],
        ["Falências de banca", str(s.get("bankruptcies", 0))],
    ]
    if report.method == "combined":
        rows.append(["Trades pré-live", str(s.get("n_pre_live", 0))])
        rows.append(["Trades scalping", str(s.get("n_scalping", 0))])
    if report.method == "scalping" and "timeouts" in s:
        rows.append(["Saídas por timeout", str(s.get("timeouts", 0))])

    tm = Table(rows, colWidths=[7 * cm, 7 * cm], hAlign="CENTER")
    tm.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(color)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CFD8DC")),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F5F5")]),
    ]))
    story.append(tm)
    story.append(Spacer(1, 0.25 * cm))

    if len(report.equity.series) >= 2:
        coef = decompose_equity_time(
            report.equity.series.index.to_pydatetime(),
            report.equity.series.values,
        ).get("coef")
        if coef is not None:
            slope = coef[0]
            story.append(Paragraph(
                f"<b>Decomposição:</b> tendência OLS = {slope:+.3f} p.p./operação · "
                f"ciclo = retorno − tendência (ver gráficos abaixo).",
                body,
            ))
            story.append(Spacer(1, 0.2 * cm))

        chart_dir = out_path.parent / "_charts_revenue"
        chart_dir.mkdir(parents=True, exist_ok=True)
        chart_path = chart_dir / f"revenue_{report.method}.png"
        chart_equity_triple(
            report.equity.series,
            report.stats.get("label", report.title),
            chart_path,
            color=color,
            accent=accent,
            bankruptcy_dates=report.equity.bankruptcies,
        )
        story.append(PageBreak())
        story.append(_centered_para("Evolução · Tendência · Ciclo", h2))
        if report.equity.bankruptcies:
            story.append(_centered_para(
                f"⚠ Quebra de banca: {', '.join(report.equity.bankruptcies)}", sub,
            ))
        story.append(Spacer(1, 0.15 * cm))
        story.append(_centered_image(chart_path, 16 * cm, 19 * cm))

        if not report.trades.empty and len(report.trades) <= 40:
            story.append(PageBreak())
            story.append(_centered_para("Últimas operações", h2))
            cols = [c for c in ["timestamp", "home", "away", "method", "side", "pnl_pct", "win"] if c in report.trades.columns]
            if not cols:
                cols = list(report.trades.columns[:6])
            trows = [cols]
            for _, r in report.trades.tail(25).iterrows():
                trows.append([
                    str(r.get(c, ""))[:20] if c != "win" else ("✓" if r.get(c) else "✗")
                    for c in cols
                ])
            tt = Table(trows, hAlign="CENTER")
            tt.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#546E7A")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("GRID", (0, 0), (-1, -1), 0.2, colors.grey),
            ]))
            story.append(tt)
    else:
        story.append(Spacer(1, 0.5 * cm))
        story.append(_centered_para(
            "Dados insuficientes para curva de equity. Acumule ticks live (scalping) ou rode o treino (pré-live).",
            sub,
        ))

    doc.build(story)
    print(f"PDF receita ({report.method}): {out_path}")
    return out_path


def generate_revenue_evolution_pdfs(
    hist,
    out_dir: Path,
    saturday: str,
    bankroll: float | None = None,
) -> list[Path]:
    """Gera 3 PDFs: pré-live, scalping e combinado."""
    reports = build_all_revenue_reports(hist, bankroll)
    paths = []
    names = {
        "pre_live": f"Receita_PreLive_{saturday}.pdf",
        "scalping": f"Receita_Scalping_{saturday}.pdf",
        "combined": f"Receita_Combinado_{saturday}.pdf",
    }
    for key, fname in names.items():
        p = out_dir / fname
        generate_revenue_pdf(reports[key], p, saturday=saturday)
        paths.append(p)
    return paths
