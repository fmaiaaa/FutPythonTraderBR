"""Odds exchange Betfair — mid, spread, preços de entrada/saída e valor."""
from __future__ import annotations

from dataclasses import dataclass

from .fair_odds import exchange_fair_odds, max_lay_odd, min_back_odd


@dataclass(frozen=True)
class ExchangeQuote:
    """Back/lay do melhor nível na exchange."""

    back: float | None = None
    lay: float | None = None

    @classmethod
    def from_prices(cls, back: float | None, lay: float | None) -> ExchangeQuote:
        return cls(
            back=float(back) if back and back > 1.01 else None,
            lay=float(lay) if lay and lay > 1.01 else None,
        )

    @property
    def mid(self) -> float | None:
        if self.back and self.lay:
            return round((self.back + self.lay) / 2.0, 3)
        return self.back or self.lay

    @property
    def spread_abs(self) -> float | None:
        if self.back and self.lay:
            return round(self.lay - self.back, 3)
        return None

    @property
    def spread_pct(self) -> float | None:
        if self.back and self.lay and self.back > 1.01:
            return round((self.lay - self.back) / self.back * 100.0, 3)
        return None

    @property
    def implied_back(self) -> float | None:
        if not self.back:
            return None
        return 1.0 / self.back

    @property
    def implied_lay(self) -> float | None:
        """P(seleção ganha) implícita no lay (aprox. 1/lay)."""
        if not self.lay:
            return None
        return 1.0 / self.lay

    @property
    def implied_mid(self) -> float | None:
        ib, il = self.implied_back, self.implied_lay
        if ib is not None and il is not None:
            return (ib + il) / 2.0
        return ib or il

    def entry_price(self, side: str) -> float | None:
        """Preço executável na entrada: BACK→back, LAY→lay."""
        side = side.upper()
        return self.back if side == "BACK" else self.lay

    def exit_price(self, entry_side: str) -> float | None:
        """Preço executável na saída (lado oposto)."""
        entry_side = entry_side.upper()
        return self.lay if entry_side == "BACK" else self.back

    def round_trip_spread_pct(self, entry_side: str = "BACK") -> float | None:
        """Custo aproximado ida+volta (spread relativo ao preço de entrada)."""
        entry = self.entry_price(entry_side)
        exit_p = self.exit_price(entry_side)
        if not entry or not exit_p or entry <= 1.01:
            return None
        return round((exit_p - entry) / entry * 100.0, 3)


@dataclass
class ExchangeValueCheck:
    probability: float
    phi: float
    side: str
    quote: ExchangeQuote
    fair: float
    threshold: float
    market_price: float | None
    edge_pp: float | None
    has_value: bool
    spread_pct: float | None

    def summary(self) -> str:
        edge = f"{self.edge_pp:+.1f}pp" if self.edge_pp is not None else "—"
        sp = f" spread {self.spread_pct:.2f}%" if self.spread_pct is not None else ""
        return (
            f"{self.side} P={self.probability:.1%} | lim {self.threshold:.2f} "
            f"merc {self.market_price or 0:.2f} | edge {edge}{sp}"
        )


def check_exchange_value(
    probability: float,
    phi: float,
    quote: ExchangeQuote,
    side: str,
    *,
    min_edge_pp: float = 0.0,
    use_mid_for_edge: bool = True,
) -> ExchangeValueCheck:
    """
    Valor na exchange — conservador na execução, mid na estimativa de edge.

    BACK: entra no back se back >= back_min(φ); edge vs implied mid/back.
    LAY:  entra no lay se lay <= lay_max(φ); edge vs implied lay.
    """
    side = side.upper()
    ex = exchange_fair_odds(probability, phi)
    spread = quote.spread_pct

    if side == "BACK":
        market = quote.back
        threshold = ex.back_min
        fair = ex.back_fair
        has = bool(market and market >= threshold)
        ref_impl = quote.implied_mid if use_mid_for_edge else quote.implied_back
        edge = round((probability - ref_impl) * 100, 2) if ref_impl else None
        if has and edge is not None and edge < min_edge_pp:
            has = False
    else:
        market = quote.lay
        threshold = ex.lay_max
        fair = ex.lay_fair
        has = bool(market and market <= threshold)
        ref_impl = quote.implied_lay or quote.implied_mid
        edge = round((ref_impl - probability) * 100, 2) if ref_impl else None
        if has and edge is not None and edge < min_edge_pp:
            has = False

    return ExchangeValueCheck(
        probability=probability,
        phi=phi,
        side=side,
        quote=quote,
        fair=fair,
        threshold=threshold,
        market_price=market,
        edge_pp=edge,
        has_value=has,
        spread_pct=spread,
    )


def scalp_covers_costs(
    quote: ExchangeQuote,
    entry_side: str,
    *,
    take_profit_pct: float,
    commission: float = 0.05,
    min_margin_pp: float = 0.3,
) -> bool:
    """Scalp só vale se TP supera spread round-trip + comissão + margem."""
    rt = quote.round_trip_spread_pct(entry_side)
    if rt is None:
        return True
    min_tp = rt / 100.0 + commission * 0.5 + min_margin_pp / 100.0
    return take_profit_pct >= min_tp


def build_scalp_exit_targets(
    quote: ExchangeQuote,
    entry_side: str,
    *,
    take_profit_pct: float,
    stop_loss_pct: float,
) -> tuple[float | None, float | None, float]:
    """
    Define alvos no preço de SAÍDA (lado oposto à entrada).

    Retorna (target_exit_odd, stop_exit_odd, entry_executable_odd).
    """
    entry_side = entry_side.upper()
    entry = quote.entry_price(entry_side)
    exit_p = quote.exit_price(entry_side)
    if not entry or not exit_p:
        return None, None, entry or 0.0

    if entry_side == "BACK":
        # Fecha com LAY: lay menor = lucro
        target = round(max(1.01, exit_p * (1.0 - take_profit_pct)), 2)
        stop = round(exit_p * (1.0 + stop_loss_pct), 2)
    else:
        # Fecha com BACK: back maior = lucro
        target = round(exit_p * (1.0 + take_profit_pct), 2)
        stop = round(max(1.01, exit_p * (1.0 - stop_loss_pct)), 2)
    return target, stop, entry
