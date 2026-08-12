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
            # Remove any taxa with 0 occurrences (deleting associated occurrences first)
            conn.execute(
                "DELETE FROM occurrences WHERE taxon_key IN (SELECT taxon_key FROM taxa WHERE occurrence_count = 0);"
            )
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


DAISIE_DATASET_KEY = "39f36f10-559b-427f-8c86-2d28afff68ca"


def score_vernacular_item(item: dict, code: str) -> int:
    """Calculate quality score for a GBIF vernacular name record.

    Higher scores indicate higher authority/official national sources.
    Negative scores indicate known corrupt datasets (e.g., DAISIE misalignments).
    """
    source = (item.get("source") or "").lower()
    ds_key = (item.get("datasetKey") or "").lower()
    country = (item.get("country") or "").upper()
    preferred = bool(item.get("preferred"))

    if (
        ds_key == DAISIE_DATASET_KEY
        or "daisie" in source
        or "alien invasive species" in source
    ):
        return -100

    score = 0
    if preferred:
        score += 100

    target_country = LANG_COUNTRY_MAP.get(code)
    if target_country and country == target_country:
        score += 50

    trusted_keywords = (
        "national checklist",
        "rødliste",
        "red list",
        "catalogue of life",
        "dyntaxa",
        "nordic crop",
        "artsdatabanken",
        "artdatabanken",
        "flora",
        "danish",
        "sweden",
        "norway",
        "denmark",
        "checklist",
        "arter.dk",
    )
    if any(kw in source for kw in trusted_keywords):
        score += 30

    vname = (item.get("vernacularName") or "").strip()
    vname_lower = vname.lower()
    if vname and vname[0].isupper():
        score += 5

    # Reject higher-rank vernacular names (e.g. ending in "-slægten", "-familien", etc.) when enriching a species
    higher_suffixes = ("slægten", "slækt", "familien", "familie", "ordenen", "orden")
    if any(vname_lower.endswith(sfx) for sfx in higher_suffixes):
        return -100

    # For Danish, reject untrusted datasets without preferred status or trusted source (score >= 30)
    if code == "da" and score < 30 and not preferred:
        return -50

    return score


def fetch_gbif_raw_api(
    url: str,
    cache_conn: sqlite3.Connection,
    max_age_days: int = 7,
) -> dict | None:
    """Fetch raw REST API response JSON from URL with 7-day raw HTTP response caching.

    Args:
        url: Full GBIF REST API endpoint URL string.
        cache_conn: Dedicated connection to gbif_cache.db.
        max_age_days: Cache TTL in days (default: 7).

    Returns:
        dict | None: Parsed JSON dict response if successful, otherwise None.
    """
    import json
    import time
    import urllib.error
    import urllib.request

    now_ts = int(time.time())
    one_week_sec = max_age_days * 86400

    # 1. Check raw API response cache by exact URL
    try:
        cursor = cache_conn.execute(
            "SELECT response_json, cached_at FROM gbif_api_cache WHERE url = ?",
            (url,),
        )
        row = cursor.fetchone()
        if row:
            cached_json, cached_at = row["response_json"], row["cached_at"]
            if (now_ts - cached_at) < one_week_sec:
                try:
                    return json.loads(cached_json)
                except (json.JSONDecodeError, TypeError, ValueError):
                    pass
    except sqlite3.Error:
        pass

    # 2. Fetch raw response over HTTP
    req = urllib.request.Request(url, headers={"User-Agent": "taxo-trainer/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                raw_bytes = resp.read()
                raw_str = raw_bytes.decode("utf-8")
                parsed_json = json.loads(raw_str)

                with cache_conn:
                    cache_conn.execute(
                        "INSERT OR REPLACE INTO gbif_api_cache (url, response_json, cached_at) VALUES (?, ?, ?)",
                        (url, raw_str, now_ts),
                    )
                return parsed_json
    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        TimeoutError,
        json.JSONDecodeError,
    ):
        pass

    return None


def enrich_vernacular_names_from_gbif(
    conn: sqlite3.Connection | None = None,
    limit: int | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
    force_all: bool = False,
) -> int:
    """Fetch missing Danish (and English) vernacular names from GBIF Species API.

    Resolves canonical names via GBIF match API and fetches backbone vernacular names
    with 1-week persistent disk caching:
    https://api.gbif.org/v1/species/match?name={canonical_name}

    Args:
        conn: Optional SQLite connection.
        limit: Max number of taxa to enrich in one call.
        progress_callback: Optional callback receiving (processed_count, total_count).
        force_all: If True, re-fetch all taxa even if vernacular names are already present.

    Returns:
        int: Number of taxa updated with new vernacular names.
    """
    import urllib.parse

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
            t_cache_conn = get_thread_cache_conn()

            all_vernacular_items = []
            keys_to_fetch = set()
            search_names = {canonical}

            # 1. Match target canonical name via GBIF Backbone Match API
            match_url = f"https://api.gbif.org/v1/species/match?name={urllib.parse.quote(canonical)}"
            match_data = fetch_gbif_raw_api(match_url, t_cache_conn)

            if match_data:
                for k_field in (
                    "usageKey",
                    "speciesKey",
                    "acceptedUsageKey",
                    "nubKey",
                ):
                    if match_data.get(k_field):
                        keys_to_fetch.add(match_data.get(k_field))

                if match_data.get("species"):
                    search_names.add(match_data.get("species"))

                # If target name is a subspecies/variety or synonym, also match base species name
                parts = canonical.strip().split()
                if len(parts) >= 2:
                    base_sp = f"{parts[0]} {parts[1]}"
                    if base_sp != canonical:
                        search_names.add(base_sp)

            # 2. Resolve backbone keys for any parent species or base species names
            for sname in search_names:
                if sname == canonical:
                    continue
                p_match_url = f"https://api.gbif.org/v1/species/match?name={urllib.parse.quote(sname)}"
                p_data = fetch_gbif_raw_api(p_match_url, t_cache_conn)
                if p_data:
                    for k_field in (
                        "usageKey",
                        "speciesKey",
                        "acceptedUsageKey",
                        "nubKey",
                    ):
                        if p_data.get(k_field):
                            keys_to_fetch.add(p_data.get(k_field))

            # 3. Fetch vernacular names exclusively via GBIF taxon keys
            for k in list(keys_to_fetch):
                v_url = f"https://api.gbif.org/v1/species/{k}/vernacularNames?limit=1000"
                v_data = fetch_gbif_raw_api(v_url, t_cache_conn)
                if v_data and "results" in v_data:
                    all_vernacular_items.extend(v_data.get("results", []))

            results = all_vernacular_items

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


        processed_count = 0
        row_dicts = [dict(r) for r in rows]

        with ThreadPoolExecutor(max_workers=30) as executor:
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
                    progress_callback(processed_count, total, f"Checked {processed_count}/{total} species...")

        # Consolidate synonym species into accepted species via GBIF
        if progress_callback:
            progress_callback(total, total, "Consolidating synonym species via GBIF API...")
        consolidate_synonyms_with_gbif(conn)

        # Enrich higher rank (Genus & Family) vernacular names
        if progress_callback:
            progress_callback(total, total, "Enriching Genus & Family vernacular names...")
        enrich_higher_ranks_vernacular_names(conn)

        if progress_callback:
            progress_callback(total, total, "Enrichment Complete!")

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
    import threading
    import urllib.parse
    from concurrent.futures import ThreadPoolExecutor, as_completed

    should_close = False
    if conn is None:
        conn = get_db_connection(APP_DB_PATH)
        should_close = True

    cache_conn = get_gbif_cache_connection()
    try:
        g_rows = conn.execute("SELECT DISTINCT genus FROM taxa WHERE genus IS NOT NULL AND genus != '';").fetchall()
        f_rows = conn.execute("SELECT DISTINCT family FROM taxa WHERE family IS NOT NULL AND family != '';").fetchall()

        targets = [(r["genus"].strip(), "GENUS") for r in g_rows] + [(r["family"].strip(), "FAMILY") for r in f_rows]
        updated = 0

        thread_local = threading.local()

        def get_thread_cache_conn() -> sqlite3.Connection:
            if not hasattr(thread_local, "conn"):
                thread_local.conn = get_gbif_cache_connection()
            return thread_local.conn

        def process_single_target(target: tuple[str, str]) -> tuple[str, str, str | None, str | None, str | None]:
            r_name, r_level = target
            t_cache = get_thread_cache_conn()

            match_url = f"https://api.gbif.org/v1/species/match?name={urllib.parse.quote(r_name)}"
            mdata = fetch_gbif_raw_api(match_url, t_cache)

            if mdata:
                gbif_key = None
                if r_level == "GENUS":
                    gbif_key = mdata.get("genusKey") or mdata.get("usageKey")
                elif r_level == "FAMILY":
                    gbif_key = mdata.get("familyKey") or mdata.get("usageKey")
                else:
                    gbif_key = mdata.get("usageKey") or mdata.get("speciesKey")

                if gbif_key:
                    v_url = f"https://api.gbif.org/v1/species/{gbif_key}/vernacularNames?limit=100"
                    vdata = fetch_gbif_raw_api(v_url, t_cache)
                    if vdata:
                        by_lang: dict[str, list[str]] = {}
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
                        return r_name, r_level, v_da, v_en, v_json_str

            return r_name, r_level, None, None, None

        # Filter out targets already present in higher_ranks table with Danish names
        existing_rows = conn.execute(
            "SELECT rank_name FROM higher_ranks WHERE vernacular_da IS NOT NULL AND vernacular_da != '';"
        ).fetchall()
        existing_names = {r["rank_name"] for r in existing_rows}
        pending_targets = [t for t in targets if t[0] not in existing_names]

        with ThreadPoolExecutor(max_workers=30) as executor:
            futures = [executor.submit(process_single_target, t) for t in pending_targets]
            for fut in as_completed(futures):
                try:
                    r_name, r_level, v_da, v_en, v_json_str = fut.result()
                    if v_da or v_en or v_json_str:
                        with conn:
                            conn.execute(
                                "INSERT OR REPLACE INTO higher_ranks (rank_name, rank_level, vernacular_da, vernacular_en, vernacular_json) VALUES (?, ?, ?, ?, ?)",
                                (r_name, r_level, v_da, v_en, v_json_str),
                            )
                        updated += 1
                except (sqlite3.Error, KeyError, ValueError):
                    pass

        return updated
    finally:
        cache_conn.close()
        if should_close:
            conn.close()




def consolidate_synonyms_with_gbif(conn: sqlite3.Connection | None = None) -> int:
    """Query GBIF Backbone Match API to resolve synonym species and merge into accepted species.

    Args:
        conn: Optional SQLite connection.

    Returns:
        int: Number of synonym species merged or removed.
    """
    import urllib.parse

    should_close = False
    if conn is None:
        conn = get_db_connection(APP_DB_PATH)
        should_close = True

    cache_conn = get_gbif_cache_connection()

    try:
        cursor = conn.execute(
            "SELECT taxon_key, canonical_name, scientific_name FROM taxa WHERE rank = 'SPECIES'"
        )
        taxa_rows = [dict(r) for r in cursor.fetchall()]

        import threading
        from concurrent.futures import ThreadPoolExecutor, as_completed

        thread_local = threading.local()

        def get_thread_cache_conn() -> sqlite3.Connection:
            if not hasattr(thread_local, "conn"):
                thread_local.conn = get_gbif_cache_connection()
            return thread_local.conn

        def check_synonym_single(r: dict) -> tuple[dict, dict | None]:
            canon = r["canonical_name"]
            url = f"https://api.gbif.org/v1/species/match?name={urllib.parse.quote(canon)}"
            t_cache = get_thread_cache_conn()
            data = fetch_gbif_raw_api(url, t_cache)
            if not data:
                return r, None

            sp_key = (
                data.get("speciesKey")
                or data.get("acceptedUsageKey")
                or data.get("usageKey")
            )
            sp_name = (
                data.get("species")
                or data.get("canonicalName")
                or canon
            )
            match_type = data.get("matchType")
            rank_str = (data.get("rank") or "").upper()
            res = {
                "species_key": str(sp_key) if sp_key else None,
                "species_name": sp_name,
                "is_synonym": data.get("status") == "SYNONYM"
                or data.get("synonym", False),
                "is_higher_rank": match_type == "HIGHERRANK"
                or rank_str in ("GENUS", "FAMILY", "ORDER", "CLASS", "PHYLUM", "KINGDOM"),
            }
            return r, res

        merged_count = 0
        with ThreadPoolExecutor(max_workers=30) as executor:
            futures = [executor.submit(check_synonym_single, r) for r in taxa_rows]
            for fut in as_completed(futures):
                try:
                    r, match = fut.result()
                    if not match:
                        continue

                    tkey = str(r["taxon_key"])
                    canon = r["canonical_name"]

                    if match.get("is_higher_rank"):
                        with conn:
                            conn.execute("DELETE FROM occurrences WHERE taxon_key = ?", (tkey,))
                            conn.execute("DELETE FROM taxa WHERE taxon_key = ?", (tkey,))
                        merged_count += 1
                        continue

                    if (
                        match["is_synonym"]
                        and match["species_name"]
                        and match["species_name"] != canon
                    ):
                        accepted_canon = match["species_name"]
                        acc_row = conn.execute(
                            "SELECT taxon_key, scientific_name FROM taxa WHERE LOWER(canonical_name) = LOWER(?) LIMIT 1",
                            (accepted_canon,),
                        ).fetchone()
                        if acc_row:
                            acc_tkey = str(acc_row["taxon_key"])
                            if acc_tkey != tkey:
                                acc_sci = acc_row["scientific_name"] or accepted_canon
                                if canon not in acc_sci:
                                    acc_sci = f"{acc_sci} ({canon})"
                                with conn:
                                    conn.execute(
                                        "UPDATE occurrences SET taxon_key = ? WHERE taxon_key = ?",
                                        (acc_tkey, tkey),
                                    )
                                    conn.execute(
                                        "UPDATE taxa SET scientific_name = ? WHERE taxon_key = ?",
                                        (acc_sci, acc_tkey),
                                    )
                                    conn.execute(
                                        "DELETE FROM taxa WHERE taxon_key = ?", (tkey,)
                                    )
                                merged_count += 1
                except (sqlite3.Error, KeyError, ValueError):
                    pass

        return merged_count
    finally:
        cache_conn.close()
        if should_close:
            conn.close()
