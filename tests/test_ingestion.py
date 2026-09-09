"""Unit tests for DarwinCore ingestion and taxonomy building modules."""

import csv
import io
import sqlite3
import zipfile

import pytest

from taxo_trainer.ingestion.dwc_parser import (
    extract_canonical_name,
    ingest_dwc_file,
    parse_month,
    resolve_dwc_source_path,
)
from taxo_trainer.ingestion.taxonomy_builder import load_custom_vernacular_json


def test_extract_canonical_name():
    """Test canonical name extraction from scientific names."""
    assert extract_canonical_name("Quercus robur L.") == "Quercus robur"
    assert extract_canonical_name("Taraxacum officinale F.H.Wigg.") == "Taraxacum officinale"
    assert extract_canonical_name("Pinus") == "Pinus"
    assert extract_canonical_name("") == ""


def test_parse_month():
    """Test month parsing logic."""
    assert parse_month("5", "2023-05-14") == 5
    assert parse_month("", "2023-11-20") == 11
    assert parse_month("13", "invalid") is None


def test_ingest_dwc_file_and_taxonomy_builder(tmp_path):
    """Test full TSV stream ingestion into a SQLite database and dictionary updating."""
    # Create sample TSV file
    tsv_file = tmp_path / "occurrence.txt"
    tsv_content = (
        "gbifID\tacceptedTaxonKey\tscientificName\tcanonicalName\tdecimalLatitude\tdecimalLongitude\tlocality\teventDate\tmonth\tassociatedMedia\tfamily\tgenus\tvernacularName\n"
        "1001\t2435140\tQuercus robur L.\tQuercus robur\t55.67\t12.56\tCopenhagen\t2023-06-10\t6\thttp://example.com/img1.jpg\tFagaceae\tQuercus\tStilk-Eg\n"
        "1002\t2435140\tQuercus robur L.\tQuercus robur\t55.68\t12.57\tCopenhagen\t2023-07-12\t7\thttp://example.com/img2.jpg\tFagaceae\tQuercus\tStilk-Eg\n"
        "1003\t2865545\tFagus sylvatica L.\tFagus sylvatica\t56.00\t12.00\tNorth Zealand\t2023-05-01\t5\thttp://example.com/img3.jpg\tFagaceae\tFagus\tAlmindelig Bøg\n"
    )
    tsv_file.write_text(tsv_content, encoding="utf-8")

    db_path = tmp_path / "app_test.db"
    inserted_occ, inserted_taxa = ingest_dwc_file(tsv_file, db_path=db_path, batch_size=2)

    assert inserted_occ == 3
    assert inserted_taxa == 2

    # Verify SQLite database contents
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as cnt FROM occurrences;")
    assert cursor.fetchone()["cnt"] == 3

    cursor.execute("SELECT * FROM taxa WHERE taxon_key = 2435140;")
    q_row = cursor.fetchone()
    assert q_row is not None
    assert q_row["canonical_name"] == "Quercus robur"
    assert q_row["family"] == "Fagaceae"
    assert q_row["occurrence_count"] == 2
    assert q_row["vernacular_da"] == "Stilk-Eg"

    # Test load_custom_vernacular_json
    dict_json = tmp_path / "dict.json"
    dict_json.write_text('{"Quercus robur": {"vernacular_da": "Stilke-Eg Custom"}}', encoding="utf-8")
    updated = load_custom_vernacular_json(dict_json, conn=conn)
    assert updated == 1

    cursor.execute("SELECT vernacular_da FROM taxa WHERE taxon_key = 2435140;")
    assert cursor.fetchone()["vernacular_da"] == "Stilke-Eg Custom"

    conn.close()


def test_consolidate_synonyms_with_gbif(tmp_path, monkeypatch):
    """Test consolidating synonym species into accepted species using mocked GBIF Match response."""
    from taxo_trainer.db import init_app_db
    from taxo_trainer.ingestion.taxonomy_builder import consolidate_synonyms_with_gbif

    db_path = tmp_path / "test_synonyms.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    init_app_db(conn)

    # Insert accepted species and a synonym species
    with conn:
        conn.execute(
            "INSERT INTO taxa (taxon_key, canonical_name, accepted_name, scientific_name, rank) VALUES ('LX6F', 'Bistorta officinalis', 'Bistorta officinalis', 'Bistorta officinalis Raf.', 'SPECIES')"
        )
        conn.execute(
            "INSERT INTO taxa (taxon_key, canonical_name, accepted_name, scientific_name, rank) VALUES ('5FY79', 'Persicaria bistorta', 'Bistorta officinalis', 'Persicaria bistorta (L.) Samp.', 'SPECIES')"
        )
        conn.execute(
            "INSERT INTO occurrences (occurrence_id, taxon_key, media_urls) VALUES ('1', '5FY79', 'http://example.com/img.jpg')"
        )

    # Mock GBIF Match API response for Persicaria bistorta -> Bistorta officinalis
    def mock_urlopen(req, timeout=5):
        url = req.full_url if hasattr(req, "full_url") else str(req)

        class MockResp:
            status = 200

            def read(self):
                if "Persicaria" in url:
                    return b'{"status": "SYNONYM", "synonym": true, "speciesKey": "LX6F", "species": "Bistorta officinalis"}'
                return b'{"status": "ACCEPTED", "synonym": false, "speciesKey": "LX6F", "species": "Bistorta officinalis"}'

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        return MockResp()

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    merged = consolidate_synonyms_with_gbif(conn)
    assert merged == 1

    # Verify synonym 5FY79 was merged into LX6F and occurrence updated
    occ = conn.execute("SELECT taxon_key FROM occurrences WHERE occurrence_id = '1'").fetchone()
    assert occ["taxon_key"] == "LX6F"

    syn_row = conn.execute("SELECT * FROM taxa WHERE taxon_key = '5FY79'").fetchone()
    assert syn_row is None

    conn.close()


def test_max_occurrences_per_taxon_threshold(tmp_path):
    """Test that max_occurrences_per_taxon caps occurrences ingested per taxon."""
    tsv_file = tmp_path / "occ_cap.txt"
    # Create TSV with 5 occurrences for taxon 101 and 2 occurrences for taxon 202
    tsv_content = (
        "gbifID\tacceptedTaxonKey\tscientificName\tcanonicalName\tdecimalLatitude\tdecimalLongitude\tlocality\teventDate\tmonth\tassociatedMedia\tfamily\tgenus\tvernacularName\n"
        "1\t101\tSpecies One L.\tSpecies One\t55.67\t12.56\tLoc1\t2023-06-10\t6\thttp://example.com/1.jpg\tFam1\tGen1\tName1\n"
        "2\t101\tSpecies One L.\tSpecies One\t55.67\t12.56\tLoc2\t2023-06-10\t6\thttp://example.com/2.jpg\tFam1\tGen1\tName1\n"
        "3\t101\tSpecies One L.\tSpecies One\t55.67\t12.56\tLoc3\t2023-06-10\t6\thttp://example.com/3.jpg\tFam1\tGen1\tName1\n"
        "4\t101\tSpecies One L.\tSpecies One\t55.67\t12.56\tLoc4\t2023-06-10\t6\thttp://example.com/4.jpg\tFam1\tGen1\tName1\n"
        "5\t101\tSpecies One L.\tSpecies One\t55.67\t12.56\tLoc5\t2023-06-10\t6\thttp://example.com/5.jpg\tFam1\tGen1\tName1\n"
        "6\t202\tSpecies Two L.\tSpecies Two\t56.00\t12.00\tLoc6\t2023-05-01\t5\thttp://example.com/6.jpg\tFam2\tGen2\tName2\n"
        "7\t202\tSpecies Two L.\tSpecies Two\t56.00\t12.00\tLoc7\t2023-05-01\t5\thttp://example.com/7.jpg\tFam2\tGen2\tName2\n"
    )
    tsv_file.write_text(tsv_content, encoding="utf-8")

    db_path = tmp_path / "app_cap.db"
    # Cap at 2 occurrences per taxon
    inserted_occ, inserted_taxa = ingest_dwc_file(
        tsv_file, db_path=db_path, batch_size=10, max_occurrences_per_taxon=2
    )

    # Taxon 101 capped at 2, Taxon 202 has 2 -> Total 4 occurrences inserted
    assert inserted_occ == 4
    assert inserted_taxa == 2

    conn = sqlite3.connect(str(db_path))
    cnt_101 = conn.execute("SELECT COUNT(*) FROM occurrences WHERE taxon_key = '101'").fetchone()[0]
    assert cnt_101 == 2
    conn.close()


@pytest.mark.parametrize(
    "latitude,longitude,expected",
    [
        ("invalid", "12.5", (None, 12.5)),
        ("55.5", "not known", (55.5, None)),
        (" ", "", (None, None)),
        ("NaN", "inf", (None, None)),
        ("91", "-181", (None, None)),
        ("-90", "180", (-90.0, 180.0)),
        ("0", "0", (0.0, 0.0)),
    ],
)
def test_ingest_invalid_coordinates_preserves_photo_observations(
    tmp_path, monkeypatch, latitude, longitude, expected
):
    """Optional coordinates cannot interrupt ingestion of usable photos."""
    monkeypatch.setattr("taxo_trainer.db.ensure_data_dir", lambda: tmp_path)
    source = tmp_path / "occurrence.txt"
    with source.open("w", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t")
        writer.writerow(["gbifID", "taxonKey", "associatedMedia", "decimalLatitude", "decimalLongitude"])
        writer.writerow(["1", "101", "https://example.com/photo", latitude, longitude])
        writer.writerow(["2", "101", "https://example.com/photo2", "55", "12"])
    target = tmp_path / "app.db"
    assert ingest_dwc_file(source, db_path=target, batch_size=1) == (2, 1)
    conn = sqlite3.connect(target)
    try:
        assert conn.execute(
            "SELECT latitude, longitude FROM occurrences WHERE occurrence_id = '1'"
        ).fetchone() == expected
        assert conn.execute("SELECT occurrence_count FROM taxa").fetchone() == (2,)
    finally:
        conn.close()


@pytest.mark.parametrize("media_source", ["associatedMedia", "accessURI", "sidecar", "zip"])
def test_unusable_media_does_not_consume_taxon_cap(tmp_path, monkeypatch, media_source):
    """Record links and malformed media must not crowd out photo observations."""
    monkeypatch.setattr("taxo_trainer.db.ensure_data_dir", lambda: tmp_path)
    source = tmp_path / "occurrence.txt"
    fields = ["gbifID", "taxonKey", "associatedMedia", "accessURI", "references", "identifier"]
    records = [
        {"gbifID": "1", "references": "https://example.com/observation/1"},
        {"gbifID": "2", "identifier": "https://example.com/observation/2"},
        {"gbifID": "3", "associatedMedia": "not-a-url|https:///missing-host"},
        {"gbifID": "4"},
        {"gbifID": "5"},
        {"gbifID": "6"},
    ]
    # No suffix requirement: providers often serve photos from dynamic URLs.
    photo = "https://images.example/image?id=4"
    if media_source in ("associatedMedia", "accessURI"):
        for record in records[3:]:
            record[media_source] = f" {photo} |{photo}"
    with source.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows({"taxonKey": "101", **record} for record in records)
    if media_source in ("sidecar", "zip"):
        multimedia = tmp_path / "multimedia.txt"
        multimedia.write_text(
            "coreid\tidentifier\taccessURI\treferences\n"
            "1\t\t\thttps://example.com/observation/1\n"
            "3\tnot-a-url\t\t\n"
            f"4\t{photo}\t\t\n5\t\t{photo}\t\n6\t{photo}\t\t\n"
        )
        if media_source == "zip":
            archive = tmp_path / "dataset.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.write(source, "occurrence.txt")
                bundle.write(multimedia, "multimedia.txt")
            source = archive
    target = tmp_path / "app.db"
    assert ingest_dwc_file(source, db_path=target, batch_size=1, max_occurrences_per_taxon=2) == (2, 1)
    conn = sqlite3.connect(target)
    try:
        assert conn.execute(
            "SELECT occurrence_id, media_urls FROM occurrences ORDER BY occurrence_id"
        ).fetchall() == [("4", photo), ("5", photo)]
        assert conn.execute("SELECT occurrence_count FROM taxa").fetchone() == (2,)
    finally:
        conn.close()


def test_fetch_gbif_raw_api_cache(tmp_path, monkeypatch):
    """Test raw API HTTP response caching in gbif_cache.db keyed by request URL."""
    from taxo_trainer.db import get_gbif_cache_connection
    from taxo_trainer.ingestion.taxonomy_builder import fetch_gbif_raw_api

    cache_db = tmp_path / "gbif_cache_test.db"
    monkeypatch.setattr("taxo_trainer.db.GBIF_CACHE_DB_PATH", cache_db)

    cache_conn = get_gbif_cache_connection()
    target_url = "https://api.gbif.org/v1/species/match?name=Quercus+robur"

    # Mock urllib.request.urlopen to return raw JSON
    class MockResp:
        status = 200

        def read(self):
            return b'{"usageKey": 2435140, "species": "Quercus robur", "rank": "SPECIES"}'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=5: MockResp())

    # 1. First fetch — triggers HTTP request and caches raw JSON string
    res1 = fetch_gbif_raw_api(target_url, cache_conn)
    assert res1 is not None
    assert res1["usageKey"] == 2435140

    # Verify raw response string stored in db under key = target_url
    row = cache_conn.execute("SELECT response_json FROM gbif_api_cache WHERE url = ?", (target_url,)).fetchone()
    assert row is not None
    assert "Quercus robur" in row["response_json"]

    # 2. Second fetch with failing HTTP mock — should read directly from disk cache
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=5: Exception("Network Down"))
    res2 = fetch_gbif_raw_api(target_url, cache_conn)
    assert res2 is not None
    assert res2["usageKey"] == 2435140

    cache_conn.close()


def test_resolve_dwc_source_path_remote_url(tmp_path, monkeypatch):
    """Test downloading and caching remote DarwinCore ZIP archive URLs."""
    from taxo_trainer.ingestion.dwc_parser import is_url, resolve_dwc_source_path

    # Verify is_url helper
    assert is_url("https://api.gbif.org/v1/occurrence/download/request/0010181-260806074905277.zip") is True
    assert is_url("http://example.com/dataset.zip") is True
    assert is_url("src/data/datasets/danske_planter_2026.zip") is False

    # Mock urllib.request.urlopen to simulate streaming zip download
    target_url = "https://api.gbif.org/v1/occurrence/download/request/0010181-260806074905277.zip"

    class MockHTTPResponse:
        def __init__(self):
            self.headers = {"Content-Length": str(len(b"PK\x03\x04MockZipData"))}
            self.read_count = 0


        def read(self, chunk_size):
            if self.read_count == 0:
                self.read_count += 1
                return b"PK\x03\x04MockZipData"
            return b""

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=30: MockHTTPResponse())
    monkeypatch.setattr("taxo_trainer.db.DATA_DIR", tmp_path)

    progress_msgs = []
    resolved = resolve_dwc_source_path(target_url, progress_callback=progress_msgs.append)

    assert resolved.exists()
    assert resolved.name == "0010181-260806074905277.zip"
    assert len(progress_msgs) >= 1
    assert "Downloading" in progress_msgs[-1] or "Connecting" in progress_msgs[0]


class DownloadResponse(io.BytesIO):
    """Offline streaming response with optional length and injected failure."""

    def __init__(self, data, length=None, fail_after_chunk=False):
        super().__init__(data)
        self.headers = {} if length is None else {"Content-Length": str(length)}
        self.fail_after_chunk = fail_after_chunk

    def read(self, size=-1):
        if self.fail_after_chunk and self.tell():
            raise OSError("Connection interrupted")
        return super().read(size)


@pytest.mark.parametrize("failure", ["batch", "activation", "empty", "bad_zip"])
def test_failed_import_preserves_live_dataset_and_retries(tmp_path, monkeypatch, failure):
    """Staging and publication failures preserve data visible to open readers."""
    monkeypatch.setattr("taxo_trainer.db.ensure_data_dir", lambda: tmp_path)
    old_source = tmp_path / "old.txt"
    header = "gbifID\ttaxonKey\tassociatedMedia\n"
    old_source.write_text(header + "old\t101\thttps://example.com/old.jpg\n")
    target = tmp_path / "app.db"
    ingest_dwc_file(old_source, db_path=target)
    reader = sqlite3.connect(target)
    try:
        reader.execute("INSERT INTO app_metadata VALUES ('theme_preference', 'dark')")
        reader.commit()
        old_dump = list(reader.iterdump())
        new_source = tmp_path / "new.txt"
        new_source.write_text(
            header + "new1\t202\thttps://example.com/1.jpg\n"
            "new2\t202\thttps://example.com/2.jpg\n"
        )
        attempted_source = new_source
        if failure == "activation":
            reader.execute("""
                CREATE TRIGGER fail_import BEFORE INSERT ON occurrences
                WHEN NEW.occurrence_id = 'new2'
                BEGIN SELECT RAISE(ABORT, 'Injected activation failure'); END
            """)
            reader.commit()
        elif failure == "empty":
            attempted_source = tmp_path / "empty.txt"
            attempted_source.write_text(header)
        elif failure == "bad_zip":
            attempted_source = tmp_path / "broken.zip"
            attempted_source.write_bytes(b"not a zip")

        prepared = []

        def progress(value):
            if isinstance(value, int):
                prepared.append(value)
                assert reader.execute("SELECT occurrence_id FROM occurrences").fetchall() == [("old",)]
                assert reader.execute(
                    "SELECT val FROM app_metadata WHERE key = 'active_dwc_path'"
                ).fetchone() == (str(old_source.resolve()),)
                if failure == "batch":
                    raise RuntimeError("Injected failure after staged batch")

        with pytest.raises((RuntimeError, sqlite3.IntegrityError, ValueError, zipfile.BadZipFile)):
            ingest_dwc_file(attempted_source, db_path=target, batch_size=1, progress_callback=progress)
        if failure == "activation":
            assert prepared and prepared[-1] == 2
            reader.execute("DROP TRIGGER fail_import")
            reader.commit()
        assert list(reader.iterdump()) == old_dump

        assert ingest_dwc_file(new_source, db_path=target, batch_size=1) == (2, 1)
        # The same reader sees the committed import, with previous add/update semantics.
        assert reader.execute("SELECT occurrence_id FROM occurrences ORDER BY occurrence_id").fetchall() == [
            ("new1",), ("new2",), ("old",)
        ]
        assert reader.execute(
            "SELECT val FROM app_metadata WHERE key = 'active_dwc_path'"
        ).fetchone() == (str(new_source.resolve()),)
        assert reader.execute(
            "SELECT val FROM app_metadata WHERE key = 'theme_preference'"
        ).fetchone() == ("dark",)
        assert reader.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert reader.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        reader.close()


@pytest.mark.parametrize("failure", ["connection", "short", "empty", "callback"])
def test_failed_download_is_not_cached_and_can_retry(tmp_path, monkeypatch, failure):
    """A failed transfer never publishes a cache entry and a retry starts fresh."""
    url = "https://example.com/dataset.txt"
    payload = b"gbifID\ttaxonKey\n1\t2\n"
    monkeypatch.setattr("taxo_trainer.db.DATA_DIR", tmp_path)
    first = DownloadResponse(
        b"" if failure == "empty" else payload,
        length=len(payload) + 1 if failure == "short" else None,
        fail_after_chunk=failure == "connection",
    )
    responses = iter([first, DownloadResponse(payload, len(payload))])
    calls = []

    def open_response(req, timeout):
        calls.append(req.full_url)
        return next(responses)

    def progress(message):
        if message.startswith("Downloading"):
            # Only a private temporary file may exist while the transfer runs.
            assert not list(tmp_path.rglob("dataset.txt"))
            if failure == "callback":
                raise RuntimeError("Progress callback failed")

    monkeypatch.setattr("urllib.request.urlopen", open_response)
    with pytest.raises((OSError, ValueError, RuntimeError)):
        resolve_dwc_source_path(url, progress)
    assert not [p for p in tmp_path.rglob("*") if p.is_file()]

    resolved = resolve_dwc_source_path(url)
    assert resolved.read_bytes() == payload
    assert resolve_dwc_source_path(url) == resolved
    assert calls == [url, url]
    assert not list(tmp_path.rglob("*.part"))


def test_url_cache_isolates_basenames_and_query_strings(tmp_path, monkeypatch):
    """Distinct URLs cannot reuse each other's files or legacy partial entries."""
    monkeypatch.setattr("taxo_trainer.db.DATA_DIR", tmp_path)
    legacy = tmp_path / "datasets" / "dataset.txt"
    legacy.parent.mkdir()
    legacy.write_bytes(b"old partial download")
    urls = [
        "https://first.example/dataset.txt?id=1",
        "https://second.example/dataset.txt?id=1",
        "https://first.example/dataset.txt?id=2",
    ]
    payloads = {url: f"dataset {i}".encode() for i, url in enumerate(urls)}
    calls = []

    def open_response(req, timeout):
        calls.append(req.full_url)
        # EOF without Content-Length is supported for successful transfers.
        return DownloadResponse(payloads[req.full_url])

    monkeypatch.setattr("urllib.request.urlopen", open_response)
    paths = [resolve_dwc_source_path(url) for url in urls]
    assert len(set(paths)) == len(urls)
    for url, path in zip(urls, paths):
        assert path.name == "dataset.txt"
        assert path.read_bytes() == payloads[url]
        assert resolve_dwc_source_path(url) == path
    assert calls == urls
    assert legacy.read_bytes() == b"old partial download"
    assert resolve_dwc_source_path(str(legacy)) == legacy
