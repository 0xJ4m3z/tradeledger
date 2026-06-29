"""
Tests for wallet address persistence and loss_watch acknowledgment in database.py.
Each test uses a fresh temp SQLite file via the isolated_db fixture.
"""

import pytest


@pytest.fixture(autouse=True)
def isolated_db(monkeypatch, tmp_path):
    db_file = str(tmp_path / "test_tradeledger.db")
    monkeypatch.setattr("app.database.DB_PATH", db_file)
    import app.database as db
    db.init_db()
    yield db


class TestLastWallet:
    def test_load_returns_empty_when_nothing_saved(self, isolated_db):
        assert isolated_db.load_last_wallet() == ""

    def test_save_and_load(self, isolated_db):
        isolated_db.save_last_wallet("0xabcdef1234567890abcdef1234567890abcdef12")
        assert isolated_db.load_last_wallet() == "0xabcdef1234567890abcdef1234567890abcdef12"

    def test_overwrite_updates_value(self, isolated_db):
        isolated_db.save_last_wallet("0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")
        isolated_db.save_last_wallet("0xBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB")
        assert isolated_db.load_last_wallet() == "0xBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"

    def test_save_empty_string(self, isolated_db):
        isolated_db.save_last_wallet("")
        assert isolated_db.load_last_wallet() == ""


class TestLossWatchAcknowledged:
    def test_load_returns_empty_list_when_nothing_saved(self, isolated_db):
        assert isolated_db.load_loss_watch_acknowledged() == []

    def test_save_and_load_markets(self, isolated_db):
        markets = ["BTC will reach 100k", "ETH merge success"]
        isolated_db.save_loss_watch_acknowledged(markets)
        assert isolated_db.load_loss_watch_acknowledged() == markets

    def test_save_empty_list(self, isolated_db):
        isolated_db.save_loss_watch_acknowledged(["A", "B"])
        isolated_db.save_loss_watch_acknowledged([])
        assert isolated_db.load_loss_watch_acknowledged() == []

    def test_overwrite_replaces(self, isolated_db):
        isolated_db.save_loss_watch_acknowledged(["Old Market"])
        isolated_db.save_loss_watch_acknowledged(["New Market 1", "New Market 2"])
        result = isolated_db.load_loss_watch_acknowledged()
        assert result == ["New Market 1", "New Market 2"]

    def test_special_characters_in_market_names(self, isolated_db):
        markets = ['Market "quotes"', "Market | pipe", "Market\nnewline"]
        isolated_db.save_loss_watch_acknowledged(markets)
        assert isolated_db.load_loss_watch_acknowledged() == markets
