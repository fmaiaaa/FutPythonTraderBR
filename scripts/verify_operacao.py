#!/usr/bin/env python
"""Verificação rápida antes/depois de iniciar a operação FPT."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("FPT_PERSIST_LOCAL", "1")
os.environ.setdefault("FPT_DATA_ROOT", r"D:\FutPythonTraderBR\data")

FAIL = 0


def ok(msg: str) -> None:
    print(f"  [OK] {msg}")


def bad(msg: str) -> None:
    global FAIL
    FAIL += 1
    print(f"  [ERRO] {msg}")


def warn(msg: str) -> None:
    print(f"  [AVISO] {msg}")


def main() -> int:
    data = Path(os.environ["FPT_DATA_ROOT"])
    print("=" * 50)
    print(" FPT — Verificação operacional")
    print("=" * 50)
    print(f" Repo:  {ROOT}")
    print(f" Dados: {data}")
    print()

    print("1. Dependências Python")
    for pkg in ("pandas", "streamlit", "yaml", "sklearn", "curl_cffi"):
        try:
            __import__(pkg if pkg != "yaml" else "yaml")
            ok(pkg)
        except ImportError:
            bad(f"{pkg} não instalado — rode: pip install -r requirements.txt")

    print("\n2. Módulos FPT")
    try:
        import dashboard_app  # noqa: F401
        ok("dashboard_app")
    except Exception as ex:
        bad(f"dashboard_app: {ex}")

    try:
        from fpt.live.display_labels import operation_type_label, summarize_game_entries
        assert operation_type_label("ENTER") == "Pré-live"
        ok("display_labels (operation_type_label)")
    except Exception as ex:
        bad(f"display_labels: {ex}")

    for mod in ("fpt.live.entry_exposure", "fpt.live.scalping_gates", "fpt.live.autonomous"):
        try:
            __import__(mod)
            ok(mod)
        except Exception as ex:
            bad(f"{mod}: {ex}")

    print("\n3. Pastas de dados")
    for sub in ("live", "daily", "merged", "live_collection"):
        p = data / sub
        if p.exists():
            ok(str(p))
        else:
            warn(f"{p} não existe (será criada na 1ª execução)")

    print("\n4. Snapshot e calendário")
    try:
        from fpt.live.monitor import load_latest_snapshot, merge_calendar_states
        from fpt.live.process_status import snapshot_meta, read_operator_status

        snap = load_latest_snapshot()
        merged = merge_calendar_states(snap)
        meta = snapshot_meta()
        op = read_operator_status()
        if merged:
            ok(f"{len(merged)} jogos no calendário merge")
        else:
            warn("0 jogos — aguarde 1º ciclo da operação (~15 min)")
        if meta.get("exists"):
            ok(f"snapshot: {meta.get('n_matches', '?')} jogos em disco")
        else:
            warn("sem snapshot — inicie a operação")
        ok(f"operador: phase={op.get('phase', '?')}")
    except Exception as ex:
        bad(f"snapshot/calendário: {ex}")

    print("\n5. Configuração")
    cfg_path = ROOT / "config" / "live.yaml"
    if cfg_path.exists():
        ok("config/live.yaml")
    else:
        bad("config/live.yaml ausente")

    prof = data / "live" / "runtime_profile.json"
    if prof.exists():
        ok(f"perfil: {prof.name}")
    else:
        warn("perfil não definido — escolha 1 ou 2 ao iniciar")

    print()
    if FAIL:
        print(f"RESULTADO: {FAIL} erro(s) — corrija antes de operar.")
        return 1
    print("RESULTADO: tudo OK — pode iniciar FPT - Operacao Completa.bat")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
