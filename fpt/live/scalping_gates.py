"""Gates de entrada scalping — janela de minuto + confirmação de tendência.

Scalping só entra após a tendência se confirmar (pressão sustentada, stats alinhados).
Reutiliza artefatos do pro-tempo (dom, vel, xG, SOT, momentum, steam).
"""
from __future__ import annotations

from dataclasses import dataclass

from .match_context import MatchLiveContext
from .pressure_odds import PressureOddsView, scalp_entry_ok


@dataclass(frozen=True)
class ScalpGateResult:
    ok: bool
    reason: str = ""


def _gates_cfg(cfg: dict) -> dict:
    return cfg.get("scalping_gates", {})


def _side_market_axes(market_id: str, side: str) -> tuple[int, int]:
    """(dom_sign, vel_sign) esperados para BACK (+1 favorece mandante). LAY inverte."""
    side_u = side.upper()
    if market_id == "home_win_ft":
        dom_sign = 1 if side_u == "BACK" else -1
    elif market_id == "away_win_ft":
        dom_sign = -1 if side_u == "BACK" else 1
    elif market_id == "draw_ft":
        dom_sign = 0
    else:
        dom_sign = 1 if side_u == "BACK" else -1
    vel_sign = dom_sign if dom_sign != 0 else 0
    return dom_sign, vel_sign


def scalp_minute_window_ok(ctx: MatchLiveContext, cfg: dict) -> ScalpGateResult:
    g = _gates_cfg(cfg)
    if not g.get("enabled", True):
        return ScalpGateResult(True)

    if ctx.elapsed_min is None:
        return ScalpGateResult(False, "minuto_desconhecido")

    em = int(ctx.elapsed_min)
    lo = int(g.get("min_elapsed_min", 10))
    hi = int(g.get("max_elapsed_min", 70))

    if em < lo:
        return ScalpGateResult(False, f"antes_{lo}m")
    if em > hi:
        return ScalpGateResult(False, f"apos_{hi}m")

    if g.get("block_ht_window", True):
        ht_lo, ht_hi = g.get("ht_block_min", [45, 50])
        if int(ht_lo) <= em <= int(ht_hi):
            return ScalpGateResult(False, "intervalo_ht")

    return ScalpGateResult(True)


def scalp_trend_confirmed(
    ctx: MatchLiveContext,
    side: str,
    market_id: str,
    cfg: dict,
    *,
    odd_move: float | None = None,
) -> ScalpGateResult:
    """Bloqueia entrada até pressão/stats confirmarem a direção do trade."""
    g = _gates_cfg(cfg)
    if not g.get("enabled", True) or not g.get("require_trend_confirmation", True):
        return ScalpGateResult(True)

    if g.get("require_prev_pressure", True) and not ctx.prev_pressure:
        return ScalpGateResult(False, "sem_historico_pressao")

    dom = ctx.pressure_dom
    vel = ctx.pressure_velocity
    if dom is None or vel is None:
        return ScalpGateResult(False, "sem_pressao")

    side_u = side.upper()
    dom_sign, vel_sign = _side_market_axes(market_id, side_u)

    min_dom = float(g.get("min_dominance", 10))
    min_vel = float(g.get("min_velocity", 5))

    if dom_sign != 0:
        if dom_sign > 0 and dom < min_dom:
            return ScalpGateResult(False, "dom_insuficiente")
        if dom_sign < 0 and dom > -min_dom:
            return ScalpGateResult(False, "dom_insuficiente")
        if vel_sign > 0 and vel < min_vel:
            return ScalpGateResult(False, "vel_insuficiente")
        if vel_sign < 0 and vel > -min_vel:
            return ScalpGateResult(False, "vel_insuficiente")
    else:
        max_abs = float(g.get("max_abs_dominance_draw", 12))
        if abs(dom) > max_abs:
            return ScalpGateResult(False, "empate_nao_neutro")

    if g.get("require_sustained_dom", True) and ctx.prev_pressure:
        prev_dom = float(ctx.prev_pressure.get("home", 0)) - float(ctx.prev_pressure.get("away", 0))
        sustain_ratio = float(g.get("min_sustain_ratio", 0.5))
        min_sustain = min_dom * sustain_ratio
        if dom_sign > 0 and (prev_dom < min_sustain or prev_dom > dom):
            return ScalpGateResult(False, "dom_nao_sustentada")
        if dom_sign < 0 and (prev_dom > -min_sustain or prev_dom < dom):
            return ScalpGateResult(False, "dom_nao_sustentada")

    if g.get("require_momentum_align", True) and ctx.graph_momentum is not None and dom_sign != 0:
        mom = float(ctx.graph_momentum)
        min_mom = float(g.get("min_momentum", 5))
        if dom_sign > 0 and mom < min_mom:
            return ScalpGateResult(False, "momentum_desalinhado")
        if dom_sign < 0 and mom > -min_mom:
            return ScalpGateResult(False, "momentum_desalinhado")

    if g.get("require_xg_align", True) and dom_sign != 0:
        xg_h = ctx.stat("ss_xg_home")
        xg_a = ctx.stat("ss_xg_away")
        min_diff = float(g.get("min_xg_diff", 0.10))
        xg_diff = xg_h - xg_a
        if dom_sign > 0 and xg_diff < min_diff:
            return ScalpGateResult(False, "xg_desalinhado")
        if dom_sign < 0 and xg_diff > -min_diff:
            return ScalpGateResult(False, "xg_desalinhado")

    if g.get("require_sot_align", True) and dom_sign != 0:
        sot_h = int(ctx.stat("ss_sot_home"))
        sot_a = int(ctx.stat("ss_sot_away"))
        min_diff = int(g.get("min_sot_diff", 0))
        sot_diff = sot_h - sot_a
        if dom_sign > 0 and sot_diff < min_diff:
            return ScalpGateResult(False, "sot_desalinhado")
        if dom_sign < 0 and sot_diff > -min_diff:
            return ScalpGateResult(False, "sot_desalinhado")

    min_combined_p = float(g.get("min_combined_pressure", 0))
    if min_combined_p > 0 and ctx.combined_pressure < min_combined_p:
        return ScalpGateResult(False, "jogo_muito_parado")

    max_goals = g.get("max_goals")
    if max_goals is not None and ctx.total_goals > int(max_goals):
        return ScalpGateResult(False, "placar_alto")

    if g.get("require_steam_align", False) and odd_move is not None and dom_sign != 0:
        steam_min = float(g.get("min_steam_align_pct", 0.02))
        if dom_sign > 0 and odd_move > -steam_min:
            return ScalpGateResult(False, "steam_desalinhado")
        if dom_sign < 0 and odd_move < steam_min:
            return ScalpGateResult(False, "steam_desalinhado")

    if g.get("require_xg_velocity", False):
        xg_vel = ctx.xg_velocity()
        min_xg_vel = float(g.get("min_xg_velocity", 0.08))
        if xg_vel is None or (dom_sign > 0 and xg_vel < min_xg_vel) or (dom_sign < 0 and xg_vel > -min_xg_vel):
            return ScalpGateResult(False, "xg_vel_insuficiente")

    return ScalpGateResult(True)


def scalp_entry_gates_ok(
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
    *,
    odd_move: float | None = None,
) -> tuple[bool, PressureOddsView | None, str]:
    """Janela → tendência → valor exchange (scalp_entry_ok)."""
    r = scalp_minute_window_ok(ctx, cfg)
    if not r.ok:
        return False, None, r.reason

    r = scalp_trend_confirmed(ctx, side, market_id, cfg, odd_move=odd_move)
    if not r.ok:
        return False, None, r.reason

    ok, view = scalp_entry_ok(
        side, market_id, odd_back, odd_lay, ctx,
        prob_home, prob_draw, prob_away, phi, cfg,
    )
    if not ok:
        return False, view, "sem_valor_exchange"
    return True, view, ""


def gate_reason_label(reason: str) -> str:
    """Rótulo legível para log/dashboard."""
    labels = {
        "minuto_desconhecido": "minuto desconhecido",
        "intervalo_ht": "intervalo (HT)",
        "sem_pressao": "sem pressão live",
        "sem_historico_pressao": "aguardando 2º tick de pressão",
        "dom_insuficiente": "dominância não confirmada",
        "vel_insuficiente": "velocidade não confirmada",
        "dom_nao_sustentada": "tendência não sustentada",
        "momentum_desalinhado": "momentum desalinhado",
        "xg_desalinhado": "xG desalinhado",
        "sot_desalinhado": "finalizações desalinhadas",
        "jogo_muito_parado": "jogo parado demais",
        "placar_alto": "placar acima do limite",
        "steam_desalinhado": "steam desalinhado",
        "xg_vel_insuficiente": "ΔxG insuficiente",
        "sem_valor_exchange": "sem valor na exchange",
        "empate_nao_neutro": "jogo não equilibrado p/ empate",
    }
    if reason in labels:
        return labels[reason]
    if reason.startswith("antes_"):
        return f"antes de {reason.replace('antes_', '').replace('m', '')}'"
    if reason.startswith("apos_"):
        return f"após {reason.replace('apos_', '').replace('m', '')}'"
    return reason or "bloqueado"
