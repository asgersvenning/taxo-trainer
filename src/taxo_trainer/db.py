"""Database connection management and schema setup for taxo-trainer.

Manages SQLite connections for app_data.db and user_data.db with WAL mode
and explicit indexing for optimal high-performance sampling.
"""

import sqlite3
from pathlib import Path

# Define default database paths relative to workspace root
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
APP_DB_PATH = DATA_DIR / "app_data.db"
USER_DB_PATH = DATA_DIR / "user_data.db"
GBIF_CACHE_DB_PATH = DATA_DIR / "gbif_cache.db"


def ensure_data_dir() -> Path:
    """Ensure the data directory exists.

    Returns:
        Path: Absolute path to the data directory.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR


def _sqlite_unicode_lower(s: str | None) -> str | None:
    """Unicode-aware lowercasing function for SQLite LOWER() queries."""
    if s is None:
        return None
    return str(s).lower()


def register_sqlite_functions(conn: sqlite3.Connection) -> None:
    """Register custom Python unicode-aware functions on a SQLite connection."""
    conn.create_function("lower", 1, _sqlite_unicode_lower)


def get_db_connection(db_path: Path = APP_DB_PATH) -> sqlite3.Connection:
    """Create and configure a SQLite connection with WAL mode enabled.

    Args:
        db_path: Path to SQLite database file.

    Returns:
        sqlite3.Connection: Configured database connection with Row factory.
    """
    ensure_data_dir()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    register_sqlite_functions(conn)
    return conn


def row_to_dict(row: sqlite3.Row | dict | None) -> dict:
    """Safely convert a sqlite3.Row or dict-like database row to a standard Python dictionary."""
    if not row:
        return {}
    if isinstance(row, dict):
        return row
    return dict(row)


def get_gbif_cache_connection() -> sqlite3.Connection:
    """Create and initialize a dedicated connection for the gbif_cache.db database file.

    Returns:
        sqlite3.Connection: Database connection to separate gbif_cache.db file.
    """
    conn = get_db_connection(GBIF_CACHE_DB_PATH)
    with conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS gbif_api_cache (
                taxon_key TEXT PRIMARY KEY,
                response_json TEXT NOT NULL,
                cached_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_gbif_cache_ts ON gbif_api_cache(cached_at);
        """)
    return conn


def prune_gbif_cache(
    conn: sqlite3.Connection | None = None,
    max_size_mb: float = 100.0,
    max_age_days: int = 7,
) -> int:
    """Prune expired (> 7 days) and LRU cache entries to maintain size under max_size_mb (100 MB).

    Args:
        conn: Optional SQLite connection to gbif_cache.db.
        max_size_mb: Maximum allowed database size in MB (default: 100.0).
        max_age_days: Maximum age of cached entries in days (default: 7).

    Returns:
        int: Number of deleted cache rows.
    """
    import time

    should_close = False
    if conn is None:
        conn = get_gbif_cache_connection()
        should_close = True

    deleted_count = 0
    now_ts = int(time.time())
    max_age_sec = max_age_days * 86400

    try:
        # 1. Delete entries older than max_age_days (7 days)
        cutoff_ts = now_ts - max_age_sec
        with conn:
            cursor = conn.execute(
                "DELETE FROM gbif_api_cache WHERE cached_at < ?", (cutoff_ts,)
            )
            deleted_count += cursor.rowcount

        # 2. Enforce 100 MB max size limit via LRU eviction
        max_bytes = int(max_size_mb * 1024 * 1024)
        cache_file = GBIF_CACHE_DB_PATH

        if cache_file.exists() and cache_file.stat().st_size > max_bytes:
            while cache_file.exists() and cache_file.stat().st_size > max_bytes:
                with conn:
                    c_del = conn.execute("""
                        DELETE FROM gbif_api_cache
                        WHERE taxon_key IN (
                            SELECT taxon_key FROM gbif_api_cache
                            ORDER BY cached_at ASC
                            LIMIT 50
                        );
                    """)
                    if c_del.rowcount == 0:
                        break
                    deleted_count += c_del.rowcount

        if deleted_count > 0:
            conn.execute("VACUUM;")
        return deleted_count
    finally:
        if should_close:
            conn.close()


def init_app_db(conn: sqlite3.Connection | None = None) -> None:
    """Initialize the schema and indices for app_data.db (taxa & occurrences).

    Args:
        conn: Optional existing connection. If None, opens connection to APP_DB_PATH.
    """
    should_close = False
    if conn is None:
        conn = get_db_connection(APP_DB_PATH)
        should_close = True
    else:
        register_sqlite_functions(conn)

    try:
        with conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS taxa (
                    taxon_key TEXT PRIMARY KEY,
                    scientific_name TEXT NOT NULL,
                    canonical_name TEXT NOT NULL,
                    accepted_name TEXT NOT NULL,
                    rank TEXT NOT NULL,
                    kingdom TEXT,
                    phylum TEXT,
                    class TEXT,
                    order_name TEXT,
                    family TEXT,
                    genus TEXT,
                    vernacular_da TEXT,
                    vernacular_en TEXT,
                    vernacular_json TEXT,
                    occurrence_count INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS occurrences (
                    occurrence_id TEXT PRIMARY KEY,
                    taxon_key TEXT REFERENCES taxa(taxon_key),
                    latitude REAL,
                    longitude REAL,
                    locality TEXT,
                    event_date TEXT,
                    month INTEGER,
                    media_urls TEXT NOT NULL,
                    coordinate_uncertainty_m REAL,
                    recorded_by TEXT,
                    references_url TEXT
                );

                CREATE TABLE IF NOT EXISTS app_metadata (
                    key TEXT PRIMARY KEY,
                    val TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS higher_ranks (
                    rank_name TEXT PRIMARY KEY,
                    rank_level TEXT NOT NULL,
                    vernacular_da TEXT,
                    vernacular_en TEXT,
                    vernacular_json TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_taxa_hierarchy ON taxa(family, genus, rank);
                CREATE INDEX IF NOT EXISTS idx_taxa_names ON taxa(canonical_name, vernacular_da, vernacular_en);
                CREATE INDEX IF NOT EXISTS idx_higher_ranks_names ON higher_ranks(rank_name, vernacular_da, vernacular_en);
            """)

            try:
                conn.execute("ALTER TABLE taxa ADD COLUMN vernacular_json TEXT;")
            except sqlite3.OperationalError:
                pass

            try:
                conn.execute("ALTER TABLE occurrences ADD COLUMN recorded_by TEXT;")
            except sqlite3.OperationalError:
                pass

            try:
                conn.execute("ALTER TABLE occurrences ADD COLUMN references_url TEXT;")
            except sqlite3.OperationalError:
                pass


            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_occ_sampling ON occurrences(taxon_key, month);
            """)
    finally:
        if should_close:
            conn.close()


def get_app_metadata(key: str, default: str = "", conn: sqlite3.Connection | None = None) -> str:
    """Retrieve metadata value from app_data.db app_metadata table.

    Args:
        key: Metadata string key.
        default: Default return value if key is missing.
        conn: Optional SQLite connection.

    Returns:
        str: Metadata value string.
    """
    should_close = False
    if conn is None:
        conn = get_db_connection(APP_DB_PATH)
        should_close = True
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS app_metadata (
                key TEXT PRIMARY KEY,
                val TEXT NOT NULL
            );
        """)
        cursor = conn.execute("SELECT val FROM app_metadata WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row["val"] if row else default
    except sqlite3.Error:
        return default

    finally:
        if should_close:
            conn.close()


def set_app_metadata(key: str, val: str, conn: sqlite3.Connection | None = None) -> None:
    """Set metadata key/val pair in app_data.db app_metadata table.

    Args:
        key: Metadata string key.
        val: Metadata string value.
        conn: Optional SQLite connection.
    """
    should_close = False
    if conn is None:
        conn = get_db_connection(APP_DB_PATH)
        should_close = True
    try:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS app_metadata (
                    key TEXT PRIMARY KEY,
                    val TEXT NOT NULL
                );
            """)
            conn.execute(
                "INSERT OR REPLACE INTO app_metadata (key, val) VALUES (?, ?)",
                (key, val),
            )
    finally:
        if should_close:
            conn.close()




def init_user_db(conn: sqlite3.Connection | None = None) -> None:
    """Initialize the schema and indices for user_data.db (user progress & history).

    Args:
        conn: Optional existing connection. If None, opens connection to USER_DB_PATH.
    """
    should_close = False
    if conn is None:
        conn = get_db_connection(USER_DB_PATH)
        should_close = True

    try:
        with conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS user_progress (
                    attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    occurrence_id TEXT,
                    target_taxon_key TEXT,
                    guessed_taxon_key TEXT,
                    is_correct BOOLEAN NOT NULL,
                    used_hint BOOLEAN NOT NULL DEFAULT 0,
                    attempt_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS user_streak (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    current_streak INTEGER NOT NULL DEFAULT 0,
                    best_streak INTEGER NOT NULL DEFAULT 0
                );

                CREATE INDEX IF NOT EXISTS idx_user_progress ON user_progress(target_taxon_key, is_correct);
                CREATE INDEX IF NOT EXISTS idx_user_progress_occ ON user_progress(occurrence_id, is_correct);
            """)
    finally:
        if should_close:
            conn.close()


def get_user_streak(conn: sqlite3.Connection | None = None) -> tuple[int, int]:
    """Get (current_streak, best_streak) from user_data.db.

    Returns:
        tuple[int, int]: (current_streak, best_streak)
    """
    should_close = False
    if conn is None:
        conn = get_db_connection(USER_DB_PATH)
        should_close = True
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_streak (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                current_streak INTEGER NOT NULL DEFAULT 0,
                best_streak INTEGER NOT NULL DEFAULT 0
            );
        """)
        row = conn.execute("SELECT current_streak, best_streak FROM user_streak WHERE id = 1").fetchone()
        if row:
            return (int(row["current_streak"]), int(row["best_streak"]))
        return (0, 0)
    finally:
        if should_close:
            conn.close()


def set_user_streak(current_streak: int, best_streak: int, conn: sqlite3.Connection | None = None) -> None:
    """Save (current_streak, best_streak) to user_data.db.

    Args:
        current_streak: Current active streak count.
        best_streak: User record best streak count.
        conn: Optional SQLite connection.
    """
    should_close = False
    if conn is None:
        conn = get_db_connection(USER_DB_PATH)
        should_close = True
    try:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_streak (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    current_streak INTEGER NOT NULL DEFAULT 0,
                    best_streak INTEGER NOT NULL DEFAULT 0
                );
            """)
            conn.execute(
                "INSERT OR REPLACE INTO user_streak (id, current_streak, best_streak) VALUES (1, ?, ?)",
                (current_streak, max(current_streak, best_streak)),
            )
    finally:
        if should_close:
            conn.close()


def init_databases() -> None:
    """Initialize both app_data.db and user_data.db schemas."""
    init_app_db()
    init_user_db()
