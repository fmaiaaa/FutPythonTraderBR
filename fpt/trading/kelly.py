from __future__ import annotations

from dataclasses import dataclass

from .config import load_config


@dataclass
class StakeDecision:
    kelly_full: float
    kelly_quarter: float
    stake_pct: float       # % da banca em risco (back = apostado; lay = exposição)
    stake_amount: float    # back: valor apostado; lay: valor matched (API)
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
        capped_by = "max_risk_3pct"

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
        capped_by = "max_risk_3pct"
    stake = round(bankroll * k_quarter, 2)
    return StakeDecision(
        kelly_full=round(k_full, 4),
        kelly_quarter=round(k_full * k_frac, 4),
        stake_pct=round(k_quarter, 4),
        stake_amount=stake,
        confidence=confidence,
        capped_by=capped_by,
    )


def kelly_lay(
    p_selection_wins: float,
    lay_odd: float,
    bankroll: float,
    confidence: float = 70.0,
) -> StakeDecision:
    """
    Kelly para lay: ganha se a seleção NÃO vence (q = 1 - p).
    stake_pct = % da banca em risco (exposição / liability), teto max_risk.
    stake_amount = valor matched na Betfair (= exposição / (lay_odd - 1)).
    """
    cfg = load_config()["trading"]
    k_frac = cfg["kelly_fraction"]
    max_risk = cfg["max_risk_per_trade"]

    L = max(float(lay_odd or 0), 1.02)
    q = max(0.001, min(0.999, 1.0 - p_selection_wins))
    b = 1.0 / (L - 1)
    k_full = kelly_fraction(q, b)
    conf_adj = max(0.3, min(1.0, confidence / 100))
    k_quarter = k_full * k_frac * conf_adj

    capped_by = None
    if k_quarter > max_risk:
        k_quarter = max_risk
        capped_by = "max_risk_3pct"

    liability = round(bankroll * k_quarter, 2)
    matched = round(liability / (L - 1), 2) if L > 1.01 else 0.0
    return StakeDecision(
        kelly_full=round(k_full, 4),
        kelly_quarter=round(k_full * k_frac, 4),
        stake_pct=round(k_quarter, 4),
        stake_amount=matched,
        confidence=confidence,
        capped_by=capped_by,
    )


def compute_back_lay_stakes(
    p: float,
    back_odd: float | None,
    lay_odd: float | None,
    bankroll: float,
    confidence: float,
    *,
    p_ht: float | None = None,
    exit_odd: float | None = None,
    uses_ht: bool = False,
) -> tuple[StakeDecision, StakeDecision]:
    """Calcula stake % Kelly para back e lay (odds = back mín / lay máx)."""
    back_price = back_odd if back_odd and back_odd > 1.01 else None
    lay_price = lay_odd if lay_odd and lay_odd > 1.01 else None

    if uses_ht and p_ht is not None and back_price and exit_odd:
        stake_back = kelly_ht_trade(p_ht, back_price, exit_odd, bankroll, confidence=confidence)
    elif back_price:
        stake_back = kelly_simple(p, back_price, bankroll, confidence=confidence)
    else:
        stake_back = StakeDecision(0, 0, 0, 0, confidence, None)

    if lay_price:
        stake_lay = kelly_lay(p, lay_price, bankroll, confidence=confidence)
    else:
        stake_lay = StakeDecision(0, 0, 0, 0, confidence, None)

    return stake_back, stake_lay


def empty_stake(confidence: float = 70.0) -> StakeDecision:
    return StakeDecision(0, 0, 0, 0, confidence, None)


def apply_pro_tempo_stake_policy(
    market_id: str,
    stake_back: StakeDecision,
    stake_lay: StakeDecision,
) -> tuple[StakeDecision, StakeDecision]:
    """Zera stakes fora de: lay time FT, back empate FT, back under gols."""
    from ..markets import stake_sides_allowed

    allow_back, allow_lay = stake_sides_allowed(market_id)
    if not allow_back:
        stake_back = empty_stake(stake_back.confidence)
    if not allow_lay:
        stake_lay = empty_stake(stake_lay.confidence)
    return stake_back, stake_lay


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
