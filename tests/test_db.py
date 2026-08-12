"""Unit tests for SQLite database initialization and schema setup."""

import sqlite3

from taxo_trainer.db import init_app_db, init_user_db


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
    assert "user_streak" in tables

    cursor.execute("PRAGMA table_info(user_progress);")
    columns = {row["name"] for row in cursor.fetchall()}
    expected_cols = {
        "attempt_id", "occurrence_id", "target_taxon_key",
        "guessed_taxon_key", "is_correct", "used_hint", "attempt_timestamp", "data_source"
    }
    assert expected_cols.issubset(columns)


def test_user_streak_data_source():
    """Test per-data-source user streak storage and retrieval."""
    from taxo_trainer.db import get_user_streak, set_user_streak

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_user_db(conn)

    # Initially 0 for both data sources
    assert get_user_streak(conn, data_source="plants.zip") == (0, 0)
    assert get_user_streak(conn, data_source="insects.zip") == (0, 0)

    # Set streak for plants.zip
    set_user_streak(5, 10, conn, data_source="plants.zip")
    assert get_user_streak(conn, data_source="plants.zip") == (5, 10)
    assert get_user_streak(conn, data_source="insects.zip") == (0, 0)

    # Set streak for insects.zip
    set_user_streak(2, 3, conn, data_source="insects.zip")
    assert get_user_streak(conn, data_source="plants.zip") == (5, 10)
    assert get_user_streak(conn, data_source="insects.zip") == (2, 3)


def test_prune_gbif_cache():
    """Test 7-day expiration and LRU size pruning in gbif_cache.db."""
    import time

    from taxo_trainer.db import prune_gbif_cache

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE gbif_api_cache (
            taxon_key TEXT PRIMARY KEY,
            response_json TEXT NOT NULL,
            cached_at INTEGER NOT NULL
        );
    """)

    now = int(time.time())
    old_ts = now - (10 * 86400)  # 10 days old (expired)
    recent_ts = now - (1 * 86400)  # 1 day old (valid)

    conn.execute("INSERT INTO gbif_api_cache VALUES ('old_key', '{}', ?)", (old_ts,))
    conn.execute("INSERT INTO gbif_api_cache VALUES ('new_key', '{}', ?)", (recent_ts,))

    # Prune with 7-day max age
    pruned = prune_gbif_cache(conn, max_size_mb=100.0, max_age_days=7)
    assert pruned == 1

    remaining = conn.execute("SELECT taxon_key FROM gbif_api_cache").fetchall()
    keys = [r["taxon_key"] for r in remaining]
    assert keys == ["new_key"]

