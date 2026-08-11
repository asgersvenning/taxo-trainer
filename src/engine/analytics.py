import sqlite3
from dataclasses import dataclass

from src.db import get_user_streak, init_user_db
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


@dataclass
class FamilyMastery:
    """Family mastery summary entry."""

    family_name: str
    display_name: str
    total_attempts: int
    correct_attempts: int
    accuracy_pct: float


@dataclass
class TroubleTaxon:
    """Struggling species entry with lowest accuracy."""

    taxon_key: int
    canonical_name: str
    display_name: str
    family: str
    total_attempts: int
    correct_attempts: int
    accuracy_pct: float


def get_time_cutoff_sql(time_range: str) -> str:
    """Return SQL clause fragment for time range filtering on attempt_timestamp.

    Supported values: '1H', '24H', '7D', '30D', '1Y', 'ALL'.
    """
    range_map = {
        "1H": "DATETIME('now', '-1 hour')",
        "24H": "DATETIME('now', '-1 day')",
        "7D": "DATETIME('now', '-7 days')",
        "30D": "DATETIME('now', '-30 days')",
        "1Y": "DATETIME('now', '-1 year')",
    }
    cutoff = range_map.get(time_range.upper())
    if cutoff:
        return f"attempt_timestamp >= {cutoff}"
    return "1=1"


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


def get_global_stats(
    user_conn: sqlite3.Connection,
    app_conn: sqlite3.Connection,
    time_range: str = "ALL",
) -> dict[str, float | int]:
    """Calculate aggregate user metrics, accuracy percentages, and mastered species counts.

    Req #9c: Unassisted accuracy strictly requires used_hint = 0.

    Args:
        user_conn: Connection to user_data.db.
        app_conn: Connection to app_data.db.
        time_range: Time range filter ('ALL', '1H', '24H', '7D', '30D', '1Y').

    Returns:
        Dict: Summary dictionary containing total_attempts, unassisted_attempts,
              unassisted_accuracy_pct, mastered_species_count, streaks, etc.
    """
    init_user_db(user_conn)
    where_time = get_time_cutoff_sql(time_range)

    cursor = user_conn.execute(
        f"SELECT COUNT(*) as total FROM user_progress WHERE {where_time};"
    )
    total_attempts = cursor.fetchone()["total"]

    cursor = user_conn.execute(
        f"SELECT COUNT(*) as cnt FROM user_progress WHERE used_hint = 0 AND {where_time};"
    )
    unassisted_attempts = cursor.fetchone()["cnt"]

    cursor = user_conn.execute(
        f"SELECT COUNT(*) as cnt FROM user_progress WHERE used_hint = 0 AND is_correct = 1 AND {where_time};"
    )
    unassisted_correct = cursor.fetchone()["cnt"]

    unassisted_accuracy_pct = (
        (unassisted_correct / unassisted_attempts * 100.0)
        if unassisted_attempts > 0
        else 0.0
    )

    # Mastered species calculation: >= 90% unassisted accuracy over >= 5 unassisted attempts
    mastery_query = f"""
        SELECT target_taxon_key,
               COUNT(*) as total_attempts,
               SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) as correct_attempts
        FROM user_progress
        WHERE used_hint = 0 AND {where_time}
        GROUP BY target_taxon_key
        HAVING total_attempts >= 5 AND (CAST(correct_attempts AS FLOAT) / total_attempts) >= 0.90;
    """
    mastered_cursor = user_conn.execute(mastery_query)
    mastered_species_count = len(mastered_cursor.fetchall())

    curr_streak, best_streak = get_user_streak(user_conn)

    return {
        "total_attempts": total_attempts,
        "unassisted_attempts": unassisted_attempts,
        "unassisted_correct": unassisted_correct,
        "unassisted_accuracy_pct": round(unassisted_accuracy_pct, 1),
        "mastered_species_count": mastered_species_count,
        "current_streak": curr_streak,
        "best_streak": best_streak,
    }


def get_family_mastery_stats(
    user_conn: sqlite3.Connection,
    app_conn: sqlite3.Connection,
    time_range: str = "ALL",
    limit: int = 5,
) -> tuple[list[FamilyMastery], list[FamilyMastery]]:
    """Return top best performing and worst performing plant families.

    Args:
        user_conn: Connection to user_data.db.
        app_conn: Connection to app_data.db.
        time_range: Time range filter.
        limit: Max families per list.

    Returns:
        tuple[list[FamilyMastery], list[FamilyMastery]]: (best_families, worst_families)
    """
    init_user_db(user_conn)
    where_time = get_time_cutoff_sql(time_range)

    query = f"""
        SELECT target_taxon_key,
               COUNT(*) as total,
               SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) as correct
        FROM user_progress
        WHERE {where_time}
        GROUP BY target_taxon_key;
    """
    rows = user_conn.execute(query).fetchall()

    family_stats: dict[str, dict[str, int]] = {}
    for r in rows:
        t_key = r["target_taxon_key"]
        tax_row = app_conn.execute(
            "SELECT family FROM taxa WHERE taxon_key = ?", (t_key,)
        ).fetchone()
        fam = tax_row["family"] if tax_row and tax_row["family"] else "Unknown"
        if fam not in family_stats:
            family_stats[fam] = {"total": 0, "correct": 0}
        family_stats[fam]["total"] += r["total"]
        family_stats[fam]["correct"] += r["correct"]

    res_list: list[FamilyMastery] = []
    for fam, s in family_stats.items():
        if s["total"] > 0:
            acc = round((s["correct"] / s["total"]) * 100.0, 1)
            hr = app_conn.execute(
                "SELECT vernacular_da, vernacular_en FROM higher_ranks WHERE rank_name = ?",
                (fam,),
            ).fetchone()
            v_disp = get_display_name(hr) if hr else fam
            disp = f"{v_disp} ({fam})" if v_disp and v_disp != fam else fam
            res_list.append(
                FamilyMastery(
                    family_name=fam,
                    display_name=disp,
                    total_attempts=s["total"],
                    correct_attempts=s["correct"],
                    accuracy_pct=acc,
                )
            )

    best = sorted(res_list, key=lambda x: (x.accuracy_pct, x.total_attempts), reverse=True)[:limit]
    worst_candidates = [f for f in res_list if f.total_attempts >= 2]
    worst = sorted(worst_candidates, key=lambda x: (x.accuracy_pct, -x.total_attempts))[:limit]

    return best, worst


def get_trouble_taxa(
    user_conn: sqlite3.Connection,
    app_conn: sqlite3.Connection,
    time_range: str = "ALL",
    limit: int = 5,
) -> list[TroubleTaxon]:
    """Return top species with lowest accuracy (attempts >= 2).

    Args:
        user_conn: Connection to user_data.db.
        app_conn: Connection to app_data.db.
        time_range: Time range filter.
        limit: Max species entries.

    Returns:
        list[TroubleTaxon]: Species requiring extra practice.
    """
    init_user_db(user_conn)
    where_time = get_time_cutoff_sql(time_range)

    query = f"""
        SELECT target_taxon_key,
               COUNT(*) as total,
               SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) as correct
        FROM user_progress
        WHERE {where_time}
        GROUP BY target_taxon_key
        HAVING total >= 2
        ORDER BY (CAST(correct AS FLOAT) / total) ASC, total DESC
        LIMIT ?;
    """
    rows = user_conn.execute(query, (limit,)).fetchall()

    results: list[TroubleTaxon] = []
    for r in rows:
        t_key = r["target_taxon_key"]
        t_row = app_conn.execute("SELECT * FROM taxa WHERE taxon_key = ?", (t_key,)).fetchone()
        if t_row:
            acc = round((r["correct"] / r["total"]) * 100.0, 1)
            results.append(
                TroubleTaxon(
                    taxon_key=t_key,
                    canonical_name=t_row["canonical_name"],
                    display_name=get_display_name(t_row),
                    family=t_row["family"] or "",
                    total_attempts=r["total"],
                    correct_attempts=r["correct"],
                    accuracy_pct=acc,
                )
            )
    return results


def get_dataset_coverage(
    user_conn: sqlite3.Connection,
    app_conn: sqlite3.Connection,
) -> dict[str, float | int]:
    """Calculate dataset species coverage metrics.

    Returns:
        dict: total_species, encountered_species, coverage_pct.
    """
    init_user_db(user_conn)
    t_row = app_conn.execute("SELECT COUNT(*) as cnt FROM taxa WHERE rank = 'SPECIES';").fetchone()
    total_species = t_row["cnt"] if t_row else 0

    e_row = user_conn.execute("SELECT COUNT(DISTINCT target_taxon_key) as cnt FROM user_progress;").fetchone()
    encountered_species = e_row["cnt"] if e_row else 0

    coverage_pct = round((encountered_species / total_species * 100.0), 1) if total_species > 0 else 0.0
    return {
        "total_species": total_species,
        "encountered_species": encountered_species,
        "coverage_pct": coverage_pct,
    }


def get_confusion_matrix(
    user_conn: sqlite3.Connection,
    app_conn: sqlite3.Connection,
    time_range: str = "ALL",
    limit: int = 10,
) -> list[ConfusionPair]:
    """Retrieve top-N pairwise species misidentifications.

    Args:
        user_conn: Connection to user_data.db.
        app_conn: Connection to app_data.db.
        time_range: Time range filter.
        limit: Max pairwise entries to return.

    Returns:
        List[ConfusionPair]: Top misidentification lookalikes.
    """
    init_user_db(user_conn)
    where_time = get_time_cutoff_sql(time_range)

    query = f"""
        SELECT target_taxon_key, guessed_taxon_key, COUNT(*) as err_count
        FROM user_progress
        WHERE is_correct = 0 AND guessed_taxon_key IS NOT NULL AND {where_time}
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
