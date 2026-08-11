"""Baixa modelos do Drive se existirem (CI)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fpt.integrations.google_drive import MODELS_ZIP_NAME, download_drive_zip, find_drive_asset


def main() -> int:
    asset = find_drive_asset(MODELS_ZIP_NAME)
    if not asset:
        print("Modelos no Drive nao encontrados")
        return 1
    ok = download_drive_zip(asset["file_id"], ROOT / "data" / "models")
    print("OK" if ok else "Falha no download")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
