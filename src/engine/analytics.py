"""User progress tracking, metrics analytics, and confusion matrix engine.

Logs identification attempts, calculates global and per-species accuracy,
enforces hint penalties, and computes taxonomic confusion matrices.
"""

import sqlite3
from dataclasses import dataclass

from src.db import init_user_db
from src.engine.validator import get_display_name


@dataclass
class ConfusionPair:
    """Pairwise misidentification count entry."""

    target_taxon_key: int
    target_canonical: str
    target_display: str
    guessed_taxon_key: int
    guessed_canonical: str
    guessed_display: str
    count: int


def log_attempt(
    user_conn: sqlite3.Connection,
    occurrence_id: str,
    target_taxon_key: int,
    guessed_taxon_key: int | None,
    is_correct: bool,
    used_hint: bool = False,
) -> int:
    """Log user question attempt into user_data.db user_progress table.

    Args:
        user_conn: Connection to user_data.db.
        occurrence_id: DwC occurrence_id.
        target_taxon_key: Ground truth target taxon_key.
        guessed_taxon_key: Optional guessed taxon_key for confusion matrix.
        is_correct: Whether guess was accurate.
        used_hint: Flag if hint was used during attempt.

    Returns:
        int: Generated attempt_id.
    """
    init_user_db(user_conn)
    with user_conn:
        cursor = user_conn.execute(
            """
            INSERT INTO user_progress (
                occurrence_id, target_taxon_key, guessed_taxon_key,
                is_correct, used_hint
            ) VALUES (?, ?, ?, ?, ?);
            """,
            (
                occurrence_id,
                target_taxon_key,
                guessed_taxon_key,
                1 if is_correct else 0,
                1 if used_hint else 0,
            ),
        )
        return cursor.lastrowid


def get_global_stats(user_conn: sqlite3.Connection, app_conn: sqlite3.Connection) -> dict[str, float | int]:
    """Calculate aggregate user metrics, accuracy percentages, and mastered species counts.

    Req #9c: Unassisted accuracy strictly requires used_hint = 0.

    Args:
        user_conn: Connection to user_data.db.
        app_conn: Connection to app_data.db.

    Returns:
        Dict: Summary dictionary containing total_attempts, unassisted_attempts,
              unassisted_accuracy_pct, mastered_species_count.
    """
    init_user_db(user_conn)

    cursor = user_conn.execute("SELECT COUNT(*) as total FROM user_progress;")
    total_attempts = cursor.fetchone()["total"]

    cursor = user_conn.execute(
        "SELECT COUNT(*) as cnt FROM user_progress WHERE used_hint = 0;"
    )
    unassisted_attempts = cursor.fetchone()["cnt"]

    cursor = user_conn.execute(
        "SELECT COUNT(*) as cnt FROM user_progress WHERE used_hint = 0 AND is_correct = 1;"
    )
    unassisted_correct = cursor.fetchone()["cnt"]

    unassisted_accuracy_pct = (
        (unassisted_correct / unassisted_attempts * 100.0)
        if unassisted_attempts > 0
        else 0.0
    )

    # Mastered species calculation: >= 90% unassisted accuracy over >= 5 unassisted attempts
    mastery_query = """
        SELECT target_taxon_key,
               COUNT(*) as total_attempts,
               SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) as correct_attempts
        FROM user_progress
        WHERE used_hint = 0
        GROUP BY target_taxon_key
        HAVING total_attempts >= 5 AND (CAST(correct_attempts AS FLOAT) / total_attempts) >= 0.90;
    """
    mastered_cursor = user_conn.execute(mastery_query)
    mastered_species_count = len(mastered_cursor.fetchall())

    return {
        "total_attempts": total_attempts,
        "unassisted_attempts": unassisted_attempts,
        "unassisted_correct": unassisted_correct,
        "unassisted_accuracy_pct": round(unassisted_accuracy_pct, 1),
        "mastered_species_count": mastered_species_count,
    }


def get_confusion_matrix(
    user_conn: sqlite3.Connection,
    app_conn: sqlite3.Connection,
    limit: int = 10,
) -> list[ConfusionPair]:
    """Retrieve top-N pairwise species misidentifications.

    Args:
        user_conn: Connection to user_data.db.
        app_conn: Connection to app_data.db.
        limit: Max pairwise entries to return.

    Returns:
        List[ConfusionPair]: Top misidentification lookalikes.
    """
    init_user_db(user_conn)

    query = """
        SELECT target_taxon_key, guessed_taxon_key, COUNT(*) as err_count
        FROM user_progress
        WHERE is_correct = 0 AND guessed_taxon_key IS NOT NULL
        GROUP BY target_taxon_key, guessed_taxon_key
        ORDER BY err_count DESC
        LIMIT ?;
    """

    cursor = user_conn.execute(query, (limit,))
    rows = cursor.fetchall()

    results: list[ConfusionPair] = []
    for r in rows:
        t_key = r["target_taxon_key"]
        g_key = r["guessed_taxon_key"]
        err_cnt = r["err_count"]

        # Fetch target details from app_conn
        t_cur = app_conn.execute("SELECT * FROM taxa WHERE taxon_key = ?", (t_key,))
        t_row = t_cur.fetchone()

        # Fetch guessed details from app_conn
        g_cur = app_conn.execute("SELECT * FROM taxa WHERE taxon_key = ?", (g_key,))
        g_row = g_cur.fetchone()

        if t_row and g_row:
            results.append(
                ConfusionPair(
                    target_taxon_key=t_key,
                    target_canonical=t_row["canonical_name"],
                    target_display=get_display_name(t_row),
                    guessed_taxon_key=g_key,
                    guessed_canonical=g_row["canonical_name"],
                    guessed_display=get_display_name(g_row),
                    count=err_cnt,
                )
            )

    return results
