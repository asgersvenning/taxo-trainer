import sqlite3
from dataclasses import dataclass

from taxo_trainer.db import get_active_data_source, get_user_streak, init_user_db
from taxo_trainer.engine.validator import get_display_name


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
    """Family mastery summary entry (backwards compatible)."""

    family_name: str
    display_name: str
    total_attempts: int
    correct_attempts: int
    accuracy_pct: float
    bayesian_score: float = 0.5

    @property
    def taxon_name(self) -> str:
        return self.family_name


@dataclass
class RankMastery:
    """Taxonomic rank mastery summary entry."""

    taxon_name: str
    display_name: str
    rank: str
    total_attempts: int
    correct_attempts: int
    accuracy_pct: float
    bayesian_score: float


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


@dataclass
class AccuracyPoint:
    """Data point for accuracy over time EMA graph."""

    attempt_num: int
    timestamp: str
    raw_correct: bool
    ema_accuracy: float


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


def get_data_source_where_sql(
    data_source: str | None,
    app_conn: sqlite3.Connection | None = None,
) -> tuple[str, list[str]]:
    """Build SQL WHERE fragment and parameter list for data source isolation.

    Args:
        data_source: Data source identifier string or None.
        app_conn: Optional app_data.db connection to look up active data source.

    Returns:
        tuple[str, list[str]]: (sql_fragment, parameters)
    """
    ds = data_source or (get_active_data_source(app_conn) if app_conn else None)
    if ds:
        return "(data_source = ? OR data_source = 'default' OR data_source IS NULL)", [ds]
    return "1=1", []


def log_attempt(
    user_conn: sqlite3.Connection,
    occurrence_id: str,
    target_taxon_key: int,
    guessed_taxon_key: int | None,
    is_correct: bool,
    used_hint: bool = False,
    data_source: str | None = None,
    app_conn: sqlite3.Connection | None = None,
) -> int:
    """Log user question attempt into user_data.db user_progress table.

    Args:
        user_conn: Connection to user_data.db.
        occurrence_id: DwC occurrence_id.
        target_taxon_key: Ground truth target taxon_key.
        guessed_taxon_key: Optional guessed taxon_key for confusion matrix.
        is_correct: Whether guess was accurate.
        used_hint: Flag if hint was used during attempt.
        data_source: Optional data source identifier string.
        app_conn: Optional connection to app_data.db to resolve active data source.

    Returns:
        int: Generated attempt_id.
    """
    init_user_db(user_conn)
    ds = data_source or (get_active_data_source(app_conn) if app_conn else "default")
    with user_conn:
        cursor = user_conn.execute(
            """
            INSERT INTO user_progress (
                occurrence_id, target_taxon_key, guessed_taxon_key,
                is_correct, used_hint, data_source
            ) VALUES (?, ?, ?, ?, ?, ?);
            """,
            (
                occurrence_id,
                target_taxon_key,
                guessed_taxon_key,
                1 if is_correct else 0,
                1 if used_hint else 0,
                ds,
            ),
        )
        return cursor.lastrowid



def get_global_stats(
    user_conn: sqlite3.Connection,
    app_conn: sqlite3.Connection,
    time_range: str = "ALL",
    data_source: str | None = None,
) -> dict[str, float | int]:
    """Calculate aggregate user metrics, accuracy percentages, and mastered species counts.

    Req #9c: Unassisted accuracy strictly requires used_hint = 0.

    Args:
        user_conn: Connection to user_data.db.
        app_conn: Connection to app_data.db.
        time_range: Time range filter ('ALL', '1H', '24H', '7D', '30D', '1Y').
        data_source: Data source identifier filter.

    Returns:
        Dict: Summary dictionary containing total_attempts, unassisted_attempts,
              unassisted_accuracy_pct, mastered_species_count, streaks, etc.
    """
    init_user_db(user_conn)
    ds = data_source or get_active_data_source(app_conn)
    where_time = get_time_cutoff_sql(time_range)
    where_ds, params_ds = get_data_source_where_sql(ds, app_conn)

    cursor = user_conn.execute(
        f"SELECT COUNT(*) as total FROM user_progress WHERE {where_time} AND {where_ds};",
        params_ds,
    )
    total_attempts = cursor.fetchone()["total"]

    cursor = user_conn.execute(
        f"SELECT COUNT(*) as cnt FROM user_progress WHERE used_hint = 0 AND {where_time} AND {where_ds};",
        params_ds,
    )
    unassisted_attempts = cursor.fetchone()["cnt"]

    cursor = user_conn.execute(
        f"SELECT COUNT(*) as cnt FROM user_progress WHERE used_hint = 0 AND is_correct = 1 AND {where_time} AND {where_ds};",
        params_ds,
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
        WHERE used_hint = 0 AND {where_time} AND {where_ds}
        GROUP BY target_taxon_key
        HAVING total_attempts >= 5 AND (CAST(correct_attempts AS FLOAT) / total_attempts) >= 0.90;
    """
    mastered_cursor = user_conn.execute(mastery_query, params_ds)
    mastered_species_count = len(mastered_cursor.fetchall())

    curr_streak, best_streak = get_user_streak(user_conn, data_source=ds)

    return {
        "total_attempts": total_attempts,
        "unassisted_attempts": unassisted_attempts,
        "unassisted_correct": unassisted_correct,
        "unassisted_accuracy_pct": round(unassisted_accuracy_pct, 1),
        "mastered_species_count": mastered_species_count,
        "current_streak": curr_streak,
        "best_streak": best_streak,
    }


def get_rank_mastery_stats(
    user_conn: sqlite3.Connection,
    app_conn: sqlite3.Connection,
    rank_level: str = "FAMILY",
    time_range: str = "ALL",
    data_source: str | None = None,
    limit: int | None = 5,
) -> tuple[list[RankMastery], list[RankMastery]]:
    """Return top best performing and worst performing taxa at the specified rank level.

    Uses Bayesian accuracy ranking under a 50% prior (pseudocount m=1, prior weight 2)
    to balance accuracy against sample size/uncertainty.

    Args:
        user_conn: Connection to user_data.db.
        app_conn: Connection to app_data.db.
        rank_level: Rank level to group by ('ORDER', 'FAMILY', 'GENUS', 'SPECIES').
        time_range: Time range filter.
        data_source: Data source identifier filter.
        limit: Optional max items per list (None or <= 0 returns all).

    Returns:
        tuple[list[RankMastery], list[RankMastery]]: (best_taxa, worst_taxa)
    """
    init_user_db(user_conn)
    ds = data_source or get_active_data_source(app_conn)
    where_time = get_time_cutoff_sql(time_range)
    where_ds, params_ds = get_data_source_where_sql(ds, app_conn)

    query = f"""
        SELECT target_taxon_key,
               COUNT(*) as total,
               SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) as correct
        FROM user_progress
        WHERE {where_time} AND {where_ds}
        GROUP BY target_taxon_key;
    """
    rows = user_conn.execute(query, params_ds).fetchall()

    rank_key = rank_level.upper()
    col_name = "family"
    if rank_key == "ORDER":
        col_name = "order_name"
    elif rank_key == "GENUS":
        col_name = "genus"
    elif rank_key == "SPECIES":
        col_name = "canonical_name"

    stats: dict[str, dict[str, int]] = {}
    for r in rows:
        t_key = r["target_taxon_key"]
        tax_row = app_conn.execute(
            f"SELECT {col_name}, canonical_name FROM taxa WHERE taxon_key = ?", (t_key,)
        ).fetchone()

        if tax_row and tax_row[col_name]:
            name_val = tax_row[col_name]
        elif tax_row and rank_key == "SPECIES":
            name_val = tax_row["canonical_name"]
        else:
            name_val = "Unknown"

        if name_val not in stats:
            stats[name_val] = {"total": 0, "correct": 0}
        stats[name_val]["total"] += r["total"]
        stats[name_val]["correct"] += r["correct"]

    res_list: list[RankMastery] = []
    for name_val, s in stats.items():
        if s["total"] > 0:
            acc = round((s["correct"] / s["total"]) * 100.0, 1)
            # Bayesian smoothed score under 50% prior (m=1 prior pseudocount correct, m=1 incorrect)
            bayesian_score = (s["correct"] + 1.0) / (s["total"] + 2.0)

            # Determine display name
            if rank_key in ("ORDER", "FAMILY"):
                hr = app_conn.execute(
                    "SELECT vernacular_da, vernacular_en FROM higher_ranks WHERE rank_name = ?",
                    (name_val,),
                ).fetchone()
                v_disp = get_display_name(hr) if hr else name_val
                disp = f"{v_disp} ({name_val})" if v_disp and v_disp != name_val else name_val
            elif rank_key == "SPECIES":
                t_r = app_conn.execute(
                    "SELECT * FROM taxa WHERE canonical_name = ? LIMIT 1", (name_val,)
                ).fetchone()
                disp = get_display_name(t_r) if t_r else name_val
            else:
                disp = name_val

            res_list.append(
                RankMastery(
                    taxon_name=name_val,
                    display_name=disp,
                    rank=rank_key,
                    total_attempts=s["total"],
                    correct_attempts=s["correct"],
                    accuracy_pct=acc,
                    bayesian_score=bayesian_score,
                )
            )

    # Best performing: sorted descending by Bayesian score, then total attempts
    best = sorted(res_list, key=lambda x: (x.bayesian_score, x.total_attempts), reverse=True)

    # Worst performing (needing practice): sorted ascending by Bayesian score, then total attempts descending
    worst = sorted(res_list, key=lambda x: (x.bayesian_score, -x.total_attempts))

    if limit is not None and limit > 0:
        return best[:limit], worst[:limit]
    return best, worst


def get_family_mastery_stats(
    user_conn: sqlite3.Connection,
    app_conn: sqlite3.Connection,
    time_range: str = "ALL",
    limit: int = 5,
    data_source: str | None = None,
) -> tuple[list[FamilyMastery], list[FamilyMastery]]:
    """Return top best performing and worst performing plant families (backwards compatible).

    Args:
        user_conn: Connection to user_data.db.
        app_conn: Connection to app_data.db.
        time_range: Time range filter.
        limit: Max families per list.
        data_source: Data source identifier filter.

    Returns:
        tuple[list[FamilyMastery], list[FamilyMastery]]: (best_families, worst_families)
    """
    best_ranks, worst_ranks = get_rank_mastery_stats(
        user_conn,
        app_conn,
        rank_level="FAMILY",
        time_range=time_range,
        data_source=data_source,
        limit=limit,
    )
    best_fams = [
        FamilyMastery(
            family_name=r.taxon_name,
            display_name=r.display_name,
            total_attempts=r.total_attempts,
            correct_attempts=r.correct_attempts,
            accuracy_pct=r.accuracy_pct,
            bayesian_score=r.bayesian_score,
        )
        for r in best_ranks
    ]
    worst_fams = [
        FamilyMastery(
            family_name=r.taxon_name,
            display_name=r.display_name,
            total_attempts=r.total_attempts,
            correct_attempts=r.correct_attempts,
            accuracy_pct=r.accuracy_pct,
            bayesian_score=r.bayesian_score,
        )
        for r in worst_ranks
    ]
    return best_fams, worst_fams


def get_trouble_taxa(
    user_conn: sqlite3.Connection,
    app_conn: sqlite3.Connection,
    time_range: str = "ALL",
    limit: int = 5,
    data_source: str | None = None,
) -> list[TroubleTaxon]:
    """Return top species with lowest accuracy.

    Args:
        user_conn: Connection to user_data.db.
        app_conn: Connection to app_data.db.
        time_range: Time range filter.
        limit: Max species entries.
        data_source: Data source identifier filter.

    Returns:
        list[TroubleTaxon]: Species requiring extra practice.
    """
    init_user_db(user_conn)
    ds = data_source or get_active_data_source(app_conn)
    where_time = get_time_cutoff_sql(time_range)
    where_ds, params_ds = get_data_source_where_sql(ds, app_conn)

    query = f"""
        SELECT target_taxon_key,
               COUNT(*) as total,
               SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) as correct
        FROM user_progress
        WHERE {where_time} AND {where_ds}
        GROUP BY target_taxon_key
        HAVING total >= 2
        ORDER BY ((CAST(correct AS FLOAT) + 1.0) / (total + 2.0)) ASC, total DESC
        LIMIT ?;
    """
    rows = user_conn.execute(query, (*params_ds, limit)).fetchall()

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
    data_source: str | None = None,
) -> dict[str, float | int]:
    """Calculate dataset species coverage metrics for active data source.

    Returns:
        dict: total_species, encountered_species, coverage_pct.
    """
    init_user_db(user_conn)
    ds = data_source or get_active_data_source(app_conn)
    where_ds, params_ds = get_data_source_where_sql(ds, app_conn)

    t_row = app_conn.execute("SELECT COUNT(*) as cnt FROM taxa WHERE rank = 'SPECIES';").fetchone()
    total_species = t_row["cnt"] if t_row else 0

    e_query = f"SELECT COUNT(DISTINCT target_taxon_key) as cnt FROM user_progress WHERE {where_ds};"
    e_row = user_conn.execute(e_query, params_ds).fetchone()
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
    data_source: str | None = None,
) -> list[ConfusionPair]:
    """Retrieve top-N pairwise species misidentifications.

    Args:
        user_conn: Connection to user_data.db.
        app_conn: Connection to app_data.db.
        time_range: Time range filter.
        limit: Max pairwise entries to return.
        data_source: Data source identifier filter.

    Returns:
        List[ConfusionPair]: Top misidentification lookalikes.
    """
    init_user_db(user_conn)
    ds = data_source or get_active_data_source(app_conn)
    where_time = get_time_cutoff_sql(time_range)
    where_ds, params_ds = get_data_source_where_sql(ds, app_conn)

    query = f"""
        SELECT target_taxon_key, guessed_taxon_key, COUNT(*) as err_count
        FROM user_progress
        WHERE is_correct = 0 AND guessed_taxon_key IS NOT NULL AND {where_time} AND {where_ds}
        GROUP BY target_taxon_key, guessed_taxon_key
        ORDER BY err_count DESC
        LIMIT ?;
    """

    cursor = user_conn.execute(query, (*params_ds, limit))
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


def format_attempt_timestamp(ts_str: str | None, default_num: int) -> str:
    """Format attempt timestamp string into clean human-readable date/time string.

    Args:
        ts_str: Raw datetime string from database.
        default_num: Fallback attempt index number.

    Returns:
        str: Formatted date/time string e.g. "2026-08-12 11:15".
    """
    if not ts_str:
        return f"#{default_num}"
    try:
        ts_clean = str(ts_str).replace("T", " ").split(".")[0].strip()
        parts = ts_clean.split(" ")
        if len(parts) >= 2:
            d_part, t_part = parts[0], parts[1][:5]
            return f"{d_part} {t_part}"
        return ts_clean[:16]
    except (IndexError, ValueError, TypeError):
        return str(ts_str)[:16]


def get_accuracy_over_time(
    user_conn: sqlite3.Connection,
    app_conn: sqlite3.Connection,
    time_range: str = "ALL",
    data_source: str | None = None,
    window_size: int = 15,
) -> list[AccuracyPoint]:
    """Calculate exponential moving average (EMA) of unassisted accuracy over time.

    Formula: S_i = alpha * x_i + (1 - alpha) * S_{i-1}, where alpha = 2 / (window_size + 1).

    Args:
        user_conn: Connection to user_data.db.
        app_conn: Connection to app_data.db.
        time_range: Time range filter ('ALL', '1H', '24H', '7D', '30D', '1Y').
        data_source: Data source identifier filter.
        window_size: EMA smoothing window size (default: 15).

    Returns:
        list[AccuracyPoint]: Chronological sequence of EMA accuracy points.
    """
    init_user_db(user_conn)
    ds = data_source or get_active_data_source(app_conn)
    where_time = get_time_cutoff_sql(time_range)
    where_ds, params_ds = get_data_source_where_sql(ds, app_conn)

    query = f"""
        SELECT attempt_id, is_correct, used_hint, attempt_timestamp
        FROM user_progress
        WHERE {where_time} AND {where_ds}
        ORDER BY attempt_timestamp ASC, attempt_id ASC;
    """
    rows = user_conn.execute(query, params_ds).fetchall()

    if not rows:
        return []

    alpha = 2.0 / (window_size + 1.0)
    points: list[AccuracyPoint] = []
    ema = 50.0

    for idx, r in enumerate(rows, start=1):
        is_unassisted_correct = (r["is_correct"] == 1) and (r["used_hint"] == 0)
        x_val = 100.0 if is_unassisted_correct else 0.0

        if idx == 1:
            ema = x_val
        else:
            ema = alpha * x_val + (1.0 - alpha) * ema

        ts = format_attempt_timestamp(r["attempt_timestamp"], idx)
        points.append(
            AccuracyPoint(
                attempt_num=idx,
                timestamp=ts,
                raw_correct=is_unassisted_correct,
                ema_accuracy=round(ema, 1),
            )
        )

    return points



