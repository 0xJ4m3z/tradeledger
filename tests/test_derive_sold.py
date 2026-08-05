"""Tests for derive_sold_from_activity — ephemeral SOLD stubs from activity SELLs."""
from app.models import UserActivity
from app.services.pnl_today import derive_sold_from_activity

_MKT = "Bitcoin Up or Down - August 5, 6:00PM-6:05PM ET"
_OUT = "Down"
_TS  = 1722905052   # some epoch


def _act(side, usdc, size=5.0, ts=_TS, outcome=_OUT, slug=None):
    return UserActivity(
        timestamp=ts,
        type="TRADE",
        title=_MKT,
        outcome=outcome,
        side=side,
        size=size,
        usdc_size=usdc,
        price=usdc / size,
        slug=slug,
    )


def test_sell_generates_stub():
    activity = [_act("BUY", 4.91), _act("SELL", 4.95)]
    stubs = derive_sold_from_activity(activity)
    assert len(stubs) == 1
    s = stubs[0]
    assert s.market == _MKT
    assert s.outcome_held == _OUT
    assert s.close_type == "SOLD"


def test_cost_basis_from_buys():
    activity = [_act("BUY", 4.91), _act("SELL", 4.95)]
    stubs = derive_sold_from_activity(activity)
    assert abs(stubs[0].cost_basis - 4.91) < 0.001


def test_redeem_value_from_sells():
    activity = [_act("BUY", 4.91), _act("SELL", 4.95)]
    stubs = derive_sold_from_activity(activity)
    assert abs(stubs[0].redeem_value - 4.95) < 0.001


def test_multiple_sells_aggregated():
    # Two SELL events for the same position (e.g. partial fills)
    activity = [
        _act("BUY", 4.91, size=5.0),
        _act("SELL", 2.50, size=2.5, ts=_TS),
        _act("SELL", 2.45, size=2.5, ts=_TS + 10),
    ]
    stubs = derive_sold_from_activity(activity)
    assert len(stubs) == 1
    assert abs(stubs[0].redeem_value - 4.95) < 0.001
    assert abs(stubs[0].quantity - 5.0) < 0.001


def test_latest_sell_ts_used():
    activity = [
        _act("BUY",  4.91, ts=_TS - 60),
        _act("SELL", 2.50, ts=_TS),
        _act("SELL", 2.45, ts=_TS + 30),
    ]
    stubs = derive_sold_from_activity(activity)
    assert stubs[0].closed_at == _TS + 30


def test_no_sell_no_stub():
    activity = [_act("BUY", 4.91)]
    stubs = derive_sold_from_activity(activity)
    assert stubs == []


def test_empty_activity():
    assert derive_sold_from_activity([]) == []


def test_slug_carried_through():
    activity = [
        _act("BUY",  4.91, slug=None),
        _act("SELL", 4.95, slug="bitcoin-up-or-down-aug5"),
    ]
    stubs = derive_sold_from_activity(activity)
    assert stubs[0].slug == "bitcoin-up-or-down-aug5"


def test_distinct_markets_produce_separate_stubs():
    mkt2 = "Ethereum Up or Down - August 5, 6:00PM-6:05PM ET"
    activity = [
        _act("BUY",  4.91),
        _act("SELL", 4.95),
        UserActivity(timestamp=_TS, type="TRADE", title=mkt2, outcome="Up",
                     side="BUY",  size=5.0, usdc_size=4.80, price=0.96),
        UserActivity(timestamp=_TS + 1, type="TRADE", title=mkt2, outcome="Up",
                     side="SELL", size=5.0, usdc_size=4.90, price=0.98),
    ]
    stubs = derive_sold_from_activity(activity)
    markets = {s.market for s in stubs}
    assert _MKT in markets
    assert mkt2 in markets


def test_winning_outcome_blank_pending():
    activity = [_act("BUY", 4.91), _act("SELL", 4.95)]
    stubs = derive_sold_from_activity(activity)
    assert stubs[0].winning_outcome == ""   # unknown until market resolves


def test_redeemed_false_for_stubs():
    activity = [_act("BUY", 4.91), _act("SELL", 4.95)]
    stubs = derive_sold_from_activity(activity)
    assert stubs[0].redeemed is False
