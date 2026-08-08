"""Todos os mercados disponíveis no endpoint jogos-do-dia FPT."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MarketDef:
    id: str
    label: str
    odd_col: str
    group: str
    selection: str  # home|draw|away|over|under|yes|no


# Mapeamento colunas jogos-do-dia -> mercados internos
JOGOS_DIA_MARKETS: list[MarketDef] = [
    # 1X2 HT
    MarketDef("home_win_ht", "Mandante HT", "Odd_H_HT", "1x2_ht", "home"),
    MarketDef("draw_ht", "Empate HT", "Odd_D_HT", "1x2_ht", "draw"),
    MarketDef("away_win_ht", "Visitante HT", "Odd_A_HT", "1x2_ht", "away"),
    # 1X2 FT
    MarketDef("home_win_ft", "Mandante FT", "Odd_H_FT", "1x2_ft", "home"),
    MarketDef("draw_ft", "Empate FT", "Odd_D_FT", "1x2_ft", "draw"),
    MarketDef("away_win_ft", "Visitante FT", "Odd_A_FT", "1x2_ft", "away"),
    # O/U HT
    MarketDef("over05_ht", "Over 0.5 HT", "Odd_Over05_HT", "ou_ht", "over"),
    MarketDef("under05_ht", "Under 0.5 HT", "Odd_Under05_HT", "ou_ht", "under"),
    MarketDef("over15_ht", "Over 1.5 HT", "Odd_Over15_HT", "ou_ht", "over"),
    MarketDef("under15_ht", "Under 1.5 HT", "Odd_Under15_HT", "ou_ht", "under"),
    MarketDef("over25_ht", "Over 2.5 HT", "Odd_Over25_HT", "ou_ht", "over"),
    MarketDef("under25_ht", "Under 2.5 HT", "Odd_Under25_HT", "ou_ht", "under"),
    # O/U FT
    MarketDef("over05_ft", "Over 0.5 FT", "Odd_Over05_FT", "ou_ft", "over"),
    MarketDef("under05_ft", "Under 0.5 FT", "Odd_Under05_FT", "ou_ft", "under"),
    MarketDef("over15_ft", "Over 1.5 FT", "Odd_Over15_FT", "ou_ft", "over"),
    MarketDef("under15_ft", "Under 1.5 FT", "Odd_Under15_FT", "ou_ft", "under"),
    MarketDef("over25_ft", "Over 2.5 FT", "Odd_Over25_FT", "ou_ft", "over"),
    MarketDef("under25_ft", "Under 2.5 FT", "Odd_Under25_FT", "ou_ft", "under"),
    MarketDef("over35_ft", "Over 3.5 FT", "Odd_Over35_FT", "ou_ft", "over"),
    MarketDef("under35_ft", "Under 3.5 FT", "Odd_Under35_FT", "ou_ft", "under"),
    MarketDef("over45_ft", "Over 4.5 FT", "Odd_Over45_FT", "ou_ft", "over"),
    MarketDef("under45_ft", "Under 4.5 FT", "Odd_Under45_FT", "ou_ft", "under"),
    # BTTS + DC
    MarketDef("btts_yes", "BTTS Sim", "Odd_BTTS_Yes", "btts", "yes"),
    MarketDef("btts_no", "BTTS Não", "Odd_BTTS_No", "btts", "no"),
    MarketDef("dc_1x", "Dupla 1X", "Odd_1X_FT", "dc", "home"),
    MarketDef("dc_12", "Dupla 12", "Odd_12_FT", "dc", "home"),
    MarketDef("dc_x2", "Dupla X2", "Odd_X2_FT", "dc", "away"),
]

# Mercados com modelo ML completo (v1 trading HT)
TRADING_MARKETS = ["home_win_ft", "draw_ft", "away_win_ft"]

# Estrategia: entrada pre-jogo, saida no intervalo (HT)
PREMATCH_HT_EXIT_MARKETS = TRADING_MARKETS  # home_win_ft, draw_ft, away_win_ft


def available_markets_for_row(row) -> list[MarketDef]:
    """Todos os mercados FPT com odd disponivel neste jogo."""
    out: list[MarketDef] = []
    for m in JOGOS_DIA_MARKETS:
        try:
            v = row.get(m.odd_col) if hasattr(row, "get") else None
            if v is not None and float(v) > 1.01:
                out.append(m)
        except (TypeError, ValueError):
            pass
    return out


def prematch_ht_markets_for_row(row) -> list[MarketDef]:
    return available_markets_for_row(row)


def market_by_id(mid: str) -> MarketDef | None:
    return next((m for m in JOGOS_DIA_MARKETS if m.id == mid), None)


def odd_column_map() -> dict[str, str]:
    return {m.id: m.odd_col for m in JOGOS_DIA_MARKETS}
