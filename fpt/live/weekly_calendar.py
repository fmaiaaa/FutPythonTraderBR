"""Calendário semanal (domingo–sábado) e janelas de scalping."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from ..calendar import fetch_range, normalize_jogos
from ..dates import apply_fetch_date, parse_fpt_date
from ..client import DATA
from ..league_filter import filter_calendar
from ..storage import persist_data_locally

BR = ZoneInfo("America/Sao_Paulo")
WEEKLY_DIR = DATA / "calendar" / "weekly"
DAILY_REFRESH_STATE = WEEKLY_DIR / "daily_refresh.json"


def _cfg() -> dict:
    from .config import load_live_config

    return load_live_config().get("weekly_calendar", {})


def week_sun_sat(anchor: date | None = None) -> tuple[date, date]:
    """Semana corrente domingo 00:00 → sábado 23:59 (ancora em qualquer dia)."""
    anchor = anchor or date.today()
    sun = anchor - timedelta(days=(anchor.weekday() + 1) % 7)
    sat = sun + timedelta(days=6)
    return sun, sat


def operating_week(from_day: date | None = None) -> tuple[date, date]:
    """Semana em operação: no sábado busca domingo→sábado seguinte; demais dias, semana corrente."""
    from_day = from_day or date.today()
    if from_day.weekday() == 5:
        return from_day + timedelta(days=1), from_day + timedelta(days=7)
    return week_sun_sat(from_day)


def next_week_sun_sat(from_day: date | None = None) -> tuple[date, date]:
    return operating_week(from_day)


def _weekly_paths(week_start: date) -> tuple[Path, Path]:
    WEEKLY_DIR.mkdir(parents=True, exist_ok=True)
    tag = week_start.isoformat()
    return (
        WEEKLY_DIR / f"week_{tag}.parquet",
        WEEKLY_DIR / f"week_{tag}.json",
    )


def _parse_kickoff_dt(row: pd.Series) -> datetime | None:
    date_part = parse_fpt_date(row.get("Date"))
    time_raw = row.get("Time")
    if time_raw is not None and not (isinstance(time_raw, float) and pd.isna(time_raw)):
        ts = pd.to_datetime(str(time_raw).strip(), format="%H:%M", errors="coerce")
        if ts is not None and not pd.isna(ts) and not pd.isna(date_part):
            date_part = date_part.replace(hour=int(ts.hour), minute=int(ts.minute), second=0, microsecond=0)
    fetch_d = row.get("_fetch_date")
    if fetch_d is not None and not (isinstance(fetch_d, float) and pd.isna(fetch_d)):
        fd = pd.to_datetime(fetch_d, errors="coerce")
        if not pd.isna(fd):
            if pd.isna(date_part):
                date_part = fd
            else:
                date_part = date_part.replace(
                    year=int(fd.year),
                    month=int(fd.month),
                    day=int(fd.day),
                )
    if pd.isna(date_part):
        return None
    if date_part.tzinfo is None:
        return date_part.to_pydatetime().replace(tzinfo=BR)
    return date_part.tz_convert(BR).to_pydatetime()


@dataclass(frozen=True)
class ScalpSlot:
    game_id: str
    home: str
    away: str
    league: str
    match_date: str
    kickoff: str
    kickoff_dt: str
    scalp_start: str
    scalp_end: str

    @property
    def key(self) -> str:
        return f"{self.home}|{self.away}"


def _window_bounds(kickoff: datetime, cfg: dict) -> tuple[datetime, datetime]:
    pre = int(cfg.get("pre_kickoff_minutes", 5))
    dur = int(cfg.get("match_duration_minutes", 105))
    extra = int(cfg.get("injury_extra_minutes", 15))
    start = kickoff - timedelta(minutes=pre)
    end = kickoff + timedelta(minutes=dur + extra)
    return start, end


def _rows_to_slots(df: pd.DataFrame, cfg: dict) -> list[ScalpSlot]:
    slots: list[ScalpSlot] = []
    for _, row in df.iterrows():
        home = str(row.get("Home", row.get("home", "")))
        away = str(row.get("Away", row.get("away", "")))
        if not home or home == "nan" or not away or away == "nan":
            continue
        ko = _parse_kickoff_dt(row)
        if ko is None:
            continue
        start, end = _window_bounds(ko, cfg)
        gid = str(row.get("Id", f"{home}|{away}|{ko.date().isoformat()}"))
        slots.append(
            ScalpSlot(
                game_id=gid,
                home=home,
                away=away,
                league=str(row.get("League", "")),
                match_date=ko.date().isoformat(),
                kickoff=ko.strftime("%d/%m/%Y %H:%M"),
                kickoff_dt=ko.isoformat(timespec="minutes"),
                scalp_start=start.isoformat(timespec="minutes"),
                scalp_end=end.isoformat(timespec="minutes"),
            )
        )
    return slots


def _filter_cal(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    from .config import load_live_config

    live_cfg = load_live_config()
    lg = live_cfg.get("leagues", {})
    return filter_calendar(
        df,
        mode=lg.get("filter_mode", "all_fpt"),
        require_fpt_base=bool(lg.get("require_fpt_base", False)),
    )


def _persist_weekly(
    cal: pd.DataFrame,
    *,
    week_start: date,
    week_end: date,
    cfg: dict | None = None,
) -> None:
    cfg = cfg or _cfg()
    if cal.empty or not persist_data_locally():
        return
    parquet_path, json_path = _weekly_paths(week_start)
    slots = _rows_to_slots(cal, cfg)
    meta = {
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "built_at": datetime.now(BR).isoformat(timespec="seconds"),
        "n_games": len(cal),
        "n_slots": len(slots),
        "buffers": {
            "pre_kickoff_minutes": cfg.get("pre_kickoff_minutes", 5),
            "match_duration_minutes": cfg.get("match_duration_minutes", 105),
            "injury_extra_minutes": cfg.get("injury_extra_minutes", 15),
        },
        "slots": [asdict(s) for s in slots],
    }
    cal.to_parquet(parquet_path, index=False)
    json_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    (WEEKLY_DIR / "latest.json").write_text(
        json.dumps({"week_start": week_start.isoformat(), "path": str(parquet_path)}, ensure_ascii=False),
        encoding="utf-8",
    )


def _load_daily_refresh_state() -> dict:
    if not DAILY_REFRESH_STATE.exists():
        return {}
    try:
        return json.loads(DAILY_REFRESH_STATE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_daily_refresh_state(*, target_day: date, run_date: date) -> None:
    if not persist_data_locally():
        return
    WEEKLY_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "target_day": target_day.isoformat(),
        "run_date": run_date.isoformat(),
        "updated_at": datetime.now(BR).isoformat(timespec="seconds"),
    }
    DAILY_REFRESH_STATE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def should_run_daily_refresh(now: datetime | None = None) -> bool:
    """True se já passou das 23h BRT e amanhã ainda não foi atualizado hoje."""
    cfg = _cfg()
    if not cfg.get("daily_refresh_enabled", True):
        return False
    now = now or datetime.now(BR)
    if now.tzinfo is None:
        now = now.replace(tzinfo=BR)
    else:
        now = now.astimezone(BR)
    refresh_hour = int(cfg.get("daily_refresh_hour", 23))
    if now.hour < refresh_hour:
        return False
    tomorrow = now.date() + timedelta(days=1)
    state = _load_daily_refresh_state()
    if state.get("target_day") == tomorrow.isoformat() and state.get("run_date") == now.date().isoformat():
        return False
    return True


def refresh_day_schedule(target_day: date, *, force: bool = False) -> int:
    """Busca FPT do dia, atualiza CSV diário e mescla no calendário semanal + janelas scalp."""
    from ..downloader import fetch_jogos_do_dia

    cfg = _cfg()
    week_start, week_end = operating_week(target_day)
    if target_day < week_start or target_day > week_end:
        week_start, week_end = week_sun_sat(target_day)

    print(f"[weekly] atualizando horários {target_day.isoformat()}")
    raw = fetch_jogos_do_dia(target_day.isoformat())
    if raw.empty:
        return 0
    raw["_fetch_date"] = target_day.isoformat()
    day_cal = _filter_cal(normalize_jogos(raw))

    if persist_data_locally():
        daily_dir = DATA / "daily"
        daily_dir.mkdir(parents=True, exist_ok=True)
        day_cal.to_csv(daily_dir / f"jogos_{target_day.isoformat()}.csv", index=False, encoding="utf-8-sig")

    parquet_path, _ = _weekly_paths(week_start)
    if parquet_path.exists():
        try:
            weekly = pd.read_parquet(parquet_path)
        except Exception:
            weekly = pd.DataFrame()
    else:
        weekly = pd.DataFrame()

    if weekly.empty:
        build_weekly_calendar(week_start=week_start, week_end=week_end, force=True)
        try:
            weekly = pd.read_parquet(parquet_path)
        except Exception:
            weekly = pd.DataFrame()

    if not weekly.empty:
        dates = apply_fetch_date(weekly).dt.date
        mask = dates != target_day
        weekly = weekly.loc[mask].copy()
    weekly = pd.concat([weekly, day_cal], ignore_index=True)
    if "Id" in weekly.columns:
        weekly = weekly.drop_duplicates(subset=["Id"], keep="last")

    _persist_weekly(weekly, week_start=week_start, week_end=week_end, cfg=cfg)
    return len(day_cal)


def ensure_daily_schedule_refresh(now: datetime | None = None) -> bool:
    """Todo dia às 23h (BRT): atualiza horários do dia seguinte."""
    now = now or datetime.now(BR)
    if not should_run_daily_refresh(now):
        return False
    tomorrow = now.date() + timedelta(days=1)
    n = refresh_day_schedule(tomorrow)
    _save_daily_refresh_state(target_day=tomorrow, run_date=now.date())
    return n >= 0


def build_weekly_calendar(
    *,
    week_start: date | None = None,
    week_end: date | None = None,
    force: bool = False,
) -> pd.DataFrame:
    cfg = _cfg()
    if week_start is None or week_end is None:
        week_start, week_end = next_week_sun_sat()
    parquet_path, json_path = _weekly_paths(week_start)

    if not force and parquet_path.exists():
        try:
            return pd.read_parquet(parquet_path)
        except Exception:
            pass

    print(f"[weekly] calendário {week_start} → {week_end}")
    raw = fetch_range(week_start, week_end)
    cal = normalize_jogos(raw)
    if cal.empty:
        return cal

    cal = _filter_cal(cal)
    if persist_data_locally():
        _persist_weekly(cal, week_start=week_start, week_end=week_end, cfg=cfg)
    return cal


def load_weekly_meta() -> dict:
    latest = WEEKLY_DIR / "latest.json"
    if not latest.exists():
        return {}
    try:
        info = json.loads(latest.read_text(encoding="utf-8"))
        json_path = WEEKLY_DIR / f"week_{info['week_start']}.json"
        if json_path.exists():
            return json.loads(json_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, KeyError):
        pass
    return {}


def load_weekly_slots() -> list[ScalpSlot]:
    meta = load_weekly_meta()
    out: list[ScalpSlot] = []
    for item in meta.get("slots") or []:
        try:
            out.append(ScalpSlot(**item))
        except TypeError:
            continue
    return out


def load_weekly_dataframe() -> pd.DataFrame:
    meta = load_weekly_meta()
    ws = meta.get("week_start")
    if not ws:
        return pd.DataFrame()
    path = WEEKLY_DIR / f"week_{ws}.parquet"
    if not path.exists():
        return pd.DataFrame()
    try:
        df = pd.read_parquet(path)
    except Exception:
        return pd.DataFrame()
    if df.empty or "Date" not in df.columns:
        return df
    out = df.copy()
    out["Date"] = apply_fetch_date(out)
    return out


def ensure_weekly_calendar(now: datetime | None = None) -> bool:
    """Atualiza no sábado (ou se não existir calendário da semana)."""
    now = now or datetime.now(BR)
    today = now.date()
    cfg = _cfg()
    fetch_wd = int(cfg.get("fetch_on_weekday", 5))
    week_start, week_end = next_week_sun_sat(today)

    meta = load_weekly_meta()
    has_current = meta.get("week_start") == week_start.isoformat()

    if has_current and today.weekday() != fetch_wd:
        return False
    if has_current and today.weekday() == fetch_wd:
        built = meta.get("built_at", "")
        if built.startswith(today.isoformat()):
            return False

    if not has_current or today.weekday() == fetch_wd or not meta:
        build_weekly_calendar(week_start=week_start, week_end=week_end, force=today.weekday() == fetch_wd)
        return True
    return False


def active_scalp_slots(now: datetime | None = None) -> list[ScalpSlot]:
    now = now or datetime.now(BR)
    if now.tzinfo is None:
        now = now.replace(tzinfo=BR)
    else:
        now = now.astimezone(BR)

    active: list[ScalpSlot] = []
    for slot in load_weekly_slots():
        try:
            start = datetime.fromisoformat(slot.scalp_start)
            end = datetime.fromisoformat(slot.scalp_end)
            if start.tzinfo is None:
                start = start.replace(tzinfo=BR)
            if end.tzinfo is None:
                end = end.replace(tzinfo=BR)
        except ValueError:
            continue
        if start <= now <= end:
            active.append(slot)
    return active


def upcoming_scalp_slots(within_hours: float = 24, now: datetime | None = None) -> list[ScalpSlot]:
    now = now or datetime.now(BR)
    if now.tzinfo is None:
        now = now.replace(tzinfo=BR)
    else:
        now = now.astimezone(BR)
    horizon = now + timedelta(hours=within_hours)
    out: list[ScalpSlot] = []
    for slot in load_weekly_slots():
        try:
            start = datetime.fromisoformat(slot.scalp_start)
            if start.tzinfo is None:
                start = start.replace(tzinfo=BR)
        except ValueError:
            continue
        if now <= start <= horizon:
            out.append(slot)
    return out
