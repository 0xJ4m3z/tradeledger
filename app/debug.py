"""Debug logging for TradeLedger.

Set TRADELEDGER_DEBUG=1 in the environment to enable verbose data-flow logging.
All output goes to stderr via Python's logging module at DEBUG level.

Usage:
    from app.debug import _dlog
    _dlog("cache", "loaded %d activity rows for %s", len(rows), wallet)
"""
import logging
import os

_DEBUG = os.getenv("TRADELEDGER_DEBUG", "0") == "1"

_log = logging.getLogger("tradeledger")

if _DEBUG and not _log.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(message)s"))
    _log.addHandler(_handler)
    _log.setLevel(logging.DEBUG)


def _dlog(tag: str, msg: str, *args) -> None:
    """Emit a debug log line only when TRADELEDGER_DEBUG=1."""
    if _DEBUG:
        _log.debug("[%s] " + msg, tag, *args)
