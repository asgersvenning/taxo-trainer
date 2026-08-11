"""Taxonomy maintenance and vernacular dictionary builder.

Handles taxonomy normalization, pre-computing occurrence counts, loading custom
vernacular dictionary JSON files, and rebuilding database indices.
"""

import json
import sqlite3
from collections.abc import Callable
from pathlib import Path

from taxo_trainer.db import (
    APP_DB_PATH,
    get_db_connection,
    get_gbif_cache_connection,
    prune_gbif_cache,
)


def update_occurrence_counts(conn: sqlite3.Connection | None = None) -> int:
    """Recalculate and update the occurrence_count field in the taxa table.

    Args:
        conn: Optional SQLite connection. If None, connects to APP_DB_PATH.

    Returns:
        int: Number of updated taxa records.
    """
    should_close = False
    if conn is None:
        conn = get_db_connection(APP_DB_PATH)
        should_close = True

    try:
        with conn:
            cursor = conn.execute("""
                UPDATE taxa
                SET occurrence_count = (
                    SELECT COUNT(*)
                    FROM occurrences
                    WHERE occurrences.taxon_key = taxa.taxon_key
                );
            """)
            updated_count = cursor.rowcount
            # Remove any taxa with 0 occurrences
            conn.execute("DELETE FROM taxa WHERE occurrence_count = 0;")
        return updated_count
    finally:
        if should_close:
            conn.close()


def load_custom_vernacular_json(
    json_path: Path, conn: sqlite3.Connection | None = None
) -> int:
    """Apply custom Danish/English vernacular dictionary JSON mappings to taxa table.

    JSON format expected:
    {
       "Quercus robur": {"vernacular_da": "Stilk-Eg", "vernacular_en": "Pedunculate Oak"},
       "1234567": {"vernacular_da": "Bøg"}
    }

    Args:
        json_path: Path to custom dictionary JSON file.
        conn: Optional SQLite connection.

    Returns:
        int: Number of taxa updated with vernacular names.
    """
    if not json_path.exists():
        return 0

    with open(json_path, "r", encoding="utf-8") as f:
        mapping: dict[str, dict[str, str]] = json.load(f)

    should_close = False
    if conn is None:
        conn = get_db_connection(APP_DB_PATH)
        should_close = True

    updated_count = 0
    try:
        with conn:
            for key, names in mapping.items():
                v_da = names.get("vernacular_da")
                v_en = names.get("vernacular_en")

                if not v_da and not v_en:
                    continue

                if key.isdigit():
                    # Match by taxon_key
                    tkey = int(key)
                    if v_da and v_en:
                        c = conn.execute(
                            "UPDATE taxa SET vernacular_da = ?, vernacular_en = ? WHERE taxon_key = ?",
                            (v_da, v_en, tkey),
                        )
                    elif v_da:
                        c = conn.execute(
                            "UPDATE taxa SET vernacular_da = ? WHERE taxon_key = ?",
                            (v_da, tkey),
                        )
                    else:
                        c = conn.execute(
                            "UPDATE taxa SET vernacular_en = ? WHERE taxon_key = ?",
                            (v_en, tkey),
                        )
                else:
                    # Match by canonical_name
                    if v_da and v_en:
                        c = conn.execute(
                            "UPDATE taxa SET vernacular_da = ?, vernacular_en = ? WHERE canonical_name = ?",
                            (v_da, v_en, key),
                        )
                    elif v_da:
                        c = conn.execute(
                            "UPDATE taxa SET vernacular_da = ? WHERE canonical_name = ?",
                            (v_da, key),
                        )
                    else:
                        c = conn.execute(
                            "UPDATE taxa SET vernacular_en = ? WHERE canonical_name = ?",
                            (v_en, key),
                        )
                updated_count += c.rowcount
        return updated_count
    finally:
        if should_close:
            conn.close()


def rebuild_indices(conn: sqlite3.Connection | None = None) -> None:
    """Rebuild and analyze database indices for fast O(1) sampling queries.

    Args:
        conn: Optional SQLite connection.
    """
    should_close = False
    if conn is None:
        conn = get_db_connection(APP_DB_PATH)
        should_close = True

    try:
        with conn:
            conn.execute("ANALYZE;")
            conn.execute("REINDEX;")
    finally:
        if should_close:
            conn.close()

LANG_MAP = {
    "dan": "da", "da": "da", "danish": "da",
    "eng": "en", "en": "en", "english": "en",
    "deu": "de", "ger": "de", "de": "de", "german": "de",
    "swe": "sv", "sv": "sv", "swedish": "sv",
    "nor": "no", "nob": "no", "nno": "no", "no": "no", "norwegian": "no",
    "fra": "fr", "fre": "fr", "fr": "fr", "french": "fr",
    "spa": "es", "es": "es", "spanish": "es",
    "nld": "nl", "dut": "nl", "nl": "nl", "dutch": "nl",
    "pol": "pl", "pl": "pl", "polish": "pl",
    "ces": "cs", "cze": "cs", "cs": "cs", "czech": "cs",
    "fin": "fi", "fi": "fi", "finnish": "fi",
    "ita": "it", "it": "it", "italian": "it",
    "por": "pt", "pt": "pt", "portuguese": "pt",
}

LANG_COUNTRY_MAP = {
    "da": "DK",
    "sv": "SE",
    "no": "NO",
    "de": "DE",
    "nl": "NL",
    "fr": "FR",
    "es": "ES",
    "en": "GB",
    "pl": "PL",
    "cs": "CZ",
    "fi": "FI",
    "it": "IT",
    "pt": "PT",
}


def score_vernacular_item(item: dict, code: str) -> int:
    """Calculate quality score for a GBIF vernacular name record.

    Higher scores indicate higher authority/official national sources.
    Negative scores indicate known corrupt datasets (e.g., DAISIE misalignments).
    """
    source = (item.get("source") or "").lower()
    country = (item.get("country") or "").upper()
    preferred = bool(item.get("preferred"))

    if "daisie" in source or "alien invasive species" in source:
        return -100

    score = 0
    if preferred:
        score += 100

    target_country = LANG_COUNTRY_MAP.get(code)
    if target_country and country == target_country:
        score += 50

    trusted_keywords = (
        "national checklist", "rødliste", "red list", "catalogue of life",
        "dyntaxa", "nordic crop", "artsdatabanken", "artdatabanken", "flora",
        "danish", "sweden", "norway", "denmark", "checklist",
    )
    if any(kw in source for kw in trusted_keywords):
        score += 30

    vname = (item.get("vernacularName") or "").strip()
    if vname and vname[0].isupper():
        score += 5

    return score


def enrich_vernacular_names_from_gbif(
    conn: sqlite3.Connection | None = None,
    limit: int | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> int:
    """Fetch missing Danish (and English) vernacular names from GBIF Species API.

    Resolves canonical names via GBIF match API and fetches backbone vernacular names
    with 1-week persistent disk caching:
    https://api.gbif.org/v1/species/match?name={canonical_name}

    Args:
        conn: Optional SQLite connection.
        limit: Max number of taxa to enrich in one call.
        progress_callback: Optional callback receiving (processed_count, total_count).

    Returns:
        int: Number of taxa updated with new vernacular names.
    """
    import json
    import time
    import urllib.error
    import urllib.parse
    import urllib.request

    should_close = False
    if conn is None:
        conn = get_db_connection(APP_DB_PATH)
        should_close = True

    cache_conn = get_gbif_cache_connection()
    prune_gbif_cache(cache_conn, max_size_mb=100.0, max_age_days=7)

    try:
        cursor = conn.execute(
            "SELECT taxon_key, canonical_name, vernacular_da, vernacular_en FROM taxa"
        )
        rows = cursor.fetchall()
        if limit:
            rows = rows[:limit]

        total = len(rows)
        updated_count = 0
        now_ts = int(time.time())
        one_week_sec = 7 * 86400  # 1 week cache TTL

        import threading
        from concurrent.futures import ThreadPoolExecutor, as_completed

        thread_local = threading.local()

        def get_thread_cache_conn() -> sqlite3.Connection:
            if not hasattr(thread_local, "conn"):
                thread_local.conn = get_gbif_cache_connection()
            return thread_local.conn

        def process_single_row(
            row_dict: dict,
        ) -> tuple[str, str | None, str | None, str | None]:
            tkey = str(row_dict["taxon_key"])
            canonical = row_dict["canonical_name"].strip()
            cache_key = canonical.lower()
            data = None

            t_cache_conn = get_thread_cache_conn()

            cache_cursor = t_cache_conn.execute(
                "SELECT response_json, cached_at FROM gbif_api_cache WHERE taxon_key = ?",
                (cache_key,),
            )
            cache_row = cache_cursor.fetchone()

            if cache_row:
                cached_json, cached_at = (
                    cache_row["response_json"],
                    cache_row["cached_at"],
                )
                if (now_ts - cached_at) < one_week_sec:
                    try:
                        data = json.loads(cached_json)
                    except (json.JSONDecodeError, TypeError, ValueError):
                        data = None

            if data is None:
                all_vernacular_items = []
                species_key = None
                species_name = canonical

                match_url = f"https://api.gbif.org/v1/species/match?name={urllib.parse.quote(canonical)}"
                req = urllib.request.Request(
                    match_url, headers={"User-Agent": "taxo-trainer/1.0"}
                )

                try:
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        if resp.status == 200:
                            match_data = json.loads(resp.read().decode("utf-8"))
                            species_key = (
                                match_data.get("speciesKey")
                                or match_data.get("usageKey")
                                or match_data.get("nubKey")
                            )
                            species_name = (
                                match_data.get("species")
                                or match_data.get("canonicalName")
                                or canonical
                            )

                            if species_key:
                                v_url = f"https://api.gbif.org/v1/species/{species_key}/vernacularNames?limit=1000"
                                req2 = urllib.request.Request(
                                    v_url, headers={"User-Agent": "taxo-trainer/1.0"}
                                )
                                with urllib.request.urlopen(req2, timeout=5) as v_resp:
                                    if v_resp.status == 200:
                                        m_json = json.loads(
                                            v_resp.read().decode("utf-8")
                                        )
                                        all_vernacular_items.extend(
                                            m_json.get("results", [])
                                        )
                except (
                    urllib.error.URLError,
                    urllib.error.HTTPError,
                    TimeoutError,
                    json.JSONDecodeError,
                ):
                    pass

                # Query GBIF species search API using GBIF-resolved species name
                try:
                    search_url = f"https://api.gbif.org/v1/species/search?q={urllib.parse.quote(species_name)}&limit=50"
                    req3 = urllib.request.Request(
                        search_url, headers={"User-Agent": "taxo-trainer/1.0"}
                    )
                    with urllib.request.urlopen(req3, timeout=5) as s_resp:
                        if s_resp.status == 200:
                            sdata = json.loads(s_resp.read().decode("utf-8"))
                            for s_item in sdata.get("results", []):
                                all_vernacular_items.extend(
                                    s_item.get("vernacularNames", [])
                                )
                                sk = s_item.get("key")
                                if sk and sk != species_key:
                                    try:
                                        v_url2 = f"https://api.gbif.org/v1/species/{sk}/vernacularNames?limit=1000"
                                        req4 = urllib.request.Request(
                                            v_url2,
                                            headers={
                                                "User-Agent": "taxo-trainer/1.0"
                                            },
                                        )
                                        with urllib.request.urlopen(
                                            req4, timeout=3
                                        ) as v_resp2:
                                            if v_resp2.status == 200:
                                                v_json2 = json.loads(
                                                    v_resp2.read().decode("utf-8")
                                                )
                                                all_vernacular_items.extend(
                                                    v_json2.get("results", [])
                                                )
                                    except (
                                        urllib.error.URLError,
                                        urllib.error.HTTPError,
                                        TimeoutError,
                                        json.JSONDecodeError,
                                    ):
                                        pass
                except (
                    urllib.error.URLError,
                    urllib.error.HTTPError,
                    TimeoutError,
                    json.JSONDecodeError,
                ):
                    pass

                data = {"results": all_vernacular_items}
                raw_str = json.dumps(data, ensure_ascii=False)
                with t_cache_conn:
                    t_cache_conn.execute(
                        "INSERT OR REPLACE INTO gbif_api_cache (taxon_key, response_json, cached_at) VALUES (?, ?, ?)",
                        (cache_key, raw_str, now_ts),
                    )

            if data and "results" in data:
                results = data.get("results", [])
                by_lang_scored: dict[str, dict[str, int]] = {}

                for item in results:
                    raw_lang = (item.get("language") or "").lower()
                    vname = item.get("vernacularName")
                    if not vname or not vname.strip():
                        continue
                    vname = vname.strip()

                    code = LANG_MAP.get(raw_lang)
                    if code:
                        sc = score_vernacular_item(item, code)
                        if sc < 0:
                            continue
                        by_lang_scored.setdefault(code, {})
                        by_lang_scored[code][vname] = max(
                            by_lang_scored[code].get(vname, -999), sc
                        )

                vernacular_dict = {}
                for code, name_scores in by_lang_scored.items():
                    sorted_names = sorted(
                        name_scores.keys(),
                        key=lambda x, ns=name_scores: (-ns[x], len(x.split()), len(x)),
                    )
                    vernacular_dict[code] = "|".join(sorted_names)

                new_da = vernacular_dict.get("da")
                new_en = vernacular_dict.get("en")
                v_json_str = (
                    json.dumps(vernacular_dict, ensure_ascii=False)
                    if vernacular_dict
                    else None
                )

                return tkey, new_da, new_en, v_json_str

            return tkey, None, None, None

        processed_count = 0
        row_dicts = [dict(r) for r in rows]

        with ThreadPoolExecutor(max_workers=10) as executor:
            future_map = {
                executor.submit(process_single_row, rd): rd for rd in row_dicts
            }
            for future in as_completed(future_map):
                try:
                    tkey, new_da, new_en, v_json_str = future.result()
                    if v_json_str or new_da or new_en:
                        with conn:
                            conn.execute(
                                """UPDATE taxa 
                                   SET vernacular_da = COALESCE(?, vernacular_da),
                                       vernacular_en = COALESCE(?, vernacular_en),
                                       vernacular_json = ? 
                                   WHERE taxon_key = ?""",
                                (new_da, new_en, v_json_str, tkey),
                            )
                        updated_count += 1
                except (sqlite3.Error, OSError, ValueError):
                    pass

                processed_count += 1
                if progress_callback:
                    progress_callback(processed_count, total)

        # Enrich higher rank (Genus & Family) vernacular names
        enrich_higher_ranks_vernacular_names(conn)

        return updated_count
    finally:
        cache_conn.close()
        if should_close:
            conn.close()


def enrich_higher_ranks_vernacular_names(conn: sqlite3.Connection | None = None) -> int:
    """Fetch and cache vernacular names for distinct Genus and Family ranks present in taxa.

    Args:
        conn: Optional SQLite connection.

    Returns:
        int: Total higher rank records updated.
    """
    import json
    import urllib.error
    import urllib.parse
    import urllib.request

    should_close = False
    if conn is None:
        conn = get_db_connection(APP_DB_PATH)
        should_close = True

    try:
        g_rows = conn.execute("SELECT DISTINCT genus FROM taxa WHERE genus IS NOT NULL AND genus != '';").fetchall()
        f_rows = conn.execute("SELECT DISTINCT family FROM taxa WHERE family IS NOT NULL AND family != '';").fetchall()

        targets = [(r["genus"].strip(), "GENUS") for r in g_rows] + [(r["family"].strip(), "FAMILY") for r in f_rows]
        updated = 0

        for r_name, r_level in targets:
            existing = conn.execute("SELECT vernacular_da, vernacular_en FROM higher_ranks WHERE rank_name = ?", (r_name,)).fetchone()
            if existing and existing["vernacular_da"]:
                continue

            match_url = f"https://api.gbif.org/v1/species/match?name={urllib.parse.quote(r_name)}"
            req = urllib.request.Request(match_url, headers={"User-Agent": "taxo-trainer/1.0"})

            try:
                with urllib.request.urlopen(req, timeout=4) as resp:
                    if resp.status == 200:
                        mdata = json.loads(resp.read().decode("utf-8"))
                        gbif_key = None
                        if r_level == "GENUS":
                            gbif_key = mdata.get("genusKey") or mdata.get("usageKey")
                        elif r_level == "FAMILY":
                            gbif_key = mdata.get("familyKey") or mdata.get("usageKey")
                        else:
                            gbif_key = mdata.get("usageKey") or mdata.get("speciesKey")
                        if gbif_key:
                            v_url = f"https://api.gbif.org/v1/species/{gbif_key}/vernacularNames?limit=100"
                            req2 = urllib.request.Request(v_url, headers={"User-Agent": "taxo-trainer/1.0"})
                            with urllib.request.urlopen(req2, timeout=4) as v_resp:
                                if v_resp.status == 200:
                                    vdata = json.loads(v_resp.read().decode("utf-8"))
                                    by_lang = {}
                                    for item in vdata.get("results", []):
                                        raw_lang = (item.get("language") or "").lower()
                                        vname = item.get("vernacularName")
                                        if not vname or not vname.strip():
                                            continue
                                        vname = vname.strip()
                                        code = LANG_MAP.get(raw_lang)
                                        if code:
                                            by_lang.setdefault(code, [])
                                            if vname not in by_lang[code]:
                                                by_lang[code].append(vname)

                                    vernacular_dict = {}
                                    for code, candidates in by_lang.items():
                                        candidates.sort(key=lambda x: (len(x.split()), len(x)))
                                        vernacular_dict[code] = "|".join(candidates)

                                    v_da = vernacular_dict.get("da")
                                    v_en = vernacular_dict.get("en")
                                    v_json_str = json.dumps(vernacular_dict, ensure_ascii=False) if vernacular_dict else None

                                    with conn:
                                        conn.execute(
                                            "INSERT OR REPLACE INTO higher_ranks (rank_name, rank_level, vernacular_da, vernacular_en, vernacular_json) VALUES (?, ?, ?, ?, ?)",
                                            (r_name, r_level, v_da, v_en, v_json_str),
                                        )
                                    updated += 1
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, sqlite3.Error):
                pass

        return updated
    finally:
        if should_close:
            conn.close()

