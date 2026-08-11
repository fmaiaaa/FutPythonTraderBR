from __future__ import annotations

"""Treina classificador de scalping sobre coletas semanais."""

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import yaml
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import accuracy_score, roc_auc_score

from ..client import DATA
from ..live.dataset_builder import build_scalping_features, load_collection_ticks, save_weekly_dataset

ROOT = Path(__file__).resolve().parents[2]
SCALPING_CFG = ROOT / "config" / "scalping_model.yaml"
MODEL_DIR = DATA / "models" / "scalping"


def _cfg() -> dict:
    if not SCALPING_CFG.exists():
        return {}
    return yaml.safe_load(SCALPING_CFG.read_text(encoding="utf-8")) or {}


def train_scalping_model(df: pd.DataFrame | None = None) -> dict:
    cfg = _cfg().get("scalping_model", {})
    min_ticks = int(cfg.get("min_ticks", 200))
    target = cfg.get("target", "target_profitable_30s")
    feature_names = list(cfg.get("features", []))
    test_frac = float(cfg.get("test_fraction", 0.25))
    clf_cfg = cfg.get("classifier", {})

    if df is None:
        raw = load_collection_ticks()
        if raw.empty:
            return {"status": "skip", "reason": "sem_coleta_live"}
        df = build_scalping_features(raw)
        save_weekly_dataset(df)

    if df.empty or len(df) < min_ticks:
        return {
            "status": "skip",
            "reason": "ticks_insuficientes",
            "rows": len(df),
            "min_ticks": min_ticks,
        }

    if target not in df.columns:
        return {"status": "skip", "reason": f"target_ausente:{target}"}

    usable = [f for f in feature_names if f in df.columns]
    if len(usable) < 5:
        return {"status": "skip", "reason": "features_insuficientes", "usable": usable}

    work = df.dropna(subset=usable + [target]).copy()
    if len(work) < min_ticks:
        return {"status": "skip", "reason": "rows_apos_dropna", "rows": len(work)}

    work = work.sort_values("timestamp")
    split = int(len(work) * (1 - test_frac))
    train_df = work.iloc[:split]
    test_df = work.iloc[split:]

    X_train = train_df[usable].astype(float)
    y_train = train_df[target].astype(int)
    X_test = test_df[usable].astype(float)
    y_test = test_df[target].astype(int)

    model = HistGradientBoostingClassifier(
        max_iter=int(clf_cfg.get("max_iter", 200)),
        learning_rate=float(clf_cfg.get("learning_rate", 0.05)),
        max_depth=int(clf_cfg.get("max_depth", 5)),
        min_samples_leaf=int(clf_cfg.get("min_samples_leaf", 20)),
        random_state=42,
    )
    model.fit(X_train, y_train)

    proba = model.predict_proba(X_test)[:, 1] if len(X_test) else np.array([])
    pred = model.predict(X_test) if len(X_test) else np.array([])
    metrics = {
        "status": "ok",
        "n_train": len(train_df),
        "n_test": len(test_df),
        "features": usable,
        "target": target,
        "accuracy": round(float(accuracy_score(y_test, pred)), 4) if len(pred) else None,
        "auc": round(float(roc_auc_score(y_test, proba)), 4) if len(proba) and len(set(y_test)) > 1 else None,
        "positive_rate_train": round(float(y_train.mean()), 4),
        "positive_rate_test": round(float(y_test.mean()), 4) if len(y_test) else None,
    }

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, MODEL_DIR / "scalping_classifier.joblib")
    joblib.dump(usable, MODEL_DIR / "scalping_features.joblib")
    (MODEL_DIR / "meta.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(f"Scalping model: {metrics}")
    return metrics
