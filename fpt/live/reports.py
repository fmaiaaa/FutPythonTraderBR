"""Relatórios PDF do fim de semana — Google Drive (GitHub Actions)."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from ..calendar import weekend_window
from ..client import DATA
from ..integrations.google_drive import list_weekend_drive_reports
from ..storage import persist_data_locally
from ..weekend import weekend_report_dir


def find_weekend_reports(saturday: date | None = None) -> dict:
    """PDFs e links Drive do fim de semana — Drive é a fonte principal."""
    start, end = weekend_window(saturday)
    saturday_iso = str(start)
    result = {
        "start": saturday_iso,
        "end": str(end),
        "report_dir": str(weekend_report_dir(start)),
        "pdfs_local": [],
        "drive_links": [],
        "manifest_path": None,
    }

    drive_pdfs = list_weekend_drive_reports(saturday_iso)
    result["drive_links"] = [
        {
            "name": f.get("name", "PDF"),
            "file_id": f.get("file_id"),
            "web_view_link": f.get("web_view_link"),
        }
        for f in drive_pdfs
    ]

    if persist_data_locally():
        out_dir = weekend_report_dir(start)
        if out_dir.exists():
            result["pdfs_local"] = sorted(
                [
                    {"name": p.name, "path": str(p), "size_kb": round(p.stat().st_size / 1024, 1)}
                    for p in out_dir.glob("*.pdf")
                ],
                key=lambda x: x["name"],
            )
            manifest = out_dir / "drive_links.json"
            if manifest.exists() and not result["drive_links"]:
                result["manifest_path"] = str(manifest)
                data = json.loads(manifest.read_text(encoding="utf-8"))
                result["drive_links"] = [
                    u for u in data.get("uploaded", []) if u.get("name", "").endswith(".pdf")
                ]

    return result
