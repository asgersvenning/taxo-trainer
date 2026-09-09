"""Zero-Pandas DarwinCore (DwC) TSV stream parser.

Uses standard library csv.DictReader to stream occurrence.txt files and populate
app_data.db in explicit transaction batches with zero pandas/polars dependencies.
Supports both direct associatedMedia columns and external multimedia.txt files.
"""

import csv
import hashlib
import io
import re
import sqlite3
import tempfile
import zipfile
from collections import defaultdict
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from taxo_trainer.db import (
    APP_DB_PATH,
    get_db_connection,
    init_app_db,
    set_app_metadata,
)


def extract_canonical_name(scientific_name: str) -> str:
    """Return clean binomial canonical name string (first two words e.g. Genus species).

    Args:
        scientific_name: Full scientific name string e.g. "Quercus robur L." or "Pinus".

    Returns:
        str: Binomial canonical name string e.g. "Quercus robur".
    """
    if not scientific_name:
        return ""
    parts = scientific_name.strip().split()
    if len(parts) >= 2:
        return f"{parts[0]} {parts[1]}"
    return parts[0] if parts else ""


def _parse_coordinate(value: str | None, bound: float) -> float | None:
    """Return a coordinate within its geographic bounds, or None if invalid.

    Args:
        value: Optional decimal coordinate from the source row.
        bound: Maximum absolute value (90 for latitude, 180 for longitude).
    """
    try:
        coordinate = float(value) if value else None
    except (TypeError, ValueError):
        return None
    # This comparison also rejects NaN and infinities.
    return coordinate if coordinate is not None and -bound <= coordinate <= bound else None


def _media_url(value: str | None) -> str | None:
    """Return a valid HTTP(S) URL from a media field without fetching it.

    Args:
        value: Candidate URL explicitly provided as media by the dataset.
    """
    if not value:
        return None
    value = value.strip()
    if any(character.isspace() for character in value):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme in ("http", "https") and parsed.hostname:
            return value
    except ValueError:
        pass
    return None


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
        if gbif_id:
            for field in ("identifier", "accessURI"):
                clean_url = _media_url(row.get(field))
                if clean_url and clean_url not in media_map[gbif_id]:
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
    if source.suffix.lower() != ".zip":
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


def is_url(s: str) -> bool:
    """Check if string is an HTTP or HTTPS URL."""
    s_clean = str(s).strip().lower()
    return s_clean.startswith(("http://", "https://"))



def resolve_dwc_source_path(
    source_str: str,
    progress_callback: Callable[[str], None] | None = None,
) -> Path:
    """Resolve a local path or atomically cache a complete download by URL.

    Args:
        source_str: Local file path string or HTTP(S) URL.
        progress_callback: Optional callback receiving status message strings.

    Returns:
        Path: Resolved local file path to the DarwinCore zip/txt archive.
    """
    import urllib.parse
    import urllib.request

    s_clean = source_str.strip()
    if not is_url(s_clean):
        return Path(s_clean)

    parsed = urllib.parse.urlparse(s_clean)
    filename = Path(parsed.path).name
    if not filename or filename.startswith("."):
        filename = "remote_dwc_dataset.zip"
    elif not filename.lower().endswith((".zip", ".tsv", ".txt", ".csv")):
        filename = f"{filename}.zip"

    from taxo_trainer.db import DATA_DIR

    # Keep the original filename/extension, but never share entries across URLs.
    # Legacy basename-only files are not trusted: they may be partial downloads.
    url_key = hashlib.sha256(s_clean.encode("utf-8")).hexdigest()
    datasets_dir = DATA_DIR / "datasets" / "downloads" / url_key
    datasets_dir.mkdir(parents=True, exist_ok=True)
    dest_path = datasets_dir / filename

    if dest_path.exists() and dest_path.stat().st_size > 0:
        if progress_callback:
            progress_callback(f"Using cached local dataset for URL: {filename}...")
        return dest_path

    if progress_callback:
        progress_callback(f"Connecting to remote URL: {filename}...")

    req = urllib.request.Request(s_clean, headers={"User-Agent": "taxo-trainer/1.0"})
    temporary_path = None
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            length_header = resp.headers.get("Content-Length")
            total_bytes = int(length_header) if length_header is not None else None
            downloaded = 0
            chunk_size = 64 * 1024

            with tempfile.NamedTemporaryFile(
                dir=datasets_dir, suffix=".part", delete=False
            ) as f_out:
                temporary_path = Path(f_out.name)
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    f_out.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback:
                        dl_mb = downloaded / (1024 * 1024)
                        if total_bytes is not None and total_bytes > 0:
                            tot_mb = total_bytes / (1024 * 1024)
                            pct = int((downloaded / total_bytes) * 100)
                            progress_callback(
                                f"Downloading {filename}... {dl_mb:.1f} MB / {tot_mb:.1f} MB ({pct}%)"
                            )
                        else:
                            progress_callback(f"Downloading {filename}... {dl_mb:.1f} MB")

            if downloaded == 0:
                raise ValueError("Downloaded dataset is empty.")
            if total_bytes is not None and downloaded != total_bytes:
                raise ValueError(
                    f"Incomplete dataset download: expected {total_bytes} bytes, received {downloaded}."
                )

        # Close both handles before replacing for compatibility with Windows.
        temporary_path.replace(dest_path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    return dest_path


def ingest_dwc_file(
    file_path: Path | str,
    db_path: Path = APP_DB_PATH,
    batch_size: int = 10000,
    max_occurrences_per_taxon: int | None = 1000,
    progress_callback: Callable[[int | str], None] | None = None,
) -> tuple[int, int]:
    """Ingest a GBIF DarwinCore occurrence.txt TSV or ZIP archive into SQLite app_data.db.

    Supports local file paths or direct HTTP(S) download URLs. Extracts both occurrence
    records and taxonomy metadata in a single fast stream, writing in explicit transaction batches.

    Args:
        file_path: Path to DarwinCore TSV file / ZIP archive, or remote HTTP(S) URL.
        db_path: Target SQLite database file path.
        batch_size: Number of records per SQLite transaction batch.
        max_occurrences_per_taxon: Optional max occurrence cap per taxon (default: 1000).
        progress_callback: Optional callback receiving count of ingested rows or status message.

    Returns:
        Tuple[int, int]: Total occurrences inserted, total unique taxa inserted/updated.
    """
    raw_source_str = str(file_path).strip()

    def status_reporter(msg: str) -> None:
        if progress_callback:
            progress_callback(msg)

    resolved_path = resolve_dwc_source_path(
        raw_source_str, progress_callback=status_reporter
    )

    conn = get_db_connection(db_path)
    init_app_db(conn)

    # Record active ingestion file path or URL metadata
    active_meta_val = (
        raw_source_str
        if is_url(raw_source_str)
        else str(resolved_path.resolve())
    )
    set_app_metadata("active_dwc_path", active_meta_val, conn)

    # Pre-index multimedia.txt if available in the same directory/ZIP
    multimedia_index = load_multimedia_index(resolved_path)

    occurrence_batch: list[tuple] = []
    taxa_accumulator: dict[str, dict[str, Any]] = {}
    taxon_occ_counts: dict[str, int] = defaultdict(int)

    inserted_occurrences = 0

    try:
        for row in stream_occurrence_tsv(resolved_path):
            occ_id = row.get("gbifID") or row.get("occurrenceID") or row.get("id")
            taxon_key_raw = (

                row.get("speciesKey")
                or row.get("acceptedTaxonKey")
                or row.get("taxonKey")
                or row.get("taxonID")
                or row.get("acceptedNameUsageID")
            )

            if not occ_id or not taxon_key_raw:
                continue

            taxon_key = str(taxon_key_raw).strip()

            # Immediate threshold filtering for max occurrences per raw taxon
            if (
                max_occurrences_per_taxon
                and max_occurrences_per_taxon > 0
                and taxon_occ_counts[taxon_key] >= max_occurrences_per_taxon
            ):
                continue


            # Gather media URLs from multimedia index + row columns
            media_urls = list(multimedia_index.get(str(occ_id), []))

            # Occurrence identifiers/references describe the record, not its photo.
            for field in ("associatedMedia", "accessURI"):
                for part in (row.get(field) or "").split("|"):
                    url = _media_url(part)
                    if url and url not in media_urls:
                        media_urls.append(url)

            # Skip if still no media URL available
            if not media_urls:
                continue

            taxon_occ_counts[taxon_key] += 1
            media = "|".join(media_urls)

            # Latitude & Longitude
            lat_raw = row.get("decimalLatitude") or row.get("latitude")
            lon_raw = row.get("decimalLongitude") or row.get("longitude")
            lat = _parse_coordinate(lat_raw, 90)
            lon = _parse_coordinate(lon_raw, 180)

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
            rank_raw = (row.get("taxonRank") or row.get("rank") or "SPECIES").upper()
            rank = (
                "SPECIES"
                if rank_raw
                in (
                    "SUBSPECIES",
                    "VARIETY",
                    "FORM",
                    "INFRASPECIFIC_NAME",
                    "SUBFAMILY",
                    "TRIBE",
                )
                else rank_raw
            )
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
