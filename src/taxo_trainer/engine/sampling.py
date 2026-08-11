"""Two-Stage Sampling Engine for taxo-trainer.

Stage 1: Vectorized taxon weight calculations using NumPy (flat, natural, log, sqrt).
Stage 2: Candidate observation selection with session anti-repeat and misidentified-only filters.
"""

import sqlite3
from dataclasses import dataclass, field

import numpy as np


@dataclass
class SamplingFilter:
    """Filter criteria and weighting parameters for Stage 1 & 2 sampling."""

    mode: str = "log"  # "flat", "natural", "log", "sqrt"
    min_count: int = 1
    family: str | None = None
    genus: str | None = None
    rank: str = "SPECIES"
    month: int | None = None
    misidentified_only: bool = False
    language: str = "da"  # "da" (Danish), "en" (English), etc.
    include_taxa: list[str] = field(default_factory=list)  # Whitelist of taxa names (species/genus/family)
    exclude_taxa: list[str] = field(default_factory=list)  # Blacklist of taxa names (species/genus/family)


@dataclass
class TargetObservation:
    """Sampled target observation data record."""

    occurrence_id: str
    taxon_key: str | int
    scientific_name: str
    canonical_name: str
    family: str
    genus: str
    vernacular_da: str
    vernacular_en: str
    latitude: float | None
    longitude: float | None
    locality: str
    event_date: str
    month: int | None
    media_urls: list[str]
    recorded_by: str = ""
    references: str = ""



def compute_weights(counts: np.ndarray, mode: str) -> np.ndarray:
    """Compute mathematical weight transformations over occurrence counts.

    Args:
        counts: 1D NumPy array of non-negative occurrence counts.
        mode: Weight transformation mode ("flat", "natural", "log", "sqrt").

    Returns:
        np.ndarray: Computed float weights array.
    """
    counts = np.asarray(counts, dtype=np.float64)
    if mode == "flat":
        return np.ones_like(counts, dtype=np.float64)
    elif mode == "natural":
        return counts
    elif mode == "log":
        return np.log1p(counts)
    elif mode == "sqrt":
        return np.sqrt(counts)
    else:
        raise ValueError(f"Unknown weight transformation mode: {mode}")


def sample_stage1_taxon(
    app_conn: sqlite3.Connection,
    filters: SamplingFilter,
) -> str | None:
    """Stage 1: Sample a target taxon_key using NumPy weight probabilities.

    Args:
        app_conn: SQLite connection to app_data.db.
        filters: SamplingFilter configuration.

    Returns:
        Optional[str]: Sampled target taxon_key or None if no matching taxa found.
    """
    query = """
        SELECT taxon_key, occurrence_count
        FROM taxa
        WHERE occurrence_count >= ? AND UPPER(rank) = UPPER(?)
    """
    params: list[object] = [filters.min_count, filters.rank]

    if filters.family:
        query += " AND UPPER(family) = UPPER(?)"
        params.append(filters.family)

    if filters.genus:
        query += " AND UPPER(genus) = UPPER(?)"
        params.append(filters.genus)

    if filters.include_taxa:
        inc_conditions = []
        for inc_item in filters.include_taxa:
            inc_conditions.append("(UPPER(canonical_name) = UPPER(?) OR UPPER(genus) = UPPER(?) OR UPPER(family) = UPPER(?))")
            params.extend([inc_item, inc_item, inc_item])
        query += " AND (" + " OR ".join(inc_conditions) + ")"

    if filters.exclude_taxa:
        for exc_item in filters.exclude_taxa:
            query += " AND NOT (UPPER(canonical_name) = UPPER(?) OR UPPER(genus) = UPPER(?) OR UPPER(family) = UPPER(?))"
            params.extend([exc_item, exc_item, exc_item])


    cursor = app_conn.execute(query, params)
    rows = cursor.fetchall()

    if not rows:
        return None

    keys = np.array([str(r["taxon_key"]) for r in rows])
    counts = np.array([r["occurrence_count"] for r in rows], dtype=np.float64)

    weights = compute_weights(counts, filters.mode)
    total_weight = np.sum(weights)

    if total_weight <= 0:
        probabilities = np.full_like(weights, 1.0 / len(weights))
    else:
        probabilities = weights / total_weight

    sampled_key = str(np.random.choice(keys, p=probabilities))
    return sampled_key


def get_candidate_observations(
    app_conn: sqlite3.Connection,
    user_conn: sqlite3.Connection,
    taxon_key: str | int,
    filters: SamplingFilter,
) -> list[sqlite3.Row]:
    """Retrieve candidate occurrence rows for a given taxon_key.

    Args:
        app_conn: SQLite connection to app_data.db.
        user_conn: SQLite connection to user_data.db.
        taxon_key: Target GBIF taxon_key.
        filters: SamplingFilter configuration.

    Returns:
        List[sqlite3.Row]: Matching occurrence candidate records.
    """
    query = "SELECT * FROM occurrences WHERE taxon_key = ?"
    params: list[object] = [str(taxon_key)]


    if filters.month is not None:
        query += " AND month = ?"
        params.append(filters.month)

    if filters.misidentified_only:
        # Restrict to occurrence_ids previously logged as incorrect
        cursor = user_conn.execute(
            "SELECT DISTINCT occurrence_id FROM user_progress WHERE is_correct = 0 AND occurrence_id IS NOT NULL"
        )
        misidentified_ids = {row["occurrence_id"] for row in cursor.fetchall()}
        if not misidentified_ids:
            return []
        placeholders = ",".join("?" for _ in misidentified_ids)
        query += f" AND occurrence_id IN ({placeholders})"
        params.extend(list(misidentified_ids))

    if not filters.misidentified_only:
        query += " LIMIT 200"

    cursor = app_conn.execute(query, params)
    return cursor.fetchall()


def sample_stage2_observation(
    app_conn: sqlite3.Connection,
    user_conn: sqlite3.Connection,
    taxon_key: str | int,
    filters: SamplingFilter,
    seen_set: set[str],
) -> TargetObservation | None:
    """Stage 2: Sample an observation for the given taxon_key, enforcing anti-repeat tracking.

    Args:
        app_conn: Connection to app_data.db.
        user_conn: Connection to user_data.db.
        taxon_key: Sampled taxon key.
        filters: Sampling filter configuration.
        seen_set: Mutable set of seen occurrence_ids in current session.

    Returns:
        Optional[TargetObservation]: Selected observation dataclass or None.
    """
    candidates = get_candidate_observations(app_conn, user_conn, taxon_key, filters)
    if not candidates:
        return None

    unseen_candidates = [c for c in candidates if c["occurrence_id"] not in seen_set]

    # Fallback: if all candidate observations for this species have been seen, reset seen status for this species
    if not unseen_candidates:
        for c in candidates:
            seen_set.discard(c["occurrence_id"])
        unseen_candidates = candidates

    chosen = unseen_candidates[np.random.randint(0, len(unseen_candidates))]
    seen_set.add(chosen["occurrence_id"])

    # Fetch taxon metadata
    taxon_cursor = app_conn.execute(
        "SELECT * FROM taxa WHERE taxon_key = ?", (taxon_key,)
    )
    taxon_row = taxon_cursor.fetchone()

    media_list = (
        [url.strip() for url in chosen["media_urls"].split("|") if url.strip()]
        if chosen["media_urls"]
        else []
    )

    rec_by = chosen["recorded_by"] if "recorded_by" in chosen.keys() and chosen["recorded_by"] else ""  # noqa: SIM118
    ref_link = chosen["references_url"] if "references_url" in chosen.keys() and chosen["references_url"] else ""  # noqa: SIM118
    if not ref_link and chosen["occurrence_id"] and str(chosen["occurrence_id"]).isdigit():
        ref_link = f"https://www.gbif.org/occurrence/{chosen['occurrence_id']}"

    return TargetObservation(
        occurrence_id=chosen["occurrence_id"],
        taxon_key=taxon_key,
        scientific_name=taxon_row["scientific_name"] if taxon_row else "",
        canonical_name=taxon_row["canonical_name"] if taxon_row else "",
        family=taxon_row["family"] if taxon_row else "",
        genus=taxon_row["genus"] if taxon_row else "",
        vernacular_da=taxon_row["vernacular_da"] if taxon_row else "",
        vernacular_en=taxon_row["vernacular_en"] if taxon_row else "",
        latitude=chosen["latitude"],
        longitude=chosen["longitude"],
        locality=chosen["locality"] or "",
        event_date=chosen["event_date"] or "",
        month=chosen["month"],
        media_urls=media_list,
        recorded_by=rec_by,
        references=ref_link,
    )



def sample_next_question(
    app_conn: sqlite3.Connection,
    user_conn: sqlite3.Connection,
    filters: SamplingFilter,
    seen_set: set[str],
    max_attempts: int = 20,
) -> TargetObservation | None:
    """Execute complete Two-Stage Sampling flow.

    Args:
        app_conn: Connection to app_data.db.
        user_conn: Connection to user_data.db.
        filters: Active sampling configuration.
        seen_set: Session tracking set of seen occurrence IDs.
        max_attempts: Max attempts to select a valid observation before giving up.

    Returns:
        Optional[TargetObservation]: Sampled question observation object.
    """
    for _ in range(max_attempts):
        taxon_key = sample_stage1_taxon(app_conn, filters)
        if taxon_key is None:
            return None
        obs = sample_stage2_observation(app_conn, user_conn, taxon_key, filters, seen_set)
        if obs is not None:
            return obs
    return None
