"""Predição com modelos treinados."""
from __future__ import annotations

from dataclasses import dataclass

import joblib
import numpy as np
import pandas as pd

from ..client import DATA
from ..features.builder import build_single_match_features
from .calibration import calibrated_probability, dynamic_phi, load_calibration
from .config import load_model_config

MODEL_DIR = DATA / "models"
MARKET_CLASS = {"home_win_ft": 0, "draw_ft": 1, "away_win_ft": 2}


def _implied_1x2(market_odds: dict | None) -> tuple[float, float, float] | None:
    if not market_odds:
        return None
    h = market_odds.get("Odd_1_FT") or market_odds.get("home_win_ft")
    d = market_odds.get("Odd_X_FT") or market_odds.get("draw_ft")
    a = market_odds.get("Odd_2_FT") or market_odds.get("away_win_ft")
    try:
        odds = [float(h), float(d), float(a)]
    except (TypeError, ValueError):
        return None
    if any(o <= 1.01 for o in odds):
        return None
    inv = [1 / o for o in odds]
    s = sum(inv)
    return inv[0] / s, inv[1] / s, inv[2] / s


def _shrink_probs(
    model: tuple[float, float, float],
    implied: tuple[float, float, float],
    shrink: float,
) -> tuple[float, float, float]:
    out = [(1 - shrink) * m + shrink * i for m, i in zip(model, implied)]
    s = sum(out)
    if s <= 0:
        return model
    return out[0] / s, out[1] / s, out[2] / s


def apply_probability_shrinkage(
    p_h: float, p_d: float, p_a: float,
    market_odds: dict | None,
    shrink: float | None = None,
) -> tuple[float, float, float]:
    """Reduz variância — blend com implied odds do mercado."""
    shrink = shrink if shrink is not None else load_model_config().get("prediction", {}).get("shrinkage_to_market", 0.35)
    implied = _implied_1x2(market_odds)
    if implied is None or shrink <= 0:
        return p_h, p_d, p_a
    return _shrink_probs((p_h, p_d, p_a), implied, shrink)


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

        X = pd.DataFrame([feats]).reindex(columns=self.feature_names, fill_value=0)
        proba = self.outcome_model.predict_proba(X)[0]
        p_h, p_d, p_a = float(proba[0]), float(proba[1]), float(proba[2])

        cfg = load_model_config()
        hier = cfg.get("hierarchical", {})
        l_ht = None
        proba_ht_l = None
        if hier.get("enabled", True) and league_slug:
            from .hierarchical import blend_probs, blend_weight, league_n_samples, load_league_models

            l_out, l_ht, l_feats = load_league_models(league_slug)
            if l_out is not None and l_feats:
                Xl = pd.DataFrame([feats]).reindex(columns=l_feats, fill_value=0)
                lp = l_out.predict_proba(Xl)[0]
                w = blend_weight(league_slug, league_n_samples(league_slug), cfg)
                if w > 0:
                    p_h, p_d, p_a = blend_probs((p_h, p_d, p_a), (float(lp[0]), float(lp[1]), float(lp[2])), w)
                if l_ht is not None:
                    proba_ht_l = l_ht.predict_proba(Xl)[0]
                else:
                    proba_ht_l = None
            else:
                proba_ht_l = None
        else:
            proba_ht_l = None

        shrink = cfg.get("prediction", {}).get("shrinkage_to_market", 0.35)
        if market_odds and market_odds.get("bf_back_home"):
            shrink = min(0.55, shrink + 0.10)
        p_h, p_d, p_a = apply_probability_shrinkage(p_h, p_d, p_a, market_odds, shrink=shrink)

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
        if proba_ht_l is not None:
            classes_l = list(l_ht.classes_)  # type: ignore[name-defined]
            if len(proba_ht_l) == 1:
                p_ht_l = float(proba_ht_l[0]) if classes_l[0] == 1 else 1.0 - float(proba_ht_l[0])
            else:
                idx_l = classes_l.index(1) if 1 in classes_l else 1
                p_ht_l = float(proba_ht_l[idx_l])
            w_ht = blend_weight(league_slug, league_n_samples(league_slug), cfg) if league_slug else 0
            p_ht = (1 - w_ht) * p_ht + w_ht * p_ht_l
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
