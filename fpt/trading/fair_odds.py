from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ExchangeFairOdds:
    """Odds justas back/lay para mercado binário (prob = P(evento))."""
    probability: float
    back_fair: float
    lay_fair: float
    phi: float
    back_min: float   # back minimo aceitavel = back_fair × φ
    lay_max: float    # lay maximo aceitavel = lay_fair / φ (sair no HT)

    def as_dict(self) -> dict:
        return {
            "prob": self.probability,
            "back_fair": self.back_fair,
            "lay_fair": self.lay_fair,
            "phi": self.phi,
            "back_min": self.back_min,
            "lay_max": self.lay_max,
        }


def fair_odd(probability: float) -> float:
    """Alias back justa."""
    return back_fair(probability)


def back_fair(probability: float) -> float:
    if probability <= 0:
        return float("inf")
    return 1.0 / probability


def lay_fair(probability: float) -> float:
    if probability >= 1:
        return float("inf")
    q = 1.0 - probability
    if q <= 0:
        return float("inf")
    return 1.0 / q


def min_back_odd(probability: float, phi: float) -> float:
    return back_fair(probability) * phi


def max_lay_odd(probability: float, phi: float) -> float:
    """Lay maximo aceitavel ao fechar (margem φ)."""
    lf = lay_fair(probability)
    if lf == float("inf"):
        return float("inf")
    return lf / phi


def min_entry_odd(probability: float, phi: float) -> float:
    return min_back_odd(probability, phi)


def exchange_fair_odds(probability: float, phi: float) -> ExchangeFairOdds:
    p = max(0.001, min(0.999, probability))
    bf, lf = back_fair(p), lay_fair(p)
    return ExchangeFairOdds(
        probability=p,
        back_fair=round(bf, 3),
        lay_fair=round(lf, 3),
        phi=phi,
        back_min=round(min_back_odd(p, phi), 3),
        lay_max=round(max_lay_odd(p, phi), 3),
    )


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
                f"P={self.probability:.1%} | back={self.fair_odd:.2f} | "
                f"back min (φ={self.phi})={self.min_odd:.2f}"
            )
        status = "VALOR" if self.has_value else "sem valor"
        edge = f"{self.edge_pct:.1f}%" if self.edge_pct is not None else "—"
        return (
            f"P={self.probability:.1%} | back={self.fair_odd:.2f} | "
            f"min={self.min_odd:.2f} | mercado={self.market_odd:.2f} | edge={edge} → {status}"
        )


def check_value(
    probability: float,
    market_odd: float | None,
    phi: float,
) -> ValueCheck:
    fo = back_fair(probability)
    mo = min_back_odd(probability, phi)
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
