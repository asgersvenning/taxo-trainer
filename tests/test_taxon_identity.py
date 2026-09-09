"""Regression coverage for ID-only taxonomy, including CoL/legacy namespaces."""

import json
import sqlite3

import pytest

from taxo_trainer.db import init_app_db, init_user_db
from taxo_trainer.engine.analytics import get_rank_mastery_stats, log_attempt
from taxo_trainer.engine.sampling import SamplingFilter, sample_stage1_taxon
from taxo_trainer.engine.validator import autocomplete_taxa, validate_user_guess
from taxo_trainer.ingestion import taxonomy_builder as builder
from taxo_trainer.ingestion.dwc_parser import ingest_dwc_file
from tests.test_gbif_requests import Response


@pytest.fixture
def database(tmp_path, monkeypatch):
    """Use isolated app/cache files and forbid any unmocked HTTP requests."""
    monkeypatch.setattr("taxo_trainer.db.ensure_data_dir", lambda: tmp_path)
    monkeypatch.setattr("taxo_trainer.db.GBIF_CACHE_DB_PATH", tmp_path / "cache.db")
    monkeypatch.setattr(builder, "_GBIF_COOLDOWN_UNTIL", 0)

    def forbidden(*args, **kwargs):
        pytest.fail("Unexpected network request")

    monkeypatch.setattr(builder, "_open_gbif", forbidden)
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_app_db(conn)
    yield conn
    conn.close()


def add_taxon(conn, key, name="Shared name", **kwargs):
    """Insert a fixture with explicitly supplied IDs."""
    columns = {
        "taxon_key": key,
        "scientific_name": name,
        "canonical_name": name,
        "accepted_name": name,
        "rank": "SPECIES",
        "occurrence_count": 1,
    } | kwargs
    conn.execute(
        f"INSERT INTO taxa ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
        tuple(columns.values()),
    )
    conn.commit()


@pytest.mark.parametrize(
    "url",
    [
        "https://api.gbif.org/v1/species/match?name=Quercus",
        "https://api.gbif.org/v2/species/match?scientificName=Quercus",
        "https://api.gbif.org/v1/species/search?q=Quercus",
        "https://api.gbif.org/v1/species/suggest?q=Quercus",
        "https://api.gbif.org/v1/species/1?name=Quercus",
        "https://api.gbif.org/v1/species/1?offset=Quercus",
        "https://api.gbif.org/v1/species/../match",
        "https://other.example/v1/species/1",
    ],
)
def test_free_text_requests_rejected_even_if_cached(database, url):
    cache = builder.get_gbif_cache_connection()
    try:
        cache.execute(
            "INSERT INTO gbif_api_cache VALUES (?, '{}', ?)",
            (url, int(builder.time.time())),
        )
        cache.commit()
        with pytest.raises(builder.GBIFRequestError, match="ID-addressed"):
            builder.fetch_gbif_raw_api(url, cache)
    finally:
        cache.close()


@pytest.mark.parametrize("col_key", ["67S22", "123"])
def test_col_identity_bridge_retains_source_keys_and_languages(
    database, monkeypatch, col_key
):
    """Both letter/digit and numeric CoL IDs retain their checklist identity."""
    add_taxon(
        database,
        col_key,
        "Local spelling",
        checklist_key=builder.COL_CHECKLIST,
        genus="Local genus",
        vernacular_json='{"fr":"Nom conservé"}',
    )
    database.execute(
        "INSERT INTO occurrences (occurrence_id,taxon_key,media_urls) VALUES ('10',?,'https://photo.example/a')",
        (col_key,),
    )
    database.commit()
    calls = []

    def respond(req, **kwargs):
        url = req.full_url
        calls.append(url)
        if url.endswith("/occurrence/10"):
            data = {
                "key": 10,
                "classifications": {
                    builder.COL_CHECKLIST: {
                        "classification": [
                            {"key": col_key, "rank": "SPECIES"},
                            {"key": "32BQ", "rank": "GENUS"},
                        ]
                    },
                    builder.BACKBONE_CHECKLIST: {
                        "classification": [{"key": "7353729", "rank": "SPECIES"}]
                    },
                },
            }
        elif "/vernacularNames" in url:
            data = {"results": [{"language": "deu", "vernacularName": "Neuer Name"}]}
        else:
            assert url.endswith("/species/7353729")
            data = {
                "key": 7353729,
                "rank": "SPECIES",
                "genusKey": 8106066,
                "genus": "Different spelling",
            }
        return Response(json.dumps(data).encode())

    monkeypatch.setattr(builder, "_open_gbif", respond)
    assert builder.enrich_vernacular_names_from_gbif(database) == 1
    row = database.execute("SELECT * FROM taxa").fetchone()
    assert row["taxon_key"] == col_key
    assert row["checklist_key"] == builder.COL_CHECKLIST
    assert row["genus_key"] == "32BQ"
    assert row["canonical_name"] == "Local spelling"
    assert json.loads(row["vernacular_json"]) == {
        "fr": "Nom conservé",
        "de": "Neuer Name",
    }
    rank = database.execute("SELECT * FROM higher_ranks").fetchone()
    assert rank["taxon_key"] == "32BQ"
    assert rank["rank_name"] == "Local genus"
    assert builder.enrich_vernacular_names_from_gbif(database) == 0
    assert len(calls) == 4  # Cached species, genus names, and occurrence on rerun.
    assert all("name=" not in url and "/match" not in url for url in calls)


def test_disagreeing_occurrence_identity_does_not_guess_by_name(database, monkeypatch):
    add_taxon(database, "67S22", checklist_key=builder.COL_CHECKLIST)
    database.execute(
        "INSERT INTO occurrences (occurrence_id,taxon_key,media_urls) VALUES ('10','67S22','https://photo.example/a')"
    )
    database.commit()
    calls = []

    def respond(req, **kwargs):
        calls.append(req.full_url)
        return Response(
            json.dumps(
                {
                    "key": 10,
                    "classifications": {
                        builder.COL_CHECKLIST: {
                            "classification": [
                                {
                                    "key": "OTHER",
                                    "rank": "SPECIES",
                                    "name": "Shared name",
                                }
                            ]
                        }
                    },
                }
            ).encode()
        )

    monkeypatch.setattr(builder, "_open_gbif", respond)
    assert builder.enrich_vernacular_names_from_gbif(database) == 0
    assert calls == ["https://api.gbif.org/v1/occurrence/10"]
    assert database.execute("SELECT COUNT(*) FROM occurrences").fetchone()[0] == 1


def test_higher_rank_response_cannot_remove_species(database, monkeypatch):
    add_taxon(database, "1", checklist_key=builder.BACKBONE_CHECKLIST)
    monkeypatch.setattr(
        builder, "_open_gbif", lambda *a, **k: Response(b'{"key":1,"rank":"GENUS"}')
    )
    assert builder.enrich_vernacular_names_from_gbif(database) == 0
    assert database.execute("SELECT COUNT(*) FROM taxa").fetchone()[0] == 1


def test_unknown_alphanumeric_id_without_observation_stays_unresolved(database):
    add_taxon(database, "UNKNOWN", vernacular_json='{"fr":"Keep me"}')
    assert builder.enrich_vernacular_names_from_gbif(database) == 0
    assert (
        database.execute("SELECT vernacular_json FROM taxa").fetchone()[0]
        == '{"fr":"Keep me"}'
    )


def test_same_name_distinct_ids_survive_selection_filters_and_analytics(database):
    for key, genus_key in [("67S22", "32BQ"), ("75R3T", "92J5D")]:
        add_taxon(database, key, genus="Shared genus", genus_key=genus_key)
        database.execute(
            "INSERT INTO higher_ranks (taxon_key,rank_name,rank_level) VALUES (?,'Shared genus','GENUS')",
            (genus_key,),
        )
    database.commit()
    matches = autocomplete_taxa(database, "Shared name")
    assert {r["value"] for r in matches} == {"67S22", "75R3T"}
    assert not validate_user_guess(database, "75R3T", "67S22").is_correct
    assert validate_user_guess(database, "67S22", "67S22").is_correct
    ambiguous = validate_user_guess(database, "Shared name", "67S22")
    assert not ambiguous.is_correct and ambiguous.matched_taxon_key is None
    assert validate_user_guess(database, "32BQ", "67S22").matched_taxon_key == "32BQ"
    assert not validate_user_guess(database, "92J5D", "67S22").is_correct
    assert (
        sample_stage1_taxon(database, SamplingFilter(include_taxa=["32BQ"])) == "67S22"
    )
    assert {
        r["taxon_key"]
        for r in autocomplete_taxa(database, "Shared name", parent_genus="32BQ")
    } == {"67S22"}
    user = sqlite3.connect(":memory:")
    user.row_factory = sqlite3.Row
    init_user_db(user)
    try:
        for key in ["67S22", "75R3T"]:
            log_attempt(user, "occ" + key, key, key, True, data_source="test")
        ranks, _ = get_rank_mastery_stats(
            user, database, rank_level="SPECIES", data_source="test"
        )
        assert {r.taxon_key for r in ranks} == {"67S22", "75R3T"}
        genera, _ = get_rank_mastery_stats(
            user, database, rank_level="GENUS", data_source="test"
        )
        assert {r.taxon_key for r in genera} == {"32BQ", "92J5D"}
    finally:
        user.close()


def test_legacy_hierarchy_is_preserved_without_inferring_ids():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE higher_ranks (rank_name TEXT PRIMARY KEY,rank_level TEXT,vernacular_da TEXT,vernacular_en TEXT,vernacular_json TEXT)"
    )
    conn.execute("INSERT INTO higher_ranks VALUES ('Quercus','GENUS','Eg',NULL,NULL)")
    init_app_db(conn)
    init_app_db(conn)
    assert conn.execute("SELECT COUNT(*) FROM higher_ranks").fetchone()[0] == 0
    assert (
        conn.execute("SELECT vernacular_da FROM legacy_higher_ranks").fetchone()[0]
        == "Eg"
    )
    conn.close()


def test_import_preserves_col_ids_and_ignores_provider_taxon_ids(database, tmp_path):
    source = tmp_path / "occurrence.txt"
    source.write_text(
        "gbifID\tspeciesKey\ttaxonID\tscientificName\tgenus\tgenusKey\tassociatedMedia\n"
        "1\t67S22\tprovider123\tArctium lappa\tArctium\t32BQ\thttps://photo.example/1\n"
        "2\t\tprovider456\tAnother name\tAnother\t\thttps://photo.example/2\n"
    )
    path = tmp_path / "app.db"
    assert ingest_dwc_file(source, db_path=path) == (1, 1)
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT taxon_key,genus_key FROM taxa").fetchall() == [
        ("67S22", "32BQ")
    ]
    assert conn.execute("SELECT taxon_key FROM higher_ranks").fetchall() == [("32BQ",)]
    conn.close()


def test_hierarchy_render_does_not_make_network_requests(database, monkeypatch):
    from nicegui import ui

    from taxo_trainer.ui.components import render_taxonomic_hierarchy_feedback

    add_taxon(database, "67S22", genus="Arctium", genus_key="32BQ")
    row = database.execute("SELECT * FROM taxa").fetchone()

    def forbidden(*a, **k):
        pytest.fail("Rendering must not resolve names through HTTP")

    monkeypatch.setattr("urllib.request.urlopen", forbidden)
    with ui.column() as container:
        render_taxonomic_hierarchy_feedback(database, row, None, is_solved=True)
    links = [
        item._props.get("href", "")
        for item in container.descendants()
        if isinstance(item, ui.link)
    ]
    assert any("67S22" in link for link in links)
    assert any("32BQ" in link for link in links)
    container.delete()


def test_explicit_checklist_collision_preserves_existing_import(database, tmp_path):
    path = tmp_path / "app.db"
    source = tmp_path / "occurrence.txt"
    header = "gbifID\tspeciesKey\tchecklistKey\tscientificName\tassociatedMedia\n"
    source.write_text(
        header
        + f"1\t123\t{builder.BACKBONE_CHECKLIST}\tFirst name\thttps://photo.example/a\n"
    )
    ingest_dwc_file(source, db_path=path)
    conn = sqlite3.connect(path)
    before = list(conn.iterdump())
    source.write_text(
        header
        + f"2\t123\t{builder.COL_CHECKLIST}\tOther name\thttps://photo.example/b\n"
    )
    with pytest.raises(ValueError, match="Conflicting GBIF checklist"):
        ingest_dwc_file(source, db_path=path)
    assert list(conn.iterdump()) == before
    conn.close()


def test_no_numeric_namespace_assumption_without_provenance(database):
    add_taxon(database, "123")
    assert builder.enrich_vernacular_names_from_gbif(database) == 0
    assert database.execute("SELECT checklist_key FROM taxa").fetchone()[0] is None


def test_archive_input_cannot_query_a_free_text_api(database):
    from taxo_trainer.ingestion.dwc_parser import resolve_dwc_source_path

    with pytest.raises(ValueError, match="archive download URL"):
        resolve_dwc_source_path("https://api.gbif.org/v1/species/search?q=Quercus")


def test_id_lookup_redirect_cannot_escape_endpoint_boundary(monkeypatch):
    import urllib.request

    def opener(handler):
        class FakeOpener:
            def open(self, request, timeout):
                return handler.redirect_request(
                    request,
                    None,
                    302,
                    "redirect",
                    {},
                    "https://api.gbif.org/v1/species/match?name=Quercus",
                )

        return FakeOpener()

    monkeypatch.setattr("urllib.request.build_opener", opener)
    with pytest.raises(builder.GBIFRequestError, match="redirected"):
        builder._open_gbif(urllib.request.Request("https://api.gbif.org/v1/species/1"))
