from __future__ import annotations



"""Engine de scalping in-play — TP/SL/timeout com execução exchange (back↔lay)."""



import json

import uuid

from dataclasses import asdict, dataclass, field

from datetime import datetime

from pathlib import Path

from zoneinfo import ZoneInfo



from ..client import DATA

from ..storage import persist_data_locally

from ..trading.exchange_odds import ExchangeQuote, build_scalp_exit_targets, scalp_covers_costs

from .config import load_live_config
from .entry_exposure import check_entry_exposure, load_open_exposures
from .models import LiveAlert, LiveMatchState



BR = ZoneInfo("America/Sao_Paulo")

OPEN_POSITIONS = DATA / "live" / "scalp_positions.json"





@dataclass

class ScalpPlan:

    side: str  # BACK | LAY — lado da ENTRADA

    stake_pct: float

    entry_odd: float

    exit_side: str

    target_exit_odd: float

    stop_exit_odd: float

    timeout_sec: int

    horizon_sec: int

    spread_pct: float | None = None





@dataclass

class ScalpPosition:

    position_id: str

    alert_id: str

    home: str

    away: str

    market: str

    side: str  # entrada BACK | LAY

    entry_odd: float

    stake_pct: float

    exit_side: str = "LAY"

    target_odd: float = 0.0  # alvo no preço de SAÍDA

    stop_odd: float = 0.0

    timeout_sec: int = 60

    entry_ts: str = ""

    market_id: str | None = None

    selection_id: int | None = None

    status: str = "OPEN"

    spread_pct: float | None = None



    def to_dict(self) -> dict:

        return asdict(self)





def _scalping_cfg() -> dict:

    return load_live_config().get("scalping", {})





def _exchange_cfg() -> dict:

    return load_live_config().get("exchange_execution", {})





def build_scalp_plan(alert: LiveAlert, side: str | None = None) -> ScalpPlan | None:

    cfg = _scalping_cfg()

    ex_cfg = _exchange_cfg()

    side = (side or alert.recommended_side or "BACK").upper()

    quote = ExchangeQuote.from_prices(alert.odd_back, alert.odd_lay)

    entry = quote.entry_price(side)

    if not entry or entry <= 1.01:

        return None



    stake_pct = float(cfg.get("stake_pct", alert.stake_pct or 0.005))

    tp = float(cfg.get("take_profit_pct", 0.015))

    sl = float(cfg.get("stop_loss_pct", 0.02))

    timeout = int(cfg.get("timeout_seconds", 60))

    horizon = int(cfg.get("target_horizon_seconds", 30))



    if ex_cfg.get("require_spread_ok", True):

        comm = float(load_live_config().get("paper", {}).get("commission", 0.05))

        margin = float(ex_cfg.get("scalp_min_margin_pp", 0.3))

        if not scalp_covers_costs(quote, side, take_profit_pct=tp, commission=comm, min_margin_pp=margin):

            return None



    target_exit, stop_exit, entry_exec = build_scalp_exit_targets(

        quote, side, take_profit_pct=tp, stop_loss_pct=sl,

    )

    if target_exit is None or stop_exit is None:

        return None



    exit_side = "LAY" if side == "BACK" else "BACK"

    return ScalpPlan(

        side=side,

        stake_pct=stake_pct,

        entry_odd=entry_exec,

        exit_side=exit_side,

        target_exit_odd=target_exit,

        stop_exit_odd=stop_exit,

        timeout_sec=timeout,

        horizon_sec=horizon,

        spread_pct=quote.spread_pct,

    )





def should_exit(

    pos: ScalpPosition,

    exit_odd: float,

    elapsed_sec: int,

) -> tuple[bool, str]:

    """Monitora preço de SAÍDA (lay se entrou back, back se entrou lay)."""

    if pos.side == "BACK":

        if exit_odd <= pos.target_odd:

            return True, "TP"

        if exit_odd >= pos.stop_odd:

            return True, "SL"

    else:

        if exit_odd >= pos.target_odd:

            return True, "TP"

        if exit_odd <= pos.stop_odd:

            return True, "SL"

    if elapsed_sec >= pos.timeout_sec:

        return True, "TIMEOUT"

    return False, ""





class ScalpingEngine:

    """Gerencia posições scalp abertas e gera alertas de saída."""



    def __init__(self):

        self.cfg = _scalping_cfg()

        self._open: dict[str, ScalpPosition] = {}

        self._load()



    def _load(self) -> None:

        if not OPEN_POSITIONS.exists():

            return

        try:

            raw = json.loads(OPEN_POSITIONS.read_text(encoding="utf-8"))

            for item in raw.get("positions", []):

                p = ScalpPosition(**item)

                if p.status == "OPEN":

                    self._open[p.position_id] = p

        except (json.JSONDecodeError, TypeError):

            pass



    def _save(self) -> None:

        if not persist_data_locally():

            return

        OPEN_POSITIONS.parent.mkdir(parents=True, exist_ok=True)

        payload = {"updated": datetime.now(BR).isoformat(), "positions": [p.to_dict() for p in self._open.values()]}

        OPEN_POSITIONS.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")



    def open_from_alert(self, alert: LiveAlert) -> ScalpPosition | None:

        plan = build_scalp_plan(alert)

        if not plan:

            return None

        cfg = load_live_config()

        side = plan.side

        ok, _ = check_entry_exposure(
            alert.home, alert.away, alert.market, side,
            load_open_exposures(), cfg,
        )

        if not ok:

            return None

        pid = f"scalp-{uuid.uuid4().hex[:10]}"

        pos = ScalpPosition(

            position_id=pid,

            alert_id=alert.alert_id,

            home=alert.home,

            away=alert.away,

            market=alert.market,

            side=plan.side,

            entry_odd=plan.entry_odd,

            stake_pct=plan.stake_pct,

            exit_side=plan.exit_side,

            target_odd=plan.target_exit_odd,

            stop_odd=plan.stop_exit_odd,

            timeout_sec=plan.timeout_sec,

            entry_ts=datetime.now(BR).isoformat(timespec="seconds"),

            market_id=alert.market_id,

            selection_id=alert.selection_id,

            spread_pct=plan.spread_pct,

        )

        self._open[pid] = pos

        self._save()

        return pos



    def close(self, position_id: str, reason: str) -> None:

        if position_id in self._open:

            self._open[position_id].status = f"CLOSED_{reason}"

            del self._open[position_id]

            self._save()



    @property

    def open_positions(self) -> list[ScalpPosition]:

        return list(self._open.values())



    def reload(self) -> None:

        self._open.clear()

        self._load()



    def clear_all(self) -> int:

        n = len(self._open)

        self._open.clear()

        self._save()

        return n



    def evaluate_exits(self, states: list[LiveMatchState]) -> list[LiveAlert]:

        if not self.cfg.get("enabled", True):

            return []

        by_match = {f"{s.home}|{s.away}": s for s in states}

        exits: list[LiveAlert] = []

        now = datetime.now(BR)



        for pid, pos in list(self._open.items()):

            state = by_match.get(f"{pos.home}|{pos.away}")

            if not state:

                continue

            side_key = {"home_win_ft": "Casa", "draw_ft": "Empate", "away_win_ft": "Visitante"}.get(pos.market, "Casa")

            odds = state.odds.get(side_key, {})

            quote = ExchangeQuote.from_prices(odds.get("back"), odds.get("lay"))

            exit_odd = quote.exit_price(pos.side)

            if not exit_odd:

                continue

            try:

                entry_dt = datetime.fromisoformat(pos.entry_ts)

                if entry_dt.tzinfo is None:

                    entry_dt = entry_dt.replace(tzinfo=BR)

                elapsed = int((now - entry_dt).total_seconds())

            except ValueError:

                elapsed = 0



            hit, reason = should_exit(pos, float(exit_odd), elapsed)

            if not hit:

                continue



            self.close(pid, reason)

            exits.append(

                LiveAlert(

                    alert_id=f"{pos.alert_id}|EXIT_{reason}",

                    alert_type="SCALP_EXIT",

                    severity="high",

                    home=pos.home,

                    away=pos.away,

                    league=state.league,

                    market=pos.market,

                    message=(

                        f"SAÍDA SCALP ({reason}): {pos.side} @ {pos.entry_odd:.2f} → "

                        f"{pos.exit_side} @ {exit_odd:.2f} | {elapsed}s"

                    ),

                    prob_est=0.0,

                    odd_back=odds.get("back"),

                    odd_lay=odds.get("lay"),

                    odd_min=pos.entry_odd,

                    edge_pp=None,

                    stake_pct=pos.stake_pct,

                    stake_valor=0.0,

                    stake_back_pct=pos.stake_pct if pos.exit_side == "BACK" else 0.0,

                    stake_lay_pct=pos.stake_pct if pos.exit_side == "LAY" else 0.0,

                    market_id=pos.market_id,

                    selection_id=pos.selection_id,

                    recommended_side=pos.exit_side,

                    score=state.score_display,

                    in_play=state.in_play,

                )

            )

        return exits


def clear_scalp_positions() -> int:
    return ScalpingEngine().clear_all()
