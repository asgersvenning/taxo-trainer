"""Unit tests for DarwinCore ingestion and taxonomy building modules."""

import sqlite3

from taxo_trainer.ingestion.dwc_parser import (
    extract_canonical_name,
    ingest_dwc_file,
    parse_month,
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
            self.headers = {"Content-Length": "100"}
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
