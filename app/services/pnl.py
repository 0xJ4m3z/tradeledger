from typing import List

import pandas as pd

from app.models import ActivePosition, ResolvedPosition


def calc_unrealized_pnl(positions: List[ActivePosition]) -> float:
    return sum(p.unrealized_pnl for p in positions)


def calc_realized_pnl(positions: List[ResolvedPosition]) -> float:
    return sum(p.realized_pnl for p in positions)


def calc_cumulative_pnl(resolved: List[ResolvedPosition]) -> pd.DataFrame:
    """Return a DataFrame with columns [date, cumulative_pnl] sorted chronologically."""
    if not resolved:
        return pd.DataFrame(columns=["date", "cumulative_pnl"])

    rows = [
        {"date": p.resolved_date, "pnl": p.realized_pnl}
        for p in resolved
        if p.resolved_date
    ]
    if not rows:
        return pd.DataFrame(columns=["date", "cumulative_pnl"])

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    df["cumulative_pnl"] = df["pnl"].cumsum()
    return df[["date", "cumulative_pnl"]]
