"""Relatórios PDF do fim de semana — local + Google Drive."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from ..calendar import weekend_window
from ..client import DATA
from ..weekend import weekend_report_dir


def find_weekend_reports(saturday: date | None = None) -> dict:
    """Lista PDFs locais e links Drive do fim de semana atual."""
    start, end = weekend_window(saturday)
    out_dir = weekend_report_dir(start)
    result = {
        "start": str(start),
        "end": str(end),
        "report_dir": str(out_dir),
        "pdfs_local": [],
        "drive_links": [],
        "manifest_path": None,
    }

    if out_dir.exists():
        result["pdfs_local"] = sorted(
            [{"name": p.name, "path": str(p), "size_kb": round(p.stat().st_size / 1024, 1)}
             for p in out_dir.glob("*.pdf")],
            key=lambda x: x["name"],
        )
        manifest = out_dir / "drive_links.json"
        if manifest.exists():
            result["manifest_path"] = str(manifest)
            data = json.loads(manifest.read_text(encoding="utf-8"))
            result["drive_links"] = [
                u for u in data.get("uploaded", [])
                if u.get("name", "").endswith(".pdf")
            ]

    # fallback: pasta legada data/weekend/*.pdf
    legacy = sorted(DATA / "weekend").glob("*.pdf") if (DATA / "weekend").exists() else []
    for p in legacy:
        if not any(x["name"] == p.name for x in result["pdfs_local"]):
            result["pdfs_local"].append({
                "name": p.name, "path": str(p),
                "size_kb": round(p.stat().st_size / 1024, 1),
            })

    return result
