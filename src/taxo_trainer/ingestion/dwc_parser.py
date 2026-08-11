"""Zero-Pandas DarwinCore (DwC) TSV stream parser.

Uses standard library csv.DictReader to stream occurrence.txt files and populate
app_data.db in explicit transaction batches with zero pandas/polars dependencies.
Supports both direct associatedMedia columns and external multimedia.txt files.
"""

import csv
import io
import re
import sqlite3
import zipfile
from collections import defaultdict
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from taxo_trainer.db import (
    APP_DB_PATH,
    get_db_connection,
    init_app_db,
    set_app_metadata,
)


def extract_canonical_name(scientific_name: str) -> str:
    """Extract clean binomial canonical name from full scientific name string.

    Args:
        scientific_name: Binomial with potential authority details e.g. "Quercus robur L."

    Returns:
        str: Binomial canonical name e.g. "Quercus robur".
    """
    if not scientific_name:
        return ""
    parts = scientific_name.strip().split()
    if len(parts) >= 2:
        return f"{parts[0]} {parts[1]}"
    return parts[0] if parts else ""


def parse_month(month_str: str, date_str: str) -> int | None:
    """Parse month (1-12) from month column or eventDate string.

    Args:
        month_str: Verbatim month value string.
        date_str: Verbatim eventDate value string e.g. "2023-05-14".

    Returns:
        Optional[int]: Integer month 1-12 if valid, otherwise None.
    """
    if month_str:
        try:
            m = int(month_str)
            if 1 <= m <= 12:
                return m
        except ValueError:
            pass

    if date_str:
        match = re.search(r"\b\d{4}-(\d{2})-\d{2}\b", date_str)
        if match:
            try:
                m = int(match.group(1))
                if 1 <= m <= 12:
                    return m
            except ValueError:
                pass
    return None


@contextmanager
def open_file_in_zip(
    zip_path: str | Path,
    file_name: str,
    mode: str = "r",
    encoding: str = "utf-8",
):
    """Opens a file inside a ZIP archive using a context manager.

    :param zip_path: Path to the ZIP archive.
    :param file_name: Name/path of the file inside the ZIP archive.
    :param mode: 'r' for text mode, 'rb' for binary mode.
    :param encoding: Text encoding (used only when mode='r').
    """
    if mode not in ("r", "rb"):
        raise ValueError(f"Invalid mode '{mode}'. Mode must be 'r' or 'rb'.")

    # Ensure ZIP archive exists
    zip_path = Path(zip_path)
    if not zip_path.is_file():
        raise FileNotFoundError(f"ZIP archive not found: {zip_path}")

    try:
        zf = zipfile.ZipFile(zip_path, "r")
    except zipfile.BadZipFile:
        raise zipfile.BadZipFile(f"File is not a valid ZIP archive: {zip_path}")

    try:
        # Check if the internal file exists
        if file_name not in zf.namelist():
            raise FileNotFoundError(
                f"File '{file_name}' not found inside ZIP archive '{zip_path}'"
            )

        # ZipFile.open returns a binary stream
        raw_stream = zf.open(file_name, "r")

        if mode == "r":
            # Wrap binary stream in TextIOWrapper for text mode reading
            text_stream = io.TextIOWrapper(raw_stream, encoding=encoding)
            try:
                yield text_stream
            finally:
                text_stream.close()
        else:
            try:
                yield raw_stream
            finally:
                raw_stream.close()
    finally:
        zf.close()


def stream_occurrence_tsv(file_path: Path) -> csv.DictReader[str]:
    """Stream DarwinCore TSV records line by line using csv.DictReader.

    Args:
        file_path: Path to GBIF occurrence.txt file.

    Yields:
        Dict[str, str]: Raw row record dictionary.
    """
    if file_path.name.lower().endswith(".zip"):
        with open_file_in_zip(file_path, "occurrence.txt", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            yield from reader
    else:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f, delimiter="\t")
            yield from reader


def parse_multimedia_txt(rows: csv.DictReader[str]) -> dict[str, list[str]]:
    """Parse DarwinCore TSV records line by line using csv.DictReader.

    Args:
        rows: csv.DictReader[str]: Raw row record dictionary.

    Returns:
        dict[str, list[str]]: Map of gbifID/occurrence_id -> list of image URLs.
    """
    media_map: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        gbif_id = (
            row.get("gbifID")
            or row.get("coreid")
            or row.get("id")
            or row.get("occurrenceID")
        )
        url = row.get("identifier") or row.get("accessURI") or row.get("references")
        if gbif_id and url and url.strip():
            clean_url = url.strip()
            if clean_url not in media_map[gbif_id]:
                media_map[gbif_id].append(clean_url)
    return media_map


def load_multimedia_index(source: Path) -> dict[str, list[str]]:
    """Index media URLs from multimedia.txt if present in the dataset directory.

    Args:
        source: Path to occurrence.txt or DarwinCore archive (.zip).

    Returns:
        Dict[str, List[str]]: Map of gbifID/occurrence_id -> list of image URLs.
    """
    media_map: dict[str, list[str]] = defaultdict(list)
    if source.name.lower().endswith("occurrences.txt"):
        candidates = [
            source.parent / "multimedia.txt",
            source.parent / "verbatim" / "multimedia.txt",
        ]
        for cand in candidates:
            if cand.exists():
                with open(cand, "r", encoding="utf-8", errors="replace") as f:
                    reader = csv.DictReader(f, delimiter="\t")
                    return parse_multimedia_txt(reader)
    elif source.name.lower().endswith(".zip"):
        try:
            with open_file_in_zip(source, "multimedia.txt", encoding="utf-8") as f:
                reader = csv.DictReader(f, delimiter="\t")
                return parse_multimedia_txt(reader)
        except FileNotFoundError:
            pass
        try:
            with open_file_in_zip(
                source, "verbatim/multimedia.txt", encoding="utf-8"
            ) as f:
                reader = csv.DictReader(f, delimiter="\t")
                return parse_multimedia_txt(reader)
        except FileNotFoundError:
            pass

    return media_map


def ingest_dwc_file(
    file_path: Path,
    db_path: Path = APP_DB_PATH,
    batch_size: int = 10000,
    progress_callback: Callable[[int], None] | None = None,
) -> tuple[int, int]:
    """Ingest a GBIF DarwinCore occurrence.txt TSV into SQLite app_data.db.

    Extracts both occurrence records and taxonomy metadata in a single fast stream,
    writing in explicit transaction batches. Merges multimedia.txt records if present.

    Args:
        file_path: Path to DarwinCore TSV file (occurrence.txt).
        db_path: Target SQLite database file path.
        batch_size: Number of records per SQLite transaction batch.
        progress_callback: Optional callback receiving count of ingested rows.

    Returns:
        Tuple[int, int]: Total occurrences inserted, total unique taxa inserted/updated.
    """
    conn = get_db_connection(db_path)
    init_app_db(conn)

    # Record active ingestion file path metadata
    set_app_metadata("active_dwc_path", str(file_path.resolve()), conn)

    # Pre-index multimedia.txt if available in the same directory
    multimedia_index = load_multimedia_index(file_path)

    occurrence_batch: list[tuple] = []
    taxa_accumulator: dict[str, dict[str, Any]] = {}

    inserted_occurrences = 0

    try:
        for row in stream_occurrence_tsv(file_path):
            occ_id = row.get("gbifID") or row.get("occurrenceID") or row.get("id")
            taxon_key_raw = (
                row.get("acceptedTaxonKey")
                or row.get("taxonKey")
                or row.get("speciesKey")
                or row.get("taxonID")
                or row.get("acceptedNameUsageID")
            )

            if not occ_id or not taxon_key_raw:
                continue

            taxon_key = str(taxon_key_raw).strip()

            # Gather media URLs from multimedia index + row columns
            media_urls = list(multimedia_index.get(str(occ_id), []))

            direct_media = (
                row.get("associatedMedia")
                or row.get("accessURI")
                or row.get("identifier")
                or ""
            )
            if direct_media:
                for part in direct_media.split("|"):
                    p = part.strip()
                    if p and p not in media_urls:
                        media_urls.append(p)

            if not media_urls:
                # Fallback: check if references or occurrenceID provides a web observation link
                ref_url = row.get("references") or row.get("occurrenceID") or ""
                if ref_url and ref_url.startswith("http"):
                    media_urls.append(ref_url.strip())

            # Skip if still no media URL available
            if not media_urls:
                continue

            media = "|".join(media_urls)

            # Latitude & Longitude
            lat_raw = row.get("decimalLatitude") or row.get("latitude")
            lon_raw = row.get("decimalLongitude") or row.get("longitude")
            lat = float(lat_raw) if lat_raw else None
            lon = float(lon_raw) if lon_raw else None

            locality = row.get("locality") or row.get("verbatimLocality") or ""
            event_date = row.get("eventDate") or ""
            month = parse_month(row.get("month") or "", event_date)

            uncertainty_raw = row.get("coordinateUncertaintyInMeters")
            try:
                uncertainty = float(uncertainty_raw) if uncertainty_raw else None
            except ValueError:
                uncertainty = None

            recorded_by = (
                row.get("recordedBy")
                or row.get("rightsHolder")
                or row.get("publisher")
                or ""
            ).strip()
            ref_link = (row.get("references") or row.get("occurrenceID") or "").strip()
            if not ref_link.startswith("http") and occ_id and str(occ_id).isdigit():
                ref_link = f"https://www.gbif.org/occurrence/{occ_id}"

            occurrence_batch.append(
                (
                    occ_id,
                    taxon_key,
                    lat,
                    lon,
                    locality,
                    event_date,
                    month,
                    media,
                    uncertainty,
                    recorded_by,
                    ref_link,
                )
            )

            # Taxon extraction
            sci_name = (
                row.get("scientificName")
                or row.get("acceptedScientificName")
                or row.get("species")
                or f"Taxon {taxon_key}"
            )
            canonical = row.get("canonicalName") or extract_canonical_name(sci_name)
            accepted = row.get("acceptedScientificName") or sci_name
            rank = (row.get("taxonRank") or row.get("rank") or "SPECIES").upper()
            kingdom = row.get("kingdom") or ""
            phylum = row.get("phylum") or ""
            cls_name = row.get("class") or ""
            order_name = row.get("order") or ""
            family = row.get("family") or ""
            genus = row.get("genus") or ""
            v_raw = (row.get("vernacularName") or "").strip()
            v_en_raw = (
                row.get("vernacularNameEN") or row.get("englishName") or ""
            ).strip()

            vernacular_da = v_raw
            vernacular_en = v_en_raw

            if taxon_key not in taxa_accumulator:
                taxa_accumulator[taxon_key] = {
                    "scientific_name": sci_name,
                    "canonical_name": canonical,
                    "accepted_name": accepted,
                    "rank": rank,
                    "kingdom": kingdom,
                    "phylum": phylum,
                    "class": cls_name,
                    "order_name": order_name,
                    "family": family,
                    "genus": genus,
                    "vernacular_da": vernacular_da,
                    "vernacular_en": vernacular_en,
                    "count": 1,
                }

            else:
                taxa_accumulator[taxon_key]["count"] += 1
                if vernacular_da and not taxa_accumulator[taxon_key]["vernacular_da"]:
                    taxa_accumulator[taxon_key]["vernacular_da"] = vernacular_da
                if vernacular_en and not taxa_accumulator[taxon_key]["vernacular_en"]:
                    taxa_accumulator[taxon_key]["vernacular_en"] = vernacular_en

            # Flush occurrence batch when full
            if len(occurrence_batch) >= batch_size:
                _flush_batch(conn, occurrence_batch, taxa_accumulator)
                inserted_occurrences += len(occurrence_batch)
                occurrence_batch.clear()
                if progress_callback:
                    progress_callback(inserted_occurrences)

        # Flush remaining occurrence batch and taxa
        if occurrence_batch or taxa_accumulator:
            _flush_batch(conn, occurrence_batch, taxa_accumulator)
            inserted_occurrences += len(occurrence_batch)
            occurrence_batch.clear()
            if progress_callback:
                progress_callback(inserted_occurrences)

    finally:
        conn.close()

    return inserted_occurrences, len(taxa_accumulator)


def _flush_batch(
    conn: sqlite3.Connection,
    occurrence_batch: list[tuple],
    taxa_accumulator: dict[str, dict[str, Any]],
) -> None:
    """Flush pending taxa updates and occurrence batch into SQLite in order.

    Args:
        conn: SQLite connection.
        occurrence_batch: List of occurrence tuple values to insert.
        taxa_accumulator: Accumulated taxonomy entries to upsert.
    """
    if not occurrence_batch and not taxa_accumulator:
        return

    taxa_batch = [
        (
            tkey,
            data["scientific_name"],
            data["canonical_name"],
            data["accepted_name"],
            data["rank"],
            data["kingdom"],
            data["phylum"],
            data["class"],
            data["order_name"],
            data["family"],
            data["genus"],
            data["vernacular_da"],
            data["vernacular_en"],
            data["count"],
        )
        for tkey, data in taxa_accumulator.items()
    ]

    with conn:
        if taxa_batch:
            conn.executemany(
                """
                INSERT INTO taxa (
                    taxon_key, scientific_name, canonical_name, accepted_name,
                    rank, kingdom, phylum, class, order_name, family, genus,
                    vernacular_da, vernacular_en, occurrence_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(taxon_key) DO UPDATE SET
                    occurrence_count = excluded.occurrence_count,
                    vernacular_da = COALESCE(NULLIF(excluded.vernacular_da, ''), taxa.vernacular_da),
                    vernacular_en = COALESCE(NULLIF(excluded.vernacular_en, ''), taxa.vernacular_en);
            """,
                taxa_batch,
            )

        if occurrence_batch:
            conn.executemany(
                """
                INSERT OR REPLACE INTO occurrences (
                    occurrence_id, taxon_key, latitude, longitude,
                    locality, event_date, month, media_urls,
                    coordinate_uncertainty_m, recorded_by, references_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
                occurrence_batch,
            )
