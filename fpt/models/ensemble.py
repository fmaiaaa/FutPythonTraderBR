"""Pipeline ensemble: RandomForest + HistGBM + GradientBoosting + seleção de features."""
from __future__ import annotations

from sklearn.ensemble import (
    GradientBoostingClassifier,
    HistGradientBoostingClassifier,
    RandomForestClassifier,
    VotingClassifier,
)
from sklearn.feature_selection import SelectFromModel
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .config import load_model_config


def _rf_params(cfg: dict) -> dict:
    p = cfg["ensemble"]["random_forest"]
    return {
        "n_estimators": p.get("n_estimators", 200),
        "max_depth": p.get("max_depth", 8),
        "min_samples_leaf": p.get("min_samples_leaf", 20),
        "max_features": p.get("max_features", "sqrt"),
        "class_weight": p.get("class_weight", "balanced_subsample"),
        "n_jobs": -1,
        "random_state": 42,
    }


def _hgb_params(cfg: dict) -> dict:
    p = cfg["ensemble"]["hist_gbm"]
    return {
        "max_iter": p.get("max_iter", 250),
        "learning_rate": p.get("learning_rate", 0.05),
        "max_depth": p.get("max_depth", 5),
        "min_samples_leaf": p.get("min_samples_leaf", 25),
        "l2_regularization": p.get("l2_regularization", 2.0),
        "random_state": 42,
    }


def _gbm_params(cfg: dict, multiclass: bool) -> dict:
    p = cfg["ensemble"]["gbm"]
    return {
        "n_estimators": p.get("n_estimators", 200),
        "learning_rate": p.get("learning_rate", 0.05),
        "max_depth": p.get("max_depth", 4),
        "min_samples_leaf": p.get("min_samples_leaf", 25),
        "subsample": p.get("subsample", 0.8),
        "max_features": p.get("max_features", "sqrt"),
        "random_state": 42,
    }


def build_base_estimators(cfg: dict, multiclass: bool = True) -> list[tuple[str, object]]:
    return [
        ("random_forest", RandomForestClassifier(**_rf_params(cfg))),
        ("hist_gbm", HistGradientBoostingClassifier(**_hgb_params(cfg))),
        ("gbm", GradientBoostingClassifier(**_gbm_params(cfg, multiclass))),
    ]


def build_ensemble_pipeline(multiclass: bool = True, cfg: dict | None = None) -> Pipeline:
    """
    Imputer → Scaler → SelectFromModel(RF) → VotingClassifier(RF, HGB, GBM).
    Regularização via hiperparâmetros + seleção de features.
    """
    cfg = cfg or load_model_config()
    fs = cfg["feature_selection"]
    estimators = build_base_estimators(cfg, multiclass)

    selector_est = RandomForestClassifier(
        n_estimators=100,
        max_depth=6,
        min_samples_leaf=30,
        max_features="sqrt",
        random_state=42,
        n_jobs=-1,
    )
    selector = SelectFromModel(
        selector_est,
        threshold=fs.get("threshold", "median"),
        max_features=fs.get("max_features", 150) if fs.get("enabled", True) else None,
    )
    if not fs.get("enabled", True):
        selector = "passthrough"

    voting = VotingClassifier(
        estimators=estimators,
        voting=cfg["ensemble"].get("voting", "soft"),
        weights=cfg["ensemble"].get("weights", [1, 1, 1]),
        n_jobs=1,
    )

    steps = [
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler", StandardScaler()),
    ]
    if fs.get("enabled", True):
        steps.append(("selector", selector))
    steps.append(("ensemble", voting))
    return Pipeline(steps)


def selected_feature_names(pipeline: Pipeline, all_names: list[str]) -> list[str]:
    """Nomes das features após SelectFromModel (ou todas se desligado)."""
    if "selector" not in pipeline.named_steps:
        return all_names
    sel = pipeline.named_steps["selector"]
    if not hasattr(sel, "get_support"):
        return all_names
    mask = sel.get_support()
    return [n for n, keep in zip(all_names, mask) if keep]
