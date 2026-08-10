"""Unit tests for DarwinCore ingestion and taxonomy building modules."""

import sqlite3

from src.ingestion.dwc_parser import (
    extract_canonical_name,
    ingest_dwc_file,
    parse_month,
)
from src.ingestion.taxonomy_builder import load_custom_vernacular_json


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
