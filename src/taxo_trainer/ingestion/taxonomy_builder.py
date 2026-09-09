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

    Dictionary keys must be GBIF taxon IDs (numeric or alphanumeric).
    Scientific names are not identity keys.

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

                c = conn.execute(
                    """UPDATE taxa SET vernacular_da = COALESCE(?, vernacular_da),
                       vernacular_en = COALESCE(?, vernacular_en) WHERE taxon_key = ?""",
                    (v_da, v_en, str(key)),
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
    "dan": "da",
    "da": "da",
    "danish": "da",
    "eng": "en",
    "en": "en",
    "english": "en",
    "deu": "de",
    "ger": "de",
    "de": "de",
    "german": "de",
    "swe": "sv",
    "sv": "sv",
    "swedish": "sv",
    "nor": "no",
    "nob": "no",
    "nno": "no",
    "no": "no",
    "norwegian": "no",
    "fra": "fr",
    "fre": "fr",
    "fr": "fr",
    "french": "fr",
    "spa": "es",
    "es": "es",
    "spanish": "es",
    "nld": "nl",
    "dut": "nl",
    "nl": "nl",
    "dutch": "nl",
    "pol": "pl",
    "pl": "pl",
    "polish": "pl",
    "ces": "cs",
    "cze": "cs",
    "cs": "cs",
    "czech": "cs",
    "fin": "fi",
    "fi": "fi",
    "finnish": "fi",
    "ita": "it",
    "it": "it",
    "italian": "it",
    "por": "pt",
    "pt": "pt",
    "portuguese": "pt",
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

    def __init__(
        self, message: str, *, retry_after_seconds: float | None = None
    ) -> None:
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


def _open_gbif(request, timeout=5):
    """Open an allowed request without following redirects to other endpoints."""
    import urllib.request

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise GBIFRequestError(
                "GBIF redirected an ID lookup; enrichment is incomplete"
            )

    return urllib.request.build_opener(NoRedirect()).open(request, timeout=timeout)


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
    import re
    import urllib.error
    import urllib.request
    from urllib.parse import parse_qsl, urlsplit

    parsed = urlsplit(url)
    allowed_path = re.fullmatch(
        r"/v1/(?:species/[0-9]+(?:/vernacularNames)?|occurrence/[0-9]+)", parsed.path
    )
    query = parse_qsl(parsed.query, keep_blank_values=True)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "api.gbif.org"
        or not allowed_path
        or parsed.fragment
        or any(
            k not in {"limit", "offset"} or not v.isascii() or not v.isdigit()
            for k, v in query
        )
    ):
        raise GBIFRequestError("Only ID-addressed GBIF record endpoints are permitted")

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
        with _open_gbif(req, timeout=5) as resp:
            if resp.status != 200:
                if diagnostics is not None:
                    diagnostics.record("failed_requests")
                raise GBIFRequestError(
                    f"GBIF returned HTTP {resp.status}; retry the incomplete enrichment later."
                )
            raw_str = resp.read().decode("utf-8")
            parsed_json = _decode_gbif_json(raw_str)
    except urllib.error.HTTPError as exc:
        if diagnostics is not None:
            diagnostics.record("failed_requests")
        if exc.code == 429:
            delay = _retry_after_seconds(
                exc.headers.get("Retry-After") if exc.headers else None
            )
            with _GBIF_COOLDOWN_LOCK:
                _GBIF_COOLDOWN_UNTIL = max(
                    _GBIF_COOLDOWN_UNTIL, time.monotonic() + delay
                )
            raise GBIFRequestError(
                f"GBIF rate limited requests (HTTP 429). Retry in {int(delay) + 1} seconds; "
                "completed lookups are cached.",
                retry_after_seconds=delay,
            ) from exc
        if exc.code == 404:
            return {}
        raise GBIFRequestError(
            f"GBIF returned HTTP {exc.code}; enrichment is incomplete."
        ) from exc
    except (OSError, http.client.HTTPException, TypeError, ValueError) as exc:
        if diagnostics is not None:
            diagnostics.record("failed_requests")
        raise GBIFRequestError(
            "GBIF lookup failed; enrichment is incomplete. Retry when the service is available."
        ) from exc

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


# GBIF checklist namespaces; CoL identifiers must not be cast to integers.
BACKBONE_CHECKLIST = "d7dddbf4-2cf0-4f39-9b2a-bb099caae36c"
COL_CHECKLIST = "7ddf754f-d193-4cc9-b351-99906754a03b"


def _record(key: str, cache: sqlite3.Connection, diagnostics=None) -> dict:
    """Read a numeric GBIF usage record, verifying the returned identity."""
    data = fetch_gbif_raw_api(
        f"https://api.gbif.org/v1/species/{key}", cache, diagnostics=diagnostics
    )
    if not data:
        return {}
    if str(data.get("key", "")) != key:
        raise GBIFRequestError("GBIF returned a different or missing taxon ID")
    return data


def _classification_node(classification: dict, rank: str) -> dict | None:
    """Find an explicit rank ID in an occurrence's GBIF classification."""
    for node in classification.get("classification", []):
        if node.get("rank") == rank and node.get("key"):
            return node
    usage = classification.get("acceptedUsage") or classification.get("usage") or {}
    return usage if usage.get("rank") == rank and usage.get("key") else None


def _resolve_usage(
    row: dict, occurrence_id: str | None, cache, diagnostics=None, *, taxonomy_only=False
) -> tuple[str | None, dict, dict]:
    """Resolve API IDs through records only; keep imported IDs as local identity.

    CoL exports use alphanumeric IDs. The v1 Species API accepts numeric keys.
    An occurrence record can explicitly provide both checklist classifications;
    use that bridge only when its source species ID agrees with the stored ID.
    Missing or ambiguous relationships remain unresolved, without name fallback.
    """
    key = str(row["taxon_key"])
    checklist = row.get("checklist_key")
    numeric_occurrence = (
        occurrence_id and str(occurrence_id).isascii() and str(occurrence_id).isdigit()
    )
    if key.isascii() and key.isdigit() and checklist == BACKBONE_CHECKLIST:
        data = _record(key, cache, diagnostics)
        links = {
            f"{r}_key": str(data[f"{r}Key"])
            for r in ("genus", "family", "order")
            if data.get(f"{r}Key")
        }
        links["checklist_key"] = BACKBONE_CHECKLIST
        return key, data, links
    if not numeric_occurrence:
        return None, {}, {}
    occurrence = fetch_gbif_raw_api(
        f"https://api.gbif.org/v1/occurrence/{occurrence_id}",
        cache,
        diagnostics=diagnostics,
    )
    if not occurrence:
        return None, {}, {}
    if str(occurrence.get("key", "")) != str(occurrence_id):
        raise GBIFRequestError("GBIF returned a different occurrence ID")
    classifications = occurrence.get("classifications", {})
    sources = []
    for namespace, classification in classifications.items():
        if checklist and namespace != checklist:
            continue
        node = _classification_node(classification, "SPECIES")
        if node and str(node["key"]) == key:
            sources.append((namespace, classification))
    if len(sources) != 1:
        return None, {}, {}
    namespace, source = sources[0]
    links = {"checklist_key": namespace}
    for rank in ("genus", "family", "order"):
        node = _classification_node(source, rank.upper())
        if node:
            links[f"{rank}_key"] = str(node["key"])
    if taxonomy_only:
        return None, {}, links
    legacy = classifications.get(BACKBONE_CHECKLIST, {})
    legacy_species = _classification_node(legacy, "SPECIES")
    if (
        not legacy_species
        or not str(legacy_species["key"]).isascii()
        or not str(legacy_species["key"]).isdigit()
    ):
        return None, {}, links
    api_key = str(legacy_species["key"])
    return api_key, _record(api_key, cache, diagnostics), links


def _names(key: str, cache, rank="SPECIES", diagnostics=None) -> dict[str, str]:
    """Retrieve names from an ID-addressed record, following pagination."""
    by_lang: dict[str, dict[str, int]] = {}
    offset = 0
    while True:
        data = fetch_gbif_raw_api(
            f"https://api.gbif.org/v1/species/{key}/vernacularNames?limit=1000&offset={offset}",
            cache,
            diagnostics=diagnostics,
        )
        results = data.get("results", [])
        for item in results:
            name = (item.get("vernacularName") or "").strip()
            code = LANG_MAP.get((item.get("language") or "").lower())
            if not name or not code:
                continue
            lowered = name.lower()
            if rank == "GENUS" and (
                lowered.endswith(("familien", "familie", "family", "families"))
                or "familien" in lowered
                or "family" in lowered
            ):
                continue
            if rank == "FAMILY" and (
                lowered.endswith(("slægten", "slægt", "genus")) or "slægten" in lowered
            ):
                continue
            score = score_vernacular_item(item, code) if rank == "SPECIES" else 0
            if score >= 0:
                by_lang.setdefault(code, {})[name] = max(
                    by_lang.get(code, {}).get(name, -999), score
                )
        if data.get("endOfRecords", True) or not results:
            break
        offset += len(results)
    return {
        code: "|".join(
            sorted(names, key=lambda n: (-names[n], len(n.split()), len(n), n))
        )
        for code, names in by_lang.items()
    }


def _merge_names(old_json, new_names: dict) -> str:
    """Preserve languages absent from a later lookup."""
    try:
        old = json.loads(old_json or "{}")
    except (ValueError, TypeError):
        old = {}
    if not isinstance(old, dict):
        old = {}
    return json.dumps(old | new_names, ensure_ascii=False, sort_keys=True)


def _lookup_taxon(row: dict, occurrence_id: str | None, diagnostics) -> tuple:
    """Fetch one taxon's ID-linked data, owning and closing its cache connection."""
    cache = get_gbif_cache_connection()
    try:
        api_key, data, links = _resolve_usage(row, occurrence_id, cache, diagnostics)
        if not api_key:
            diagnostics.record("unresolved_ids")
            return row, links, {}, [], None
        if data.get("rank") not in ("SPECIES", "SUBSPECIES", "VARIETY", "FORM"):
            diagnostics.record("unresolved_ids")
            return row, links, {}, [], None
        names = _names(api_key, cache, diagnostics=diagnostics)
        accepted = data.get("acceptedKey")
        # Preserve original taxon/history IDs; accepted identity is a relationship.
        local_accepted = str(row["taxon_key"])
        if accepted and str(accepted) != api_key:
            accepted_data = _record(str(accepted), cache, diagnostics)
            if accepted_data.get("rank") == "SPECIES":
                names = _names(str(accepted), cache, diagnostics=diagnostics) | names
                if links.get("checklist_key") == BACKBONE_CHECKLIST:
                    local_accepted = str(accepted)
        ranks = []
        for rank in ("genus", "family", "order"):
            local_key, rank_api_key = links.get(f"{rank}_key"), data.get(f"{rank}Key")
            if not local_key or not rank_api_key:
                continue
            # Both keys come from the explicit classifications of this taxon.
            rank_names = (
                _names(str(rank_api_key), cache, rank.upper(), diagnostics)
                if rank != "order"
                else {}
            )
            ranks.append(
                (
                    local_key,
                    row.get(rank if rank != "order" else "order_name")
                    or data.get(rank)
                    or local_key,
                    rank.upper(),
                    rank_names,
                    links.get("checklist_key"),
                )
            )
        return row, links, names, ranks, local_accepted
    finally:
        cache.close()


def enrich_vernacular_names_from_gbif(
    conn: sqlite3.Connection | None = None,
    limit: int | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
    force_all: bool = False,
) -> int:
    """Enrich names through explicit GBIF IDs, preserving stored identities.

    Args:
        conn: Optional application connection.
        limit: Maximum taxa to check.
        progress_callback: Optional checked/total/message callback.
        force_all: Retained for caller compatibility; all selected taxa are checked,
            and fresh cached responses are reused.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    own = conn is None
    conn = conn if conn is not None else get_db_connection(APP_DB_PATH)
    diagnostics = LookupDiagnostics()
    try:
        cache = get_gbif_cache_connection()
        try:
            prune_gbif_cache(cache, max_size_mb=100.0, max_age_days=7)
        finally:
            cache.close()
        rows = [dict(r) for r in conn.execute("SELECT * FROM taxa")]
        if limit is not None:
            rows = rows[:limit]
        targets = [
            (
                r,
                conn.execute(
                    "SELECT occurrence_id FROM occurrences WHERE taxon_key = ? LIMIT 1",
                    (r["taxon_key"],),
                ).fetchone(),
            )
            for r in rows
        ]
        updated = 0
        with ThreadPoolExecutor(max_workers=30) as executor:
            futures = [
                executor.submit(_lookup_taxon, r, obs[0] if obs else None, diagnostics)
                for r, obs in targets
            ]
            try:
                for checked, future in enumerate(as_completed(futures), 1):
                    row, links, names, ranks, accepted = future.result()
                    merged = _merge_names(row.get("vernacular_json"), names)
                    old = _merge_names(row.get("vernacular_json"), {})
                    if names and (
                        merged != old
                        or names.get("da", row.get("vernacular_da"))
                        != row.get("vernacular_da")
                        or names.get("en", row.get("vernacular_en"))
                        != row.get("vernacular_en")
                    ):
                        with conn:
                            conn.execute(
                                "UPDATE taxa SET vernacular_json=?, vernacular_da=COALESCE(?,vernacular_da), vernacular_en=COALESCE(?,vernacular_en) WHERE taxon_key=?",
                                (
                                    merged,
                                    names.get("da"),
                                    names.get("en"),
                                    row["taxon_key"],
                                ),
                            )
                        updated += 1
                    with conn:
                        for column, value in links.items():
                            conn.execute(
                                f"UPDATE taxa SET {column}=? WHERE taxon_key=?",
                                (value, row["taxon_key"]),
                            )
                        if accepted:
                            conn.execute(
                                "UPDATE taxa SET accepted_taxon_key=? WHERE taxon_key=?",
                                (accepted, row["taxon_key"]),
                            )
                        for key, name, rank, rank_names, checklist in ranks:
                            existing = conn.execute(
                                "SELECT * FROM higher_ranks WHERE taxon_key=?", (key,)
                            ).fetchone()
                            if existing and existing["checklist_key"] not in (
                                None,
                                checklist,
                            ):
                                raise GBIFRequestError(
                                    "Conflicting checklist identity for higher rank"
                                )
                            rank_json = _merge_names(
                                existing["vernacular_json"] if existing else None,
                                rank_names,
                            )
                            conn.execute(
                                """INSERT INTO higher_ranks (taxon_key,rank_name,rank_level,vernacular_da,vernacular_en,vernacular_json,checklist_key)
                                VALUES (?,?,?,?,?,?,?) ON CONFLICT(taxon_key) DO UPDATE SET
                                rank_name=excluded.rank_name, checklist_key=excluded.checklist_key, vernacular_da=COALESCE(excluded.vernacular_da,higher_ranks.vernacular_da),
                                vernacular_en=COALESCE(excluded.vernacular_en,higher_ranks.vernacular_en),vernacular_json=excluded.vernacular_json""",
                                (
                                    key,
                                    name,
                                    rank,
                                    rank_names.get("da"),
                                    rank_names.get("en"),
                                    rank_json,
                                    checklist,
                                ),
                            )
                    if progress_callback:
                        progress_callback(
                            checked,
                            len(rows),
                            f"Checked {checked}/{len(rows)} species...",
                        )
            except Exception:
                for pending in futures:
                    pending.cancel()
                raise
        if progress_callback:
            progress_callback(len(rows), len(rows), "Name lookup complete.")
        return updated
    finally:
        _LOGGER.info("GBIF name lookup diagnostics: %s", dict(diagnostics.counts))
        if own:
            conn.close()


_TAXONOMY_REPAIR_LOCK = threading.Lock()


def repair_missing_taxonomy(conn: sqlite3.Connection | None = None) -> int:
    """Restore missing rank IDs from explicit GBIF classifications in background.

    Existing names and history IDs are retained. This does not fetch vernacular
    names or invent links for unresolved taxa; cached ID requests and the shared
    GBIF rate-limit handling apply. Only one repair runs per process at a time.
    """
    from concurrent.futures import ThreadPoolExecutor

    if not _TAXONOMY_REPAIR_LOCK.acquire(blocking=False):
        return 0
    own = conn is None
    diagnostics = LookupDiagnostics()
    updated = 0
    try:
        conn = conn if conn is not None else get_db_connection(APP_DB_PATH)
        rows = [dict(row) for row in conn.execute("""
            SELECT t.*, (SELECT occurrence_id FROM occurrences o
                         WHERE o.taxon_key=t.taxon_key LIMIT 1) AS occurrence_id
            FROM taxa t WHERE (genus IS NOT NULL AND genus_key IS NULL)
                OR (family IS NOT NULL AND family_key IS NULL)
                OR (order_name IS NOT NULL AND order_key IS NULL)
                OR (genus_key IS NOT NULL AND NOT EXISTS (SELECT 1 FROM higher_ranks h WHERE h.taxon_key=t.genus_key))
                OR (family_key IS NOT NULL AND NOT EXISTS (SELECT 1 FROM higher_ranks h WHERE h.taxon_key=t.family_key))
                OR (order_key IS NOT NULL AND NOT EXISTS (SELECT 1 FROM higher_ranks h WHERE h.taxon_key=t.order_key))
        """)]

        def lookup(row):
            if all(not row[rank if rank != "order" else "order_name"] or row[f"{rank}_key"]
                   for rank in ("genus", "family", "order")):
                return row, {"checklist_key": row["checklist_key"], **{
                    f"{rank}_key": row[f"{rank}_key"] for rank in ("genus", "family", "order")
                    if row[f"{rank}_key"]}}
            cache = get_gbif_cache_connection()
            try:
                _, _, links = _resolve_usage(row, row["occurrence_id"], cache,
                                             diagnostics, taxonomy_only=True)
                return row, links
            finally:
                cache.close()

        with ThreadPoolExecutor(max_workers=4) as executor:
            for row, links in executor.map(lookup, rows):
                if not links:
                    continue
                # Preserve links that another operation may have populated.
                with conn:
                    current = conn.execute("SELECT * FROM taxa WHERE taxon_key=?",
                                           (row["taxon_key"],)).fetchone()
                    if not current:
                        continue
                    checklist = links.get("checklist_key")
                    if (current["checklist_key"] is not None and checklist is not None
                            and current["checklist_key"] != checklist):
                        diagnostics.record("checklist_conflicts")
                        _LOGGER.warning("Skipping taxonomy repair for taxon %s: checklist %s conflicts with %s",
                                        row["taxon_key"], current["checklist_key"], checklist)
                        continue
                    checklist = current["checklist_key"] or checklist
                    ranks = []
                    for rank in ("genus", "family", "order"):
                        key = current[f"{rank}_key"] or links.get(f"{rank}_key")
                        name = current[rank if rank != "order" else "order_name"]
                        if key and name:
                            existing = conn.execute("SELECT checklist_key FROM higher_ranks WHERE taxon_key=?", (key,)).fetchone()
                            # Unknown provenance is not a confirmed collision. Never
                            # overwrite known provenance or infer it from another ID.
                            if (existing and existing[0] is not None and checklist is not None
                                    and existing[0] != checklist):
                                diagnostics.record("checklist_conflicts")
                                _LOGGER.warning(
                                    "Skipping taxonomy repair for taxon %s: rank ID %s has checklist %s, requested %s",
                                    row["taxon_key"], key, existing[0], checklist)
                                break
                            ranks.append((key, name, rank.upper(), checklist))
                    else:
                        # Validate every rank before writing any part of this taxon.
                        before = conn.total_changes
                        for column, value in links.items():
                            if current[column] is None and value is not None:
                                conn.execute(f"UPDATE taxa SET {column}=? WHERE taxon_key=?",
                                             (value, row["taxon_key"]))
                        conn.executemany("""INSERT INTO higher_ranks
                            (taxon_key,rank_name,rank_level,checklist_key) VALUES (?,?,?,?)
                            ON CONFLICT(taxon_key) DO NOTHING""", ranks)
                        updated += conn.total_changes > before
        return updated
    finally:
        if own and conn is not None:
            conn.close()
        _TAXONOMY_REPAIR_LOCK.release()
        _LOGGER.info("Taxonomy link repair: %s taxa; %s", updated, dict(diagnostics.counts))
