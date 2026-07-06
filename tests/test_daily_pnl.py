"""Tests for app/services/daily_pnl.py."""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.models import ResolvedPosition
from app.services.daily_pnl import (
    build_daily_pnl_rows,
    sort_closed_positions_newest_first,
)

_ET = ZoneInfo("America/New_York")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _ts(d: date, hour: int = 12) -> int:
    """Return epoch seconds for a given date at the given ET hour."""
    return int(datetime(d.year, d.month, d.day, hour, 0, 0, tzinfo=_ET).timestamp())


def _pos(
    market: str = "M",
    outcome: str = "Yes",
    cost: float = 10.0,
    redeem: float = 20.0,
    resolved_date: str | None = None,
    closed_at: int | None = None,
) -> ResolvedPosition:
    return ResolvedPosition(
        market=market,
        outcome_held=outcome,
        winning_outcome=outcome,
        quantity=100,
        cost_basis=cost,
        redeem_value=redeem,
        redeemed=True,
        resolved_date=resolved_date,
        closed_at=closed_at,
    )


# ── sort_closed_positions_newest_first ────────────────────────────────────────

class TestSortNewestFirst:
    def test_sorts_by_closed_at_descending(self):
        today = date(2025, 6, 1)
        yesterday = date(2025, 5, 31)
        p_new = _pos("A", closed_at=_ts(today))
        p_old = _pos("B", closed_at=_ts(yesterday))
        result = sort_closed_positions_newest_first([p_old, p_new])
        assert result[0].market == "A"
        assert result[1].market == "B"

    def test_closed_at_epoch_beats_resolved_date_only(self):
        """A position with closed_at ranks before one with only resolved_date.

        The key is (closed_at or 0, resolved_date).  Any real closed_at epoch
        (~1.6B+) is larger than the 0 fallback used for positions lacking it, so
        positions with closed_at always sort before those relying on resolved_date
        regardless of which calendar date appears newer.
        """
        p_with_epoch = _pos("A", closed_at=_ts(date(2025, 1, 1)))
        p_date_only  = _pos("B", resolved_date="2026-01-01")  # newer calendar date, no epoch
        result = sort_closed_positions_newest_first([p_date_only, p_with_epoch])
        assert result[0].market == "A"  # epoch wins over resolved_date-only
        assert result[1].market == "B"

    def test_resolved_date_fallback_descending(self):
        """Positions without closed_at fall back to resolved_date sorting."""
        p1 = _pos("A", resolved_date="2025-03-15")
        p2 = _pos("B", resolved_date="2025-01-01")
        p3 = _pos("C", resolved_date="2025-06-30")
        result = sort_closed_positions_newest_first([p2, p1, p3])
        assert [p.market for p in result] == ["C", "A", "B"]

    def test_stable_for_positions_with_neither_field(self):
        """Positions missing both closed_at and resolved_date preserve relative order."""
        p1 = _pos("A")
        p2 = _pos("B")
        p3 = _pos("C")
        result = sort_closed_positions_newest_first([p1, p2, p3])
        # All have key (0, "") — stable sort preserves order
        assert [p.market for p in result] == ["A", "B", "C"]

    def test_returns_new_list(self):
        """Should not mutate the input list."""
        positions = [_pos("A", closed_at=100), _pos("B", closed_at=200)]
        original = list(positions)
        result = sort_closed_positions_newest_first(positions)
        assert positions == original  # input unchanged
        assert result is not positions

    def test_empty_input(self):
        assert sort_closed_positions_newest_first([]) == []

    def test_single_item(self):
        p = _pos("A", closed_at=12345)
        assert sort_closed_positions_newest_first([p]) == [p]

    def test_mixed_has_and_no_closed_at(self):
        """Positions with closed_at sort before those with only resolved_date (epoch 0 < any real ts)."""
        today_ts = _ts(date(2025, 6, 15))
        p_with_ts = _pos("New", closed_at=today_ts)
        p_date_only = _pos("Old", resolved_date="2024-01-01")
        # (today_ts, "") >> (0, "2024-01-01") → p_with_ts first
        result = sort_closed_positions_newest_first([p_date_only, p_with_ts])
        assert result[0].market == "New"
        assert result[1].market == "Old"

    def test_merge_keeps_newest_first(self):
        """Simulates a merge operation: new prepended to existing, then sorted."""
        existing = [
            _pos("E1", closed_at=_ts(date(2025, 5, 1))),
            _pos("E2", closed_at=_ts(date(2025, 4, 1))),
        ]
        incoming = [
            _pos("N1", closed_at=_ts(date(2025, 6, 1))),   # newer than existing
            _pos("N2", closed_at=_ts(date(2025, 4, 15))),  # between existing entries
        ]
        combined = sort_closed_positions_newest_first(incoming + existing)
        assert [p.market for p in combined] == ["N1", "E1", "N2", "E2"]

    def test_new_position_lands_at_top(self):
        """After merge, the newest position should be first."""
        old = [_pos("A", closed_at=_ts(date(2025, 1, 10)))]
        fresh = [_pos("B", closed_at=_ts(date(2025, 6, 20)))]
        result = sort_closed_positions_newest_first(fresh + old)
        assert result[0].market == "B"


# ── build_daily_pnl_rows ──────────────────────────────────────────────────────

class TestBuildDailyPnlRows:
    def test_empty_positions(self):
        assert build_daily_pnl_rows([], "all") == []

    def test_single_day_win(self):
        d = date(2025, 6, 1)
        p = _pos("M", cost=50.0, redeem=75.0, closed_at=_ts(d))
        rows = build_daily_pnl_rows([p], "all")
        assert len(rows) == 1
        assert rows[0]["date"] == d
        assert rows[0]["pnl"] == pytest.approx(25.0)
        assert rows[0]["count"] == 1
        assert rows[0]["wins"] == 1
        assert rows[0]["losses"] == 0
        assert rows[0]["cumulative"] == pytest.approx(25.0)

    def test_single_day_loss(self):
        d = date(2025, 6, 1)
        p = _pos("M", cost=50.0, redeem=0.0, closed_at=_ts(d))
        rows = build_daily_pnl_rows([p], "all")
        assert rows[0]["pnl"] == pytest.approx(-50.0)
        assert rows[0]["wins"] == 0
        assert rows[0]["losses"] == 1

    def test_multiple_days_newest_first(self):
        d1 = date(2025, 6, 1)
        d2 = date(2025, 6, 3)
        d3 = date(2025, 6, 5)
        positions = [
            _pos("A", cost=10.0, redeem=20.0, closed_at=_ts(d3)),
            _pos("B", cost=10.0, redeem=5.0,  closed_at=_ts(d1)),
            _pos("C", cost=10.0, redeem=15.0, closed_at=_ts(d2)),
        ]
        rows = build_daily_pnl_rows(positions, "all")
        assert len(rows) == 3
        assert rows[0]["date"] == d3   # newest first
        assert rows[1]["date"] == d2
        assert rows[2]["date"] == d1   # oldest last

    def test_cumulative_runs_oldest_to_newest(self):
        d1 = date(2025, 6, 1)
        d2 = date(2025, 6, 2)
        positions = [
            _pos("A", cost=10.0, redeem=20.0, closed_at=_ts(d1)),  # +10
            _pos("B", cost=10.0, redeem=5.0,  closed_at=_ts(d2)),  # -5
        ]
        rows = build_daily_pnl_rows(positions, "all")
        # rows[0] = d2 (newest), cumulative = +10 + (-5) = +5
        # rows[1] = d1 (oldest), cumulative = +10
        assert rows[0]["date"] == d2
        assert rows[0]["cumulative"] == pytest.approx(5.0)
        assert rows[1]["date"] == d1
        assert rows[1]["cumulative"] == pytest.approx(10.0)

    def test_same_day_aggregation(self):
        d = date(2025, 6, 1)
        positions = [
            _pos("A", cost=10.0, redeem=20.0, closed_at=_ts(d, hour=9)),   # +10
            _pos("B", cost=20.0, redeem=10.0, closed_at=_ts(d, hour=14)),  # -10
            _pos("C", cost=5.0,  redeem=15.0, closed_at=_ts(d, hour=16)),  # +10
        ]
        rows = build_daily_pnl_rows(positions, "all")
        assert len(rows) == 1
        assert rows[0]["count"] == 3
        assert rows[0]["wins"] == 2
        assert rows[0]["losses"] == 1
        assert rows[0]["pnl"] == pytest.approx(10.0)

    def test_resolved_date_fallback(self):
        """Positions without closed_at should use resolved_date."""
        p = _pos("M", cost=10.0, redeem=20.0, resolved_date="2025-05-15")
        rows = build_daily_pnl_rows([p], "all")
        assert len(rows) == 1
        assert rows[0]["date"] == date(2025, 5, 15)

    def test_positions_without_any_date_excluded(self):
        """Positions lacking both closed_at and resolved_date are skipped."""
        p_no_date = _pos("X", cost=10.0, redeem=20.0)
        p_with_ts = _pos("Y", cost=5.0,  redeem=10.0, closed_at=_ts(date(2025, 1, 1)))
        rows = build_daily_pnl_rows([p_no_date, p_with_ts], "all")
        assert len(rows) == 1
        assert rows[0]["date"] == date(2025, 1, 1)
