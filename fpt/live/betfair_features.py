from __future__ import annotations

"""Features Betfair para enriquecer predição em tempo real."""

import numpy as np


def betfair_exchange_features(market_odds_dict: dict) -> dict[str, float]:
    """Extrai features de exchange a partir do dict de odds Betfair."""
    feats: dict[str, float] = {}
    backs, lays, spreads = [], [], []
    for side in ("home", "draw", "away"):
        bb = market_odds_dict.get(f"bf_back_{side}")
        bl = market_odds_dict.get(f"bf_lay_{side}")
        if bb and bb > 1.01:
            feats[f"bf_impl_{side}"] = 1.0 / bb
            backs.append(1.0 / bb)
        if bl and bl > 1.01:
            feats[f"bf_impl_lay_{side}"] = 1.0 / bl
        if bb and bl and bb > 1.01:
            sp = (bl - bb) / bb
            feats[f"bf_spread_{side}"] = sp
            spreads.append(sp)
        if bb and bl:
            mids = (bb + bl) / 2
            if mids > 1.01:
                lays.append(1.0 / mids)

    if len(backs) == 3:
        s = sum(backs)
        if s > 0:
            feats["bf_overround_back"] = s
            feats["bf_impl_home_norm"] = backs[0] / s
            feats["bf_impl_draw_norm"] = backs[1] / s
            feats["bf_impl_away_norm"] = backs[2] / s

    if spreads:
        feats["bf_spread_mean"] = float(np.mean(spreads))
        feats["bf_spread_max"] = float(np.max(spreads))

    tm = market_odds_dict.get("bf_total_matched")
    if tm:
        feats["bf_log_matched"] = float(np.log1p(tm))

    if market_odds_dict.get("bf_in_play"):
        feats["bf_in_play"] = 1.0

    return feats


def enhanced_market_odds_dict(base: dict, betfair_dict: dict | None) -> dict:
    """Merge FPT + Betfair; Betfair sobrescreve 1X2 quando disponível."""
    out = dict(base or {})
    if not betfair_dict:
        return out
    for k in ("Odd_1_FT", "Odd_X_FT", "Odd_2_FT", "home_win_ft", "draw_ft", "away_win_ft"):
        bf_key = {
            "Odd_1_FT": "bf_back_home",
            "home_win_ft": "bf_back_home",
            "Odd_X_FT": "bf_back_draw",
            "draw_ft": "bf_back_draw",
            "Odd_2_FT": "bf_back_away",
            "away_win_ft": "bf_back_away",
        }.get(k)
        if bf_key and betfair_dict.get(bf_key):
            out[k] = betfair_dict[bf_key]
    out.update(betfair_exchange_features(betfair_dict))
    out.update({k: v for k, v in betfair_dict.items() if k.startswith("bf_")})
    return out
