from __future__ import annotations

from dataclasses import dataclass

from .config import load_config


@dataclass
class StakeDecision:
    kelly_full: float
    kelly_quarter: float
    stake_pct: float
    stake_amount: float
    confidence: float
    capped_by: str | None

    def summary(self) -> str:
        cap = f" (teto: {self.capped_by})" if self.capped_by else ""
        return (
            f"Kelly cheio={self.kelly_full:.2%} | ¼Kelly={self.kelly_quarter:.2%} | "
            f"stake={self.stake_pct:.2%} = {self.stake_amount:.2f}{cap}"
        )


def kelly_fraction(p: float, b: float) -> float:
    """
    f* = (bp - q) / b
    p = prob vitória, q = 1-p, b = lucro líquido por unidade (odd - 1)
    """
    if b <= 0 or p <= 0 or p >= 1:
        return 0.0
    q = 1 - p
    f = (p * b - q) / b
    return max(0.0, f)


def kelly_ht_trade(
    p_ht: float,
    entry_odd: float,
    expected_exit_odd: float,
    bankroll: float,
    confidence: float = 70.0,
    edge_pp: float | None = None,
) -> StakeDecision:
    """
    Kelly sobre a operação de trading HT (não sobre vitória FT).
    b = odd_efetiva - 1, onde odd_efetiva = entry / exit
    """
    cfg = load_config()["trading"]
    k_frac = cfg["kelly_fraction"]
    max_risk = cfg["max_risk_per_trade"]

    eff_odd = entry_odd / max(expected_exit_odd, 1.01)
    b = eff_odd - 1
    k_full = kelly_fraction(p_ht, b)

    conf_adj = max(0.3, min(1.0, confidence / 100))
    if edge_pp is not None and edge_pp < 2:
        conf_adj *= 0.7

    k_quarter = k_full * k_frac * conf_adj
    capped_by = None
    if k_quarter > max_risk:
        k_quarter = max_risk
        capped_by = "max_risk_1pct"

    stake = round(bankroll * k_quarter, 2)
    return StakeDecision(
        kelly_full=round(k_full, 4),
        kelly_quarter=round(k_full * k_frac, 4),
        stake_pct=round(k_quarter, 4),
        stake_amount=stake,
        confidence=confidence,
        capped_by=capped_by,
    )


def kelly_simple(
    p: float,
    entry_odd: float,
    bankroll: float,
    confidence: float = 70.0,
) -> StakeDecision:
    """Kelly clássico sobre odd de referência (odd mínima aceitável)."""
    cfg = load_config()["trading"]
    k_frac = cfg["kelly_fraction"]
    max_risk = cfg["max_risk_per_trade"]

    k_full = kelly_fraction(p, max(entry_odd - 1, 0.01))
    conf_adj = max(0.3, min(1.0, confidence / 100))
    k_quarter = k_full * k_frac * conf_adj
    capped_by = None
    if k_quarter > max_risk:
        k_quarter = max_risk
        capped_by = "max_risk_1pct"
    stake = round(bankroll * k_quarter, 2)
    return StakeDecision(
        kelly_full=round(k_full, 4),
        kelly_quarter=round(k_full * k_frac, 4),
        stake_pct=round(k_quarter, 4),
        stake_amount=stake,
        confidence=confidence,
        capped_by=capped_by,
    )


def explain_zero_stake(
    stake: StakeDecision,
    p: float,
    p_ht: float,
    back_min: float,
    uses_ht_kelly: bool,
) -> str:
    """Explica por que stake % = 0 no relatorio."""
    if stake.stake_pct > 0:
        return ""
    b = max(back_min - 1, 0.01)
    if uses_ht_kelly:
        eff_b = b * 0.6
        if p_ht < 0.35:
            return f"P(lucro HT)={p_ht:.1%} baixa — trade HT sem expectativa positiva"
        if kelly_fraction(p_ht, eff_b) <= 0:
            return (
                f"Kelly HT<=0: P(lucro HT)={p_ht:.1%} vs back min {back_min:.2f} "
                f"(sem edge na saida no intervalo)"
            )
    if kelly_fraction(p, b) <= 0:
        return f"Kelly<=0: prob={p:.1%} sem edge na back min {back_min:.2f}"
    if stake.capped_by:
        return ""
    return "Confianca baixa reduziu 1/4 Kelly a zero"
