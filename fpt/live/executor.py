"""Execução de ordens Betfair após aprovação de alerta."""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ..client import DATA
from ..storage import persist_data_locally
from ..integrations.betfair import get_betfair_client
from ..trading.config import load_config as load_trading_config
from .config import load_live_config
from .models import LiveAlert

BR = ZoneInfo("America/Sao_Paulo")
EXEC_LOG = DATA / "live" / "executions.jsonl"


def _execution_cfg() -> dict:
    cfg = load_live_config()
    return cfg.get("execution", {})


def _min_stake_brl() -> float:
    return float(_execution_cfg().get("min_stake_brl", 2.0))


class BetfairExecutor:
    """Coloca ordens LIMIT na Betfair BR (BACK/LAY)."""

    def __init__(self):
        self.client = get_betfair_client()
        self.exec_cfg = _execution_cfg()
        self.bankroll = load_trading_config()["trading"]["bankroll"]

    @property
    def enabled(self) -> bool:
        return bool(self.exec_cfg.get("enabled", False)) and self.client.configured

    @property
    def paper_mode(self) -> bool:
        return bool(self.exec_cfg.get("paper_mode", True))

    def _log(self, payload: dict) -> None:
        if not persist_data_locally():
            return
        EXEC_LOG.parent.mkdir(parents=True, exist_ok=True)
        payload["logged_at"] = datetime.now(BR).isoformat(timespec="seconds")
        with EXEC_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def execute_alert(
        self,
        alert: LiveAlert,
        *,
        side: str = "BACK",
        bankroll: float | None = None,
        approved: bool = True,
    ) -> dict:
        """
        Executa ordem a partir de alerta ENTER/HT_EXIT.
        side: BACK | LAY
        """
        if not approved:
            return {"status": "REJECTED", "message": "Operação não aprovada pelo usuário"}

        if not self.enabled:
            return {"status": "DISABLED", "message": "Execução desabilitada em config/live.yaml"}

        bankroll = bankroll or self.bankroll
        side = side.upper()
        stake_pct = alert.stake_back_pct if side == "BACK" else alert.stake_lay_pct
        price = alert.odd_back if side == "BACK" else alert.odd_lay

        if stake_pct <= 0:
            return {"status": "SKIP", "message": f"Stake {side} = 0%"}
        if not price or price <= 1.01:
            return {"status": "SKIP", "message": f"Odd {side} indisponível"}
        if not alert.market_id:
            return {"status": "ERROR", "message": "market_id ausente"}
        if not alert.selection_id:
            return {"status": "ERROR", "message": "selection_id ausente — reconecte Betfair"}

        stake_amount = max(round(bankroll * stake_pct, 2), _min_stake_brl())
        instruction = self.client.build_limit_instruction(
            selection_id=int(alert.selection_id),
            side=side,
            size=stake_amount,
            price=float(price),
        )
        customer_ref = f"fpt-{uuid.uuid4().hex[:12]}"

        payload = {
            "alert_id": alert.alert_id,
            "home": alert.home,
            "away": alert.away,
            "market": alert.market,
            "side": side,
            "stake_pct": stake_pct,
            "stake_amount": stake_amount,
            "price": price,
            "market_id": alert.market_id,
            "selection_id": alert.selection_id,
            "paper_mode": self.paper_mode,
        }

        if self.paper_mode:
            payload["status"] = "PAPER"
            payload["message"] = f"[PAPER] {side} {stake_amount:.2f} @ {price:.2f}"
            self._log(payload)
            return payload

        try:
            self.client.login()
            result = self.client.place_orders(alert.market_id, [instruction], customer_ref)
            payload["status"] = "PLACED"
            payload["betfair_result"] = result
            ir = (result.get("instructionReports") or [{}])[0]
            payload["bet_id"] = ir.get("betId")
            payload["order_status"] = ir.get("status")
            payload["message"] = f"Ordem {side} enviada: {stake_amount:.2f} @ {price:.2f}"
            self._log(payload)
            return payload
        except Exception as ex:
            payload["status"] = "ERROR"
            payload["message"] = str(ex)
            self._log(payload)
            return payload


def load_recent_executions(limit: int = 20) -> list[dict]:
    if not EXEC_LOG.exists():
        return []
    lines = EXEC_LOG.read_text(encoding="utf-8").splitlines()
    out = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return list(reversed(out))
