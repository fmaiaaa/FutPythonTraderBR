from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SofaScoreEvent:
    event_id: int
    home: str
    away: str
    home_slug: str = ""
    away_slug: str = ""
    status_type: str = ""
    start_timestamp: int | None = None
    score_home: int | None = None
    score_away: int | None = None
    minute: int | None = None
    tournament: str = ""

    @property
    def is_live(self) -> bool:
        return self.status_type.lower() in ("inprogress", "live", "interrupted", "1sthalf", "2ndhalf")

    @property
    def is_finished(self) -> bool:
        return self.status_type.lower() in (
            "finished", "ended", "afterpenalties", "afterextratime",
            "cancelled", "canceled", "postponed", "abandoned", "walkover", "awarded",
        )

    @property
    def is_halftime(self) -> bool:
        return self.status_type.lower() in ("halftime", "half_time", "break")

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> SofaScoreEvent:
        home = raw.get("homeTeam") or {}
        away = raw.get("awayTeam") or {}
        hs = raw.get("homeScore") or {}
        aws = raw.get("awayScore") or {}
        status = raw.get("status") or {}
        tour = raw.get("tournament") or {}
        time_info = raw.get("time") or {}
        minute = time_info.get("current") or time_info.get("played")
        if minute is None:
            desc = str(status.get("description") or "")
            import re
            m = re.search(r"(\d+)", desc)
            if m:
                minute = int(m.group(1))
        return cls(
            event_id=int(raw["id"]),
            home=str(home.get("name") or ""),
            away=str(away.get("name") or ""),
            home_slug=str(home.get("slug") or ""),
            away_slug=str(away.get("slug") or ""),
            status_type=str(status.get("type") or ""),
            start_timestamp=raw.get("startTimestamp"),
            score_home=hs.get("current"),
            score_away=aws.get("current"),
            minute=int(minute) if minute is not None else None,
            tournament=str(tour.get("name") or ""),
        )


@dataclass
class SofaScoreLiveStats:
    event_id: int
    minute: int | None = None
    possession_home: float | None = None
    possession_away: float | None = None
    shots_home: int | None = None
    shots_away: int | None = None
    shots_on_target_home: int | None = None
    shots_on_target_away: int | None = None
    xg_home: float | None = None
    xg_away: float | None = None
    corners_home: int | None = None
    corners_away: int | None = None
    big_chances_home: int | None = None
    big_chances_away: int | None = None
    shots_inside_box_home: int | None = None
    shots_inside_box_away: int | None = None
    graph_momentum: float | None = None
    pressure_home: float | None = None
    pressure_away: float | None = None
    raw_groups: dict[str, Any] = field(default_factory=dict)

    def to_flat_dict(self) -> dict[str, Any]:
        return {
            "sofascore_event_id": self.event_id,
            "ss_minute": self.minute,
            "ss_possession_home": self.possession_home,
            "ss_possession_away": self.possession_away,
            "ss_shots_home": self.shots_home,
            "ss_shots_away": self.shots_away,
            "ss_sot_home": self.shots_on_target_home,
            "ss_sot_away": self.shots_on_target_away,
            "ss_xg_home": self.xg_home,
            "ss_xg_away": self.xg_away,
            "ss_corners_home": self.corners_home,
            "ss_corners_away": self.corners_away,
            "ss_big_chances_home": self.big_chances_home,
            "ss_big_chances_away": self.big_chances_away,
            "ss_shots_box_home": self.shots_inside_box_home,
            "ss_shots_box_away": self.shots_inside_box_away,
            "ss_graph_momentum": self.graph_momentum,
            "ss_pressure_home": self.pressure_home,
            "ss_pressure_away": self.pressure_away,
        }
