"""Posições gerenciadas — saídas automáticas pré-live e in-play."""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from ..client import DATA
from ..storage import persist_data_locally
from .config import load_live_config
from .models import LiveAlert, LiveMatchState

BR = ZoneInfo("America/Sao_Paulo")
POSITIONS_FILE = DATA / "live" / "managed_positions.json"

SIDE_KEY = {"home_win_ft": "home", "draw_ft": "draw", "away_win_ft": "away"}
MARKET_LABELS = {
    "home_win_ft": "Mandante",
    "draw_ft": "Empate",
    "away_win_ft": "Visitante",
}


@dataclass
class ManagedPosition:
    position_id: str
    home: str
    away: str
    league: str
    market: str
    side: str  # BACK | LAY
    entry_type: str  # pre_live | scalp
    entry_score_home: int
    entry_score_away: int
    market_id: str | None
    selection_id: int | None
    stake_amount: float
    entry_odd: float
    entry_ts: str
    bet_id: str | None = None
    max_goals_before_exit: int | None = None
    status: str = "OPEN"

    @property
    def entry_total_goals(self) -> int:
        return self.entry_score_home + self.entry_score_away

    def to_dict(self) -> dict:
        return asdict(self)


def _exit_rules() -> dict:
    return load_live_config().get("autonomous", {}).get("exit_rules", {})


class PositionManager:
    """Rastreia entradas e gera alertas de saída automática."""

    def __init__(self):
        self._open: dict[str, ManagedPosition] = {}
        self._load()

    def _load(self) -> None:
        if not POSITIONS_FILE.exists():
            return
        try:
            raw = json.loads(POSITIONS_FILE.read_text(encoding="utf-8"))
            for item in raw.get("positions", []):
                p = ManagedPosition(**item)
                if p.status == "OPEN":
                    self._open[p.position_id] = p
        except (json.JSONDecodeError, TypeError):
            pass

    def _save(self) -> None:
        if not persist_data_locally():
            return
        POSITIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "updated": datetime.now(BR).isoformat(timespec="seconds"),
            "positions": [p.to_dict() for p in self._open.values()],
        }
        POSITIONS_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def register_entry(
        self,
        alert: LiveAlert,
        *,
        side: str,
        stake_amount: float,
        entry_type: str = "pre_live",
        bet_id: str | None = None,
    ) -> ManagedPosition:
        sh, sa = _parse_score(alert.score)
        rules = _exit_rules()
        max_goals = rules.get("max_goals_before_exit")
        pid = f"pos-{uuid.uuid4().hex[:10]}"
        pos = ManagedPosition(
            position_id=pid,
            home=alert.home,
            away=alert.away,
            league=alert.league,
            market=alert.market,
            side=side.upper(),
            entry_type=entry_type,
            entry_score_home=sh,
            entry_score_away=sa,
            market_id=alert.market_id,
            selection_id=alert.selection_id,
            stake_amount=stake_amount,
            entry_odd=float(alert.odd_back if side.upper() == "BACK" else (alert.odd_lay or alert.odd_back or 0)),
            entry_ts=datetime.now(BR).isoformat(timespec="seconds"),
            bet_id=bet_id,
            max_goals_before_exit=int(max_goals) if max_goals is not None else None,
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
    def open_positions(self) -> list[ManagedPosition]:
        return list(self._open.values())

    def evaluate_exits(self, states: list[LiveMatchState]) -> list[tuple[ManagedPosition, LiveAlert]]:
        rules = _exit_rules()
        by_match = {f"{s.home}|{s.away}": s for s in states}
        out: list[tuple[ManagedPosition, LiveAlert]] = []

        for pid, pos in list(self._open.items()):
            if pos.entry_type == "scalp":
                continue
            state = by_match.get(f"{pos.home}|{pos.away}")
            if not state:
                continue

            sh = state.score_home if state.score_home is not None else 0
            sa = state.score_away if state.score_away is not None else 0
            total = sh + sa
            elapsed = state.elapsed_min or 0
            reason = _should_exit(pos, sh, sa, total, elapsed, state.in_play, rules)
            if not reason:
                continue

            alert = _build_exit_alert(pos, state, reason)
            if alert:
                out.append((pos, alert))
        return out

    def apply_exits(self, pairs: list[tuple[ManagedPosition, LiveAlert]]) -> None:
        for pos, _ in pairs:
            self.close(pos.position_id, "AUTO")

    def reload(self) -> None:
        self._open.clear()
        self._load()

    def clear_all(self) -> int:
        n = len(self._open)
        self._open.clear()
        self._save()
        return n


def clear_managed_positions() -> int:
    return PositionManager().clear_all()


def _parse_score(score: str) -> tuple[int, int]:
    if not score or score == "—":
        return 0, 0
    try:
        parts = score.replace(" ", "").split("-")
        return int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        return 0, 0


def _should_exit(
    pos: ManagedPosition,
    sh: int,
    sa: int,
    total: int,
    elapsed: int,
    in_play: bool,
    rules: dict,
) -> str | None:
    if not in_play:
        return None

    if rules.get("exit_at_ht", True) and elapsed >= 45:
        return "HT"

    if pos.max_goals_before_exit is not None and total >= pos.max_goals_before_exit:
        if total > pos.entry_total_goals:
            return "GOALS_LIMIT"

    if rules.get("lay_exit_on_team_goal", True) and pos.side == "LAY":
        if pos.market == "home_win_ft" and sh > pos.entry_score_home:
            return "GOAL_LAY_HOME"
        if pos.market == "away_win_ft" and sa > pos.entry_score_away:
            return "GOAL_LAY_AWAY"

    if rules.get("back_draw_exit_on_goal", True) and pos.side == "BACK" and pos.market == "draw_ft":
        if sh != sa and total > pos.entry_total_goals:
            return "DRAW_BROKEN"

    if rules.get("exit_on_any_goal", False) and total > pos.entry_total_goals:
        return "ANY_GOAL"

    return None


def _build_exit_alert(pos: ManagedPosition, state: LiveMatchState, reason: str) -> LiveAlert | None:
    side_key = SIDE_KEY.get(pos.market, "home")
    label = {"home": "Casa", "draw": "Empate", "away": "Visitante"}.get(side_key, "Casa")
    odds = state.odds.get(label, {})
    exit_side = "LAY" if pos.side == "BACK" else "BACK"
    price = odds.get("lay") if exit_side == "LAY" else odds.get("back")
    if not price:
        return None

    return LiveAlert(
        alert_id=f"{pos.position_id}|EXIT_{reason}",
        alert_type="AUTO_EXIT",
        severity="high",
        home=pos.home,
        away=pos.away,
        league=state.league,
        market=pos.market,
        message=(
            f"SAÍDA AUTO ({reason}): fechar {pos.side} @ {pos.entry_odd:.2f} "
            f"→ {exit_side} @ {price:.2f} | {state.score_display}"
        ),
        prob_est=0.0,
        odd_back=odds.get("back"),
        odd_lay=odds.get("lay"),
        odd_min=pos.entry_odd,
        edge_pp=None,
        stake_pct=0.0,
        stake_valor=pos.stake_amount,
        stake_back_pct=1.0 if exit_side == "BACK" else 0.0,
        stake_lay_pct=1.0 if exit_side == "LAY" else 0.0,
        market_id=pos.market_id,
        selection_id=pos.selection_id,
        recommended_side=exit_side,
        score=state.score_display,
        in_play=state.in_play,
    )
