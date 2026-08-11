"""Pulse cloud 24h — um scan live + upload Drive (GitHub Actions / cron)."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("FPT_PERSIST_LOCAL", "1")
os.environ.setdefault("FPT_PROFILE", "robust")


def main() -> int:
    p = argparse.ArgumentParser(description="Scan live + publica snapshot no Drive")
    p.add_argument("--no-upload", action="store_true", help="Só scan local, sem Drive")
    p.add_argument("--profile", default="robust", choices=("robust", "watchlist", "all_leagues"))
    args = p.parse_args()

    os.environ["FPT_PROFILE"] = args.profile

    from fpt.live.cloud_pulse import run_cloud_pulse

    try:
        pulse = run_cloud_pulse(upload_drive=not args.no_upload)
    except RuntimeError as ex:
        print(f"ERRO: {ex}")
        return 1

    print(pulse)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
