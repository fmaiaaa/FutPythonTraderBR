from __future__ import annotations

import re
import unicodedata

from .models import SofaScoreEvent

_STOPWORDS = {"fc", "sc", "ec", "ac", "cd", "cf", "clube", "futebol", "de", "da", "do", "the", "mk", "sk"}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower().strip())
    s = s.encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _tokens(s: str) -> set[str]:
    parts = [
        p for p in _norm(s).replace("-", " ").replace(".", " ").split()
        if p and p not in _STOPWORDS and len(p) > 1
    ]
    return set(parts)


def match_teams(fpt_home: str, fpt_away: str, event: SofaScoreEvent) -> bool:
    """Fuzzy match nomes FPT ↔ SofaScore (mesmo padrão Betfair)."""
    h_tok = _tokens(fpt_home)
    a_tok = _tokens(fpt_away)
    ev_h = _tokens(event.home)
    ev_a = _tokens(event.away)
    if not h_tok or not a_tok or not ev_h or not ev_a:
        h0 = (_norm(fpt_home).split() or [""])[0]
        a0 = (_norm(fpt_away).split() or [""])[0]
        ev_name = _norm(f"{event.home} {event.away}")
        return bool(h0 and a0 and h0 in ev_name and a0 in ev_name)

    h_overlap = len(h_tok & ev_h) / max(len(h_tok), 1)
    a_overlap = len(a_tok & ev_a) / max(len(a_tok), 1)
    if h_overlap >= 0.5 and a_overlap >= 0.5:
        return True

    # ordem invertida (raro)
    h_rev = len(h_tok & ev_a) / max(len(h_tok), 1)
    a_rev = len(a_tok & ev_h) / max(len(a_tok), 1)
    return h_rev >= 0.5 and a_rev >= 0.5


def find_event(
    fpt_home: str,
    fpt_away: str,
    events: list[SofaScoreEvent],
) -> SofaScoreEvent | None:
    for ev in events:
        if match_teams(fpt_home, fpt_away, ev):
            return ev
    return None
