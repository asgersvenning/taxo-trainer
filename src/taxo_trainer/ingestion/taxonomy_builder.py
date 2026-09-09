"""Taxonomy maintenance and vernacular dictionary builder.

Handles taxonomy normalization, pre-computing occurrence counts, loading custom
vernacular dictionary JSON files, and rebuilding database indices.
"""

import json
import logging
import sqlite3
import threading
import time
from collections import Counter
from collections.abc import Callable
from email.utils import parsedate_to_datetime
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


_GBIF_COOLDOWN_LOCK = threading.Lock()
_GBIF_COOLDOWN_UNTIL = 0.0
_LOGGER = logging.getLogger(__name__)


class LookupDiagnostics:
    """Thread-safe request counters for backend diagnostics, not user progress."""

    def __init__(self) -> None:
        self.counts: Counter[str] = Counter()
        self.lock = threading.Lock()

    def record(self, event: str) -> None:
        """Count a request/cache event under the shared worker lock."""
        with self.lock:
            self.counts[event] += 1


class GBIFRequestError(RuntimeError):
    """A lookup failed; this does not mean the taxon has no vernacular names."""

    def __init__(self, message: str, *, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


def _decode_gbif_json(payload: str) -> dict:
    """Decode the object/list structure consumed by GBIF enrichment.

    Args:
        payload: JSON text from a response or cache entry.
    """
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise TypeError("Expected a GBIF JSON object")
    if "results" in data and (
        not isinstance(data["results"], list)
        or any(not isinstance(item, dict) for item in data["results"])
    ):
        raise ValueError("Expected a list of GBIF result objects")
    return data


def _retry_after_seconds(value: str | None) -> float:
    """Interpret Retry-After as seconds or an HTTP date, defaulting to 60s.

    Args:
        value: Optional Retry-After response header.
    """
    if value:
        try:
            return max(1, int(value))
        except ValueError:
            try:
                return max(1, parsedate_to_datetime(value).timestamp() - time.time())
            except (TypeError, ValueError, OverflowError):
                pass
    return 60.0


def fetch_gbif_raw_api(
    url: str,
    cache_conn: sqlite3.Connection,
    max_age_days: int = 7,
    diagnostics: LookupDiagnostics | None = None,
) -> dict:
    """Fetch raw REST API response JSON from URL with 7-day raw HTTP response caching.

    Args:
        url: Full GBIF REST API endpoint URL string.
        cache_conn: Dedicated connection to gbif_cache.db.
        max_age_days: Cache TTL in days (default: 7).
        diagnostics: Optional shared backend counters for this lookup run.

    Returns:
        dict: Parsed JSON response, including valid empty/no-match results.

    Raises:
        GBIFRequestError: Lookup failed or uncached requests are cooling down.
    """
    import http.client
    import json
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
                    data = _decode_gbif_json(cached_json)
                    if diagnostics is not None:
                        diagnostics.record("cache_hits")
                    return data
                except (json.JSONDecodeError, TypeError, ValueError):
                    pass
    except sqlite3.Error:
        _LOGGER.warning("Could not read GBIF cache; attempting lookup", exc_info=True)

    global _GBIF_COOLDOWN_UNTIL
    with _GBIF_COOLDOWN_LOCK:
        remaining = _GBIF_COOLDOWN_UNTIL - time.monotonic()
    if remaining > 0:
        if diagnostics is not None:
            diagnostics.record("cooldown_skips")
        raise GBIFRequestError(
            f"GBIF requests are paused after rate limiting. Retry in {int(remaining) + 1} seconds. "
            "Previously cached responses remain available.",
            retry_after_seconds=remaining,
        )

    # 2. Fetch raw response over HTTP
    req = urllib.request.Request(url, headers={"User-Agent": "taxo-trainer/1.0"})
    if diagnostics is not None:
        diagnostics.record("requests")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status != 200:
                if diagnostics is not None:
                    diagnostics.record("failed_requests")
                raise GBIFRequestError(f"GBIF returned HTTP {resp.status}; retry the incomplete enrichment later.")
            raw_str = resp.read().decode("utf-8")
            parsed_json = _decode_gbif_json(raw_str)
    except urllib.error.HTTPError as exc:
        if diagnostics is not None:
            diagnostics.record("failed_requests")
        if exc.code == 429:
            delay = _retry_after_seconds(exc.headers.get("Retry-After") if exc.headers else None)
            with _GBIF_COOLDOWN_LOCK:
                _GBIF_COOLDOWN_UNTIL = max(_GBIF_COOLDOWN_UNTIL, time.monotonic() + delay)
            raise GBIFRequestError(
                f"GBIF rate limited requests (HTTP 429). Retry in {int(delay) + 1} seconds; "
                "completed lookups are cached.",
                retry_after_seconds=delay,
            ) from exc
        raise GBIFRequestError(f"GBIF returned HTTP {exc.code}; enrichment is incomplete.") from exc
    except (OSError, http.client.HTTPException, TypeError, ValueError) as exc:
        if diagnostics is not None:
            diagnostics.record("failed_requests")
        raise GBIFRequestError("GBIF lookup failed; enrichment is incomplete. Retry when the service is available.") from exc

    try:
        with cache_conn:
            cache_conn.execute(
                "INSERT OR REPLACE INTO gbif_api_cache (url, response_json, cached_at) VALUES (?, ?, ?)",
                (url, raw_str, int(time.time())),
            )
    except sqlite3.Error:
        # A cache write failure must not discard an otherwise successful lookup.
        if diagnostics is not None:
            diagnostics.record("cache_write_failures")
        _LOGGER.warning("GBIF lookup succeeded but could not be cached", exc_info=True)
    return parsed_json


def enrich_vernacular_names_from_gbif(
    conn: sqlite3.Connection | None = None,
    limit: int | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
    force_all: bool = False,
) -> int:
    """Look up vernacular names in all supported languages from GBIF.

    Resolves canonical names via GBIF match API and fetches backbone vernacular names
    with 1-week persistent disk caching:
    https://api.gbif.org/v1/species/match?name={canonical_name}

    Args:
        conn: Optional SQLite connection.
        limit: Max number of taxa to enrich in one call.
        progress_callback: Optional callback receiving counts and a phase message.
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
    diagnostics = LookupDiagnostics()

    try:
        prune_gbif_cache(cache_conn, max_size_mb=100.0, max_age_days=7)
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
            match_data = fetch_gbif_raw_api(match_url, t_cache_conn, diagnostics=diagnostics)

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
                p_data = fetch_gbif_raw_api(p_match_url, t_cache_conn, diagnostics=diagnostics)
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
                v_data = fetch_gbif_raw_api(v_url, t_cache_conn, diagnostics=diagnostics)
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
                            update = conn.execute(
                                """UPDATE taxa 
                                   SET vernacular_da = COALESCE(?, vernacular_da),
                                       vernacular_en = COALESCE(?, vernacular_en),
                                       vernacular_json = ? 
                                   WHERE taxon_key = ? AND (
                                       vernacular_da IS NOT COALESCE(?, vernacular_da)
                                       OR vernacular_en IS NOT COALESCE(?, vernacular_en)
                                       OR vernacular_json IS NOT ?
                                   )""",
                                (new_da, new_en, v_json_str, tkey, new_da, new_en, v_json_str),
                            )
                        updated_count += update.rowcount
                except (sqlite3.Error, OSError, ValueError, RuntimeError) as exc:
                    for pending in future_map:
                        pending.cancel()
                    if isinstance(exc, GBIFRequestError):
                        raise
                    raise RuntimeError("Species enrichment is incomplete; retry to finish remaining lookups.") from exc

                processed_count += 1
                if progress_callback:
                    progress_callback(processed_count, total, f"Checked {processed_count}/{total} species...")

        # Consolidate synonym species into accepted species via GBIF
        if progress_callback:
            progress_callback(0, 0, "Checking accepted scientific names...")
        consolidate_synonyms_with_gbif(conn, diagnostics=diagnostics)

        # Enrich higher rank (Genus & Family) vernacular names
        if progress_callback:
            progress_callback(0, 0, "Looking up genus and family names...")
        enrich_higher_ranks_vernacular_names(conn, diagnostics=diagnostics)

        if progress_callback:
            progress_callback(total, total, "Name lookup complete.")

        return updated_count
    finally:
        _LOGGER.info("GBIF name lookup diagnostics: %s", dict(diagnostics.counts))
        cache_conn.close()
        if should_close:
            conn.close()



def enrich_higher_ranks_vernacular_names(
    conn: sqlite3.Connection | None = None,
    diagnostics: LookupDiagnostics | None = None,
) -> int:
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

            match_url = f"https://api.gbif.org/v1/species/match?name={urllib.parse.quote(r_name)}&rank={urllib.parse.quote(r_level)}"
            mdata = fetch_gbif_raw_api(match_url, t_cache, diagnostics=diagnostics)

            if mdata:
                gbif_key = None
                if r_level == "GENUS":
                    gbif_key = mdata.get("genusKey")
                    if not gbif_key and (mdata.get("rank") or "").upper() == "GENUS":
                        gbif_key = mdata.get("usageKey")
                elif r_level == "FAMILY":
                    gbif_key = mdata.get("familyKey")
                    if not gbif_key and (mdata.get("rank") or "").upper() == "FAMILY":
                        gbif_key = mdata.get("usageKey")
                else:
                    gbif_key = mdata.get("usageKey") or mdata.get("speciesKey")

                if gbif_key:
                    v_url = f"https://api.gbif.org/v1/species/{gbif_key}/vernacularNames?limit=100"
                    vdata = fetch_gbif_raw_api(v_url, t_cache, diagnostics=diagnostics)
                    if vdata:
                        by_lang: dict[str, list[str]] = {}
                        for item in vdata.get("results", []):
                            raw_lang = (item.get("language") or "").lower()
                            vname = item.get("vernacularName")
                            if not vname or not vname.strip():
                                continue
                            vname = vname.strip()

                            # Reject family suffixes for Genus and genus suffixes for Family
                            v_lower = vname.lower()
                            if r_level == "GENUS" and (
                                v_lower.endswith(("familien", "familie", "family", "families"))
                                or "familien" in v_lower
                                or "family" in v_lower
                            ):
                                continue
                            if r_level == "FAMILY" and (
                                v_lower.endswith(("slægten", "slægt", "genus"))
                                or "slægten" in v_lower
                            ):
                                continue

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

        # Language coverage can change; check all targets using the shared cache.
        pending_targets = targets

        with ThreadPoolExecutor(max_workers=30) as executor:
            futures = [executor.submit(process_single_target, t) for t in pending_targets]
            for fut in as_completed(futures):
                try:
                    r_name, r_level, v_da, v_en, v_json_str = fut.result()
                    if v_da or v_en or v_json_str:
                        with conn:
                            conn.execute(
                                """INSERT INTO higher_ranks
                                   (rank_name, rank_level, vernacular_da, vernacular_en, vernacular_json)
                                   VALUES (?, ?, ?, ?, ?)
                                   ON CONFLICT(rank_name) DO UPDATE SET
                                       vernacular_da = COALESCE(excluded.vernacular_da, higher_ranks.vernacular_da),
                                       vernacular_en = COALESCE(excluded.vernacular_en, higher_ranks.vernacular_en),
                                       vernacular_json = json_patch(
                                           COALESCE(higher_ranks.vernacular_json, '{}'),
                                           COALESCE(excluded.vernacular_json, '{}')
                                       )""",
                                (r_name, r_level, v_da, v_en, v_json_str),
                            )
                        updated += 1
                except (sqlite3.Error, KeyError, ValueError, RuntimeError) as exc:
                    for pending in futures:
                        pending.cancel()
                    if isinstance(exc, GBIFRequestError):
                        raise
                    raise RuntimeError("Higher-rank enrichment is incomplete; retry to finish remaining lookups.") from exc

        return updated
    finally:
        cache_conn.close()
        if should_close:
            conn.close()




def consolidate_synonyms_with_gbif(
    conn: sqlite3.Connection | None = None,
    diagnostics: LookupDiagnostics | None = None,
) -> int:
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
            data = fetch_gbif_raw_api(url, t_cache, diagnostics=diagnostics)
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
                except (sqlite3.Error, KeyError, ValueError, RuntimeError) as exc:
                    for pending in futures:
                        pending.cancel()
                    if isinstance(exc, GBIFRequestError):
                        raise
                    raise RuntimeError("Synonym consolidation is incomplete; retry to finish remaining lookups.") from exc

        return merged_count
    finally:
        cache_conn.close()
        if should_close:
            conn.close()
