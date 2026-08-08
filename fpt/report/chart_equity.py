"""Gráficos de evolução da banca — geral, tendência e ciclo (tempo × % banca)."""
from __future__ import annotations

from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# Estilo profissional
plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Segoe UI", "Arial", "DejaVu Sans"],
    "axes.titlesize": 11,
    "axes.labelsize": 9,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "legend.fontsize": 8,
    "figure.facecolor": "#FAFAFA",
    "axes.facecolor": "#FFFFFF",
    "axes.edgecolor": "#B0BEC5",
    "grid.color": "#ECEFF1",
})

TITLE_FONT = {"fontname": "Times New Roman", "fontsize": 12, "fontweight": "bold", "color": "#1A237E"}


def decompose_equity_time(dates: np.ndarray, y: np.ndarray) -> dict:
    """Tendência OLS e ciclo (resíduo) sobre eixo temporal."""
    y = np.asarray(y, dtype=float)
    if len(y) < 3:
        return {"dates": dates, "raw": y, "trend": y.copy(), "cycle": np.zeros_like(y)}
    x_num = mdates.date2num(pd.to_datetime(dates))
    coef = np.polyfit(x_num, y, 1)
    trend = np.polyval(coef, x_num)
    cycle = y - trend
    return {"dates": dates, "raw": y, "trend": trend, "cycle": cycle, "coef": coef}


def _style_axes(ax, title: str, ylabel: str, xlabel: str | None = None) -> None:
    ax.set_title(title, **TITLE_FONT, pad=8)
    ax.set_ylabel(ylabel, fontsize=9, color="#37474F")
    if xlabel:
        ax.set_xlabel(xlabel, fontsize=9, color="#37474F")
    ax.axhline(0, color="#78909C", linewidth=0.7, linestyle="-", alpha=0.6)
    ax.axhline(-100, color="#B71C1C", linewidth=1.0, linestyle="--", alpha=0.7, label="Falência (-100%)")
    ax.grid(True, alpha=0.4, linestyle="-", linewidth=0.5)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


def _mark_bankruptcies(ax, dates, y, bankruptcy_dates: list) -> None:
    if not bankruptcy_dates:
        return
    bdates = pd.to_datetime(bankruptcy_dates)
    for bd in bdates:
        ax.axvline(bd, color="#D32F2F", linewidth=1.2, linestyle=":", alpha=0.85)
        ax.scatter([bd], [-100], marker="X", s=120, color="#D32F2F", zorder=10, edgecolors="white", linewidths=0.8)


def _format_date_axis(ax) -> None:
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m/%y"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=4, maxticks=10))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=30, ha="right")


def chart_equity_triple(
    curve: pd.Series,
    title: str,
    path: Path,
    color: str = "#1565C0",
    accent: str = "#C62828",
    bankruptcy_dates: list | None = None,
) -> Path:
    """
    curve: DatetimeIndex → % retorno sobre banca inicial (0 = início, -100 = falência).
    3 painéis: evolução | tendência | ciclo.
    """
    bankruptcy_dates = bankruptcy_dates or []
    dates = curve.index.to_pydatetime()
    y = curve.values.astype(float)
    d = decompose_equity_time(dates, y)

    fig, axes = plt.subplots(3, 1, figsize=(9, 10), facecolor="#FAFAFA")
    fig.subplots_adjust(hspace=0.38, top=0.96, bottom=0.08, left=0.10, right=0.96)

    # —— Geral ——
    ax = axes[0]
    ax.plot(dates, d["raw"], color=color, linewidth=1.6, label="Retorno acumulado", zorder=3)
    ax.fill_between(dates, d["raw"], 0, where=np.array(d["raw"]) >= 0, alpha=0.12, color="#2E7D32")
    ax.fill_between(dates, d["raw"], 0, where=np.array(d["raw"]) < 0, alpha=0.12, color="#C62828")
    _mark_bankruptcies(ax, dates, y, bankruptcy_dates)
    _style_axes(ax, f"{title} — Evolução geral", "Retorno (% sobre banca)")
    _format_date_axis(ax)
    if len(y) > 1:
        ax.text(
            0.02, 0.97, f"Final: {y[-1]:+.1f}%  |  Min: {y.min():+.1f}%  |  Max: {y.max():+.1f}%",
            transform=ax.transAxes, fontsize=8, va="top",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor="#CFD8DC", alpha=0.9),
        )
    if bankruptcy_dates:
        ax.text(0.98, 0.03, f"Falência: {len(bankruptcy_dates)}", transform=ax.transAxes,
                fontsize=8, ha="right", color="#B71C1C", fontweight="bold")

    # —— Tendência ——
    ax = axes[1]
    ax.plot(dates, d["raw"], color=color, alpha=0.22, linewidth=1)
    ax.plot(dates, d["trend"], color=accent, linewidth=2.2, label="Tendência (OLS)", zorder=4)
    _mark_bankruptcies(ax, dates, y, bankruptcy_dates)
    _style_axes(ax, "Tendência", "Retorno (%)")
    _format_date_axis(ax)
    ax.legend(loc="upper left", framealpha=0.95)
    if "coef" in d:
        slope = d["coef"][0]  # % por dia (escala date num)
        ax.text(0.02, 0.97, f"Inclinação: {slope:.4f} %/dia", transform=ax.transAxes, fontsize=8, va="top")

    # —— Ciclo ——
    ax = axes[2]
    ax.fill_between(dates, 0, d["cycle"], where=np.array(d["cycle"]) >= 0, color="#43A047", alpha=0.35, label="Acima tend.")
    ax.fill_between(dates, 0, d["cycle"], where=np.array(d["cycle"]) < 0, color="#E53935", alpha=0.35, label="Abaixo tend.")
    ax.plot(dates, d["cycle"], color="#546E7A", linewidth=0.9, alpha=0.8)
    _mark_bankruptcies(ax, dates, y, bankruptcy_dates)
    _style_axes(ax, "Ciclo (desvio vs tendência)", "Desvio (p.p.)", "Data")
    _format_date_axis(ax)
    ax.legend(loc="upper left", framealpha=0.95)
    std_c = float(np.std(d["cycle"])) if len(d["cycle"]) > 1 else 0
    ax.text(0.02, 0.97, f"Volatilidade ciclo σ: {std_c:.2f} p.p.", transform=ax.transAxes, fontsize=8, va="top")

    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=140, bbox_inches="tight", facecolor="#FAFAFA")
    plt.close(fig)
    return path
