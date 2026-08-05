"""Tests for app.services.credentials — credential file loading."""
import json
import os
import tempfile

import pytest

from app.services.credentials import load_from_file, validate_file


# ── Helpers ────────────────────────────────────────────────────────────────────

def _write_env(content: str) -> str:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False)
    f.write(content)
    f.close()
    return f.name


def _write_json(data: dict) -> str:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(data, f)
    f.close()
    return f.name


# ── .env format ───────────────────────────────────────────────────────────────

def test_load_env_standard_keys():
    path = _write_env(
        "CLOB_API_KEY=mykey\n"
        "CLOB_API_SECRET=mysecret\n"
        "CLOB_API_PASSPHRASE=mypass\n"
    )
    try:
        result = load_from_file(path)
        assert result == ("mykey", "mysecret", "mypass")
    finally:
        os.unlink(path)


def test_load_env_poly_prefix_keys():
    path = _write_env(
        "POLY_API_KEY=k\nPOLY_API_SECRET=s\nPOLY_API_PASSPHRASE=p\n"
    )
    try:
        result = load_from_file(path)
        assert result == ("k", "s", "p")
    finally:
        os.unlink(path)


def test_load_env_builder_keys():
    path = _write_env(
        "BUILDER_API_KEY=k\nBUILDER_SECRET=s\nBUILDER_PASSPHRASE=p\n"
    )
    try:
        result = load_from_file(path)
        assert result == ("k", "s", "p")
    finally:
        os.unlink(path)


def test_load_env_strips_quotes():
    path = _write_env(
        'CLOB_API_KEY="key-with-quotes"\n'
        "CLOB_API_SECRET='secret-with-quotes'\n"
        "CLOB_API_PASSPHRASE=barepass\n"
    )
    try:
        result = load_from_file(path)
        assert result == ("key-with-quotes", "secret-with-quotes", "barepass")
    finally:
        os.unlink(path)


def test_load_env_skips_comments_and_blanks():
    path = _write_env(
        "# This is a comment\n"
        "\n"
        "CLOB_API_KEY=k\n"
        "# another comment\n"
        "CLOB_API_SECRET=s\n"
        "CLOB_API_PASSPHRASE=p\n"
    )
    try:
        result = load_from_file(path)
        assert result is not None
    finally:
        os.unlink(path)


def test_load_env_ignores_private_key():
    """Private keys and other fields are present but must not be returned."""
    path = _write_env(
        "PRIVATE_KEY=0xdeadbeef\n"
        "CLOB_API_KEY=k\n"
        "CLOB_API_SECRET=s\n"
        "CLOB_API_PASSPHRASE=p\n"
        "CHAIN_ID=137\n"
    )
    try:
        result = load_from_file(path)
        assert result == ("k", "s", "p")
    finally:
        os.unlink(path)


def test_load_env_missing_passphrase_returns_none():
    path = _write_env("CLOB_API_KEY=k\nCLOB_API_SECRET=s\n")
    try:
        result = load_from_file(path)
        assert result is None
    finally:
        os.unlink(path)


# ── JSON format ───────────────────────────────────────────────────────────────

def test_load_json_standard_keys():
    path = _write_json({"api_key": "k", "secret": "s", "passphrase": "p"})
    try:
        result = load_from_file(path)
        assert result == ("k", "s", "p")
    finally:
        os.unlink(path)


def test_load_json_camel_case():
    path = _write_json({"apiKey": "k", "secret": "s", "passphrase": "p"})
    try:
        result = load_from_file(path)
        assert result == ("k", "s", "p")
    finally:
        os.unlink(path)


def test_load_json_extra_fields_ignored():
    path = _write_json({
        "private_key": "0xdeadbeef",
        "api_key": "k",
        "secret": "s",
        "passphrase": "p",
        "wallet": "0xabc",
    })
    try:
        result = load_from_file(path)
        assert result == ("k", "s", "p")
    finally:
        os.unlink(path)


def test_load_json_missing_field_returns_none():
    path = _write_json({"api_key": "k", "secret": "s"})
    try:
        result = load_from_file(path)
        assert result is None
    finally:
        os.unlink(path)


# ── Edge cases ────────────────────────────────────────────────────────────────

def test_load_missing_file_returns_none():
    result = load_from_file("/tmp/definitely_does_not_exist_xyz.env")
    assert result is None


def test_load_empty_path_returns_none():
    assert load_from_file("") is None
    assert load_from_file(None) is None  # type: ignore[arg-type]


# ── validate_file ─────────────────────────────────────────────────────────────

def test_validate_ok():
    path = _write_env("CLOB_API_KEY=k\nCLOB_API_SECRET=s\nCLOB_API_PASSPHRASE=p\n")
    try:
        ok, msg = validate_file(path)
        assert ok is True
        assert "✓" in msg
    finally:
        os.unlink(path)


def test_validate_missing_file():
    ok, msg = validate_file("/tmp/no_such_file_xyz.env")
    assert ok is False
    assert "not found" in msg.lower()


def test_validate_no_path():
    ok, msg = validate_file("")
    assert ok is False


def test_validate_incomplete_file():
    path = _write_env("CLOB_API_KEY=k\n")
    try:
        ok, msg = validate_file(path)
        assert ok is False
        assert "missing" in msg.lower() or "CLOB_API_KEY" in msg
    finally:
        os.unlink(path)
