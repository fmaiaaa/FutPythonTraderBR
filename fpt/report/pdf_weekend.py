"""PDF semanal — estimativas sabado e domingo."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
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
        str(out_path), pagesize=A4,
        rightMargin=1.5 * cm, leftMargin=1.5 * cm,
        topMargin=1.5 * cm, bottomMargin=1.5 * cm,
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle("title", parent=styles["Heading1"], fontSize=16, spaceAfter=12)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=12, spaceAfter=8)
    body = styles["Normal"]

    story = []
    story.append(Paragraph("FutPythonTrader — Relatorio Semanal", title))
    story.append(Paragraph(
        f"Periodo: <b>{meta.get('start')}</b> (Sab) a <b>{meta.get('end')}</b> (Dom)<br/>"
        f"Gerado: {datetime.now().strftime('%d/%m/%Y %H:%M')}<br/>"
        f"Jogos BR analisados: {meta.get('n_games_br', meta.get('n_games', 0))} | "
        f"Entradas ENTER: {sum(1 for e in entries if e.get('action') == 'ENTER')}",
        body,
    ))
    story.append(Spacer(1, 0.4 * cm))

    # Agrupa por jogo (melhor mercado = home_win_ft ou ENTER)
    by_match: dict[tuple, list] = defaultdict(list)
    for e in entries:
        key = (e.get("date"), e.get("home"), e.get("away"))
        by_match[key].append(e)

    for day in sorted({e.get("date") for e in entries}):
        day_label = "Sabado" if str(day).endswith(meta.get("start", "")[-2:]) else "Domingo"
        story.append(Paragraph(f"{day_label} — {day}", h2))

        day_matches = [k for k in by_match if k[0] == day]
        for key in sorted(day_matches, key=lambda k: k[2]):
            evs = by_match[key]
            best = next((x for x in evs if x.get("action") == "ENTER"), evs[0])
            enter_tag = " [ENTER]" if best.get("action") == "ENTER" else ""
            story.append(Paragraph(
                f"<b>{best['home']} x {best['away']}</b>{enter_tag} — {best.get('league', '')} "
                f"({best.get('time', '')})",
                body,
            ))

            rows = [["Mercado", "Prob", "Justa", "phi", "Min", "Mercado", "Edge", "Stake R$", "Acao"]]
            for e in evs:
                mkt = e.get("market", "").replace("_ft", "").replace("_", " ")
                rows.append([
                    mkt,
                    _fmt_pct(e.get("prob")),
                    _fmt_f(e.get("odd_justa")),
                    _fmt_f(e.get("phi"), 3),
                    _fmt_f(e.get("odd_min")),
                    _fmt_f(e.get("odd_mercado")),
                    _fmt_f(e.get("edge_pp"), 1) + " pp" if e.get("edge_pp") is not None else "-",
                    _fmt_f(e.get("stake")),
                    e.get("action", ""),
                ])
            t = Table(rows, colWidths=[2.2 * cm, 1.3 * cm, 1.2 * cm, 1 * cm, 1.2 * cm, 1.3 * cm, 1.5 * cm, 1.5 * cm, 1.3 * cm])
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a5276")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f6f7")]),
            ]))
            story.append(t)

            if best.get("schedule_notes"):
                story.append(Paragraph(f"<i>Agenda: {best['schedule_notes']}</i>", body))
            story.append(Spacer(1, 0.3 * cm))

    if not entries:
        story.append(Paragraph("Nenhum jogo analisado neste periodo.", body))

    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph(
        "<i>Estrategia: pre-jogo, saida HT, 1/4 Kelly, phi dinamico. "
        "Nao constitui recomendacao financeira.</i>",
        body,
    ))
    doc.build(story)
    print(f"PDF: {out_path}")
    return out_path
