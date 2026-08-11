"""Operação autônoma — um clique, loop completo."""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ..client import DATA
from ..pipeline import load_merged
from ..storage import persist_data_locally
from .collector import LiveDataCollector
from .config import load_live_config
from .executor import BetfairExecutor
from .models import LiveAlert, LiveMatchState
from .monitor import LiveMonitor
from .scalping import ScalpingEngine
from .scalping_strategies import is_scalp_entry
from .entry_exposure import check_entry_exposure, exposure_block_message, load_open_exposures
from .trade_positions import PositionManager

BR = ZoneInfo("America/Sao_Paulo")
ROBOT_LOG = DATA / "live" / "robot_log.jsonl"
EXECUTED_FILE = DATA / "live" / "executed_alerts.json"


@dataclass
class TickResult:
    ts: str
    balance: float
    n_games: int
    n_live: int
    n_entries: int
    n_exits: int
    n_errors: int
    states: list[LiveMatchState] = field(default_factory=list)
    log_lines: list[str] = field(default_factory=list)


class AutonomousOperator:
    """Robô: scan → entradas → saídas → coleta de dados."""

    _instance: "AutonomousOperator | None" = None
    _lock = threading.Lock()

    def __init__(self):
        self.cfg = load_live_config()
        self.auto_cfg = self.cfg.get("autonomous", {})
        self.monitor = LiveMonitor()
        self.executor = BetfairExecutor()
        self.scalper = ScalpingEngine()
        self.positions = PositionManager()
        self.collector = LiveDataCollector.get()
        self._running = False
        self._thread: threading.Thread | None = None
        self._executed: set[str] = set()
        self._last_result: TickResult | None = None
        self._full_states: list[LiveMatchState] = []
        self._last_full_scan_ts: float = 0.0
        self._load_executed()
        if not persist_data_locally():
            os.environ["FPT_PERSIST_LOCAL"] = "1"

    @classmethod
    def get(cls) -> "AutonomousOperator":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @property
    def running(self) -> bool:
        return self._running

    @property
    def last_result(self) -> TickResult | None:
        return self._last_result

    def _load_executed(self) -> None:
        if not EXECUTED_FILE.exists():
            return
        try:
            raw = json.loads(EXECUTED_FILE.read_text(encoding="utf-8"))
            self._executed = set(raw.get("ids", []))
        except json.JSONDecodeError:
            pass

    def _save_executed(self) -> None:
        EXECUTED_FILE.parent.mkdir(parents=True, exist_ok=True)
        EXECUTED_FILE.write_text(
            json.dumps({"updated": datetime.now(BR).isoformat(), "ids": sorted(self._executed)[-500:]}),
            encoding="utf-8",
        )

    def _log(self, line: str) -> None:
        payload = {"ts": datetime.now(BR).isoformat(timespec="seconds"), "msg": line}
        ROBOT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with ROBOT_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def fetch_balance(self, log_errors: bool = True) -> float:
        exec_cfg = self.cfg.get("execution", {})
        if exec_cfg.get("paper_mode", True):
            from .paper_db import get_available_bankroll, init_paper_db

            init_paper_db()
            return get_available_bankroll()

        reserve = float(self.auto_cfg.get("balance_reserve_pct", 0.05))
        if self.auto_cfg.get("use_betfair_balance", True) and self.executor.client.configured:
            try:
                bal = self.executor.client.available_balance()
                return max(0.0, bal * (1.0 - reserve))
            except Exception as ex:
                if log_errors:
                    self._log(f"Saldo Betfair indisponível: {ex}")
        return float(self.cfg.get("live", {}).get("bankroll", 1000.0))

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self.collector.set_robot_collects(True)
        self._log("Robô INICIADO")
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        self.collector.set_robot_collects(False)
        self._log("Robô PARADO")

    def _loop(self) -> None:
        interval = int(self.auto_cfg.get("refresh_seconds", 30))
        while self._running:
            try:
                self._last_result = self.tick()
            except Exception as ex:
                self._log(f"ERRO tick: {ex}")
            time.sleep(interval)

    def tick(self) -> TickResult:
        from .weekly_calendar import active_scalp_slots, ensure_daily_schedule_refresh, ensure_weekly_calendar

        self._apply_pending_reset()
        lines: list[str] = []
        errors = 0
        entries = 0
        exits = 0

        try:
            if ensure_weekly_calendar():
                self._log("Calendário semanal atualizado (domingo→sábado)")
            if ensure_daily_schedule_refresh():
                self._log("Horários do dia seguinte atualizados (23h)")
        except Exception as ex:
            lines.append(f"Calendário: {ex}")

        balance = self.fetch_balance()
        try:
            df = load_merged()
        except FileNotFoundError:
            df = None

        full_iv = int(self.auto_cfg.get("full_scan_interval_seconds", 900))
        now_ts = time.time()
        if now_ts - self._last_full_scan_ts >= full_iv or not self._full_states:
            self._full_states = self.monitor.scan_full(df)
            self._last_full_scan_ts = now_ts
            lines.append(f"Scan completo: {len(self._full_states)} jogos")

        active = active_scalp_slots()
        slot_keys = {s.key for s in active}
        for p in self.scalper.open_positions:
            slot_keys.add(f"{p.home}|{p.away}")

        scalp_states: list[LiveMatchState] = []
        if slot_keys:
            scalp_states = self.monitor.scan_scalp(df, slot_keys=slot_keys)
            lines.append(f"Scan scalp: {len(scalp_states)} jogos na janela")

        merged: dict[str, LiveMatchState] = {f"{s.home}|{s.away}": s for s in self._full_states}
        for s in scalp_states:
            merged[f"{s.home}|{s.away}"] = s
        states = list(merged.values())
        n_live = sum(1 for s in states if s.in_play and s.status not in ("FT", "CLOSED"))

        if self.auto_cfg.get("collect_data", True):
            try:
                n_rows = self.collector.collect_tick(scalp_states or self._full_states)
                if n_rows:
                    lines.append(f"Coleta: {n_rows} linhas")
            except Exception as ex:
                errors += 1
                lines.append(f"Coleta falhou: {ex}")

        scalp_types = tuple(
            t for t in (
                "PRESSURE_STEAM", "SCALP_PRESSURE_STEAM", "SCALP_STEAM_MOMENTUM",
                "SCALP_PRESSURE_SURGE", "SCALP_XG_SPIKE", "SCALP_DOMINANCE", "SCALP_FADE_STEAM",
            )
        )

        for state in self._full_states:
            for alert in state.alerts:
                if alert.alert_type != "ENTER" and alert.alert_type not in ("AUTO_EXIT", "HT_EXIT"):
                    continue
                if alert.alert_type in scalp_types:
                    continue
                entries, exits, errors = self._process_alert(
                    alert, state, balance, lines, entries, exits, errors,
                )

        for state in scalp_states:
            for alert in state.alerts:
                if alert.alert_type != "ENTER" and alert.alert_type not in scalp_types + ("SCALP_EXIT", "HT_EXIT", "AUTO_EXIT"):
                    continue
                if alert.alert_type == "ENTER":
                    continue
                entries, exits, errors = self._process_alert(
                    alert, state, balance, lines, entries, exits, errors,
                )

        exit_pairs = self.positions.evaluate_exits(states)
        for pos, alert in exit_pairs:
            if alert.alert_id in self._executed:
                continue
            side = alert.recommended_side
            res = self.executor.execute_alert(
                alert, side=side, bankroll=balance, approved=True, stake_amount=pos.stake_amount,
            )
            if res.get("status") in ("PLACED", "PAPER"):
                self._executed.add(alert.alert_id)
                self._save_executed()
                self.positions.close(pos.position_id, "AUTO")
                exits += 1
                lines.append(f"AUTO_EXIT {pos.home} x {pos.away}: {res.get('message')}")
                if res.get("status") == "PAPER":
                    self._settle_paper_exit(pos, alert, res)

        for line in lines:
            self._log(line)

        self._record_minute_timeline(states)

        return TickResult(
            ts=datetime.now(BR).isoformat(timespec="seconds"),
            balance=balance,
            n_games=len(states),
            n_live=n_live,
            n_entries=entries,
            n_exits=exits,
            n_errors=errors,
            states=states,
            log_lines=lines,
        )

    def _record_minute_timeline(self, states: list[LiveMatchState]) -> None:
        from .minute_store import record_bankroll_minute, record_match_minutes_from_states

        try:
            record_match_minutes_from_states(states)
            if self.executor.paper_mode:
                n_pos = len(self.positions.open_positions) + len(self.scalper.open_positions)
                record_bankroll_minute(n_positions=n_pos)
        except Exception as ex:
            self._log(f"Aviso timeline minuto: {ex}")

    def _process_alert(
        self,
        alert: LiveAlert,
        state: LiveMatchState,
        balance: float,
        lines: list[str],
        entries: int,
        exits: int,
        errors: int,
    ) -> tuple[int, int, int]:
        if alert.alert_id in self._executed:
            return entries, exits, errors
        if not self._should_execute(alert):
            return entries, exits, errors
        if not alert.market_id and not self.executor.paper_mode:
            return entries, exits, errors
        if not alert.selection_id and alert.alert_type == "ENTER" and not self.executor.paper_mode:
            return entries, exits, errors

        side = alert.recommended_side or ("LAY" if alert.alert_type in ("HT_EXIT", "AUTO_EXIT", "SCALP_EXIT") else "BACK")
        if alert.alert_type == "ENTER" or is_scalp_entry(alert.alert_type):
            exp_ok, exp_reason = check_entry_exposure(
                alert.home, alert.away, alert.market, side,
                load_open_exposures(), self.cfg,
            )
            if not exp_ok:
                self._log(
                    f"SKIP {alert.home} x {alert.away} {alert.market} {side}: "
                    f"{exposure_block_message(exp_reason)}"
                )
                return entries, exits, errors
        res = self.executor.execute_alert(alert, side=side, bankroll=balance, approved=True)
        status = res.get("status", "ERR")
        if status in ("PLACED", "PAPER"):
            self._executed.add(alert.alert_id)
            self._save_executed()
            msg = res.get("message", status)
            lines.append(f"{alert.alert_type} {alert.home} x {alert.away}: {msg}")

            if alert.alert_type == "ENTER":
                entries += 1
                pos = self.positions.register_entry(
                    alert,
                    side=side,
                    stake_amount=float(res.get("stake_amount", 0)),
                    entry_type="pre_live",
                    bet_id=res.get("bet_id"),
                )
                if status == "PAPER":
                    self._record_paper_entry(pos, alert, res, side)
            elif is_scalp_entry(alert.alert_type):
                entries += 1
                self.scalper.open_from_alert(alert)
                pos = self.positions.register_entry(
                    alert,
                    side=side,
                    stake_amount=float(res.get("stake_amount", 0)),
                    entry_type="scalp",
                    bet_id=res.get("bet_id"),
                )
                if status == "PAPER":
                    self._record_paper_entry(pos, alert, res, side)
            else:
                exits += 1
                if status == "PAPER":
                    self._settle_paper_exit_by_alert(alert, side, res)
        elif status not in ("SKIP", "DISABLED"):
            errors += 1
            lines.append(f"Falha {alert.alert_type}: {res.get('message')}")
        return entries, exits, errors

    def _apply_pending_reset(self) -> None:
        from .operation_control import consume_pending_reset

        action = consume_pending_reset()
        if not action:
            return
        self._executed.clear()
        self._save_executed()
        self.positions.reload()
        self.scalper.reload()
        if action == "bankroll":
            self._log("Reset de saldo inicial aplicado — banca e entradas zeradas")
        else:
            self._log("Reset de entradas aplicado — posições fechadas, aguardando novas oportunidades")

    def _should_execute(self, alert: LiveAlert) -> bool:
        exec_cfg = self.cfg.get("execution", {})
        scalp_cfg = self.cfg.get("scalping", {})
        if alert.alert_type == "ENTER":
            return bool(exec_cfg.get("auto_execute", False))
        if is_scalp_entry(alert.alert_type):
            return bool(scalp_cfg.get("auto_execute_scalp", False))
        if alert.alert_type in ("HT_EXIT", "SCALP_EXIT", "AUTO_EXIT"):
            return bool(self.auto_cfg.get("auto_exit", True))
        return False

    def _record_paper_entry(self, pos, alert: LiveAlert, res: dict, side: str) -> None:
        from .paper_db import record_paper_entry

        rec = record_paper_entry(
            position_id=pos.position_id,
            alert_id=alert.alert_id,
            home=alert.home,
            away=alert.away,
            market=alert.market,
            alert_type=alert.alert_type,
            side=side,
            stake_amount=float(res.get("stake_amount", 0)),
            stake_pct=float(res.get("stake_pct", 0)),
            entry_odd=float(res.get("price", pos.entry_odd)),
        )
        if not rec.get("ok"):
            self._log(f"PAPER entry não registrada: {rec.get('error')}")

    def _settle_paper_exit(self, pos, alert: LiveAlert, res: dict) -> None:
        from .paper_db import settle_paper_exit

        price = float(res.get("price") or 0)
        if price <= 1.01:
            return
        side = (alert.recommended_side or res.get("side") or "LAY").upper()
        settled = settle_paper_exit(
            position_id=pos.position_id,
            exit_side=side,
            exit_odd=price,
            alert_type=alert.alert_type,
        )
        if settled:
            self._log(
                f"PAPER P&L {pos.home} x {pos.away}: R$ {settled['pnl']:+.2f} "
                f"| banca R$ {settled['bankroll']:.2f}"
            )

    def _settle_paper_exit_by_alert(self, alert: LiveAlert, side: str, res: dict) -> None:
        """Fecha trade paper quando saída não veio do PositionManager."""
        from .paper_db import list_paper_trades, settle_paper_exit

        price = float(res.get("price") or 0)
        if price <= 1.01:
            return
        for t in list_paper_trades(open_only=True):
            if t["home"] == alert.home and t["away"] == alert.away and t["market"] == alert.market:
                settled = settle_paper_exit(
                    position_id=t["position_id"],
                    exit_side=side,
                    exit_odd=price,
                    alert_type=alert.alert_type,
                )
                if settled:
                    self._log(
                        f"PAPER P&L {alert.home} x {alert.away}: R$ {settled['pnl']:+.2f} "
                        f"| banca R$ {settled['bankroll']:.2f}"
                    )
                break


def run_betfair_operator_forever(operator: AutonomousOperator | None = None) -> None:
    """Loop 24/7 headless — processo CMD separado."""
    import os
    import signal

    from .process_status import write_operator_status

    op = operator or AutonomousOperator()
    op.auto_cfg = op.cfg.get("autonomous", {})
    op._running = True
    op._log("Operação Betfair INICIADA (headless 24/7)")
    write_operator_status(None, running=True, pid=os.getpid())

    def _stop(signum, _frame):
        op._log(f"Sinal {signum} — parando operação")
        op._running = False

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    interval = int(op.auto_cfg.get("refresh_seconds", 30))
    try:
        while op._running:
            err: str | None = None
            try:
                write_operator_status(
                    op._last_result,
                    running=True,
                    pid=os.getpid(),
                    phase="scanning",
                )
                op._last_result = op.tick()
                write_operator_status(op._last_result, running=True, pid=os.getpid())
            except Exception as ex:
                err = str(ex)
                op._log(f"ERRO tick: {ex}")
                write_operator_status(op._last_result, running=True, pid=os.getpid(), error=err)
            time.sleep(interval)
    finally:
        op._running = False
        write_operator_status(op._last_result, running=False, pid=os.getpid())
        op._log("Operação Betfair PARADA (headless)")


def load_robot_log(limit: int = 50) -> list[dict]:
    if not ROBOT_LOG.exists():
        return []
    lines = ROBOT_LOG.read_text(encoding="utf-8").splitlines()
    out = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return list(reversed(out))
