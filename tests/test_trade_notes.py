"""Tests for trade notes persistence and in-memory cache (app/services/notes.py).

All tests use a temp SQLite DB via the TRADELEDGER_DB env var so the live DB
is never touched.  No UI or PySide6 imports needed.
"""
import os
import tempfile

import pytest

_TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMP_DB.close()
os.environ.setdefault("TRADELEDGER_DB", _TMP_DB.name)


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    """Each test gets its own empty SQLite file."""
    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("TRADELEDGER_DB", db_path)
    # Reload the module-level DB_PATH binding
    import app.database as db
    db.DB_PATH = db_path
    db.init_db()
    # Reset note cache for isolation
    import app.services.notes as notes
    notes._cache = {}
    notes._wallet = ""
    yield


_WALLET = "0x99d058607b4E01844C0153e6977C09c9531Aa67e"
_MARKET = "DOGE Up or Down - August 5, 2:10-2:15PM ET"


def test_set_and_get_note():
    import app.services.notes as notes
    notes.load_for_wallet(_WALLET)
    notes.set(_MARKET, "bot faked out by spike")
    assert notes.get(_MARKET) == "bot faked out by spike"
    assert notes.has_note(_MARKET)


def test_note_persists_across_reload():
    import app.services.notes as notes
    notes.load_for_wallet(_WALLET)
    notes.set(_MARKET, "held to resolution, would have won")

    # Simulate a new session by resetting the cache and reloading
    notes._cache = {}
    notes._wallet = ""
    notes.load_for_wallet(_WALLET)

    assert notes.get(_MARKET) == "held to resolution, would have won"


def test_delete_note():
    import app.services.notes as notes
    notes.load_for_wallet(_WALLET)
    notes.set(_MARKET, "temporary note")
    notes.delete(_MARKET)
    assert notes.get(_MARKET) is None
    assert not notes.has_note(_MARKET)


def test_delete_note_persists():
    import app.services.notes as notes
    notes.load_for_wallet(_WALLET)
    notes.set(_MARKET, "to be deleted")
    notes.delete(_MARKET)

    notes._cache = {}
    notes.load_for_wallet(_WALLET)
    assert notes.get(_MARKET) is None


def test_overwrite_note():
    import app.services.notes as notes
    notes.load_for_wallet(_WALLET)
    notes.set(_MARKET, "first note")
    notes.set(_MARKET, "updated note")
    notes.load_for_wallet(_WALLET)
    assert notes.get(_MARKET) == "updated note"


def test_blank_note_ignored():
    import app.services.notes as notes
    notes.load_for_wallet(_WALLET)
    notes.set(_MARKET, "   ")   # blank → no-op
    assert notes.get(_MARKET) is None


def test_notes_are_wallet_scoped():
    import app.services.notes as notes
    wallet_b = "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    notes.load_for_wallet(_WALLET)
    notes.set(_MARKET, "wallet A note")

    # Switch to wallet B — should see no notes
    notes.load_for_wallet(wallet_b)
    assert notes.get(_MARKET) is None

    # Switch back to wallet A — note should return
    notes.load_for_wallet(_WALLET)
    assert notes.get(_MARKET) == "wallet A note"


def test_get_returns_none_when_no_wallet():
    import app.services.notes as notes
    notes.load_for_wallet("")
    assert notes.get(_MARKET) is None
    # set should be a no-op with no wallet
    notes.set(_MARKET, "orphan note")
    assert notes.get(_MARKET) is None


def test_load_all_trade_notes_returns_dict():
    import app.database as db
    db.save_trade_note(_WALLET, "Market A", "note 1")
    db.save_trade_note(_WALLET, "Market B", "note 2")
    result = db.load_all_trade_notes(_WALLET)
    assert result == {"Market A": "note 1", "Market B": "note 2"}


def test_note_stripping():
    """Notes are stored with leading/trailing whitespace stripped."""
    import app.services.notes as notes
    notes.load_for_wallet(_WALLET)
    notes.set(_MARKET, "  padded note  ")
    notes.load_for_wallet(_WALLET)
    assert notes.get(_MARKET) == "padded note"
