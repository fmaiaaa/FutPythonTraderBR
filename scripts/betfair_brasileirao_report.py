"""Relatório de odds Match Odds (back/lay) — Brasileirão Série A — Betfair BR."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fpt.integrations.betfair import get_betfair_client

SERIE_A_ID = "13"
BR = ZoneInfo("America/Sao_Paulo")


def best_prices(runner: dict) -> tuple[float | None, float | None]:
    ex = runner.get("ex", {})
    backs = ex.get("availableToBack", [])
    lays = ex.get("availableToLay", [])
    back = backs[0]["price"] if backs else None
    lay = lays[0]["price"] if lays else None
    return back, lay


def runner_key(event_name: str, runner_name: str) -> str:
    lname = runner_name.lower()
    if "draw" in lname or lname == "the draw":
        return "empate"
    if " v " in event_name:
        home, away = [p.strip() for p in event_name.split(" v ", 1)]
        if runner_name == home or home.lower() in lname:
            return "casa"
        if runner_name == away or away.lower() in lname:
            return "visitante"
    return runner_name


def fetch_today_odds() -> list[dict]:
    bf = get_betfair_client()
    bf.login()

    today = datetime.now(BR).date()
    start = datetime(today.year, today.month, today.day, tzinfo=BR).astimezone(timezone.utc)
    end = start + timedelta(days=1)

    events = bf.call(
        "SportsAPING/v1.0/listEvents",
        {
            "filter": {
                "eventTypeIds": ["1"],
                "competitionIds": [SERIE_A_ID],
                "marketStartTime": {
                    "from": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "to": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                },
            }
        },
    )

    rows: list[dict] = []
    for evwrap in sorted(events, key=lambda x: x["event"]["openDate"]):
        ev = evwrap["event"]
        cats = bf.call(
            "SportsAPING/v1.0/listMarketCatalogue",
            {
                "filter": {"eventIds": [ev["id"]], "marketTypeCodes": ["MATCH_ODDS"]},
                "maxResults": "1",
                "marketProjection": ["RUNNER_DESCRIPTION", "EVENT", "MARKET_START_TIME"],
            },
        )
        if not cats:
            continue

        cat = cats[0]
        books = bf.list_market_book([cat["marketId"]])
        if not books:
            continue

        book = books[0]
        by_id = {r["selectionId"]: r for r in book.get("runners", [])}
        kickoff = datetime.fromisoformat(ev["openDate"].replace("Z", "+00:00")).astimezone(BR)

        game: dict = {
            "jogo": ev["name"],
            "horario": kickoff.strftime("%d/%m/%Y %H:%M"),
            "mercado_id": cat["marketId"],
        }

        for runner in cat.get("runners", []):
            sid = runner["selectionId"]
            back, lay = best_prices(by_id.get(sid, {}))
            key = runner_key(ev["name"], runner.get("runnerName", ""))
            game[key] = {
                "runner": runner.get("runnerName", key),
                "back": back,
                "lay": lay,
            }

        rows.append(game)

    return rows


def format_report(rows: list[dict], today: datetime.date) -> str:
    now = datetime.now(BR)
    lines = [
        f"Brasileirão Série A — odds Betfair ({today.strftime('%d/%m/%Y')})",
        f"Gerado em {now.strftime('%d/%m/%Y %H:%M')} (horário de Brasília)",
        f"Mercado: Match Odds (1X2) | Fonte: Betfair Exchange BR",
        "",
    ]

    if not rows:
        lines.append("Nenhum jogo encontrado para hoje.")
        return "\n".join(lines)

    for g in rows:
        lines.append("=" * 72)
        lines.append(f"{g['jogo']}  |  {g['horario']}")
        lines.append("-" * 72)
        lines.append(f"{'Seleção':<24} {'Back':>8} {'Lay':>8}")
        lines.append("-" * 72)
        for label, key in [("Casa", "casa"), ("Empate", "empate"), ("Visitante", "visitante")]:
            o = g.get(key, {})
            if not isinstance(o, dict):
                continue
            b, l = o.get("back"), o.get("lay")
            bs = f"{b:.2f}" if b else "—"
            ls = f"{l:.2f}" if l else "—"
            lines.append(f"{o.get('runner', label):<24} {bs:>8} {ls:>8}")
        lines.append("")

    return "\n".join(lines)


def main() -> None:
    today = datetime.now(BR).date()
    rows = fetch_today_odds()
    report = format_report(rows, today)

    out_dir = ROOT / "data" / "betfair" / today.strftime("%Y-%m")
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"brasileirao_{today.isoformat()}"
    (out_dir / f"{stem}.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    txt_path = out_dir / f"{stem}.txt"
    txt_path.write_text(report, encoding="utf-8")

    print(report)
    print(f"\nSalvo: {txt_path}")


if __name__ == "__main__":
    main()
