"""Upload manual dos PDFs do fim de semana para Google Drive."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fpt.calendar import weekend_window
from fpt.integrations.google_drive import upload_weekend_folder
from fpt.weekend import weekend_report_dir


def main():
    p = argparse.ArgumentParser(description="Upload relatorio fim de semana → Google Drive")
    p.add_argument("--dir", type=str, default="", help="Pasta do relatorio (data/weekend/...)")
    p.add_argument("--date", type=str, default="", help="Sabado ISO YYYY-MM-DD (subpasta Drive)")
    args = p.parse_args()

    if args.dir:
        out_dir = Path(args.dir)
        sat = args.date or out_dir.name
    else:
        start, _ = weekend_window()
        out_dir = weekend_report_dir(start)
        sat = str(start)

    if not out_dir.exists():
        print(f"Pasta nao encontrada: {out_dir}")
        print("Rode: python main.py fim-de-semana")
        sys.exit(1)

    pdfs = list(out_dir.glob("*.pdf"))
    if not pdfs:
        print(f"Nenhum PDF em {out_dir}")
        sys.exit(1)

    manifest = upload_weekend_folder(out_dir, sat)
    uploaded = manifest.get("uploaded", [])
    errors = manifest.get("errors", [])
    print(f"Upload: {len(uploaded)} ok | erros: {errors}")
    for u in uploaded:
        print(f"  - {u.get('name')}: {u.get('web_view_link', '—')}")

    if errors:
        print("ERRO nos arquivos:", errors)
        sys.exit(1)
    if not uploaded:
        print("Nenhum arquivo enviado — verifique GOOGLE_DRIVE_FOLDER_ID e permissao da SA")
        sys.exit(1)


if __name__ == "__main__":
    main()
