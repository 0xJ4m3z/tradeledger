"""Tests for market window end-time parsing (app/services/window_timing.py).

_window_end_et / _window_closed drive the Sold→Closed graduation in the overview:
a SOLD position stays in Sold while its window is open, moves to Closed after.
"""
from datetime import datetime, timezone
from unittest.mock import patch

from app.services.window_timing import window_closed, window_end_et

try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:
    from datetime import timedelta
    _ET = timezone(timedelta(hours=-4))   # EDT for Aug dates


# ── window_end_et ──────────────────────────────────────────────────────────────

def test_parses_both_ampm():
    end = window_end_et("BNB Up or Down - August 5, 4:55PM-5:00PM ET",
                        resolved_date="2026-08-05", closed_at=None)
    assert end is not None
    assert end.hour == 17 and end.minute == 0   # 5:00 PM ET


def test_parses_end_ampm_only():
    end = window_end_et("Solana Up or Down - August 5, 4:45-5:00PM ET",
                        resolved_date="2026-08-05", closed_at=None)
    assert end is not None
    assert end.hour == 17 and end.minute == 0


def test_parses_am_window():
    end = window_end_et("Bitcoin Up or Down - August 5, 10:40-10:45AM ET",
                        resolved_date="2026-08-05", closed_at=None)
    assert end is not None
    assert end.hour == 10 and end.minute == 45


def test_no_window_in_title_returns_none():
    end = window_end_et("Bitcoin above 63,200 on August 5, 3PM ET?",
                        resolved_date="2026-08-05", closed_at=None)
    assert end is None


def test_full_iso_resolved_date_used_directly():
    # "2026-08-05T21:00:00Z" = 5:00 PM ET in summer (UTC-4)
    end = window_end_et("BNB Up or Down - August 5, 4:55PM-5:00PM ET",
                        resolved_date="2026-08-05T21:00:00Z", closed_at=None)
    assert end is not None
    end_utc = end.astimezone(timezone.utc)
    assert end_utc.hour == 21 and end_utc.minute == 0


def test_falls_back_to_closed_at_date():
    import time
    # 2026-08-05 in ET — use epoch for noon UTC that day
    noon_aug5_utc = int(datetime(2026, 8, 5, 16, 0, tzinfo=timezone.utc).timestamp())
    end = window_end_et("BNB Up or Down - August 5, 4:55PM-5:00PM ET",
                        resolved_date=None, closed_at=noon_aug5_utc)
    assert end is not None
    assert end.hour == 17 and end.minute == 0


# ── window_closed ──────────────────────────────────────────────────────────────

def test_window_closed_true_after_end():
    # Mock now to 5:05 PM ET (21:05 UTC)
    future = datetime(2026, 8, 5, 21, 5, tzinfo=timezone.utc)
    with patch("app.services.window_timing.datetime") as mock_dt:
        mock_dt.now.return_value = future
        mock_dt.fromtimestamp = datetime.fromtimestamp
        mock_dt.strptime = datetime.strptime
        mock_dt.fromisoformat = datetime.fromisoformat
        result = window_closed("BNB Up or Down - August 5, 4:55PM-5:00PM ET",
                               "2026-08-05", None)
    assert result is True


def test_window_closed_false_before_end():
    # Mock now to 4:55 PM ET (20:55 UTC)
    before = datetime(2026, 8, 5, 20, 55, tzinfo=timezone.utc)
    with patch("app.services.window_timing.datetime") as mock_dt:
        mock_dt.now.return_value = before
        mock_dt.fromtimestamp = datetime.fromtimestamp
        mock_dt.strptime = datetime.strptime
        mock_dt.fromisoformat = datetime.fromisoformat
        result = window_closed("BNB Up or Down - August 5, 4:55PM-5:00PM ET",
                               "2026-08-05", None)
    assert result is False


def test_window_closed_false_unparseable_title():
    # Positions with non-window titles (e.g. "Bitcoin above X on Date?")
    # always return False — safe fallback keeps them visible in Sold
    assert window_closed("S&P 500 (SPX) Opens Up or Down on August 5?",
                         "2026-08-05", None) is False
