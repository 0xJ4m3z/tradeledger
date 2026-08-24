from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


@dataclass
class ActivePosition:
    market: str
    outcome: str
    quantity: float
    avg_cost: float
    current_price: float
    slug: Optional[str] = None        # Polymarket eventSlug → polymarket.com/event/{slug}
    asset_id: Optional[str] = None    # CLOB token ID → used for WebSocket market stream

    @property
    def current_value(self) -> float:
        return self.quantity * self.current_price

    @property
    def cost_basis(self) -> float:
        return self.quantity * self.avg_cost

    @property
    def unrealized_pnl(self) -> float:
        return self.current_value - self.cost_basis

    @property
    def unrealized_pnl_pct(self) -> float:
        if self.cost_basis == 0:
            return 0.0
        return (self.unrealized_pnl / self.cost_basis) * 100


@dataclass
class ResolvedPosition:
    market: str
    outcome_held: str
    winning_outcome: str
    quantity: float
    cost_basis: float
    redeem_value: float
    redeemed: bool
    resolved_date: Optional[str] = None
    closed_at: Optional[int] = None   # epoch seconds from API timestamp field
    close_type: str = "UNKNOWN"       # REDEEMED_WIN | SOLD | RESOLVED_LOSS | UNKNOWN
    slug: Optional[str] = None        # Polymarket eventSlug → polymarket.com/event/{slug}

    @property
    def realized_pnl(self) -> float:
        return self.redeem_value - self.cost_basis

    @property
    def realized_pnl_pct(self) -> float:
        if self.cost_basis == 0:
            return 0.0
        return (self.realized_pnl / self.cost_basis) * 100

    @property
    def is_win(self) -> bool:
        """outcome_held == winning_outcome — deliberately NOT realized_pnl's
        sign. This distinguishes a correct directional call from a good
        execution: a stop-loss can fire at a real dollar loss on a market
        that goes on to resolve the user's way (see
        test_stop_loss_sold_negative_pnl_but_outcome_won — this was already
        broken once the other way, P/L sign standing in for outcome, and
        fixed). Don't conflate the two again.

        2026-08-24: except when winning_outcome is still empty — a SOLD
        position whose market hasn't resolved yet (see
        build_sold_stub_positions()'s "unknown until market resolves" note
        in pnl_today.py). outcome_held is never "", so that always evaluated
        to a confident False ("Loss") even for a position that was
        genuinely profitable the moment it was sold — the real bug behind
        a real, profitable early exit showing up red everywhere is_win
        flows (Overview's closed list, the P/L tab, this position's own
        transaction dialog), while that same dialog's Net tile correctly
        showed green, because it's computed independently from raw
        activity rather than through this property. Fall back to the one
        thing that IS actually known yet — realized P/L — only for that
        unresolved case. Once the market resolves and winning_outcome gets
        populated for real (the position "graduates" out of stub status),
        this reverts to the outcome-based signal automatically."""
        if not self.winning_outcome:
            return self.realized_pnl >= 0
        return self.outcome_held == self.winning_outcome


@dataclass
class UserActivity:
    timestamp: int    # epoch seconds
    type: str         # TRADE, REDEEM, SPLIT, MERGE, REWARD, …
    title: str        # market name
    outcome: str
    side: str         # BUY | SELL | ""
    size: float       # tokens
    usdc_size: float  # dollars
    price: float
    slug: Optional[str] = None  # Polymarket eventSlug → polymarket.com/event/{slug}

    @property
    def datetime_utc(self) -> str:
        return datetime.fromtimestamp(self.timestamp, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
