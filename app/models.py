from dataclasses import dataclass
from typing import Optional


@dataclass
class ActivePosition:
    market: str
    outcome: str
    quantity: float
    avg_cost: float
    current_price: float

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
        return self.outcome_held == self.winning_outcome
