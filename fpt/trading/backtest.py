from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .config import load_config
from .fair_odds import check_value
from .ht_trading import estimate_ht_trade, ht_state_label, parse_ht_score
from .kelly import kelly_ht_trade
from .probabilities import estimate_match_probabilities
from .context import apply_context, ContextInput


@dataclass
class BacktestResult:
    trades: pd.DataFrame
    summary: dict

    def print_summary(self):
        s = self.summary
        print(f"Trades: {s['n_trades']} | Win rate: {s['win_rate']:.1%}")
        print(f"P&L total: {s['total_pnl']:.2f} | ROI: {s['roi']:.2f}%")
        print(f"Max drawdown: {s['max_drawdown']:.2f} | Sharpe≈: {s['sharpe']:.2f}")
        print(f"Melhor φ testado: {s.get('best_phi', '—')}")


def run_backtest(
    df: pd.DataFrame,
    league_slug: str | None = None,
    market: str = "home_win_ft",
    phi: float | None = None,
    bankroll: float = 1000.0,
    test_fraction: float = 0.25,
) -> BacktestResult:
    """
    Backtest walk-forward simplificado.
    Entrada: back pré-jogo @ Odd_*_FT | Saída: lay proxy no HT.
    """
    cfg = load_config()
    phi = phi or cfg["trading"]["phi"]
    comm = cfg["trading"]["commission"]

    odd_col = {"home_win_ft": "Odd_1_FT", "draw_ft": "Odd_X_FT", "away_win_ft": "Odd_2_FT"}[market]
    sub = df.dropna(subset=[odd_col, "Home_Score", "Away_Score", "Home", "Away"]).copy()
    if league_slug and "League_Slug" in sub.columns:
        sub = sub[sub["League_Slug"] == league_slug]
    if "Date" in sub.columns:
        sub = sub.sort_values("Date")

    n = len(sub)
    split = int(n * (1 - test_fraction))
    train = sub.iloc[:split]
    test = sub.iloc[split:]

    records = []
    rolling_bank = bankroll

    for idx, row in test.iterrows():
        home, away = row["Home"], row["Away"]
        entry_odd = float(row[odd_col])
        if entry_odd <= 1.05:
            continue

        hist = train if len(train) < idx else sub.loc[:idx].iloc[:-1]
        if len(hist) < 50:
            continue

        probs = estimate_match_probabilities(hist, home, away, league_slug)
        adj = apply_context(probs, hist, home, away, ContextInput())
        p = adj.home if market == "home_win_ft" else adj.draw if market == "draw_ft" else adj.away

        val = check_value(p, entry_odd, phi)
        if not val.has_value:
            continue

        ht_est = estimate_ht_trade(probs, entry_odd, market)
        stake_d = kelly_ht_trade(ht_est, entry_odd, rolling_bank, probs.sample_home, probs.sample_away, val.edge_pct)
        if stake_d.stake_amount <= 0:
            continue

        hg, ag = parse_ht_score(row.get("Min_Goals_Home"), row.get("Min_Goals_Away"))
        state = ht_state_label(hg, ag, market)
        mults = estimate_ht_trade(probs, entry_odd, market).exit_multipliers
        exit_odd = entry_odd * mults.get(state, 1.0)
        pnl_pct = (entry_odd / exit_odd - 1) * (1 - 2 * comm)
        pnl = stake_d.stake_amount * pnl_pct
        rolling_bank += pnl

        records.append({
            "date": row.get("Date"),
            "home": home,
            "away": away,
            "market": market,
            "entry_odd": entry_odd,
            "exit_odd_est": round(exit_odd, 3),
            "ht_score": f"{hg}-{ag}",
            "ht_state": state,
            "p_model": p,
            "stake": stake_d.stake_amount,
            "pnl": round(pnl, 2),
            "bankroll": round(rolling_bank, 2),
            "win": pnl > 0,
        })

    trades = pd.DataFrame(records)
    summary = _summarize(trades, bankroll)
    summary["phi"] = phi
    return BacktestResult(trades=trades, summary=summary)


def optimize_phi(
    df: pd.DataFrame,
    league_slug: str | None = None,
    market: str = "home_win_ft",
    phi_grid: list[float] | None = None,
) -> pd.DataFrame:
    """Testa vários φ em validação — NÃO use o mesmo set para escolher e reportar."""
    cfg = load_config()
    phi_grid = phi_grid or cfg.get("simulation", {}).get("default_phi_grid", [1.05, 1.08, 1.10, 1.12])
    rows = []
    for phi in phi_grid:
        res = run_backtest(df, league_slug, market, phi=phi)
        rows.append({"phi": phi, **res.summary})
    return pd.DataFrame(rows).sort_values("roi", ascending=False)


def _summarize(trades: pd.DataFrame, start_bankroll: float) -> dict:
    if trades.empty:
        return {
            "n_trades": 0, "win_rate": 0, "total_pnl": 0, "roi": 0,
            "max_drawdown": 0, "sharpe": 0,
        }
    pnl = trades["pnl"]
    cum = pnl.cumsum()
    peak = cum.cummax()
    dd = (cum - peak).min()
    std = pnl.std()
    sharpe = (pnl.mean() / std * (len(pnl) ** 0.5)) if std > 0 else 0
    return {
        "n_trades": len(trades),
        "win_rate": trades["win"].mean(),
        "total_pnl": round(pnl.sum(), 2),
        "roi": round(pnl.sum() / start_bankroll * 100, 2),
        "max_drawdown": round(float(dd), 2),
        "sharpe": round(float(sharpe), 2),
        "best_phi": None,
    }
