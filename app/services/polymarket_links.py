"""Public Polymarket URL builder — read-only, no auth required."""
from typing import Optional

_BASE_URL = "https://polymarket.com/event"


def polymarket_url_for_slug(slug: Optional[str]) -> Optional[str]:
    """Return the public Polymarket event page URL for a given slug.

    Returns None if slug is falsy (None, empty string) so callers can use
    a simple truthiness check before opening the URL.
    """
    if not slug:
        return None
    return f"{_BASE_URL}/{slug}"
