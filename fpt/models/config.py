"""Configuração dos modelos ML."""
from __future__ import annotations

from pathlib import Path

import yaml

from ..client import ROOT

_DEFAULT: dict = {
    "split": {"train_fraction": 0.70, "test_fraction": 0.30},
    "feature_selection": {"enabled": True, "max_features": 150, "threshold": "median"},
    "ensemble": {
        "voting": "soft",
        "weights": [1, 1, 1],
        "random_forest": {"n_estimators": 200, "max_depth": 8, "min_samples_leaf": 20},
        "hist_gbm": {"max_iter": 250, "learning_rate": 0.05, "max_depth": 5, "l2_regularization": 2.0},
        "gbm": {"n_estimators": 200, "learning_rate": 0.05, "max_depth": 4, "subsample": 0.8},
    },
    "calibration": {"method": "isotonic", "cv_folds": 3},
    "evaluation": {
        "bankroll": 1000.0,
        "fixed_stakes_pct": [0.002, 0.005, 0.01, 0.02, 0.05, 0.10],
        "min_history": 100,
    },
    "prediction": {"shrinkage_to_market": 0.40},
}


def load_model_config() -> dict:
    path = ROOT / "config" / "models.yaml"
    if not path.exists():
        return _DEFAULT.copy()
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    merged = _DEFAULT.copy()
    for k, v in cfg.items():
        if isinstance(v, dict) and isinstance(merged.get(k), dict):
            merged[k] = {**merged[k], **v}
        else:
            merged[k] = v
    return merged
