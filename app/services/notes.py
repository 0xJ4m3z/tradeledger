"""Trade notes — per-market text annotations that follow a trade across all tabs.

Notes are keyed by market title and stored under the current wallet address.
Because the same market title appears on Active, Resolved, Closed, and Activity
tabs, a note added anywhere is visible everywhere.

Usage:
    from app.services import notes

    notes.load_for_wallet("0xABC...")   # call at startup and on wallet change
    note = notes.get("DOGE Up or Down - August 5")
    notes.set("DOGE Up or Down - August 5", "bot faked out by spike, resolved Up")
    notes.delete("DOGE Up or Down - August 5")
    notes.has_note("DOGE Up or Down - August 5")  # → True

All reads/writes go through the module-level _cache so the DB is only hit on
explicit set/delete/load calls — table rendering never blocks on I/O.

Read-only guarantee: this module persists analyst notes only.  It never places
trades, signs transactions, or touches wallet credentials.
"""
from typing import Dict, Optional

from app.database import delete_trade_note, load_all_trade_notes, save_trade_note

_cache: Dict[str, str] = {}   # market_title → note text
_wallet: str = ""


def load_for_wallet(wallet: str) -> None:
    """Load (or reload) all notes for *wallet* into the in-memory cache.

    Call this at startup and whenever the active wallet changes.
    """
    global _wallet, _cache
    _wallet = wallet or ""
    _cache  = load_all_trade_notes(_wallet) if _wallet else {}


def get(market: str) -> Optional[str]:
    """Return the note for *market*, or None if none exists."""
    return _cache.get(market) or None


def has_note(market: str) -> bool:
    """True when a non-empty note exists for *market*."""
    return bool(_cache.get(market))


def set(market: str, note: str) -> None:  # noqa: A001  (shadows built-in 'set' intentionally)
    """Save *note* for *market* and persist to SQLite.

    Strips leading/trailing whitespace.  Does nothing if note is blank or no
    wallet is loaded — call delete() to remove a note.
    """
    if not _wallet or not market or not note.strip():
        return
    _cache[market] = note.strip()
    save_trade_note(_wallet, market, note.strip())


def delete(market: str) -> None:
    """Delete the note for *market* from cache and SQLite."""
    _cache.pop(market, None)
    delete_trade_note(_wallet, market)


def current_wallet() -> str:
    """Return the wallet address notes are currently loaded for."""
    return _wallet
