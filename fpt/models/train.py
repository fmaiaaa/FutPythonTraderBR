"""Treinamento de modelos robustos (HistGradientBoosting + calibração)."""
from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ..client import DATA
from ..features.builder import FeatureBuilder
from .calibration import (
    build_calibration_curve,
    expected_calibration_error,
    save_calibration,
)

MODEL_DIR = DATA / "models"


def _make_pipeline(multiclass: bool = True) -> Pipeline:
    clf = HistGradientBoostingClassifier(
        max_iter=300,
        learning_rate=0.06,
        max_depth=6,
        min_samples_leaf=30,
        l2_regularization=1.0,
        random_state=42,
    )
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler", StandardScaler()),
        ("clf", clf),
    ])


def train_models(df: pd.DataFrame, min_history: int = 100) -> dict:
    print("Gerando features (agenda cruzada + stats FPT)...")
    fb = FeatureBuilder(df)
    X, y_out, y_ht = fb.build_training_matrix(min_history=min_history)
    feature_names = list(X.columns)
    print(f"Dataset: {len(X)} amostras × {len(feature_names)} features")

    # split temporal 80/20
    split = int(len(X) * 0.8)
    X_train, X_val = X.iloc[:split], X.iloc[split:]
    y_train, y_val = y_out.iloc[:split], y_out.iloc[split:]

    print("Treinando Modelo 1 — 1X2 (multiclasse)...")
    pipe_out = _make_pipeline()
    pipe_out.fit(X_train, y_train)
    proba_val = pipe_out.predict_proba(X_val)
    pred_class = np.argmax(proba_val, axis=1)
    acc = (pred_class == y_val.values).mean()
    ll = log_loss(y_val, proba_val)
    print(f"  Acurácia val: {acc:.3f} | LogLoss: {ll:.3f}")

    # calibração por classe (home win = classe 0)
    y_binary_home = (y_val.values == 0).astype(int)
    p_home = proba_val[:, 0]
    ece = expected_calibration_error(y_binary_home, p_home)
    brier = brier_score_loss(y_binary_home, p_home)
    curve_out = build_calibration_curve(y_binary_home, p_home)
    print(f"  ECE(home): {ece:.4f} | Brier: {brier:.4f}")

    print("Treinando Modelo 2 — lucro HT (back mandante)...")
    ht_mask = y_ht.notna()
    X_ht = X[ht_mask]
    y_ht_clean = y_ht[ht_mask].astype(int)
    split_ht = int(len(X_ht) * 0.8)
    X_ht_train, X_ht_val = X_ht.iloc[:split_ht], X_ht.iloc[split_ht:]
    y_ht_train, y_ht_val = y_ht_clean.iloc[:split_ht], y_ht_clean.iloc[split_ht:]

    pipe_ht = _make_pipeline(multiclass=False)
    ht_auc, ht_ece, ht_brier = 0.5, 0.1, 0.25
    ht_curve: list[dict] = []

    if len(np.unique(y_ht_train)) < 2:
        print("  AVISO: target HT com classe única — treino simplificado")
        pipe_ht.fit(X_ht_train, y_ht_train)
        cal_ht = pipe_ht
    else:
        pipe_ht.fit(X_ht_train, y_ht_train)
        proba_ht = pipe_ht.predict_proba(X_ht_val)
        p_ht_val = proba_ht[:, 1] if proba_ht.shape[1] > 1 else proba_ht[:, 0]
        ht_auc = roc_auc_score(y_ht_val, p_ht_val) if len(np.unique(y_ht_val)) > 1 else 0.5
        ht_ece = expected_calibration_error(y_ht_val.values, p_ht_val)
        ht_curve = build_calibration_curve(y_ht_val.values, p_ht_val)
        ht_brier = brier_score_loss(y_ht_val, p_ht_val)
        print(f"  AUC HT: {ht_auc:.3f} | ECE: {ht_ece:.4f} | Brier: {ht_brier:.4f}")
        cal_ht = CalibratedClassifierCV(pipe_ht, method="isotonic", cv=3)
        cal_ht.fit(X_ht_train, y_ht_train)

    print("Calibrando probabilidades (1X2)...")
    cal_out = CalibratedClassifierCV(pipe_out, method="isotonic", cv=3)
    cal_out.fit(X_train, y_train)

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(cal_out, MODEL_DIR / "model_outcome.joblib")
    joblib.dump(cal_ht, MODEL_DIR / "model_ht_trade.joblib")
    joblib.dump(feature_names, MODEL_DIR / "feature_names.joblib")

    meta = {
        "n_samples": len(X),
        "n_features": len(feature_names),
        "acc_val": round(float(acc), 4),
        "logloss_val": round(float(ll), 4),
        "ece_home": round(float(ece), 4),
        "ht_auc": round(float(ht_auc), 4),
        "ht_ece": round(float(ht_ece), 4),
        "feature_names": feature_names[:30],
    }
    (MODEL_DIR / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    save_calibration(curve_out, ht_curve, ece, ht_ece)
    print(f"Modelos salvos em {MODEL_DIR}")
    return meta
