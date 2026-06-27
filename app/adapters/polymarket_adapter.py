"""
Read-only Polymarket position lookup via data-api.polymarket.com.

Fetches active and redeemable positions for a given wallet address.
No authentication required — public API only.

Safety: read-only. No private keys, signatures, or transactions ever.
"""

from typing import List

import requests

from app.models import ActivePosition, ResolvedPosition

_DATA_API = "https://data-api.polymarket.com"
_TIMEOUT   = 30
_PAGE_SIZE = 50


class PolymarketLookupError(Exception):
    pass


def _paginate(params: dict) -> List[dict]:
    """Fetch all pages from /positions, returning a flat list of records."""
    params = dict(params)  # don't mutate caller's dict
    results: List[dict] = []
    offset = 0
    while True:
        params["limit"]  = _PAGE_SIZE
        params["offset"] = offset
        try:
            r = requests.get(f"{_DATA_API}/positions", params=params, timeout=_TIMEOUT)
            r.raise_for_status()
        except requests.RequestException as exc:
            raise PolymarketLookupError(f"Network error: {exc}") from exc
        page = r.json()
        if not page:
            break
        results.extend(page)
        if len(page) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE
    return results


def _to_active(row: dict) -> ActivePosition:
    size      = float(row.get("size") or row.get("quantity") or row.get("balance") or 0)
    avg_price = float(row.get("avgPrice") or 0)
    cur_price = float(row.get("curPrice") or avg_price)
    return ActivePosition(
        market        = row.get("title") or "Unknown",
        outcome       = row.get("outcome") or "",
        quantity      = size,
        avg_cost      = avg_price,
        current_price = cur_price,
    )


def _to_redeemable(row: dict) -> ResolvedPosition:
    size          = float(row.get("size") or row.get("quantity") or 0)
    avg_price     = float(row.get("avgPrice") or 0)
    current_value = float(row.get("currentValue") or 0)
    outcome       = row.get("outcome") or ""
    return ResolvedPosition(
        market          = row.get("title") or "Unknown",
        outcome_held    = outcome,
        winning_outcome = outcome,       # redeemable ⟹ this outcome won
        quantity        = size,
        cost_basis      = avg_price * size,
        redeem_value    = current_value,
        redeemed        = False,         # not yet redeemed
        resolved_date   = row.get("endDate"),
    )


def fetch_active_positions(wallet: str) -> List[ActivePosition]:
    """Return all open positions, including redeemable (won but not yet claimed)."""
    rows = _paginate({"user": wallet, "sizeThreshold": "0"})
    return [_to_active(r) for r in rows]


def fetch_redeemable_positions(wallet: str) -> List[ResolvedPosition]:
    """Return positions that are resolved and pending redemption.

    sizeThreshold omitted intentionally — redeemable positions always
    have size > 0, and including the param causes server-side timeouts.
    """
    rows = _paginate({"user": wallet, "redeemable": "true"})
    return [_to_redeemable(r) for r in rows]
