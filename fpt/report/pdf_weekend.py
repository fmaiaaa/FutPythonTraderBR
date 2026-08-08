"""PDF semanal — estimativas sabado e domingo."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def _fmt_pct(v) -> str:
    try:
        return f"{float(v):.1%}"
    except (TypeError, ValueError):
        return "-"


def _fmt_f(v, n=2) -> str:
    try:
        if v is None:
            return "-"
        return f"{float(v):.{n}f}"
    except (TypeError, ValueError):
        return "-"


def generate_weekend_pdf(entries: list[dict], meta: dict, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(out_path), pagesize=landscape(A4),
        rightMargin=1.2 * cm, leftMargin=1.2 * cm,
        topMargin=1.2 * cm, bottomMargin=1.2 * cm,
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle("title", parent=styles["Heading1"], fontSize=14, spaceAfter=10)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=10, spaceAfter=6)
    body = styles["Normal"]

    story = []
    story.append(Paragraph("FutPythonTrader — Referencia Semanal (Watchlist)", title))
    story.append(Paragraph(
        f"Periodo: <b>{meta.get('start')}</b> a <b>{meta.get('end')}</b> | "
        f"Gerado: {datetime.now().strftime('%d/%m/%Y %H:%M')}<br/>"
        f"Jogos: {meta.get('n_games_watchlist', meta.get('n_games', 0))} | "
        f"Linhas pre-jogo: {len(entries)} — odd justa, phi, minima e stake",
        body,
    ))
    story.append(Spacer(1, 0.3 * cm))

    by_match: dict[tuple, list] = defaultdict(list)
    for e in entries:
        key = (e.get("date"), e.get("home"), e.get("away"))
        by_match[key].append(e)

    for key in sorted(by_match.keys()):
        evs = by_match[key]
        head = evs[0]
        story.append(Paragraph(
            f"<b>{head['home']} x {head['away']}</b> — {head.get('league', '')} "
            f"({head.get('date')} {head.get('time', '')})",
            h2,
        ))

        rows = [["Mercado", "Prob", "Justa", "phi", "Min", "Odd ref", "Stake %", "R$"]]
        for e in sorted(evs, key=lambda x: x.get("market", "")):
            rows.append([
                e.get("market_label", e.get("market", ""))[:22],
                _fmt_pct(e.get("prob")),
                _fmt_f(e.get("odd_justa")),
                _fmt_f(e.get("phi"), 3),
                _fmt_f(e.get("odd_min")),
                _fmt_f(e.get("odd_mercado")),
                _fmt_pct(e.get("pct_banca")),
                _fmt_f(e.get("stake")),
            ])
        t = Table(rows, colWidths=[4 * cm, 1.4 * cm, 1.2 * cm, 1.1 * cm, 1.2 * cm, 1.2 * cm, 1.4 * cm, 1.4 * cm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a5276")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f6f7")]),
        ]))
        story.append(t)
        story.append(Spacer(1, 0.25 * cm))

    if not entries:
        story.append(Paragraph("Nenhum jogo na watchlist neste periodo.", body))

    story.append(Spacer(1, 0.4 * cm))
    story.append(Paragraph(
        "<i>Referencia pre-jogo. Compare odd minima com movimentacao do mercado. "
        "Nao constitui recomendacao financeira.</i>",
        body,
    ))
    doc.build(story)
    print(f"PDF: {out_path}")
    return out_path
