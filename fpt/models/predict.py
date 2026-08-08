"""Predição com modelos treinados."""
from __future__ import annotations

from dataclasses import dataclass

import joblib
import numpy as np
import pandas as pd

from ..client import DATA
from ..features.builder import build_single_match_features
from .calibration import calibrated_probability, dynamic_phi, load_calibration

MODEL_DIR = DATA / "models"
MARKET_CLASS = {"home_win_ft": 0, "draw_ft": 1, "away_win_ft": 2}


@dataclass
class ModelPrediction:
    prob_home: float
    prob_draw: float
    prob_away: float
    prob_selection: float
    p_ht_profitable: float
    phi_dynamic: float
    confidence: float
    schedule_notes: list[str]
    model_loaded: bool

    def prob_dict(self) -> dict[str, float]:
        return {"home": self.prob_home, "draw": self.prob_draw, "away": self.prob_away}


class ModelPredictor:
    def __init__(self):
        self.outcome_model = None
        self.ht_model = None
        self.feature_names: list[str] = []
        self._load()

    def _load(self):
        try:
            self.outcome_model = joblib.load(MODEL_DIR / "model_outcome.joblib")
            self.ht_model = joblib.load(MODEL_DIR / "model_ht_trade.joblib")
            self.feature_names = joblib.load(MODEL_DIR / "feature_names.joblib")
        except FileNotFoundError:
            pass

    @property
    def ready(self) -> bool:
        return self.outcome_model is not None

    def predict(
        self,
        df: pd.DataFrame,
        home: str,
        away: str,
        market: str = "home_win_ft",
        match_date: str | None = None,
        league_slug: str | None = None,
        market_odds: dict | None = None,
    ) -> ModelPrediction:
        feats, notes = build_single_match_features(
            df, home, away, match_date, league_slug, market_odds
        )
        if not self.ready:
            from ..trading.probabilities import estimate_match_probabilities
            p = estimate_match_probabilities(df, home, away, league_slug)
            sel = p.home if market == "home_win_ft" else p.draw if market == "draw_ft" else p.away
            return ModelPrediction(
                prob_home=p.home, prob_draw=p.draw, prob_away=p.away,
                prob_selection=sel, p_ht_profitable=0.5,
                phi_dynamic=1.08, confidence=40.0, schedule_notes=notes, model_loaded=False,
            )

        X = pd.DataFrame([feats]).reindex(columns=self.feature_names)
        proba = self.outcome_model.predict_proba(X)[0]
        p_h, p_d, p_a = float(proba[0]), float(proba[1]), float(proba[2])

        cls = MARKET_CLASS.get(market, 0)
        raw_sel = [p_h, p_d, p_a][cls]
        cal_sel = calibrated_probability(raw_sel, "outcome")

        proba_ht = self.ht_model.predict_proba(X)[0]
        classes = list(self.ht_model.classes_)
        if len(proba_ht) == 1:
            p_ht = float(proba_ht[0]) if classes[0] == 1 else 1.0 - float(proba_ht[0])
        else:
            idx = classes.index(1) if 1 in classes else 1
            p_ht = float(proba_ht[idx])
        p_ht = calibrated_probability(p_ht, "ht_trade")

        phi = dynamic_phi(cal_sel, "outcome")
        cal = load_calibration()
        ece = cal.get("ece_outcome", 0.05)
        confidence = max(0, min(100, 100 * (1 - ece * 3) * min(1, feats.get("h_n_10", 5) / 10)))

        return ModelPrediction(
            prob_home=round(p_h, 4),
            prob_draw=round(p_d, 4),
            prob_away=round(p_a, 4),
            prob_selection=round(cal_sel, 4),
            p_ht_profitable=round(p_ht, 4),
            phi_dynamic=phi,
            confidence=round(confidence, 1),
            schedule_notes=notes,
            model_loaded=True,
        )


_predictor: ModelPredictor | None = None


def get_predictor() -> ModelPredictor:
    global _predictor
    if _predictor is None:
        _predictor = ModelPredictor()
    return _predictor
