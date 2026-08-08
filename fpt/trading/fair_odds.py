from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ValueCheck:
    probability: float
    fair_odd: float
    min_odd: float
    market_odd: float | None
    edge_pct: float | None
    has_value: bool
    phi: float

    def summary(self) -> str:
        if self.market_odd is None:
            return (
                f"P={self.probability:.1%} | justa={self.fair_odd:.2f} | "
                f"mínima (φ={self.phi})={self.min_odd:.2f}"
            )
        status = "VALOR" if self.has_value else "sem valor"
        edge = f"{self.edge_pct:.1f}%" if self.edge_pct is not None else "—"
        return (
            f"P={self.probability:.1%} | justa={self.fair_odd:.2f} | "
            f"mín={self.min_odd:.2f} | mercado={self.market_odd:.2f} | edge={edge} → {status}"
        )


def fair_odd(probability: float) -> float:
    if probability <= 0:
        return float("inf")
    return 1.0 / probability


def min_entry_odd(probability: float, phi: float) -> float:
    return fair_odd(probability) * phi


def check_value(
    probability: float,
    market_odd: float | None,
    phi: float,
) -> ValueCheck:
    fo = fair_odd(probability)
    mo = min_entry_odd(probability, phi)
    edge = None
    has = False
    if market_odd and market_odd > 0:
        implied = 1.0 / market_odd
        edge = round((probability - implied) * 100, 2)
        has = market_odd >= mo
    return ValueCheck(
        probability=probability,
        fair_odd=round(fo, 3),
        min_odd=round(mo, 3),
        market_odd=market_odd,
        edge_pct=edge,
        has_value=has,
        phi=phi,
    )
