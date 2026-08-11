from __future__ import annotations

from dashboard_app import _format_entry_rows


def test_format_entry_rows_shows_operation():
    rows = _format_entry_rows([
        {
            "home": "Flamengo",
            "away": "Vasco",
            "entry_side": "BACK",
            "market": "draw_ft",
            "entry_odd": 2.5,
            "exit_odd": 2.2,
            "stake_amount": 2.0,
            "pnl": 0.35,
            "status": "CLOSED",
        },
        {
            "home": "A",
            "away": "B",
            "entry_side": "LAY",
            "market": "away_win_ft",
            "entry_odd": 3.0,
            "stake_amount": 2.0,
            "status": "OPEN",
        },
    ])
    assert rows[0]["Operação"] == "BACK Empate"
    assert rows[0]["Mercado"] == "Empate"
    assert rows[0]["Lado"] == "BACK"
    assert rows[1]["Operação"] == "LAY Visitante"
    assert rows[0]["Jogo"] == "Flamengo x Vasco"
    assert rows[0]["Lucro R$"] == "+0.35"
    assert rows[1]["Lucro R$"] == "—"
