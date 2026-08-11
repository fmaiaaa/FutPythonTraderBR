from __future__ import annotations

import pandas as pd


def label_ticks(df: pd.DataFrame, horizons: tuple[int, ...] = (10, 30, 60)) -> pd.DataFrame:
    """Adiciona colunas forward de odd back_home (+10/+30/+60s)."""
    if df.empty:
        return df
    out = df.copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], errors="coerce")
    out = out.sort_values(["home", "away", "timestamp"])

    for sec in horizons:
        col = f"back_home_fwd_{sec}s"
        parts = []
        for (_, _), g in out.groupby(["home", "away"], sort=False):
            g = g.sort_values("timestamp")
            values = g["back_home"].tolist()
            times = g["timestamp"].tolist()
            fwd = []
            for i, t0 in enumerate(times):
                target = t0 + pd.Timedelta(seconds=sec)
                j = i + 1
                best = None
                while j < len(times) and times[j] <= target:
                    best = values[j]
                    j += 1
                fwd.append(best)
            parts.append(pd.Series(fwd, index=g.index))
        out[col] = pd.concat(parts).sort_index()
        out[f"delta_back_home_{sec}s"] = out[col] - out["back_home"]
    return out
