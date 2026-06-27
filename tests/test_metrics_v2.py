"""
Tests for v0.2 metrics additions: compute_total_tracked_value.
"""

from app.services.metrics import compute_total_tracked_value


class TestTotalTrackedValue:
    def test_sums_active_and_wallet(self):
        assert compute_total_tracked_value(2256.00, 1244.00) == 3500.00

    def test_zero_wallet_value(self):
        assert compute_total_tracked_value(2256.00, 0.0) == 2256.00

    def test_zero_active_value(self):
        assert compute_total_tracked_value(0.0, 1244.00) == 1244.00

    def test_both_zero(self):
        assert compute_total_tracked_value(0.0, 0.0) == 0.0

    def test_fractional_values_rounded_to_cents(self):
        result = compute_total_tracked_value(100.001, 200.004)
        assert result == round(100.001 + 200.004, 2)

    def test_large_values(self):
        assert compute_total_tracked_value(50_000.00, 25_000.00) == 75_000.00
