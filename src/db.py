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


def ensure_data_dir() -> Path:
    """Ensure the data directory exists.

    Returns:
        Path: Absolute path to the data directory.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR


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
    return conn


def init_app_db(conn: sqlite3.Connection | None = None) -> None:
    """Initialize the schema and indices for app_data.db (taxa & occurrences).

    Args:
        conn: Optional existing connection. If None, opens connection to APP_DB_PATH.
    """
    should_close = False
    if conn is None:
        conn = get_db_connection(APP_DB_PATH)
        should_close = True

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

                CREATE TABLE IF NOT EXISTS gbif_api_cache (
                    taxon_key TEXT PRIMARY KEY,
                    response_json TEXT NOT NULL,
                    cached_at INTEGER NOT NULL
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

                CREATE INDEX IF NOT EXISTS idx_user_progress ON user_progress(target_taxon_key, is_correct);
                CREATE INDEX IF NOT EXISTS idx_user_progress_occ ON user_progress(occurrence_id, is_correct);
            """)
    finally:
        if should_close:
            conn.close()


def init_databases() -> None:
    """Initialize both app_data.db and user_data.db schemas."""
    init_app_db()
    init_user_db()
