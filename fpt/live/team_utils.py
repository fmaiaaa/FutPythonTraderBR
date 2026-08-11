"""Utilitários de matching de times — sem dependências live pesadas."""
from __future__ import annotations


def teams_match(home_a: str, away_a: str, home_b: str, away_b: str) -> bool:
    """Fuzzy match FPT ↔ posição/alerta (Flamengo ~ Flamengo RJ)."""
    from fpt.integrations.sofascore.match import _tokens

    ha, aa = _tokens(home_a), _tokens(away_a)
    hb, ab = _tokens(home_b), _tokens(away_b)
    if not ha or not aa or not hb or not ab:
        return home_a == home_b and away_a == away_b
    h_ok = len(ha & hb) / max(len(ha), 1) >= 0.5
    a_ok = len(aa & ab) / max(len(aa), 1) >= 0.5
    if h_ok and a_ok:
        return True
    h_rev = len(ha & ab) / max(len(ha), 1) >= 0.5
    a_rev = len(aa & hb) / max(len(aa), 1) >= 0.5
    return h_rev and a_rev
