"""
Read-only Polymarket position lookup via data-api.polymarket.com
and gamma-api.polymarket.com.

Fetches active, resolved, and closed positions for a wallet address.
No authentication required — public API only.

Safety: read-only. No private keys, signatures, or transactions ever.
"""

import json
from typing import Dict, List, Optional

import requests

from app.debug import _dlog
from app.models import ActivePosition, ResolvedPosition, UserActivity

_DATA_API         = "https://data-api.polymarket.com"
_GAMMA_API        = "https://gamma-api.polymarket.com"
_TIMEOUT          = 30
_RETRY_TIMEOUT    = 45   # longer timeout for the one retry attempt
_PAGE_SIZE        = 50   # /positions endpoint
_CLOSED_PAGE_SIZE = 50   # /closed-positions endpoint (API max: 50)

# In-process cache: (slug, asset_id) → winning outcome name (or None on failure).
# asset_id is "" when the caller doesn't have a specific token ID.
# Keyed by both so different sub-markets within the same event are cached separately.
_slug_winner_cache: Dict[tuple, Optional[str]] = {}


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


def _winner_from_markets(markets: list) -> Optional[str]:
    """Extract the winning outcome from a list of Gamma API market objects.

    Checks the market's winner/winnerOutcome field first, then derives it from
    the outcomePrices array (outcome with price ≥ 0.99 = resolved winner).
    Returns the first winner found, or None if no market is resolved.
    """
    for market in markets:
        w = market.get("winner") or market.get("winnerOutcome")
        if w:
            return str(w)

        raw_outcomes = market.get("outcomes", "[]")
        raw_prices   = market.get("outcomePrices", "[]")
        try:
            mkt_outcomes = (json.loads(raw_outcomes)
                            if isinstance(raw_outcomes, str) else raw_outcomes)
            mkt_prices   = (json.loads(raw_prices)
                            if isinstance(raw_prices, str) else raw_prices)
            for o, p in zip(mkt_outcomes, mkt_prices):
                if float(p) >= 0.99:
                    return str(o)
        except (ValueError, TypeError, json.JSONDecodeError):
            pass

    return None


def _fetch_winner_by_condition_id(condition_id: str) -> Optional[str]:
    """Return the resolved winning outcome for a specific Polymarket market.

    Queries gamma-api.polymarket.com/markets?condition_id=<id>.  Each binary
    market has a unique conditionId, so this returns exactly one market — no
    multi-market disambiguation needed.  Critical for events with many
    sub-markets at different price levels (e.g. "ETH above 1,830", "ETH above
    1,990", …) that all share one event slug but resolve independently.

    Results are cached in _slug_winner_cache under the key ("cond", condition_id).

    Read-only — no auth, no side effects.
    """
    cache_key = ("cond", condition_id)
    if cache_key in _slug_winner_cache:
        return _slug_winner_cache[cache_key]

    winner: Optional[str] = None
    try:
        r = requests.get(
            f"{_GAMMA_API}/markets",
            params={"condition_id": condition_id},
            timeout=8,
        )
        r.raise_for_status()
        data = r.json()
        markets = data if isinstance(data, list) else ([data] if data else [])
        winner = _winner_from_markets(markets)
    except Exception as exc:
        _dlog("gamma_winner", "condition_id=%s error=%s", condition_id, exc)

    _slug_winner_cache[cache_key] = winner
    _dlog("gamma_winner", "condition_id=%s → winner=%s", condition_id, winner)
    return winner


def _fetch_winner_from_gamma(slug: str, asset_id: str = "") -> Optional[str]:
    """Return the resolved winning outcome for a Polymarket event by slug.

    Queries gamma-api.polymarket.com/events with the event slug.  When multiple
    sub-markets share the same event slug (e.g. "ETH above X" price-level series),
    asset_id narrows the lookup to the market whose clobTokenIds include it.

    Prefer _fetch_winner_by_condition_id when the position's conditionId is
    available — it's a direct single-market lookup with no disambiguation.

    Results are cached as (slug, asset_id).  Read-only — no auth, no side effects.
    """
    cache_key = (slug, asset_id)
    if cache_key in _slug_winner_cache:
        return _slug_winner_cache[cache_key]

    winner: Optional[str] = None
    try:
        r = requests.get(
            f"{_GAMMA_API}/events",
            params={"slug": slug},
            timeout=8,
        )
        r.raise_for_status()
        data = r.json()
        events = data if isinstance(data, list) else ([data] if data else [])

        matched_by_token = False

        for event in events:
            # Only use the event-level winner when not filtering by token —
            # it's ambiguous for events that span multiple sub-markets.
            if not asset_id:
                w = event.get("winner") or event.get("winnerOutcome")
                if w:
                    winner = str(w)
                    break

            for market in event.get("markets", []):
                if asset_id:
                    clob_ids = market.get("clobTokenIds") or []
                    if isinstance(clob_ids, str):
                        try:
                            clob_ids = json.loads(clob_ids)
                        except (ValueError, json.JSONDecodeError):
                            clob_ids = []
                    if asset_id not in clob_ids:
                        continue
                    matched_by_token = True

                w = _winner_from_markets([market])
                if w:
                    winner = w
                    break

            if winner:
                break

        # If asset_id filtering found no clobTokenIds match (API omitted the
        # field), fall back to unfiltered only for single-market events.
        if asset_id and not matched_by_token and winner is None:
            total_markets = sum(len(e.get("markets", [])) for e in events)
            if total_markets == 1:
                winner = _fetch_winner_from_gamma(slug)

    except Exception as exc:
        _dlog("gamma_winner", "slug=%s asset_id=%s error=%s", slug, asset_id, exc)

    _slug_winner_cache[cache_key] = winner
    _dlog("gamma_winner", "slug=%s asset_id=%s → winner=%s", slug, asset_id, winner)
    return winner


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
        slug          = row.get("eventSlug") or row.get("slug") or None,
        asset_id      = (row.get("assetId") or row.get("asset_id")
                         or row.get("tokenId") or row.get("token_id") or None),
    )


def _binary_opposite(outcome: str) -> str:
    """Return the opposite outcome name for common binary markets (Yes/No, Up/Down).

    Used as a last-resort fallback when Gamma is unavailable and we know the
    user's outcome lost (currentValue ≈ 0) but need the winner's name.
    Returns "" for non-standard outcome strings.
    """
    return {"yes": "No", "no": "Yes", "up": "Down", "down": "Up"}.get(
        outcome.lower(), ""
    )


def _to_resolved(row: dict) -> ResolvedPosition:
    size          = float(row.get("size") or row.get("quantity") or 0)
    avg_price     = float(row.get("avgPrice") or 0)
    current_value = float(row.get("currentValue") or 0)
    outcome       = row.get("outcome") or ""
    slug          = row.get("eventSlug") or row.get("slug") or None
    asset_id      = (row.get("assetId") or row.get("asset_id")
                     or row.get("tokenId") or row.get("token_id") or "")
    condition_id  = row.get("conditionId") or row.get("condition_id") or ""

    # Use currentValue / size as the primary winning-outcome signal — identical
    # logic to _to_closed's curPrice approach.  For a resolved binary market,
    # each token is worth ~$1 (winner) or ~$0 (loser).
    #
    # IMPORTANT: for positions that were partially CLOB-sold before resolution,
    # `size` from the API is the ORIGINAL total-bought quantity, not the remaining
    # redeemable amount.  `currentValue` always reflects only the remaining shares.
    # Example: bought 203 shares, sold 201, 2 remain redeemable → size=203, currentValue=2.
    # That makes cur_price_approx = 2/203 ≈ 0.01, which looks like a loser signal,
    # even though the position won.  The Gamma lookup rescues the winning_outcome label,
    # but cost_basis and quantity must also be corrected (see below).
    #
    # Why this still beats Gamma as the first-pass signal:
    #   • No network call — uses data already in the row.
    #   • Multi-market events each return their own currentValue (no cache-poisoning).
    cur_price_approx = (current_value / size) if size > 0 else -1.0

    if cur_price_approx >= 0.99:
        # User's tokens are worth ~$1 each → their outcome won.
        winning_outcome = outcome

    elif 0.0 <= cur_price_approx <= 0.01:
        # Either a clear loser OR a partial-sell winner (big original size, tiny remainder).
        # Gamma tells us which outcome actually won.
        if condition_id:
            gamma_winner = _fetch_winner_by_condition_id(condition_id)
            if gamma_winner is None and slug:
                gamma_winner = _fetch_winner_from_gamma(slug, asset_id)
        elif slug:
            gamma_winner = _fetch_winner_from_gamma(slug, asset_id)
        else:
            gamma_winner = None
        winning_outcome = gamma_winner or _binary_opposite(outcome) or outcome

    else:
        # currentValue not yet settled (market still pricing in) — use Gamma.
        if condition_id:
            gamma_winner = _fetch_winner_by_condition_id(condition_id)
            if gamma_winner is None and slug:
                gamma_winner = _fetch_winner_from_gamma(slug, asset_id)
        elif slug:
            gamma_winner = _fetch_winner_from_gamma(slug, asset_id)
        else:
            gamma_winner = None
        winning_outcome = gamma_winner if gamma_winner else outcome

    # Compute the actual remaining (redeemable) quantity and its proportional cost.
    #
    # For a winner (settlement price = $1.00/token):
    #   remaining_qty = currentValue / $1 = currentValue
    #   cost_basis    = avgPrice × remaining_qty
    #
    # This is correct whether or not a partial sell occurred:
    #   • No partial sell: remaining_qty = size, cost_basis = avgPrice × size  (unchanged)
    #   • Partial sell: remaining_qty < size, cost_basis = proportional share  (fixed)
    #
    # For a loser (settlement price = $0.00/token):
    #   currentValue ≈ 0, so remaining_qty cannot be inferred from it.
    #   Fall back to `size`.  Partial-sell losers in the redeemable endpoint are
    #   rare (worthless tokens are auto-settled) so this edge-case is acceptable.
    user_won = winning_outcome.lower() == outcome.lower()
    if user_won:
        remaining_qty = current_value   # $1/token at settlement → qty == USDC value
    else:
        remaining_qty = size            # loser fallback — use full reported size

    return ResolvedPosition(
        market          = row.get("title") or "Unknown",
        outcome_held    = outcome,
        winning_outcome = winning_outcome,
        quantity        = remaining_qty,
        cost_basis      = avg_price * remaining_qty,
        redeem_value    = current_value,
        redeemed        = False,
        resolved_date   = row.get("endDate"),
        slug            = slug,
    )


def _to_closed(row: dict) -> ResolvedPosition:
    """Map a closed-positions record to ResolvedPosition.

    Handles all close types: market resolution (win/loss), CLOB sell
    (including stop-loss triggers), and manual redemption.

    Field semantics from the Polymarket API:
      totalBought  — total SHARES/tokens purchased (NOT USDC spent)
      avgPrice     — average price per share in USDC
      realizedPnl  — net profit/loss in USDC
      curPrice     — current price of the outcome token AFTER market resolution
                     (≈ 1.0 if this outcome won; ≈ 0.0 if it lost)
    Derived:
      cost_basis   = totalBought × avgPrice   (USDC actually spent buying)
      redeem_value = cost_basis + realizedPnl (USDC received on close)

    Winner determination:
      curPrice is the post-resolution price of the outcome the user held.
      For a fully resolved binary market it is always ~0 or ~1, regardless
      of whether the user exited via redemption, CLOB sell, or stop-loss —
      so it is the authoritative signal for the actual winning outcome.
      We only fall back to a proceeds-based heuristic for legacy records
      where curPrice is unavailable or still mid-market.
    """
    avg_price    = float(row.get("avgPrice") or 0)
    total_bought = float(row.get("totalBought") or 0)
    realized_pnl = float(row.get("realizedPnl") or 0)
    outcome      = row.get("outcome") or ""
    opposite     = row.get("oppositeOutcome") or ""
    cur_price    = float(row.get("curPrice") if row.get("curPrice") is not None else -1)
    slug         = row.get("eventSlug") or row.get("slug") or None
    asset_id     = (row.get("assetId") or row.get("asset_id")
                    or row.get("tokenId") or row.get("token_id") or "")
    condition_id = row.get("conditionId") or row.get("condition_id") or ""

    quantity     = total_bought                       # shares bought
    cost_basis   = total_bought * avg_price           # USDC spent
    redeem_value = cost_basis + realized_pnl          # USDC received

    # Gamma API is the authoritative source for the actual winning outcome.
    # conditionId gives a direct single-market lookup; falls back to event slug.
    if condition_id:
        gamma_winner = _fetch_winner_by_condition_id(condition_id)
        if gamma_winner is None and slug:
            gamma_winner = _fetch_winner_from_gamma(slug, asset_id)
    elif slug:
        gamma_winner = _fetch_winner_from_gamma(slug, asset_id)
    else:
        gamma_winner = None

    if cur_price >= 0.98:
        # Token resolved at ~$1 → user's outcome won.  Gamma confirms.
        winning_outcome = outcome
        per_share = (redeem_value / quantity) if quantity > 0 else 0
        close_type = "REDEEMED_WIN" if per_share >= 0.95 else "SOLD"
    elif 0.0 <= cur_price <= 0.02:
        # Token resolved at ~$0 → the OTHER outcome won.
        # If oppositeOutcome is missing, Gamma fills the gap.
        winning_outcome = opposite or gamma_winner or ""
        close_type = "RESOLVED_LOSS" if redeem_value < 0.01 else "SOLD"
    else:
        # curPrice is mid-market (CLOB sell price, not resolution price) or
        # unavailable.  This is the common case for stop-loss SOLD positions.
        if redeem_value < 0.01:
            # Got back nothing → resolved against them without any CLOB exit.
            winning_outcome = opposite or gamma_winner or ""
            close_type      = "RESOLVED_LOSS"
        elif quantity > 0 and (redeem_value / quantity) >= 0.95:
            # Got back ~$1/share → effectively redeemed at full value.
            winning_outcome = outcome
            close_type      = "REDEEMED_WIN"
        else:
            # Sold at mid-market via stop-loss / take-profit exit.
            # Gamma is the primary source for the actual market resolution.
            if gamma_winner:
                winning_outcome = gamma_winner
            else:
                # Gamma unavailable or market not yet resolved — fall back
                # to P/L sign as last resort (can be wrong for stop-loss
                # positions where the user's direction ultimately won).
                winning_outcome = outcome if realized_pnl >= 0 else opposite
                _dlog("closed_winner",
                      "gamma miss for '%s' (slug=%s) | fallback P/L sign | "
                      "all keys: %s",
                      row.get("title", "?"), slug, sorted(row.keys()))
            close_type = "SOLD"

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
        close_type      = close_type,
        slug            = slug,
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
        slug      = row.get("eventSlug") or row.get("slug") or None,
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
