"""Unit tests for SQLite database initialization and schema setup."""

import sqlite3

from src.db import init_app_db, init_user_db


def test_init_app_db_in_memory():
    """Test app_data schema creation on an in-memory SQLite database."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_app_db(conn)

    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = {row["name"] for row in cursor.fetchall()}

    assert "taxa" in tables
    assert "occurrences" in tables

    # Verify taxa schema columns
    cursor.execute("PRAGMA table_info(taxa);")
    columns = {row["name"] for row in cursor.fetchall()}
    expected_cols = {
        "taxon_key", "scientific_name", "canonical_name", "accepted_name",
        "rank", "kingdom", "phylum", "class", "order_name", "family",
        "genus", "vernacular_da", "vernacular_en", "occurrence_count"
    }
    assert expected_cols.issubset(columns)


def test_init_user_db_in_memory():
    """Test user_data schema creation on an in-memory SQLite database."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_user_db(conn)

    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = {row["name"] for row in cursor.fetchall()}

    assert "user_progress" in tables

    cursor.execute("PRAGMA table_info(user_progress);")
    columns = {row["name"] for row in cursor.fetchall()}
    expected_cols = {
        "attempt_id", "occurrence_id", "target_taxon_key",
        "guessed_taxon_key", "is_correct", "used_hint", "attempt_timestamp"
    }
    assert expected_cols.issubset(columns)
