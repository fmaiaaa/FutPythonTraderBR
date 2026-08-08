"""Calibração e φ dinâmico baseado no erro do modelo."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from ..client import DATA

CALIB_PATH = DATA / "models" / "calibration.json"


def expected_calibration_error(y_true: np.ndarray, y_prob: np.ndarray, n_bins: int = 10) -> float:
    bins = np.linspace(0, 1, n_bins + 1)
    ece = 0.0
    for i in range(n_bins):
        mask = (y_prob >= bins[i]) & (y_prob < bins[i + 1])
        if mask.sum() == 0:
            continue
        acc = y_true[mask].mean()
        conf = y_prob[mask].mean()
        ece += mask.sum() / len(y_true) * abs(acc - conf)
    return float(ece)


def build_calibration_curve(y_true: np.ndarray, y_prob: np.ndarray, n_bins: int = 10) -> list[dict]:
    bins = np.linspace(0, 1, n_bins + 1)
    curve = []
    for i in range(n_bins):
        lo, hi = bins[i], bins[i + 1]
        mask = (y_prob >= lo) & (y_prob < hi)
        if mask.sum() < 5:
            continue
        curve.append({
            "bin_lo": float(lo),
            "bin_hi": float(hi),
            "predicted_mean": float(y_prob[mask].mean()),
            "observed_rate": float(y_true[mask].mean()),
            "error": float(y_prob[mask].mean() - y_true[mask].mean()),
            "count": int(mask.sum()),
        })
    return curve


def save_calibration(outcome_curve: list[dict], ht_curve: list[dict], ece_outcome: float, ece_ht: float):
    CALIB_PATH.parent.mkdir(parents=True, exist_ok=True)
    CALIB_PATH.write_text(json.dumps({
        "outcome": outcome_curve,
        "ht_trade": ht_curve,
        "ece_outcome": ece_outcome,
        "ece_ht": ece_ht,
    }, indent=2), encoding="utf-8")


def load_calibration() -> dict:
    if CALIB_PATH.exists():
        return json.loads(CALIB_PATH.read_text(encoding="utf-8"))
    return {"outcome": [], "ht_trade": [], "ece_outcome": 0.05, "ece_ht": 0.05}


def dynamic_phi(
    probability: float,
    model_type: str = "outcome",
    base_phi: float = 1.03,
    ece_weight: float = 2.5,
) -> float:
    """
    φ de segurança = base + penalidade por erro de calibração na faixa da probabilidade.
    Se o modelo superestima nessa faixa, exige odd maior para entrar.
    """
    cal = load_calibration()
    curve = cal.get(model_type, cal.get("outcome", []))
    ece = cal.get(f"ece_{model_type}", cal.get("ece_outcome", 0.05))

    bin_error = 0.0
    for b in curve:
        if b["bin_lo"] <= probability < b["bin_hi"]:
            # erro > 0 → modelo superestima → aumentar phi
            bin_error = max(0.0, b["error"])
            break

    phi = base_phi + bin_error * ece_weight + ece * 0.5
    return round(max(1.02, min(1.25, phi)), 4)


def calibrated_probability(raw_prob: float, model_type: str = "outcome") -> float:
    """Ajusta probabilidade usando curva de calibração (isotônica simplificada por bin)."""
    cal = load_calibration()
    curve = cal.get(model_type, cal.get("outcome", []))
    for b in curve:
        if b["bin_lo"] <= raw_prob < b["bin_hi"]:
            # shrink toward observed
            obs = b["observed_rate"]
            pred = b["predicted_mean"]
            if pred > 0:
                ratio = obs / pred
                return max(0.01, min(0.99, raw_prob * ratio))
    return raw_prob
