"""Finaliza semana: dataset + treino scalping + upload Drive."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fpt.calendar import weekend_window
from fpt.integrations.google_drive import upload_file, upload_live_collection_bundle
from fpt.live.dataset_builder import build_weekly_scalping_dataset, load_collection_ticks
from fpt.models.train_scalping import train_scalping_model
from fpt.weekend import weekend_report_dir


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--upload-drive", action="store_true", help="Envia zip ao Google Drive")
    p.add_argument("--saturday", type=str, default="", help="YYYY-MM-DD pasta histórico Drive")
    args = p.parse_args()

    print("=== Dataset scalping semanal ===")
    df = build_weekly_scalping_dataset(days_back=14)
    print(f"Linhas dataset: {len(df)}")

    print("\n=== Treino modelo scalping ===")
    metrics = train_scalping_model(df if not df.empty else None)
    print(json.dumps(metrics, indent=2))

    if args.upload_drive:
        start, _ = weekend_window()
        sat = args.saturday or str(start)
        info = upload_live_collection_bundle()
        if info:
            print(f"Drive collection: {info.get('web_view_link')}")
            out_dir = weekend_report_dir(sat)
            out_dir.mkdir(parents=True, exist_ok=True)
            manifest = out_dir / "live_collection_drive.json"
            manifest.write_text(json.dumps(info, indent=2), encoding="utf-8")
            upload_file(manifest, history_date=sat)
        meta_path = Path("data/models/scalping/meta.json")
        if meta_path.exists():
            upload_file(meta_path, history_date=sat)

    ticks = load_collection_ticks()
    if ticks.empty:
        print("AVISO: nenhuma coleta live — modelo scalping skip ou fraco")
        return 0 if metrics.get("status") == "skip" else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
