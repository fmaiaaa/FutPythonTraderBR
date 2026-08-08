"""Treinamento ensemble com validação temporal 70/30 + fit final em 100%."""
from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import (
    accuracy_score,
    brier_score_loss,
    log_loss,
    mean_absolute_error,
    roc_auc_score,
)
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import Pipeline

from ..client import DATA
from ..features.builder import FeatureBuilder
from .calibration import (
    build_calibration_curve,
    expected_calibration_error,
    save_calibration,
)
from .config import load_model_config
from .ensemble import build_ensemble_pipeline, selected_feature_names

MODEL_DIR = DATA / "models"


def _temporal_split(n: int, train_fraction: float) -> int:
    return int(n * train_fraction)


def _metrics_multiclass(y_true, proba) -> dict:
    pred = np.argmax(proba, axis=1)
    acc = accuracy_score(y_true, pred)
    ll = log_loss(y_true, proba, labels=[0, 1, 2])
    y_home = (y_true == 0).astype(int)
    p_home = proba[:, 0]
    ece = expected_calibration_error(y_home, p_home)
    brier = brier_score_loss(y_home, p_home)
    mae_home = mean_absolute_error(y_home, p_home)
    return {
        "accuracy": round(float(acc), 4),
        "logloss": round(float(ll), 4),
        "ece_home": round(float(ece), 4),
        "brier_home": round(float(brier), 4),
        "mae_home": round(float(mae_home), 4),
    }


def _metrics_binary(y_true, p_pos) -> dict:
    auc = roc_auc_score(y_true, p_pos) if len(np.unique(y_true)) > 1 else 0.5
    ece = expected_calibration_error(y_true, p_pos)
    brier = brier_score_loss(y_true, p_pos)
    mae = mean_absolute_error(y_true, p_pos)
    return {
        "auc": round(float(auc), 4),
        "ece": round(float(ece), 4),
        "brier": round(float(brier), 4),
        "mae": round(float(mae), 4),
    }


def _timeseries_cv_scores(pipe, X: pd.DataFrame, y: pd.Series, n_splits: int = 5) -> dict:
    """TimeSeriesSplit — validação cruzada temporal."""
    tscv = TimeSeriesSplit(n_splits=n_splits)
    accs, lls = [], []
    for train_idx, test_idx in tscv.split(X):
        if len(test_idx) < 20 or len(train_idx) < 50:
            continue
        pipe_cv = build_ensemble_pipeline(multiclass=True)
        pipe_cv.fit(X.iloc[train_idx], y.iloc[train_idx])
        proba = pipe_cv.predict_proba(X.iloc[test_idx])
        m = _metrics_multiclass(y.iloc[test_idx].values, proba)
        accs.append(m["accuracy"])
        lls.append(m["logloss"])
    if not accs:
        return {"cv_accuracy_mean": None, "cv_logloss_mean": None, "cv_folds": 0}
    return {
        "cv_accuracy_mean": round(float(np.mean(accs)), 4),
        "cv_logloss_mean": round(float(np.mean(lls)), 4),
        "cv_folds": len(accs),
    }


def train_models(df: pd.DataFrame, min_history: int | None = None) -> dict:
    cfg = load_model_config()
    min_history = min_history if min_history is not None else cfg["evaluation"]["min_history"]
    train_frac = cfg["split"]["train_fraction"]

    print("Gerando features (H2H + temporada + contexto + stats FPT)...")
    fb = FeatureBuilder(df)
    X, y_out, y_ht = fb.build_training_matrix(min_history=min_history)
    feature_names = list(X.columns)
    print(f"Dataset: {len(X)} amostras x {len(feature_names)} features")

    split = _temporal_split(len(X), train_frac)
    X_train, X_test = X.iloc[:split], X.iloc[split:]
    y_train, y_test = y_out.iloc[:split], y_out.iloc[split:]
    print(f"Split temporal: treino {len(X_train)} ({train_frac:.0%}) | teste {len(X_test)} ({1-train_frac:.0%})")

    print("TimeSeriesSplit (validacao cruzada temporal)...")
    cv_pipe = build_ensemble_pipeline(multiclass=True, cfg=cfg)
    cv_scores = _timeseries_cv_scores(cv_pipe, X_train, y_train, n_splits=5)
    if cv_scores.get("cv_folds"):
        print(
            f"  CV ({cv_scores['cv_folds']} folds) — Acc: {cv_scores['cv_accuracy_mean']:.3f} | "
            f"LogLoss: {cv_scores['cv_logloss_mean']:.3f}"
        )

    print("Treinando Modelo 1 — 1X2 (ensemble RF + HistGBM + GBM)...")
    pipe_out = build_ensemble_pipeline(multiclass=True, cfg=cfg)
    pipe_out.fit(X_train, y_train)

    proba_test = pipe_out.predict_proba(X_test)
    metrics_out_train = _metrics_multiclass(y_train.values, pipe_out.predict_proba(X_train))
    metrics_out_test = _metrics_multiclass(y_test.values, proba_test)
    print(
        f"  Holdout — Acc: {metrics_out_test['accuracy']:.3f} | LogLoss: {metrics_out_test['logloss']:.3f} | "
        f"ECE(home): {metrics_out_test['ece_home']:.4f} | MAE(home): {metrics_out_test['mae_home']:.4f}"
    )

    y_binary_home = (y_test.values == 0).astype(int)
    curve_out = build_calibration_curve(y_binary_home, proba_test[:, 0])

    if metrics_out_train["accuracy"] - metrics_out_test["accuracy"] > 0.15:
        print("  AVISO: gap treino-teste elevado — regularizacao + shrinkage mercado.")

    print("Treinando Modelo 2 — lucro HT (ensemble)...")
    ht_mask = y_ht.notna()
    X_ht = X[ht_mask]
    y_ht_clean = y_ht[ht_mask].astype(int)
    split_ht = _temporal_split(len(X_ht), train_frac)
    X_ht_train, X_ht_test = X_ht.iloc[:split_ht], X_ht.iloc[split_ht:]
    y_ht_train, y_ht_test = y_ht_clean.iloc[:split_ht], y_ht_clean.iloc[split_ht:]

    pipe_ht = build_ensemble_pipeline(multiclass=False, cfg=cfg)
    metrics_ht_test = {"auc": 0.5, "ece": 0.1, "brier": 0.25, "mae": 0.25}
    ht_curve: list[dict] = []

    if len(np.unique(y_ht_train)) < 2:
        print("  AVISO: target HT com classe unica")
        pipe_ht.fit(X_ht_train, y_ht_train)
        cal_ht: Pipeline | CalibratedClassifierCV = pipe_ht
    else:
        pipe_ht.fit(X_ht_train, y_ht_train)
        proba_ht_test = pipe_ht.predict_proba(X_ht_test)
        p_ht_test = proba_ht_test[:, 1] if proba_ht_test.shape[1] > 1 else proba_ht_test[:, 0]
        metrics_ht_test = _metrics_binary(y_ht_test.values, p_ht_test)
        ht_curve = build_calibration_curve(y_ht_test.values, p_ht_test)
        print(
            f"  Holdout — AUC: {metrics_ht_test['auc']:.3f} | ECE: {metrics_ht_test['ece']:.4f} | "
            f"MAE: {metrics_ht_test['mae']:.4f}"
        )

    cal_method = cfg["calibration"]["method"]
    cal_cv = cfg["calibration"]["cv_folds"]

    print("Fit FINAL em 100% dos dados (modelo de producao)...")
    pipe_out_full = build_ensemble_pipeline(multiclass=True, cfg=cfg)
    pipe_out_full.fit(X, y_out)
    cal_out = CalibratedClassifierCV(pipe_out_full, method=cal_method, cv=cal_cv)
    cal_out.fit(X, y_out)

    if len(np.unique(y_ht_clean)) >= 2:
        pipe_ht_full = build_ensemble_pipeline(multiclass=False, cfg=cfg)
        pipe_ht_full.fit(X_ht, y_ht_clean)
        cal_ht = CalibratedClassifierCV(pipe_ht_full, method=cal_method, cv=cal_cv)
        cal_ht.fit(X_ht, y_ht_clean)
    elif not isinstance(cal_ht, CalibratedClassifierCV):
        cal_ht.fit(X_ht, y_ht_clean)

    sel_out = selected_feature_names(pipe_out_full, feature_names)
    try:
        base_ht = pipe_ht_full if len(np.unique(y_ht_clean)) >= 2 else pipe_ht
        sel_ht = selected_feature_names(base_ht, feature_names)
    except Exception:
        sel_ht = sel_out[:20]

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(cal_out, MODEL_DIR / "model_outcome.joblib")
    joblib.dump(cal_ht, MODEL_DIR / "model_ht_trade.joblib")
    joblib.dump(feature_names, MODEL_DIR / "feature_names.joblib")
    joblib.dump(sel_out, MODEL_DIR / "selected_features_outcome.joblib")
    joblib.dump(sel_ht, MODEL_DIR / "selected_features_ht.joblib")

    meta = {
        "model_type": "ensemble_voting",
        "base_learners": ["RandomForest", "HistGradientBoosting", "GradientBoosting"],
        "feature_selection": cfg["feature_selection"],
        "split": cfg["split"],
        "validation": "temporal_70_30 + TimeSeriesSplit",
        "production_fit": "100% dataset after holdout validation",
        "n_samples": len(X),
        "n_train": len(X_train),
        "n_test": len(X_test),
        "n_features_raw": len(feature_names),
        "n_features_selected_outcome": len(sel_out),
        "n_features_selected_ht": len(sel_ht),
        "metrics_outcome_train": metrics_out_train,
        "metrics_outcome_test": metrics_out_test,
        "metrics_ht_test": metrics_ht_test,
        "timeseries_cv": cv_scores,
        "prediction_shrinkage": cfg.get("prediction", {}).get("shrinkage_to_market", 0.4),
        "features": ["h2h", "season_period", "context", "schedule", "betfair_optional"],
        "selected_features_sample": sel_out[:25],
    }
    (MODEL_DIR / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    save_calibration(curve_out, ht_curve, metrics_out_test["ece_home"], metrics_ht_test["ece"])
    print(f"Modelos PRODUCAO salvos em {MODEL_DIR} | features: {len(sel_out)}/{len(feature_names)}")
    return meta
