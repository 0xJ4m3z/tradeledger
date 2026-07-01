"""Tests for pchip_smooth in app/services/chart_utils."""
from app.services.chart_utils import pchip_smooth


class TestPchipSmooth:
    # ── Edge cases: degenerate inputs ─────────────────────────────────────────

    def test_empty_returns_empty(self):
        xs, ys = pchip_smooth([], [], n=50)
        assert xs == []
        assert ys == []

    def test_single_point_returns_original(self):
        xs, ys = pchip_smooth([1.0], [5.0], n=50)
        assert xs == [1.0]
        assert ys == [5.0]

    def test_two_points_returns_original(self):
        x, y = [0.0, 1.0], [0.0, 10.0]
        xs, ys = pchip_smooth(x, y, n=50)
        assert xs == x
        assert ys == y

    def test_fewer_than_3_distinct_points_returns_original(self):
        """Duplicate x reduces effective count below 3 → fall back."""
        x = [0.0, 1.0, 1.0]   # only 2 distinct x values after dedup
        y = [0.0, 5.0, 6.0]
        xs, ys = pchip_smooth(x, y, n=100)
        assert xs == x
        assert ys == y

    def test_all_duplicate_x_does_not_crash(self):
        x = [1.0, 1.0, 1.0]
        y = [3.0, 4.0, 5.0]
        xs, ys = pchip_smooth(x, y, n=100)
        assert len(xs) >= 1  # returned something without raising

    # ── Output shape ──────────────────────────────────────────────────────────

    def test_output_has_n_points(self):
        x = [0.0, 1.0, 2.0, 3.0]
        y = [0.0, 5.0, 3.0, 8.0]
        xs, ys = pchip_smooth(x, y, n=100)
        assert len(xs) == 100
        assert len(ys) == 100

    def test_default_n_is_300(self):
        x = [0.0, 1.0, 2.0, 3.0]
        y = [0.0, 5.0, 3.0, 8.0]
        xs, ys = pchip_smooth(x, y)
        assert len(xs) == 300
        assert len(ys) == 300

    # ── Interpolation correctness ─────────────────────────────────────────────

    def test_endpoints_match_original_data(self):
        """Curve must pass exactly through first and last data points."""
        x = [0.0, 1.0, 2.0, 3.0]
        y = [0.0, 5.0, 3.0, 8.0]
        xs, ys = pchip_smooth(x, y, n=200)
        assert abs(ys[0]  - y[0])  < 1e-9
        assert abs(ys[-1] - y[-1]) < 1e-9

    def test_final_value_matches_final_input(self):
        """Last smoothed value must equal the last actual P/L point."""
        x = [0.0, 1.0, 2.0, 3.0, 4.0]
        y = [0.0, 10.0, -5.0, 20.0, 15.0]
        _, ys = pchip_smooth(x, y, n=300)
        assert abs(ys[-1] - y[-1]) < 1e-9

    def test_output_x_spans_full_input_range(self):
        x = [0.0, 1.0, 2.0, 3.0]
        y = [0.0, 5.0, 3.0, 8.0]
        xs, _ = pchip_smooth(x, y, n=200)
        assert abs(xs[0]  - x[0])  < 1e-9
        assert abs(xs[-1] - x[-1]) < 1e-9

    # ── Shape-preserving (monotonicity / no overshoot) ────────────────────────

    def test_monotone_rise_stays_monotone(self):
        """PCHIP must not introduce dips in a strictly increasing sequence."""
        x = [0.0, 1.0, 2.0, 3.0, 4.0]
        y = [0.0, 2.0, 4.0, 6.0, 8.0]
        _, ys = pchip_smooth(x, y, n=300)
        diffs = [ys[i + 1] - ys[i] for i in range(len(ys) - 1)]
        assert all(d >= -1e-9 for d in diffs), "Monotone sequence must not dip"

    def test_monotone_fall_stays_monotone(self):
        """PCHIP must not introduce peaks in a strictly decreasing sequence."""
        x = [0.0, 1.0, 2.0, 3.0, 4.0]
        y = [8.0, 6.0, 4.0, 2.0, 0.0]
        _, ys = pchip_smooth(x, y, n=300)
        diffs = [ys[i + 1] - ys[i] for i in range(len(ys) - 1)]
        assert all(d <= 1e-9 for d in diffs), "Monotone fall must not peak"

    def test_no_overshoot_beyond_data_range(self):
        """Smoothed values must stay within the input y-value range."""
        x = [0.0, 1.0, 2.0, 3.0, 4.0]
        y = [0.0, 10.0, -5.0, 20.0, 15.0]
        _, ys = pchip_smooth(x, y, n=300)
        assert min(ys) >= min(y) - 0.01
        assert max(ys) <= max(y) + 0.01

    def test_flat_segment_does_not_overshoot(self):
        """A flat region between two rising segments must stay close to its value."""
        x = [0.0, 1.0, 2.0, 3.0]
        y = [0.0, 5.0, 5.0, 8.0]
        xs, ys = pchip_smooth(x, y, n=300)
        # Points strictly between x=1 and x=2 should be very close to 5.0
        mid = [(xv, yv) for xv, yv in zip(xs, ys) if 1.0 < xv < 2.0]
        for xv, yv in mid:
            assert abs(yv - 5.0) < 0.1, f"Flat segment overshot at x={xv:.3f}: y={yv:.4f}"
