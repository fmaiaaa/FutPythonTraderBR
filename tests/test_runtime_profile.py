from __future__ import annotations

import pandas as pd

from fpt.live.config import load_live_config
from fpt.live.match_coverage import in_live_feeds_ok, prematch_feeds_ok
from fpt.live.runtime_profile import PROFILES, apply_runtime_profile, save_profile
from fpt.trading.market_sim import ExchangeSide, MarketOdds


def _odds_bf():
    ex = ExchangeSide(back=2.0, lay=2.02, selection_id=1)
    return MarketOdds(
        home=2.0, draw=3.5, away=4.0, source="betfair_br",
        exchange={"home": ex, "draw": ExchangeSide(back=3.5, lay=3.52), "away": ExchangeSide(back=4.0, lay=4.02)},
        market_id="1.1", in_play=False,
    )


def test_all_leagues_profile_coverage(tmp_path, monkeypatch):
    import fpt.live.runtime_profile as rp

    prof_file = tmp_path / "runtime_profile.json"
    monkeypatch.setattr(rp, "PROFILE_FILE", prof_file)
    rp.save_profile("all_leagues")
    cfg = apply_runtime_profile({"leagues": {}, "coverage": {}, "execution": {}})
    assert cfg["leagues"]["filter_mode"] == "all_fpt"
    assert cfg["coverage"]["pre_live_require_fpt"] is True


def test_prematch_requires_fpt_and_betfair():
    cfg = load_live_config()
    row = pd.Series({"Odd_1_FT": 1.65, "Odd_X_FT": 3.8, "Odd_2_FT": 5.5})
    odds = _odds_bf()
    assert prematch_feeds_ok(
        in_play=False, market_id="1.1", odds_source="betfair_br",
        row=row, market_odds=odds, cfg=cfg,
    )
    assert not prematch_feeds_ok(
        in_play=False, market_id=None, odds_source="fpt_row",
        row=row, market_odds=odds, cfg=cfg,
    )


def test_in_live_requires_ss_and_bf():
    cfg = load_live_config()
    odds = _odds_bf()
    odds.in_play = True
    assert in_live_feeds_ok(
        in_play=True, market_id="1.1", sofascore_event_id=123,
        odds_source="betfair_br", market_odds=odds, cfg=cfg,
    )
    assert not in_live_feeds_ok(
        in_play=True, market_id="1.1", sofascore_event_id=None,
        odds_source="betfair_br", market_odds=odds, cfg=cfg,
    )
