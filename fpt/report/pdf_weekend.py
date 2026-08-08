"""PDF semanal — 1 PDF por campeonato, 1 jogo por pagina."""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from ..leagues import league_file_slug, league_sort_key, league_theme

GROUP_ORDER = {"1x2_ft": 1, "1x2_ht": 2, "ou_ht": 3, "ou_ft": 4, "btts": 5, "dc": 6}

PAGE_W = A4[0]
CONTENT_W = PAGE_W - 3 * cm  # margens 1.5cm


def _fmt_pct(v) -> str:
    try:
        return f"{float(v):.1%}"
    except (TypeError, ValueError):
        return "—"


def _fmt_f(v, n=2) -> str:
    try:
        if v is None:
            return "—"
        return f"{float(v):.{n}f}"
    except (TypeError, ValueError):
        return "—"


def _fmt_date_br(d) -> str:
    if d is None or str(d).lower() in ("nan", "none", ""):
        return "—"
    s = str(d).strip()
    if "T" in s:
        s = s.split("T")[0]
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(3)}/{m.group(2)}/{m.group(1)}"
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})", s)
    if m:
        return s[:10]
    return s[:10]


def _fmt_period(meta: dict) -> str:
    a = _fmt_date_br(meta.get("start"))
    b = _fmt_date_br(meta.get("end"))
    if a == b or b == "—":
        return a
    return f"{a} — {b}"


def _p(text: str, style: ParagraphStyle) -> Paragraph:
    safe = (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    return Paragraph(safe, style)


def _hex(h: str) -> colors.Color:
    return colors.HexColor(h)


def _tint(hex_color: str, factor: float = 0.92) -> colors.Color:
    c = _hex(hex_color)
    r, g, b = c.red, c.green, c.blue
    return colors.Color(r + (1 - r) * factor, g + (1 - g) * factor, b + (1 - b) * factor)


def _sort_markets(evs: list[dict]) -> list[dict]:
    return sorted(
        evs,
        key=lambda e: (
            GROUP_ORDER.get(e.get("market_group", ""), 9),
            e.get("market_label", e.get("market", "")),
        ),
    )


def _cover_page(story, league: str, meta: dict, theme: dict, styles) -> None:
    primary = theme["primary"]
    accent = theme["accent"]
    title_style = ParagraphStyle(
        "cover_main", parent=styles["Title"], fontSize=32, leading=38,
        textColor=_hex(primary), alignment=TA_CENTER, spaceAfter=20,
        fontName="Helvetica-Bold",
    )
    league_style = ParagraphStyle(
        "cover_league", parent=styles["Normal"], fontSize=18, leading=24,
        textColor=_hex(accent), alignment=TA_CENTER, spaceAfter=12,
        fontName="Helvetica-Bold",
    )
    date_style = ParagraphStyle(
        "cover_date", parent=styles["Normal"], fontSize=13, leading=18,
        textColor=_hex(theme["dark"]), alignment=TA_CENTER,
    )
    band = Table([[""]], colWidths=[CONTENT_W], rowHeights=[0.45 * cm])
    band.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), _hex(primary))]))
    story.append(band)
    story.append(Spacer(1, 5 * cm))
    story.append(_p("FutPythonTrader", title_style))
    story.append(Spacer(1, 0.8 * cm))
    story.append(_p(_fmt_period(meta), date_style))
    story.append(Spacer(1, 1.2 * cm))
    story.append(_p(league, league_style))
    story.append(Spacer(1, 2 * cm))
    line = Table([[""]], colWidths=[6 * cm], rowHeights=[0.12 * cm])
    line.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), _hex(accent)), ("ALIGN", (0, 0), (-1, -1), "CENTER")]))
    t = Table([[line]], colWidths=[CONTENT_W])
    t.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER")]))
    story.append(t)
    story.append(PageBreak())


def _match_table(evs: list[dict], theme: dict, styles) -> Table:
    primary = theme["primary"]
    accent = theme["accent"]
    cell = ParagraphStyle("cell", parent=styles["Normal"], fontSize=6.5, leading=8, alignment=TA_LEFT)
    cell_c = ParagraphStyle("cell_c", parent=cell, alignment=TA_CENTER)
    hdr = ParagraphStyle("hdr", parent=cell, fontSize=6.5, textColor=colors.white, alignment=TA_CENTER, fontName="Helvetica-Bold")

    headers = [
        "Mercado", "Prob", "P(HT)", "Back J.", "Lay J.", "φ",
        "Bk min", "Ly max", "Odd", "Stake Back", "Stake Lay",
    ]
    rows = [[_p(h, hdr) for h in headers]]

    for e in evs:
        label = e.get("market_label", e.get("market", ""))
        stake_back = float(e.get("stake_back_pct") or e.get("pct_banca") or 0)
        stake_lay = float(e.get("stake_lay_pct") or 0)
        rows.append([
            _p(label, cell),
            _p(_fmt_pct(e.get("prob")), cell_c),
            _p(_fmt_pct(e.get("p_lucro_ht")), cell_c),
            _p(_fmt_f(e.get("back_justa")), cell_c),
            _p(_fmt_f(e.get("lay_justa")), cell_c),
            _p(_fmt_f(e.get("phi"), 3), cell_c),
            _p(_fmt_f(e.get("back_min") or e.get("odd_min")), cell_c),
            _p(_fmt_f(e.get("lay_max")), cell_c),
            _p(_fmt_f(e.get("odd_mercado")), cell_c),
            _p(_fmt_pct(stake_back), cell_c),
            _p(_fmt_pct(stake_lay), cell_c),
        ])

    # 18cm total
    widths = [2.55 * cm, 1.15 * cm, 1.15 * cm, 1.25 * cm, 1.25 * cm, 0.85 * cm,
              1.25 * cm, 1.25 * cm, 1.15 * cm, 1.15 * cm, 1.15 * cm]
    t = Table(rows, colWidths=widths, repeatRows=1)
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), _hex(primary)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.2, _hex(theme["secondary"])),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
    ]
    tint_a = _tint(primary, 0.96)
    tint_b = colors.white
    for ri in range(1, len(rows)):
        bg = tint_a if ri % 2 == 1 else tint_b
        style_cmds.append(("BACKGROUND", (0, ri), (-1, ri), bg))
        ev = evs[ri - 1]
        sb = float(ev.get("stake_back_pct") or ev.get("pct_banca") or 0)
        sl = float(ev.get("stake_lay_pct") or 0)
        if sb > 0 or sl > 0:
            style_cmds.append(("BACKGROUND", (9, ri), (10, ri), _tint(accent, 0.75)))
            style_cmds.append(("TEXTCOLOR", (9, ri), (10, ri), _hex(theme["dark"])))
    t.setStyle(TableStyle(style_cmds))
    return t


def _generate_league_pdf(
    entries: list[dict],
    meta: dict,
    league: str,
    out_path: Path,
) -> Path:
    theme = league_theme(league)
    primary = theme["primary"]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(out_path), pagesize=A4,
        rightMargin=1.5 * cm, leftMargin=1.5 * cm,
        topMargin=1.2 * cm, bottomMargin=1.2 * cm,
    )
    styles = getSampleStyleSheet()
    match_title = ParagraphStyle(
        "mt", fontSize=14, leading=17, textColor=colors.white,
        alignment=TA_CENTER, fontName="Helvetica-Bold",
    )
    match_sub = ParagraphStyle(
        "ms", fontSize=8, leading=11, textColor=colors.HexColor("#ECEFF1"), alignment=TA_CENTER,
    )

    story = []
    _cover_page(story, league, meta, theme, styles)

    by_match: dict[tuple, list] = defaultdict(list)
    for e in entries:
        key = (e.get("date"), e.get("home"), e.get("away"))
        by_match[key].append(e)

    match_keys = sorted(
        by_match.keys(),
        key=lambda k: (str(k[0]), str(by_match[k][0].get("time", ""))),
    )

    for idx, key in enumerate(match_keys):
        evs = _sort_markets(by_match[key])
        head = evs[0]
        date_br = _fmt_date_br(head.get("date"))
        time_s = str(head.get("time") or "").strip()[:5]

        hdr = Table(
            [[Paragraph(f"{head['home']}  ×  {head['away']}", match_title)]],
            colWidths=[CONTENT_W],
        )
        hdr.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), _hex(primary)),
            ("TOPPADDING", (0, 0), (-1, -1), 12),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ]))
        story.append(hdr)

        sub_txt = f"{date_br}" + (f"  ·  {time_s}" if time_s and time_s != "nan" else "") + f"  ·  {len(evs)} mercados"
        sub = Table([[Paragraph(sub_txt, match_sub)]], colWidths=[CONTENT_W])
        sub.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), _hex(theme["dark"])),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]))
        story.append(sub)
        story.append(Spacer(1, 0.35 * cm))
        story.append(_match_table(evs, theme, styles))

        if idx < len(match_keys) - 1:
            story.append(PageBreak())

    if not entries:
        story.append(Paragraph("Nenhum jogo neste campeonato no periodo.", styles["Normal"]))

    doc.build(story)
    print(f"PDF [{league}]: {out_path}")
    return out_path


def generate_weekend_pdfs_by_league(
    entries: list[dict],
    meta: dict,
    out_dir: Path,
) -> list[Path]:
    """Gera um PDF profissional por campeonato."""
    by_league: dict[str, list] = defaultdict(list)
    for e in entries:
        lg = e.get("league") or "Outros"
        by_league[lg].append(e)

    paths: list[Path] = []
    for league in sorted(by_league.keys(), key=lambda l: league_sort_key(l)):
        slug = league_file_slug(league)
        fname = f"FutPythonTrader_{slug}_{meta.get('start')}_{meta.get('end')}.pdf"
        paths.append(_generate_league_pdf(by_league[league], meta, league, out_dir / fname))
    return paths


def generate_weekend_pdf(entries: list[dict], meta: dict, out_path: Path) -> Path:
    """Compat — gera PDFs por liga na pasta do out_path."""
    pdfs = generate_weekend_pdfs_by_league(entries, meta, out_path.parent)
    return pdfs[0] if pdfs else out_path
