"""Entradas pro-tempo (pré-jogo → saída HT): critérios rigorosos e rótulos de ação."""
from __future__ import annotations

from ..markets import market_by_id

# Mercados operáveis na estratégia pro-tempo
PRO_TEMPO_1X2 = frozenset({"home_win_ft", "draw_ft", "away_win_ft"})


def format_action_label(market_id: str, side: str) -> str:
    """Ex.: BACK Empate FT, LAY Mandante FT, BACK Under 2.5 FT."""
    m = market_by_id(market_id)
    name = m.label if m else market_id.replace("_", " ")
    return f"{side} {name}"


def _get(rec, key: str, default=None):
    if isinstance(rec, dict):
        return rec.get(key, default)
    return getattr(rec, key, default)


def assess_pro_tempo_entry(
    rec,
    market_id: str,
    odd_back: float | None,
    odd_lay: float | None,
    cfg: dict,
    *,
    require_exchange_odd: bool = True,
    ctx: "MatchLiveContext | None" = None,
) -> tuple[bool, str | None, str]:
    """Delega ao motor de estratégias pro-tempo (clássicas + live)."""
    from .match_context import MatchLiveContext
    from .pro_tempo_strategies import best_signal_for_market, evaluate_pro_tempo_strategies

    if ctx is None:
        ctx = MatchLiveContext(home="", away="", in_play=False)

    signals = evaluate_pro_tempo_strategies(
        ctx, {market_id: rec}, {market_id: (odd_back, odd_lay)}, cfg,
        betfair_ok=require_exchange_odd,
    )
    sig = best_signal_for_market(signals, market_id)
    if sig:
        label = sig.label.replace(f"[{sig.strategy_id}] ", "")
        return True, sig.side, label
    return False, None, "—"


def assess_watch(rec, market_id: str, odd_back: float | None, cfg: dict) -> str | None:
    """Quase-entrada para monitoramento."""
    live = cfg.get("live", {})
    watch_pct = float(live.get("watch_near_value_pct", 2.0)) / 100
    min_edge = float(live.get("min_edge_pp", 1.0))

    if market_id != "draw_ft" or not odd_back:
        return None
    back_min = _get(rec, "odd_minima_entrada")
    edge = _get(rec, "edge_pp")
    if not back_min:
        return None
    if odd_back >= back_min * (1 - watch_pct) and edge is not None and edge >= min_edge * 0.5:
        return f"WATCH {format_action_label(market_id, 'BACK')}"
    return None


def pick_best_action(
    recs: list[dict],
    alerts: list,
) -> tuple[str, str, float, str | None]:
    """
    Escolhe a melhor ação para exibição.
    Retorna (action_label, market_id, confidence, entry_side).
    """
    # Alertas ENTER já filtrados
    for a in alerts:
        if getattr(a, "alert_type", None) == "ENTER":
            side = getattr(a, "recommended_side", "BACK")
            mkt = getattr(a, "market", "")
            label = format_action_label(mkt, side) if mkt else a.message[:40]
            return label, mkt, 0.0, side

    best_label = "—"
    best_mkt = ""
    best_conf = 0.0
    best_side = None
    best_edge = -999.0

    for r in recs:
        if r.get("action") != "ENTER":
            continue
        edge = r.get("edge_pp")
        conf = float(r.get("confianca", 0) or 0)
        score = (edge if edge is not None else 0) + conf * 0.01
        if score > best_edge:
            best_edge = score
            best_label = r.get("action_label") or "ENTER"
            best_mkt = r.get("market", "")
            best_conf = conf
            best_side = r.get("entry_side")

    if best_label != "—":
        return best_label, best_mkt, best_conf, best_side

    for r in recs:
        watch = r.get("watch_label")
        if watch:
            return watch, r.get("market", ""), float(r.get("confianca", 0) or 0), None

    return "—", "", 0.0, None
