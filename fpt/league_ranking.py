"""Ranking de ligas — autorização de operação + multiplicador Kelly."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from .client import DATA
from .leagues import WATCHLIST_CATALOG

BR = ZoneInfo("America/Sao_Paulo")
RANKING_DIR = DATA / "leagues"
RANKING_FILE = RANKING_DIR / "ranking.json"


@dataclass
class LeagueRank:
    key: str
    label: str
    tier: int
    kelly_multiplier: float
    min_bets_required: int
    n_bets: int = 0
    roi_pct: float | None = None
    clv_pp: float | None = None
    can_operate: bool = True
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _default_rankings(cfg: dict | None = None) -> dict[str, LeagueRank]:
    cfg = cfg or {}
    rk_cfg = cfg.get("ranking", {})
    t1_kelly = float(rk_cfg.get("tier1_kelly_multiplier", 0.25))
    t3_kelly = float(rk_cfg.get("tier3_kelly_multiplier", 0.05))
    min_t1 = int(rk_cfg.get("min_bets_tier1", 300))
    min_t2 = int(rk_cfg.get("min_bets_tier2", 1000))
    min_t3 = int(rk_cfg.get("min_bets_tier3", 3000))

    out: dict[str, LeagueRank] = {}
    for _country, slug, label in WATCHLIST_CATALOG:
        out[slug] = LeagueRank(
            key=slug,
            label=label,
            tier=1,
            kelly_multiplier=t1_kelly,
            min_bets_required=min_t1,
            can_operate=True,
            notes=["watchlist tier 1"],
        )
        out[label] = out[slug]

    out["_default_probation"] = LeagueRank(
        key="_default_probation",
        label="Liga em probation",
        tier=3,
        kelly_multiplier=t3_kelly,
        min_bets_required=min_t3,
        can_operate=True,
        notes=["ligas FPT fora da watchlist — Kelly mínimo"],
    )
    out["_disabled"] = LeagueRank(
        key="_disabled",
        label="Desabilitada",
        tier=4,
        kelly_multiplier=0.0,
        min_bets_required=min_t2,
        can_operate=False,
    )
    return out


def load_league_rankings(cfg: dict | None = None) -> dict[str, LeagueRank]:
    defaults = _default_rankings(cfg)
    if not RANKING_FILE.exists():
        return defaults
    try:
        raw = json.loads(RANKING_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return defaults

    merged = dict(defaults)
    for item in raw.get("leagues", []):
        key = item.get("key") or item.get("slug") or item.get("label")
        if not key:
            continue
        merged[key] = LeagueRank(
            key=key,
            label=item.get("label", key),
            tier=int(item.get("tier", 3)),
            kelly_multiplier=float(item.get("kelly_multiplier", 0.05)),
            min_bets_required=int(item.get("min_bets_required", 300)),
            n_bets=int(item.get("n_bets", 0)),
            roi_pct=item.get("roi_pct"),
            clv_pp=item.get("clv_pp"),
            can_operate=bool(item.get("can_operate", True)),
            notes=list(item.get("notes") or []),
        )
    return merged


def save_league_rankings(ranks: dict[str, LeagueRank]) -> None:
    RANKING_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated": datetime.now(BR).isoformat(timespec="seconds"),
        "leagues": [r.to_dict() for r in ranks.values() if not r.key.startswith("_")],
    }
    RANKING_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def resolve_league_rank(
    *,
    league_slug: str | None = None,
    league_label: str | None = None,
    league_raw: str | None = None,
    cfg: dict | None = None,
) -> LeagueRank:
    ranks = load_league_rankings(cfg)
    for key in (league_slug, league_label, league_raw):
        if key and key in ranks:
            return ranks[key]
    return ranks["_default_probation"]


def adjust_stake_pct(base_pct: float, rank: LeagueRank) -> float:
    if not rank.can_operate or base_pct <= 0:
        return 0.0
    return round(base_pct * rank.kelly_multiplier, 6)


def league_operation_allowed(
    *,
    league_slug: str | None = None,
    league_label: str | None = None,
    league_raw: str | None = None,
    cfg: dict | None = None,
) -> tuple[bool, LeagueRank, str]:
    """Retorna (permitido, rank, motivo_bloqueio)."""
    rank = resolve_league_rank(
        league_slug=league_slug,
        league_label=league_label,
        league_raw=league_raw,
        cfg=cfg,
    )
    lg_cfg = cfg or {}
    if lg_cfg.get("watchlist_only"):
        from .leagues import is_watchlist_league

        league = league_raw or league_label or ""
        if league and not is_watchlist_league(league):
            return False, rank, "fora_watchlist"
    min_tier = lg_cfg.get("operate_min_tier")
    if min_tier is not None:
        if rank.tier > int(min_tier) or not rank.can_operate:
            return False, rank, "tier_insuficiente"
    if not rank.can_operate:
        return False, rank, "desabilitada"
    return True, rank, ""
