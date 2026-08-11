"""Modelos hierárquicos — global + específico por liga (blend)."""
from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV

from ..client import DATA
from ..features.builder import FeatureBuilder
from .config import load_model_config
from .ensemble import build_ensemble_pipeline, selected_feature_names
from .train import _metrics_binary, _metrics_multiclass, _temporal_split, train_models

MODEL_DIR = DATA / "models"
LEAGUES_DIR = MODEL_DIR / "leagues"
INDEX_FILE = LEAGUES_DIR / "index.json"


def _league_slug_safe(slug: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in slug)[:80]


def blend_weight(league_slug: str | None, n_samples: int, cfg: dict) -> float:
    hier = cfg.get("hierarchical", {})
    if not league_slug:
        return 0.0
    min_n = int(hier.get("min_samples_per_league", 500))
    if n_samples < min_n:
        return 0.0
    base = float(hier.get("league_blend_weight", 0.55))
    # Mais amostras → mais peso no modelo da liga
    scale = min(1.0, (n_samples - min_n) / max(min_n * 2, 1))
    return base * scale


def train_league_model(
    df: pd.DataFrame,
    league_slug: str,
    *,
    min_history: int,
    cfg: dict,
) -> dict | None:
    sub = df[df["League_Slug"].astype(str) == league_slug].copy()
    if len(sub) < int(cfg.get("hierarchical", {}).get("min_samples_per_league", 500)):
        return None

    fb = FeatureBuilder(sub)
    X, y_out, y_ht = fb.build_training_matrix(min_history=min_history)
    if len(X) < 200:
        return None

    feature_names = list(X.columns)
    pipe_out = build_ensemble_pipeline(multiclass=True, cfg=cfg)
    pipe_out.fit(X, y_out)
    cal_out = CalibratedClassifierCV(pipe_out, method=cfg["calibration"]["method"], cv=2)
    cal_out.fit(X, y_out)

    ht_mask = y_ht.notna()
    cal_ht = None
    if ht_mask.sum() >= 100 and y_ht[ht_mask].nunique() >= 2:
        X_ht, y_ht_c = X[ht_mask], y_ht[ht_mask].astype(int)
        pipe_ht = build_ensemble_pipeline(multiclass=False, cfg=cfg)
        pipe_ht.fit(X_ht, y_ht_c)
        cal_ht = CalibratedClassifierCV(pipe_ht, method=cfg["calibration"]["method"], cv=2)
        cal_ht.fit(X_ht, y_ht_c)

    out_dir = LEAGUES_DIR / _league_slug_safe(league_slug)
    out_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(cal_out, out_dir / "model_outcome.joblib")
    if cal_ht is not None:
        joblib.dump(cal_ht, out_dir / "model_ht_trade.joblib")
    joblib.dump(feature_names, out_dir / "feature_names.joblib")

    split = _temporal_split(len(X), cfg["split"]["train_fraction"])
    proba_test = cal_out.predict_proba(X.iloc[split:])
    metrics = _metrics_multiclass(y_out.iloc[split:].values, proba_test) if split < len(X) else {}

    meta = {
        "league_slug": league_slug,
        "n_samples": len(X),
        "n_features": len(feature_names),
        "metrics_holdout": metrics,
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def train_hierarchical_models(df: pd.DataFrame, min_history: int | None = None) -> dict:
    cfg = load_model_config()
    hier = cfg.get("hierarchical", {})
    if not hier.get("enabled", True):
        return {"global": train_models(df, min_history=min_history), "leagues": {}}

    print("=== Modelo GLOBAL (padrões gerais do futebol) ===")
    global_meta = train_models(df, min_history=min_history)

    league_metas: dict[str, dict] = {}
    if "League_Slug" not in df.columns:
        return {"global": global_meta, "leagues": league_metas}

    min_history = min_history or cfg["evaluation"]["min_history"]
    min_samples = int(hier.get("min_samples_per_league", 500))
    max_leagues = int(hier.get("max_leagues", 40))
    counts = df["League_Slug"].value_counts()
    slugs = [s for s, n in counts.items() if n >= min_samples][:max_leagues]

    print(f"=== Modelos por LIGA ({len(slugs)} com >={min_samples} jogos) ===")
    LEAGUES_DIR.mkdir(parents=True, exist_ok=True)
    for slug in slugs:
        slug = str(slug)
        print(f"  Treinando: {slug} ({counts[slug]} jogos)...")
        meta = train_league_model(df, slug, min_history=min_history, cfg=cfg)
        if meta:
            league_metas[slug] = meta

    index = {
        "leagues": {
            slug: {"n_samples": m["n_samples"], "path": str(LEAGUES_DIR / _league_slug_safe(slug))}
            for slug, m in league_metas.items()
        },
        "blend_weight_default": hier.get("league_blend_weight", 0.55),
    }
    INDEX_FILE.write_text(json.dumps(index, indent=2), encoding="utf-8")
    print(f"Índice hierárquico: {INDEX_FILE} ({len(league_metas)} ligas)")
    return {"global": global_meta, "leagues": league_metas}


def load_league_models(league_slug: str | None) -> tuple[object | None, object | None, list[str]]:
    if not league_slug:
        return None, None, []
    path = LEAGUES_DIR / _league_slug_safe(league_slug)
    if not path.exists():
        return None, None, []
    try:
        out = joblib.load(path / "model_outcome.joblib")
        ht = joblib.load(path / "model_ht_trade.joblib")
        feats = joblib.load(path / "feature_names.joblib")
        return out, ht, feats
    except FileNotFoundError:
        try:
            out = joblib.load(path / "model_outcome.joblib")
            feats = joblib.load(path / "feature_names.joblib")
            return out, None, feats
        except FileNotFoundError:
            return None, None, []


def blend_probs(
    global_p: tuple[float, float, float],
    league_p: tuple[float, float, float],
    weight: float,
) -> tuple[float, float, float]:
    w = max(0.0, min(1.0, weight))
    out = [(1 - w) * g + w * l for g, l in zip(global_p, league_p)]
    s = sum(out)
    if s <= 0:
        return global_p
    return out[0] / s, out[1] / s, out[2] / s


def league_n_samples(league_slug: str | None) -> int:
    if not INDEX_FILE.exists() or not league_slug:
        return 0
    try:
        idx = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
        ent = idx.get("leagues", {}).get(league_slug, {})
        return int(ent.get("n_samples", 0))
    except (json.JSONDecodeError, TypeError):
        return 0
