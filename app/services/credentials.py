"""Load Polymarket CLOB API credentials from a file.

Supports two file formats:

  .env (or any text file with KEY=VALUE lines):
    CLOB_API_KEY=your_key
    CLOB_API_SECRET=your_secret
    CLOB_API_PASSPHRASE=your_passphrase

  .json:
    {
      "api_key": "your_key",
      "secret": "your_secret",
      "passphrase": "your_passphrase"
    }

Only the three CLOB auth fields are read.  Private keys, wallet addresses,
RPC endpoints, and every other field in the file are silently ignored.

TradeLedger is read-only and never signs transactions or places trades.
"""
from __future__ import annotations

import json
import os
from typing import Optional, Tuple

#: Returned by load_from_file — (api_key, secret, passphrase)
CredsTuple = Tuple[str, str, str]

# ── Recognised key-name variants (lowercased for matching) ────────────────────
_KEY_ALIASES = {
    "clob_api_key",
    "poly_api_key",
    "poly_builder_api_key",
    "builder_api_key",
    "api_key",
    "apikey",
}
_SECRET_ALIASES = {
    "clob_api_secret",
    "poly_api_secret",
    "poly_builder_secret",
    "builder_secret",
    "api_secret",
    "secret",
}
_PASS_ALIASES = {
    "clob_api_passphrase",
    "poly_api_passphrase",
    "poly_builder_passphrase",
    "builder_passphrase",
    "api_passphrase",
    "passphrase",
}


# ── Public API ─────────────────────────────────────────────────────────────────

def load_from_file(path: str) -> Optional[CredsTuple]:
    """Return (api_key, secret, passphrase) from a .env or .json file.

    Returns None if the file is missing, unreadable, or does not contain all
    three required fields.  Any error is swallowed; callers should treat None
    as "not configured".
    """
    if not path or not os.path.isfile(path):
        return None
    try:
        ext = os.path.splitext(path)[1].lower()
        if ext == ".json":
            return _load_json(path)
        return _load_env(path)
    except Exception:
        return None


def validate_file(path: str) -> tuple[bool, str]:
    """Check a credential file and return (ok, status_message).

    ok=True means all three auth fields were found.
    The status message is suitable for display next to the file picker.
    """
    if not path:
        return False, "No file selected"
    if not os.path.isfile(path):
        return False, "File not found"
    creds = load_from_file(path)
    if creds is None:
        return False, "Missing fields — need CLOB_API_KEY, CLOB_API_SECRET, CLOB_API_PASSPHRASE"
    return True, "✓  Credentials loaded"


# ── Parsers ────────────────────────────────────────────────────────────────────

def _load_env(path: str) -> Optional[CredsTuple]:
    """Parse a KEY=VALUE file (dotenv style)."""
    kv: dict[str, str] = {}
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, _, v = line.partition("=")
                # Strip optional surrounding quotes from the value
                v = v.strip().strip('"').strip("'")
                kv[k.strip().lower()] = v

    api_key    = _pick(kv, _KEY_ALIASES)
    secret     = _pick(kv, _SECRET_ALIASES)
    passphrase = _pick(kv, _PASS_ALIASES)

    if api_key and secret and passphrase:
        return (api_key, secret, passphrase)
    return None


def _load_json(path: str) -> Optional[CredsTuple]:
    """Parse a JSON object for credential fields."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        return None

    kv = {k.lower(): str(v) for k, v in data.items() if isinstance(v, str)}

    api_key    = _pick(kv, _KEY_ALIASES)
    secret     = _pick(kv, _SECRET_ALIASES)
    passphrase = _pick(kv, _PASS_ALIASES)

    if api_key and secret and passphrase:
        return (api_key, secret, passphrase)
    return None


def _pick(kv: dict[str, str], aliases: set[str]) -> Optional[str]:
    """Return the first non-empty value whose lowercased key is in aliases."""
    for alias in aliases:
        v = kv.get(alias, "")
        if v:
            return v
    return None
