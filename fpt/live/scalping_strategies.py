"""Estratégias de scalping in-play."""
from __future__ import annotations

from .match_context import MatchLiveContext
from .entry_exposure import OpenExposure, check_entry_exposure
from .scalping_gates import scalp_entry_gates_ok, scalp_minute_window_ok

# Tipos executados pelo robô como scalp (TP/SL/timeout)
SCALP_ENTRY_TYPES = frozenset({
    "PRESSURE_STEAM",  # legado
    "SCALP_PRESSURE_STEAM",
    "SCALP_STEAM_MOMENTUM",
    "SCALP_PRESSURE_SURGE",
    "SCALP_XG_SPIKE",
    "SCALP_DOMINANCE",
    "SCALP_FADE_STEAM",
})


def is_scalp_entry(alert_type: str) -> bool:
    return alert_type in SCALP_ENTRY_TYPES


def _scalp_cfg(cfg: dict) -> dict:
    return cfg.get("scalping", {})


def _strat_cfg(cfg: dict, sid: str) -> dict:
    return cfg.get("scalping_strategies", {}).get(sid, {})


def _enabled(cfg: dict, sid: str, default: bool = True) -> bool:
    return bool(_strat_cfg(cfg, sid).get("enabled", default))


def evaluate_scalping_strategies(
    ctx: MatchLiveContext,
    *,
    home: str,
    away: str,
    league: str,
    market: str,
    market_label: str,
    odd_back: float | None,
    odd_lay: float | None,
    prob_est: float,
    odd_min: float,
    edge_pp: float | None,
    prob_home: float,
    prob_draw: float,
    prob_away: float,
    phi: float,
    market_id: str | None,
    selection_id: int | None,
    score: str,
    cfg: dict,
    bankroll: float,
    alert_id_fn,
    open_exposures: list | None = None,
    pending_exposures: list | None = None,
) -> list[dict]:
    """
    Retorna dicts prontos para virar LiveAlert.
    Keys: alert_type, side, message, stake_pct
    """
    if not ctx.in_play or ctx.pressure_home is None or ctx.pressure_away is None:
        return []

    sc = _scalp_cfg(cfg)
    if not sc.get("enabled", True):
        return []

    window = scalp_minute_window_ok(ctx, cfg)
    if not window.ok:
        return []

    dom = ctx.pressure_dom or 0.0
    vel = ctx.pressure_velocity or 0.0
    stake_pct = float(sc.get("stake_pct", 0.02))

    prev = (ctx.prev_odds or {}).get(market) if ctx.prev_odds else None
    odd_move = ((odd_back - prev) / prev) if prev and odd_back and prev > 1.01 else None
    alerts: list[dict] = []
    exp_open = open_exposures or []
    exp_pending = pending_exposures

    def _add(alert_type: str, side: str, msg: str, stake: float | None = None):
        ok, pov, gate_reason = scalp_entry_gates_ok(
            side, market, odd_back, odd_lay, ctx,
            prob_home, prob_draw, prob_away, phi, cfg,
            odd_move=odd_move,
        )
        if not ok:
            return
        if exp_pending is not None:
            exp_ok, _ = check_entry_exposure(
                home, away, market, side, exp_open + exp_pending, cfg,
            )
            if not exp_ok:
                return
            exp_pending.append(OpenExposure(
                home, away, market, side, entry_type="scalp", source="pending",
            ))
        extra = f" | {pov.summary()}" if pov else ""
        alerts.append({
            "alert_type": alert_type,
            "side": side,
            "message": msg + extra,
            "stake_pct": stake if stake is not None else stake_pct,
        })

    # 1) PRESSURE + STEAM (legado + novo id)
    if _enabled(cfg, "pressure_steam"):
        ps = _strat_cfg(cfg, "pressure_steam")
        min_dom = float(ps.get("min_dominance", 12.0))
        min_delta = float(ps.get("min_pressure_delta", 8.0))
        steam_pct = float(ps.get("steam_pct", 0.03))
        if odd_move is not None:
            if dom >= min_dom and vel >= min_delta and odd_move <= -steam_pct:
                _add(
                    "SCALP_PRESSURE_STEAM", "BACK",
                    f"SCALP P+STEAM {market_label} BACK: pressão H +{vel:.1f} | "
                    f"odd {prev:.2f}→{odd_back:.2f} | dom={dom:.1f}",
                )
            elif dom <= -min_dom and vel <= -min_delta and odd_move >= steam_pct:
                _add(
                    "SCALP_PRESSURE_STEAM", "LAY",
                    f"SCALP P+STEAM {market_label} LAY: pressão A {vel:.1f} | "
                    f"odd {prev:.2f}→{odd_back:.2f} | dom={dom:.1f}",
                )

    # 2) STEAM + MOMENTUM gráfico
    if _enabled(cfg, "steam_momentum") and odd_move is not None and ctx.graph_momentum is not None:
        sm = _strat_cfg(cfg, "steam_momentum")
        steam_pct = float(sm.get("steam_pct", 0.03))
        min_mom = float(sm.get("min_graph_momentum", 12.0))
        mom = float(ctx.graph_momentum)
        if odd_move <= -steam_pct and mom >= min_mom and dom >= float(sm.get("min_dominance", 8)):
            _add("SCALP_STEAM_MOMENTUM", "BACK",
                 f"SCALP STEAM+MOM {market_label} BACK: mom={mom:+.0f} odd↓ {odd_move:.1%}")
        elif odd_move >= steam_pct and mom <= -min_mom and dom <= -float(sm.get("min_dominance", 8)):
            _add("SCALP_STEAM_MOMENTUM", "LAY",
                 f"SCALP STEAM+MOM {market_label} LAY: mom={mom:+.0f} odd↑ {odd_move:.1%}")

    # 3) SURGE de pressão (sem steam obrigatório)
    if _enabled(cfg, "pressure_surge"):
        pu = _strat_cfg(cfg, "pressure_surge")
        if abs(vel) >= float(pu.get("min_velocity", 10)) and abs(dom) >= float(pu.get("min_dominance", 15)):
            side = "BACK" if vel > 0 and dom > 0 else "LAY"
            _add(
                "SCALP_PRESSURE_SURGE", side,
                f"SCALP SURGE {market_label} {side}: vel={vel:+.1f} dom={dom:.1f}",
                stake=float(pu.get("stake_pct", stake_pct * 0.75)),
            )

    # 4) Spike de xG live
    if _enabled(cfg, "xg_spike"):
        xg = _strat_cfg(cfg, "xg_spike")
        xg_vel = ctx.xg_velocity()
        if xg_vel is not None and xg_vel >= float(xg.get("min_xg_delta", 0.15)):
            if ctx.combined_xg >= float(xg.get("min_combined_xg", 0.5)):
                side = "BACK" if dom >= float(xg.get("min_dom", 8)) else "LAY"
                _add("SCALP_XG_SPIKE", side,
                     f"SCALP xG+ {market_label} {side}: ΔxG={xg_vel:.2f} total={ctx.combined_xg:.2f}")

    # 5) Dominância sustentada
    if _enabled(cfg, "dominance"):
        dcfg = _strat_cfg(cfg, "dominance")
        prev_dom = None
        if ctx.prev_pressure:
            prev_dom = float(ctx.prev_pressure.get("home", 0)) - float(ctx.prev_pressure.get("away", 0))
        if abs(dom) >= float(dcfg.get("min_dominance", 25)):
            if prev_dom is not None and abs(prev_dom) >= float(dcfg.get("min_prev_dominance", 20)):
                side = "BACK" if dom > 0 else "LAY"
                _add("SCALP_DOMINANCE", side,
                     f"SCALP DOM {market_label} {side}: dom={dom:.1f} (prev={prev_dom:.1f})")

    # 6) Fade steam (steam sem pressão)
    if _enabled(cfg, "fade_steam") and odd_move is not None:
        fs = _strat_cfg(cfg, "fade_steam")
        steam_pct = float(fs.get("steam_pct", 0.03))
        if odd_move <= -steam_pct and dom < float(fs.get("max_support_dom", 5)):
            _add("SCALP_FADE_STEAM", "LAY",
                 f"SCALP FADE {market_label} LAY: steam falso odd↓ {odd_move:.1%} dom={dom:.1f}")
        elif odd_move >= steam_pct and dom > -float(fs.get("max_support_dom", 5)):
            _add("SCALP_FADE_STEAM", "BACK",
                 f"SCALP FADE {market_label} BACK: steam falso odd↑ {odd_move:.1%} dom={dom:.1f}")

    # Dedup: mesma direção — mantém só o de maior prioridade
    priority = {
        "SCALP_PRESSURE_STEAM": 5,
        "SCALP_STEAM_MOMENTUM": 4,
        "SCALP_XG_SPIKE": 3,
        "SCALP_DOMINANCE": 2,
        "SCALP_PRESSURE_SURGE": 1,
        "SCALP_FADE_STEAM": 1,
    }
    by_side: dict[str, dict] = {}
    for a in alerts:
        key = a["side"]
        if key not in by_side or priority.get(a["alert_type"], 0) > priority.get(by_side[key]["alert_type"], 0):
            by_side[key] = a
    return list(by_side.values())
