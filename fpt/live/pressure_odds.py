"""Pressão SofaScore → probabilidade live → odds de entrada (exchange-aware)."""
from __future__ import annotations

import math
from dataclasses import dataclass

from ..trading.exchange_odds import ExchangeQuote, check_exchange_value
from ..trading.fair_odds import exchange_fair_odds
from .match_context import MatchLiveContext


@dataclass
class PressureOddsView:
    market_id: str
    side: str
    prob_model: float
    prob_live: float
    back_fair: float
    back_min: float
    lay_fair: float
    lay_max: float
    market_back: float | None
    market_lay: float | None
    edge_back_pp: float | None
    edge_lay_pp: float | None
    has_back_value: bool
    has_lay_value: bool
    spread_pct: float | None = None

    def summary(self) -> str:
        sp = f" sp {self.spread_pct:.1f}%" if self.spread_pct is not None else ""
        return (
            f"P live {self.prob_live:.1%} (mod {self.prob_model:.1%}) | "
            f"back min {self.back_min:.2f} lay max {self.lay_max:.2f}{sp}"
        )


def _cfg_po(cfg: dict) -> dict:
    return cfg.get("pressure_odds", {})


def _clamp(p: float, lo: float = 0.01, hi: float = 0.99) -> float:
    return max(lo, min(hi, p))


def _logit(p: float) -> float:
    p = _clamp(p)
    return math.log(p / (1.0 - p))


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def blend_1x2_with_pressure(
    prob_home: float,
    prob_draw: float,
    prob_away: float,
    ctx: MatchLiveContext,
    *,
    blend_weight: float = 0.35,
    xg_weight: float = 0.15,
    dominance_scale: float = 2.0,
) -> tuple[float, float, float]:
    p_h, p_d, p_a = prob_home, prob_draw, prob_away
    total = p_h + p_d + p_a
    if total > 0:
        p_h, p_d, p_a = p_h / total, p_d / total, p_a / total

    ph = float(ctx.pressure_home or 0)
    pa = float(ctx.pressure_away or 0)
    if ph + pa < 1:
        return p_h, p_d, p_a

    w = max(0.0, min(1.0, blend_weight))
    live_h_share = ph / (ph + pa)
    two = p_h + p_a
    if two > 0.001:
        model_h_share = p_h / two
        new_h_share = (1.0 - w) * model_h_share + w * live_h_share
    else:
        new_h_share = live_h_share

    xg_h = float(ctx.sofascore_stats.get("ss_xg_home") or 0)
    xg_a = float(ctx.sofascore_stats.get("ss_xg_away") or 0)
    if xg_h + xg_a > 0.05 and xg_weight > 0:
        xg_dom = (xg_h - xg_a) / max(xg_h + xg_a, 0.1)
        logit = _logit(new_h_share)
        logit += xg_weight * xg_dom * 3.0
        new_h_share = _sigmoid(logit)

    dom = ctx.pressure_dom
    if dom is not None and dominance_scale > 0:
        logit = _logit(new_h_share)
        logit += (float(dom) / 100.0) * dominance_scale * w
        new_h_share = _sigmoid(logit)

    new_h_share = _clamp(new_h_share, 0.02, 0.98)
    scale = 1.0 - p_d
    return new_h_share * scale, p_d, (1.0 - new_h_share) * scale


def _prob_for_market(market_id: str, p_h: float, p_d: float, p_a: float) -> float:
    if market_id == "home_win_ft":
        return p_h
    if market_id == "draw_ft":
        return p_d
    if market_id == "away_win_ft":
        return p_a
    return p_h


def pressure_odds_for_market(
    market_id: str,
    side: str,
    ctx: MatchLiveContext,
    prob_home: float,
    prob_draw: float,
    prob_away: float,
    phi: float,
    cfg: dict,
    *,
    odd_back: float | None = None,
    odd_lay: float | None = None,
) -> PressureOddsView:
    po = _cfg_po(cfg)
    p_h, p_d, p_a = blend_1x2_with_pressure(
        prob_home, prob_draw, prob_away, ctx,
        blend_weight=float(po.get("blend_weight", 0.35)),
        xg_weight=float(po.get("xg_weight", 0.15)),
        dominance_scale=float(po.get("dominance_scale", 2.0)),
    )
    p_model = _prob_for_market(market_id, prob_home, prob_draw, prob_away)
    p_live = _prob_for_market(market_id, p_h, p_d, p_a)
    ex = exchange_fair_odds(p_live, phi)
    quote = ExchangeQuote.from_prices(odd_back, odd_lay)
    min_edge = float(po.get("min_edge_pp", 0.5))

    back_chk = check_exchange_value(p_live, phi, quote, "BACK", min_edge_pp=min_edge)
    lay_chk = check_exchange_value(p_live, phi, quote, "LAY", min_edge_pp=min_edge)

    return PressureOddsView(
        market_id=market_id,
        side=side,
        prob_model=p_model,
        prob_live=p_live,
        back_fair=ex.back_fair,
        back_min=ex.back_min,
        lay_fair=ex.lay_fair,
        lay_max=ex.lay_max,
        market_back=odd_back,
        market_lay=odd_lay,
        edge_back_pp=back_chk.edge_pp,
        edge_lay_pp=lay_chk.edge_pp,
        has_back_value=back_chk.has_value,
        has_lay_value=lay_chk.has_value,
        spread_pct=quote.spread_pct,
    )


def scalp_entry_ok(
    side: str,
    market_id: str,
    odd_back: float | None,
    odd_lay: float | None,
    ctx: MatchLiveContext,
    prob_home: float,
    prob_draw: float,
    prob_away: float,
    phi: float,
    cfg: dict,
) -> tuple[bool, PressureOddsView | None]:
    po = _cfg_po(cfg)
    if not po.get("enabled", True):
        return True, None
    if ctx.pressure_home is None or ctx.pressure_away is None:
        return not po.get("require_pressure", True), None

    view = pressure_odds_for_market(
        market_id, side, ctx, prob_home, prob_draw, prob_away, phi, cfg,
        odd_back=odd_back, odd_lay=odd_lay,
    )
    ok = view.has_back_value if side.upper() == "BACK" else view.has_lay_value

    ex_cfg = cfg.get("exchange_execution", {})
    if ok and ex_cfg.get("require_spread_ok", True):
        from ..trading.exchange_odds import scalp_covers_costs

        quote = ExchangeQuote.from_prices(odd_back, odd_lay)
        scalp_cfg = cfg.get("scalping", {})
        tp = float(scalp_cfg.get("take_profit_pct", 0.015))
        comm = float(cfg.get("paper", {}).get("commission", 0.05))
        margin = float(ex_cfg.get("scalp_min_margin_pp", 0.3))
        if not scalp_covers_costs(quote, side, take_profit_pct=tp, commission=comm, min_margin_pp=margin):
            ok = False

    return ok, view
