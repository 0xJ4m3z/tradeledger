"""
Read-only Polymarket position lookup via data-api.polymarket.com.

Fetches active, resolved, and closed positions for a wallet address.
No authentication required — public API only.

Safety: read-only. No private keys, signatures, or transactions ever.
"""

from typing import List

import requests

from app.models import ActivePosition, ResolvedPosition, UserActivity

_DATA_API         = "https://data-api.polymarket.com"
_TIMEOUT          = 30
_RETRY_TIMEOUT    = 45   # longer timeout for the one retry attempt
_PAGE_SIZE        = 50   # /positions endpoint
_CLOSED_PAGE_SIZE = 50   # /closed-positions endpoint (API max: 50)


class PolymarketLookupError(Exception):
    pass


def _get_with_retry(url: str, params: dict) -> requests.Response:
    """GET with one retry on 408 / connection timeout using a longer timeout."""
    try:
        r = requests.get(url, params=params, timeout=_TIMEOUT)
        if r.status_code == 408:
            r = requests.get(url, params=params, timeout=_RETRY_TIMEOUT)
        r.raise_for_status()
        return r
    except requests.RequestException as exc:
        raise PolymarketLookupError(f"Network error: {exc}") from exc


def _paginate(path: str, params: dict, page_size: int, max_pages: int = 0) -> List[dict]:
    """Fetch pages from a Polymarket Data API endpoint.

    max_pages: stop after this many pages (0 = no limit).
    """
    params = dict(params)
    results: List[dict] = []
    offset = 0
    pages  = 0
    while True:
        params["limit"]  = page_size
        params["offset"] = offset
        r    = _get_with_retry(f"{_DATA_API}/{path}", params)
        page = r.json()
        if not page:
            break
        results.extend(page)
        pages += 1
        if len(page) < page_size:
            break
        if max_pages and pages >= max_pages:
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


def _to_resolved(row: dict) -> ResolvedPosition:
    size          = float(row.get("size") or row.get("quantity") or 0)
    avg_price     = float(row.get("avgPrice") or 0)
    current_value = float(row.get("currentValue") or 0)
    outcome       = row.get("outcome") or ""
    return ResolvedPosition(
        market          = row.get("title") or "Unknown",
        outcome_held    = outcome,
        winning_outcome = outcome,   # resolved + not redeemed ⟹ user's outcome won
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

    Field semantics from the Polymarket API:
      totalBought  — total SHARES/tokens purchased (NOT USDC spent)
      avgPrice     — average price per share in USDC
      realizedPnl  — net profit/loss in USDC
    Derived:
      cost_basis   = totalBought × avgPrice   (USDC actually spent buying)
      redeem_value = cost_basis + realizedPnl (USDC received on close)
    """
    avg_price    = float(row.get("avgPrice") or 0)
    total_bought = float(row.get("totalBought") or 0)
    realized_pnl = float(row.get("realizedPnl") or 0)
    outcome      = row.get("outcome") or ""
    opposite     = row.get("oppositeOutcome") or ""

    is_win          = realized_pnl > 0
    winning_outcome = outcome if is_win else opposite

    quantity   = total_bought                       # shares bought
    cost_basis = total_bought * avg_price           # USDC spent
    redeem_value = cost_basis + realized_pnl        # USDC received

    return ResolvedPosition(
        market          = row.get("title") or "Unknown",
        outcome_held    = outcome,
        winning_outcome = winning_outcome,
        quantity        = quantity,
        cost_basis      = cost_basis,
        redeem_value    = redeem_value,
        redeemed        = True,
        resolved_date   = row.get("endDate"),
        closed_at       = int(row.get("timestamp") or 0) or None,
    )


def fetch_active_positions(wallet: str) -> List[ActivePosition]:
    """Return all open positions from the /positions endpoint (includes resolved-not-yet-claimed).

    sizeThreshold omitted — active positions always have size > 0, and passing
    sizeThreshold=0 causes server-side 408 timeouts on large wallets.
    Callers should deduplicate against fetch_resolved_positions to avoid showing the
    same market in both lists.
    """
    rows = _paginate("positions", {"user": wallet}, _PAGE_SIZE)
    return [_to_active(r) for r in rows]


def fetch_resolved_positions(wallet: str) -> List[ResolvedPosition]:
    """Return positions that are resolved and pending redemption.

    sizeThreshold omitted — resolved positions always have size > 0,
    and including it causes server-side 408 timeouts.
    """
    rows = _paginate("positions", {"user": wallet, "redeemable": "true"}, _PAGE_SIZE)
    return [_to_resolved(r) for r in rows]


def _to_activity(row: dict) -> UserActivity:
    return UserActivity(
        timestamp = int(row.get("timestamp") or 0),
        type      = row.get("type") or "",
        title     = row.get("title") or "",
        outcome   = row.get("outcome") or "",
        side      = row.get("side") or "",
        size      = float(row.get("size") or 0),
        usdc_size = float(row.get("usdcSize") or 0),
        price     = float(row.get("price") or 0),
    )


def fetch_activity(wallet: str) -> List[UserActivity]:
    """Return the 100 most-recent activity events for a wallet, newest first."""
    rows = _paginate(
        "activity",
        {"user": wallet, "sortBy": "TIMESTAMP", "sortDirection": "DESC"},
        page_size=100,
        max_pages=1,
    )
    return [_to_activity(r) for r in rows]


def fetch_activity_page(wallet: str, offset: int, limit: int = 100) -> List[UserActivity]:
    """Fetch one page of activity at the given offset (for infinite-scroll load-more)."""
    r = _get_with_retry(
        f"{_DATA_API}/activity",
        {
            "user":          wallet,
            "sortBy":        "TIMESTAMP",
            "sortDirection": "DESC",
            "limit":         limit,
            "offset":        offset,
        },
    )
    rows = r.json()
    return [_to_activity(row) for row in rows] if rows else []


def fetch_closed_positions_page(
    wallet: str,
    offset: int,
    limit: int = 50,
    sorted_: bool = True,
) -> List[ResolvedPosition]:
    """Fetch one page of closed positions at the given offset.

    sorted_=True (default) adds sortBy=TIMESTAMP/sortDirection=DESC — used for the
    initial 2-page display fetch where newest-first order matters.

    sorted_=False omits the sort params — used by the backfill thread where row order
    is irrelevant and the sort clause causes server-side 408 timeouts at high offsets.
    """
    params: dict = {"user": wallet, "limit": limit, "offset": offset}
    if sorted_:
        params["sortBy"]        = "TIMESTAMP"
        params["sortDirection"] = "DESC"
    r = _get_with_retry(f"{_DATA_API}/closed-positions", params)
    page = r.json()
    return [_to_closed(row) for row in page] if page else []


def fetch_closed_positions(wallet: str) -> List[ResolvedPosition]:
    """Return the 100 most-recent fully closed positions (redeemed or sold).

    Capped at 2 pages to avoid server-side 408 timeouts on wallets with
    thousands of historical trades. Sorted by timestamp (newest first).
    """
    rows = _paginate(
        "closed-positions",
        {"user": wallet, "sortBy": "TIMESTAMP", "sortDirection": "DESC"},
        _CLOSED_PAGE_SIZE,
        max_pages=2,
    )
    return [_to_closed(r) for r in rows]
