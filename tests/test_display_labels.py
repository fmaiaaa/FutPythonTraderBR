from fpt.live.display_labels import (
    find_operation_for_game,
    format_operation,
    market_label,
    operation_type_label,
    summarize_game_entries,
    teams_match,
)


def test_operation_type_label():
    assert operation_type_label(entry_type="pre_live") == "Pré-live"
    assert operation_type_label(entry_type="scalp") == "Scalping"
    assert operation_type_label("ENTER") == "Pré-live"
    assert operation_type_label("SCALP_PRESSURE_STEAM") == "Scalping"


def test_summarize_game_entries():
    positions = [
        {
            "home": "Flamengo",
            "away": "Palmeiras",
            "operation": "LAY Visitante",
            "market": "Visitante",
            "modo": "Pré-live",
            "side": "LAY",
        },
        {
            "home": "Flamengo",
            "away": "Palmeiras",
            "operation": "BACK Under 2.5 HT",
            "market": "Under 2.5 HT",
            "modo": "Pré-live",
            "side": "BACK",
        },
    ]
    s = summarize_game_entries("Flamengo RJ", "Palmeiras SP", positions)
    assert s["modo"] == "Pré-live"
    assert "Visitante" in s["mercado"]
    assert "LAY Visitante" in s["operacao"]


def test_format_operation_lay_visitante():
    assert format_operation("LAY", "away_win_ft") == "LAY Visitante"


def test_format_operation_back_under():
    assert format_operation("BACK", "under25_ft") == "BACK Under 2.5 FT"


def test_format_operation_back_empate():
    assert format_operation("BACK", "draw_ft") == "BACK Empate"


def test_teams_match_flamengo_alias():
    assert teams_match("Flamengo RJ", "Vitoria", "Flamengo", "Vitoria BA")


def test_find_operation_for_game():
    positions = [{"home": "Flamengo", "away": "Palmeiras", "operation": "LAY Visitante"}]
    assert find_operation_for_game("Flamengo MG", "Palmeiras SP", positions) in ("LAY Visitante", "—")

    assert market_label("over15_ft") == "Over 1.5 FT"
