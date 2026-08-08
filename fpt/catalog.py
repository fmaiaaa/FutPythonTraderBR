"""Catálogo global FPT — todos países/ligas/temporadas."""
from __future__ import annotations

import json
from pathlib import Path

CATALOG_PATH = Path(__file__).parent / "catalog.json"


def load_catalog() -> dict:
    if not CATALOG_PATH.exists():
        raise FileNotFoundError(f"Catálogo não encontrado: {CATALOG_PATH}")
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def iter_bases(catalog: dict | None = None, country: str | None = None):
    catalog = catalog or load_catalog()
    countries = [country] if country else catalog.keys()
    for c in countries:
        if c not in catalog:
            continue
        for slug, meta in catalog[c].items():
            for season in meta["seasons"]:
                yield c, slug, season, meta


def count_bases(catalog: dict | None = None) -> int:
    return sum(1 for _ in iter_bases(catalog))


def brazil_slugs(catalog: dict | None = None) -> list[str]:
    catalog = catalog or load_catalog()
    return list(catalog.get("brazil", {}).keys())
