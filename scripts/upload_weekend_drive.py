"""Upload manual dos PDFs do fim de semana para Google Drive."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fpt.calendar import weekend_window
from fpt.integrations.google_drive import upload_weekend_folder
from fpt.weekend import weekend_report_dir


def main():
    start, _ = weekend_window()
    out_dir = weekend_report_dir(start)
    if not out_dir.exists():
        print(f"Pasta nao encontrada: {out_dir}")
        print("Rode: python main.py fim-de-semana")
        sys.exit(1)
    manifest = upload_weekend_folder(out_dir, str(start))
    n = len(manifest.get("uploaded", []))
    err = manifest.get("errors", [])
    print(f"Upload: {n} ok | erros: {err}")
    if not n:
        sys.exit(1)


if __name__ == "__main__":
    main()
