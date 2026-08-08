"""Saída final da operação — todos os campos solicitados."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TradeRecommendation:
    home: str
    away: str
    market: str
    action: str  # ENTER | SKIP

    # Probabilidades
    probabilidade_estimada: float
    prob_home: float
    prob_draw: float
    prob_away: float
    p_lucro_ht: float

    # Odds
    odd_justa: float
    phi_seguranca: float
    odd_minima_entrada: float
    odd_mercado: float | None
    edge_pp: float | None          # prob_estimada - prob_implícita
    implied_market: float | None

    # P&L e banca
    lucro_estimado_pct: float      # retorno esperado % sobre stake (trade HT)
    kelly_cheio: float
    kelly_quarto: float
    pct_banca: float
    stake_valor: float
    confianca: float

    # Meta
    model_loaded: bool
    schedule_notes: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}

    def report(self) -> str:
        mkt = {"home_win_ft": "Mandante FT", "draw_ft": "Empate FT", "away_win_ft": "Visitante FT"}.get(
            self.market, self.market
        )
        lines = [
            f"{'='*62}",
            f"{self.home} x {self.away}  |  {mkt}  ->  {self.action}",
            f"",
            f"PROBABILIDADE ESTIMADA:     {self.probabilidade_estimada:.2%}",
            f"  (H {self.prob_home:.1%} | E {self.prob_draw:.1%} | A {self.prob_away:.1%})",
            f"P(lucro no HT):             {self.p_lucro_ht:.2%}",
            f"",
            f"ODD JUSTA:                  {self.odd_justa:.3f}",
            f"φ SEGURANCA (erro modelo): {self.phi_seguranca:.3f}",
            f"ODD MÍNIMA ENTRADA:         {self.odd_minima_entrada:.3f}",
        ]
        if self.odd_mercado:
            lines += [
                f"ODD MERCADO:                {self.odd_mercado:.3f}",
                f"Prob. implícita mercado:    {self.implied_market:.2%}" if self.implied_market else "",
                f"EDGE:                       {self.edge_pp:+.2f} p.p." if self.edge_pp is not None else "",
            ]
        lines += [
            f"",
            f"LUCRO ESTIMADO (HT):        {self.lucro_estimado_pct:+.2f}%",
            f"KELLY CHEIO:                {self.kelly_cheio:.2%}",
            f"¼ KELLY:                    {self.kelly_quarto:.2%}",
            f"% DA BANCA:                 {self.pct_banca:.2%}  (= R$ {self.stake_valor:.2f})",
            f"CONFIANÇA:                  {self.confianca:.0f}/100",
            f"Modelo ML:                  {'sim' if self.model_loaded else 'Poisson (treine: main.py treinar)'}",
        ]
        if self.schedule_notes:
            lines.append("")
            lines.append("AGENDA / CALENDÁRIO:")
            for n in self.schedule_notes:
                lines.append(f"  • {n}")
        if self.reasons:
            lines.append("")
            lines.append("Motivos SKIP: " + "; ".join(self.reasons))
        return "\n".join(l for l in lines if l is not None)
