"""Operação Betfair 24/7 — processo CMD separado do dashboard."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fpt.live.autonomous import AutonomousOperator, run_betfair_operator_forever  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="Robô Betfair 24/7 (entradas + saídas automáticas)")
    p.add_argument("--paper", action="store_true", help="Força paper_mode (simulação)")
    args = p.parse_args()

    print("=" * 50)
    print(" FPT — Operação Betfair (24/7)")
    print(" Campeonatos: perfil robust (14 ligas tier 1)")
    print(" Ctrl+C para parar com segurança")
    print("=" * 50)

    op = AutonomousOperator()
    if args.paper:
        op.cfg.setdefault("execution", {})["paper_mode"] = True

    exec_cfg = op.cfg.get("execution", {})
    if exec_cfg.get("paper_mode", True):
        from fpt.live.paper_db import init_paper_db

        paper = init_paper_db()
        print(f" Modo: PAPER | Banca inicial R$ {paper['initial_bankroll']:.2f}")
        print(f" Teto stake: {paper['max_stake_pct']:.1%}")
    else:
        mode = "REAL"
        print(f" Modo execução: {mode}")

    print(f" Coleta de dados: {'sim' if op.auto_cfg.get('collect_data') else 'não (processo separado)'}")

    run_betfair_operator_forever(op)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
