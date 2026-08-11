"""Raiz de dados e projeto — padrão disco D: (Windows)."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"

_DEFAULT_D_DATA = Path("D:/FutPythonTraderBR/data")
_DEFAULT_D_PROJECT = Path("D:/FutPythonTraderBR/project")


def project_root() -> Path:
    """Diretório do código — preferir cópia em D: se existir."""
    env = os.environ.get("FPT_PROJECT_ROOT", "").strip()
    if env:
        return Path(env)
    if _DEFAULT_D_PROJECT.exists():
        return _DEFAULT_D_PROJECT
    return ROOT


def data_root() -> Path:
    """Diretório de persistência (merged, models, live, ticks, etc.)."""
    env = os.environ.get("FPT_DATA_ROOT", "").strip()
    if env:
        return Path(env)
    if os.name == "nt" and Path("D:/").exists():
        return _DEFAULT_D_DATA
    return project_root() / "data"


def ensure_data_dirs() -> Path:
    root = data_root()
    for sub in (
        "merged",
        "models",
        "models/scalping",
        "models/leagues",
        "live",
        "live_collection",
        "betfair/ticks",
        "sofascore/snapshots",
        "weekend",
        "daily",
        "calendar",
        "raw",
        "leagues",
    ):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root
