"""Grupos de colunas FPT utilizáveis (pré-jogo: odds; pós-jogo: stats rolling)."""

# Odds pré-jogo — mercado implícito (features + referência)
ODDS_1X2 = ["Odd_1_FT", "Odd_X_FT", "Odd_2_FT"]
ODDS_1X2_HT = ["Odd_1_HT", "Odd_X_HT", "Odd_2_HT"]
ODDS_OU_FT = ["Over_FT_0_5", "Under_FT_0_5", "Over_FT_1_5", "Under_FT_1_5",
              "Over_FT_2_5", "Under_FT_2_5", "Over_FT_3_5", "Under_FT_3_5"]
ODDS_OU_HT = ["Over_HT_0_5", "Under_HT_0_5", "Over_HT_1_5", "Under_HT_1_5", "Over_HT_2_5", "Under_HT_2_5"]
ODDS_BTTS = ["BTTS_Yes", "BTTS_No"]
ODDS_DC = ["DC_1X", "DC_12", "DC_X2"]

# Stats FT — rolling form (usar histórico do time, não do jogo atual)
STAT_FT_HOME_PREFIX = [
    "xG_Home_FT", "xGOT_Home_FT", "xA_Home_FT", "Possession_Home_FT",
    "Total_Shots_Home_FT", "Shots_On_Target_Home_FT", "Big_Chances_Home_FT",
    "Corners_Home_FT", "Yellow_Cards_Home_FT", "Red_Cards_Home_FT",
    "Fouls_Home_FT", "Goalkeeper_Saves_Home_FT", "Touches_Box_Home_FT",
    "Duels_Won_Home_FT", "Passes_Pct_Home_FT", "Goals_Prevented_Home_FT",
]
STAT_FT_AWAY_PREFIX = [c.replace("Home", "Away") for c in STAT_FT_HOME_PREFIX]

STAT_HT_HOME_PREFIX = [
    "xG_Home_HT", "xGOT_Home_HT", "Possession_Home_HT", "Total_Shots_Home_HT",
    "Shots_On_Target_Home_HT", "Big_Chances_Home_HT", "Corners_Home_HT",
    "Yellow_Cards_Home_HT", "Fouls_Home_HT",
]
STAT_HT_AWAY_PREFIX = [c.replace("Home", "Away") for c in STAT_HT_HOME_PREFIX]

META = ["Match_ID", "Country", "Season", "Div", "League", "Date", "Time", "Round",
        "Home", "Away", "Home_Score", "Away_Score", "Min_Goals_Home", "Min_Goals_Away",
        "League_Slug", "League_Name"]

LEAGUE_TIER = {
    "serie-a-betano": 5,
    "serie-b": 4,
    "serie-b-superbet": 4,
    "serie-c": 3,
    "serie-d": 2,
    "copa-betano-do-brasil": 4,
}
