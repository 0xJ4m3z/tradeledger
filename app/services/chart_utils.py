"""Chart rendering utilities — pure numpy, no Qt dependency."""
from __future__ import annotations

from typing import List, Tuple


def pchip_smooth(
    x_vals: List[float],
    y_vals: List[float],
    n: int = 300,
) -> Tuple[List[float], List[float]]:
    """Shape-preserving monotone cubic interpolation (PCHIP) using numpy.

    Returns (x_dense, y_dense) — n evenly-spaced visual points suitable for
    drawing a smooth line through the original data.

    Falls back to (x_vals, y_vals) unchanged when:
    - fewer than 3 distinct x values exist
    - any numeric error occurs during interpolation

    The Fritsch-Carlson algorithm guarantees no spurious overshoots or
    sign-flips: local extrema in the input stay local extrema in the curve,
    and monotone segments remain monotone.
    """
    try:
        import numpy as np
    except ImportError:
        return x_vals, y_vals

    if not x_vals:
        return x_vals, y_vals

    x = np.asarray(x_vals, dtype=float)
    y = np.asarray(y_vals, dtype=float)

    # Deduplicate: keep first occurrence of each unique x value
    _, uniq = np.unique(x, return_index=True)
    x, y = x[uniq], y[uniq]

    if len(x) < 3:
        return list(x_vals), list(y_vals)

    try:
        h = np.diff(x)                                        # segment widths
        h_safe = np.where(h != 0.0, h, 1e-14)
        d = np.diff(y) / h_safe                               # finite-difference slopes

        # ── Fritsch-Carlson slopes ─────────────────────────────────────────────
        m = np.empty(len(x))
        m[0]  = d[0]
        m[-1] = d[-1]

        for k in range(1, len(x) - 1):
            if d[k-1] * d[k] <= 0.0:
                m[k] = 0.0          # local extremum: flat slope prevents overshoot
            else:
                w1 = 2.0 * h[k] + h[k-1]
                w2 =       h[k] + 2.0 * h[k-1]
                m[k] = (w1 + w2) / (w1 / d[k-1] + w2 / d[k])

        # ── Monotonicity constraint on each segment ────────────────────────────
        for k in range(len(d)):
            if abs(d[k]) < 1e-14:
                m[k] = m[k + 1] = 0.0
            else:
                a, b = m[k] / d[k], m[k + 1] / d[k]
                r = a * a + b * b
                if r > 9.0:
                    t = 3.0 / np.sqrt(r)
                    m[k]     = t * a * d[k]
                    m[k + 1] = t * b * d[k]

        # ── Evaluate on dense grid ─────────────────────────────────────────────
        xs  = np.linspace(x[0], x[-1], n)
        seg = np.clip(np.searchsorted(x, xs, side="right") - 1, 0, len(x) - 2)

        t   = (xs - x[seg]) / h_safe[seg]
        t2  = t * t
        t3  = t2 * t

        h00 =  2.0 * t3 - 3.0 * t2 + 1.0
        h10 =        t3 - 2.0 * t2 + t
        h01 = -2.0 * t3 + 3.0 * t2
        h11 =        t3 -       t2

        ys = (h00 * y[seg]
              + h10 * h_safe[seg] * m[seg]
              + h01 * y[seg + 1]
              + h11 * h_safe[seg] * m[seg + 1])

        return list(xs), list(ys)

    except Exception:
        return list(x_vals), list(y_vals)
