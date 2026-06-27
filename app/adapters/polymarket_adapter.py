"""
Read-only Polymarket position lookup via data-api.polymarket.com.

Fetches active, redeemable, and closed positions for a wallet address.
No authentication required — public API only.

Safety: read-only. No private keys, signatures, or transactions ever.
"""

from typing import List

import requests

from app.models import ActivePosition, ResolvedPosition

_DATA_API         = "https://data-api.polymarket.com"
_TIMEOUT          = 30
_PAGE_SIZE        = 50   # /positions endpoint
_CLOSED_PAGE_SIZE = 50   # /closed-positions endpoint (API max: 50)


class PolymarketLookupError(Exception):
    pass


def _paginate(path: str, params: dict, page_size: int) -> List[dict]:
    """Fetch all pages from a Polymarket Data API endpoint."""
    params = dict(params)
    results: List[dict] = []
    offset = 0
    while True:
        params["limit"]  = page_size
        params["offset"] = offset
        try:
            r = requests.get(f"{_DATA_API}/{path}", params=params, timeout=_TIMEOUT)
            r.raise_for_status()
        except requests.RequestException as exc:
            raise PolymarketLookupError(f"Network error: {exc}") from exc
        page = r.json()
        if not page:
            break
        results.extend(page)
        if len(page) < page_size:
            break
        offset += page_size
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
        winning_outcome = outcome,   # redeemable ⟹ user's outcome won
        quantity        = size,
        cost_basis      = avg_price * size,
        redeem_value    = current_value,
        redeemed        = False,
        resolved_date   = row.get("endDate"),
    )


def _to_closed(row: dict) -> ResolvedPosition:
    """Map a closed-positions record to ResolvedPosition.

    Handles all close types: market resolution (win/loss), CLOB sell
    (including stop-loss triggers), and manual redemption.
    realizedPnl is the only reliable win indicator across all types —
    curPrice is the mid-market at close time, not the final resolution
    price, so it cannot be used for sold positions.
    """
    avg_price    = float(row.get("avgPrice") or 0)
    total_bought = float(row.get("totalBought") or 0)
    realized_pnl = float(row.get("realizedPnl") or 0)
    outcome      = row.get("outcome") or ""
    opposite     = row.get("oppositeOutcome") or ""

    is_win          = realized_pnl > 0
    winning_outcome = outcome if is_win else opposite

    quantity = (total_bought / avg_price) if avg_price > 0 else 0.0

    return ResolvedPosition(
        market          = row.get("title") or "Unknown",
        outcome_held    = outcome,
        winning_outcome = winning_outcome,
        quantity        = quantity,
        cost_basis      = total_bought,
        redeem_value    = total_bought + realized_pnl,
        redeemed        = True,
        resolved_date   = row.get("endDate"),
    )


def fetch_active_positions(wallet: str) -> List[ActivePosition]:
    """Return all open positions, including redeemable (won but not yet claimed)."""
    rows = _paginate("positions", {"user": wallet, "sizeThreshold": "0"}, _PAGE_SIZE)
    return [_to_active(r) for r in rows]


def fetch_redeemable_positions(wallet: str) -> List[ResolvedPosition]:
    """Return positions that are resolved and pending redemption.

    sizeThreshold omitted — redeemable positions always have size > 0,
    and including it causes server-side 408 timeouts.
    """
    rows = _paginate("positions", {"user": wallet, "redeemable": "true"}, _PAGE_SIZE)
    return [_to_redeemable(r) for r in rows]


def fetch_closed_positions(wallet: str) -> List[ResolvedPosition]:
    """Return fully closed positions (redeemed or sold)."""
    rows = _paginate("closed-positions", {"user": wallet}, _CLOSED_PAGE_SIZE)
    return [_to_closed(r) for r in rows]
