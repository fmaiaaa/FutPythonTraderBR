"""Estratégias pro-tempo — pré-jogo + confirmação live."""
from __future__ import annotations

from dataclasses import dataclass

from ..markets import stake_sides_allowed
from .match_context import MatchLiveContext, market_id_for_side
from .pro_tempo import format_action_label, _get


@dataclass
class ProTempoSignal:
    strategy_id: str
    market_id: str
    side: str
    label: str
    phase: str
    score: float = 0.0


def _base_rec_ok(rec, cfg: dict, *, side: str, market_id: str) -> bool:
    live = cfg.get("live", {})
    min_edge = float(live.get("min_edge_pp", 1.0))
    min_conf = float(live.get("min_confidence", 40))
    min_p_ht = float(live.get("min_p_ht_profit", 0.48))

    conf = float(_get(rec, "confianca", 0) or 0)
    if conf < min_conf:
        return False
    edge = _get(rec, "edge_pp")
    p_ht = float(_get(rec, "p_lucro_ht", 0) or 0)
    if edge is not None and edge < min_edge:
        return False
    if market_id in ("home_win_ft", "draw_ft", "away_win_ft") and p_ht < min_p_ht:
        return False

    stake = float(_get(rec, "stake_back_pct", 0) or 0) if side == "BACK" else float(_get(rec, "stake_lay_pct", 0) or 0)
    return stake > 0


def _odd_ok(
    rec,
    side: str,
    odd_back: float | None,
    odd_lay: float | None,
    require_exchange: bool,
    *,
    require_entry_bounds: bool = True,
) -> bool:
    from ..trading.exchange_odds import ExchangeQuote

    quote = ExchangeQuote.from_prices(odd_back, odd_lay)
    exec_price = quote.entry_price(side)
    if require_exchange and not exec_price:
        return False

    back_min = _get(rec, "odd_minima_entrada")
    lay_max = _get(rec, "lay_max")
    if side == "BACK":
        if require_entry_bounds and exec_price and back_min and exec_price < back_min:
            return False
    else:
        if require_entry_bounds and exec_price and lay_max and exec_price > lay_max:
            return False
    return True


def _cfg_strat(cfg: dict, sid: str) -> dict:
    return cfg.get("pro_tempo_strategies", {}).get(sid, {})


def _enabled(cfg: dict, sid: str, default: bool = True) -> bool:
    return bool(_cfg_strat(cfg, sid).get("enabled", default))


def _signal(strategy_id: str, market_id: str, side: str, phase: str, score: float = 1.0) -> ProTempoSignal:
    return ProTempoSignal(
        strategy_id=strategy_id,
        market_id=market_id,
        side=side,
        label=f"[{strategy_id}] {format_action_label(market_id, side)}",
        phase=phase,
        score=score,
    )


def evaluate_pro_tempo_strategies(
    ctx: MatchLiveContext,
    recs: dict[str, object],
    odds: dict[str, tuple[float | None, float | None]],
    cfg: dict,
    *,
    betfair_ok: bool,
) -> list[ProTempoSignal]:
    """Avalia todas as estratégias pro-tempo para o jogo."""
    pt_cfg = cfg.get("pro_tempo", {})
    classic_prematch_only = bool(pt_cfg.get("classic_prematch_only", True))
    signals: list[ProTempoSignal] = []

    for market_id, rec in recs.items():
        odd_back, odd_lay = odds.get(market_id, (None, None))
        allow_back, allow_lay = stake_sides_allowed(market_id)

        # --- A1/A3 BACK clássico (pré-jogo) ---
        if _enabled(cfg, "back_draw_classic") and market_id == "draw_ft" and allow_back:
            if not ctx.in_play or not classic_prematch_only:
                if _base_rec_ok(rec, cfg, side="BACK", market_id=market_id):
                    if _odd_ok(rec, "BACK", odd_back, odd_lay, betfair_ok):
                        signals.append(_signal("back_draw_classic", market_id, "BACK", "prematch"))

        if _enabled(cfg, "back_under_classic") and market_id.startswith("under") and allow_back:
            if not ctx.in_play or not classic_prematch_only:
                if _base_rec_ok(rec, cfg, side="BACK", market_id=market_id):
                    if _odd_ok(rec, "BACK", odd_back, odd_lay, False):
                        signals.append(_signal("back_under_classic", market_id, "BACK", "prematch"))

        # --- A2 LAY 1X2 clássico ---
        if _enabled(cfg, "lay_1x2_classic") and market_id in ("home_win_ft", "away_win_ft") and allow_lay:
            if not ctx.in_play or not classic_prematch_only:
                if _base_rec_ok(rec, cfg, side="LAY", market_id=market_id):
                    if _odd_ok(rec, "LAY", odd_back, odd_lay, betfair_ok):
                        signals.append(_signal("lay_1x2_classic", market_id, "LAY", "prematch"))

    if not ctx.in_play:
        return signals

    # --- Live confirm / late (B + C) ---
    signals.extend(_eval_live_strategies(ctx, recs, odds, cfg, betfair_ok))
    return signals


def _eval_live_strategies(
    ctx: MatchLiveContext,
    recs: dict[str, object],
    odds: dict[str, tuple[float | None, float | None]],
    cfg: dict,
    betfair_ok: bool,
) -> list[ProTempoSignal]:
    out: list[ProTempoSignal] = []
    dom = ctx.pressure_dom
    vel = ctx.pressure_velocity

    # B1 / C3 — Under jogo morto
    for sid in ("under_dead_game", "back_under_over_cancelled"):
        if not _enabled(cfg, sid):
            continue
        s = _cfg_strat(cfg, sid)
        w = s.get("window_min", [15, 38])
        if not ctx.in_window(int(w[0]), int(w[1])):
            continue
        if ctx.implied_over25() is not None and ctx.implied_over25() < float(s.get("min_implied_over25", 0.52)):
            continue
        if ctx.combined_pressure > float(s.get("max_combined_pressure", 25)):
            continue
        if ctx.combined_xg > float(s.get("max_combined_xg", 0.45)):
            continue
        if ctx.total_goals > int(s.get("max_goals", 1)):
            continue
        for mid in s.get("markets", ["under15_ht", "under25_ft"]):
            rec = recs.get(mid)
            if rec is None:
                continue
            ob, ol = odds.get(mid, (None, None))
            if _base_rec_ok(rec, cfg, side="BACK", market_id=mid) and _odd_ok(
                rec, "BACK", ob, ol, False, require_entry_bounds=False,
            ):
                out.append(_signal(sid, mid, "BACK", "live_confirm", score=2.0))
                break

    # B5 — Under HT conservador
    if _enabled(cfg, "under_ht_conservative"):
        s = _cfg_strat(cfg, "under_ht_conservative")
        w = s.get("window_min", [28, 42])
        if ctx.in_window(int(w[0]), int(w[1])) and ctx.total_goals == 0:
            if ctx.combined_shots <= int(s.get("max_combined_shots", 8)):
                if float(ctx.pressure_home or 0) < float(s.get("max_side_pressure", 15)):
                    if float(ctx.pressure_away or 0) < float(s.get("max_side_pressure", 15)):
                        for mid in s.get("markets", ["under05_ht", "under15_ht"]):
                            rec = recs.get(mid)
                            if rec is None:
                                continue
                            ob, _ = odds.get(mid, (None, None))
                            if _base_rec_ok(rec, cfg, side="BACK", market_id=mid) and _odd_ok(
                                rec, "BACK", ob, None, False, require_entry_bounds=False,
                            ):
                                out.append(_signal("under_ht_conservative", mid, "BACK", "live_confirm", score=1.8))
                                break

    fav = ctx.favorite_side(float(_cfg_strat(cfg, "lay_favorite_absent").get("max_favorite_odd", 1.85)))
    dog = ctx.underdog_side()

    # B2 — Lay favorito ausente
    if _enabled(cfg, "lay_favorite_absent") and fav and dom is not None:
        s = _cfg_strat(cfg, "lay_favorite_absent")
        w = s.get("window_min", [10, 40])
        if ctx.in_window(int(w[0]), int(w[1])):
            min_opp = float(s.get("min_opposite_dominance", 12))
            opposed = (fav == "away" and dom >= min_opp) or (fav == "home" and dom <= -min_opp)
            fav_sot = ctx.stat("ss_sot_home" if fav == "home" else "ss_sot_away")
            opp_sot = ctx.stat("ss_sot_away" if fav == "home" else "ss_sot_home")
            weak_fav = fav_sot <= float(s.get("max_favorite_sot", 1)) and opp_sot >= float(s.get("min_opponent_sot", 2))
            if opposed or weak_fav:
                mid = market_id_for_side(fav)
                rec = recs.get(mid)
                ob, ol = odds.get(mid, (None, None))
                if rec and _base_rec_ok(rec, cfg, side="LAY", market_id=mid) and _odd_ok(rec, "LAY", ob, ol, betfair_ok):
                    out.append(_signal("lay_favorite_absent", mid, "LAY", "live_confirm", score=2.2))

    # B3 — Lay zebra morto
    if _enabled(cfg, "lay_underdog_dead") and dog and dom is not None and vel is not None:
        s = _cfg_strat(cfg, "lay_underdog_dead")
        w = s.get("window_min", [10, 45])
        if ctx.in_window(int(w[0]), int(w[1])):
            fav_dom = dom if dog == "away" else -dom
            if fav_dom >= float(s.get("min_favorite_dominance", 20)) and vel >= float(s.get("min_velocity", 5)):
                mid = market_id_for_side(dog)
                rec = recs.get(mid)
                ob, ol = odds.get(mid, (None, None))
                if rec and _base_rec_ok(rec, cfg, side="LAY", market_id=mid) and _odd_ok(rec, "LAY", ob, ol, betfair_ok):
                    out.append(_signal("lay_underdog_dead", mid, "LAY", "live_confirm", score=2.0))

    # B4 — Back empate tardio
    if _enabled(cfg, "back_draw_late"):
        s = _cfg_strat(cfg, "back_draw_late")
        w = s.get("window_min", [25, 40])
        if ctx.in_window(int(w[0]), int(w[1])) and dom is not None:
            if ctx.total_goals <= int(s.get("max_goals", 2)):
                if abs(dom) <= float(s.get("max_abs_dominance", 8)):
                    rec = recs.get("draw_ft")
                    ob, ol = odds.get("draw_ft", (None, None))
                    if rec and _base_rec_ok(rec, cfg, side="BACK", market_id="draw_ft"):
                        if _odd_ok(rec, "BACK", ob, ol, betfair_ok):
                            out.append(_signal("back_draw_late", "draw_ft", "BACK", "live_late", score=1.7))

    # C1 — Fade steam favorito
    if _enabled(cfg, "fade_favorite_steam") and fav and ctx.prev_odds and dom is not None:
        s = _cfg_strat(cfg, "fade_favorite_steam")
        mid = market_id_for_side(fav)
        prev = ctx.prev_odds.get(mid)
        ob, ol = odds.get(mid, (None, None))
        if prev and ob and prev > 1.01:
            move = (ob - prev) / prev
            steam = float(s.get("steam_pct", 0.05))
            if move <= -steam:
                fake = (fav == "home" and dom < float(s.get("max_support_dom", 5))) or (
                    fav == "away" and dom > -float(s.get("max_support_dom", 5))
                )
                if fake:
                    rec = recs.get(mid)
                    if rec and _base_rec_ok(rec, cfg, side="LAY", market_id=mid) and _odd_ok(rec, "LAY", ob, ol, betfair_ok):
                        out.append(_signal("fade_favorite_steam", mid, "LAY", "live_confirm", score=1.9))

    # C2 — Fade steam zebra
    if _enabled(cfg, "fade_underdog_steam") and dog and ctx.prev_odds and dom is not None:
        s = _cfg_strat(cfg, "fade_underdog_steam")
        mid = market_id_for_side(dog)
        prev = ctx.prev_odds.get(mid)
        ob, ol = odds.get(mid, (None, None))
        if prev and ob and prev > 1.01:
            move = (ob - prev) / prev
            steam = float(s.get("steam_pct", 0.05))
            fav_dom = dom if dog == "away" else -dom
            if move <= -steam and fav_dom >= float(s.get("min_favorite_dom", 15)):
                rec = recs.get(mid)
                if rec and _base_rec_ok(rec, cfg, side="LAY", market_id=mid) and _odd_ok(rec, "LAY", ob, ol, betfair_ok):
                    out.append(_signal("fade_underdog_steam", mid, "LAY", "live_confirm", score=1.8))

    return out


def best_signal_for_market(signals: list[ProTempoSignal], market_id: str) -> ProTempoSignal | None:
    matched = [s for s in signals if s.market_id == market_id]
    if not matched:
        return None
    return max(matched, key=lambda s: s.score)


def best_signal_global(signals: list[ProTempoSignal]) -> ProTempoSignal | None:
    if not signals:
        return None
    return max(signals, key=lambda s: s.score)
