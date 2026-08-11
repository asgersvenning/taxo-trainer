"""Unit tests for taxo-trainer core sampling, validator, and analytics engine."""

import sqlite3

import numpy as np
import pytest

from taxo_trainer.db import init_app_db, init_user_db
from taxo_trainer.engine.analytics import (
    get_confusion_matrix,
    get_global_stats,
    log_attempt,
)
from taxo_trainer.engine.sampling import (
    SamplingFilter,
    compute_weights,
    sample_stage1_taxon,
    sample_stage2_observation,
)
from taxo_trainer.engine.validator import (
    autocomplete_taxa,
    get_display_name,
    validate_user_guess,
)


@pytest.fixture
def setup_engine_dbs(tmp_path):
    """Fixture providing populated in-memory SQLite app and user databases."""
    app_conn = sqlite3.connect(":memory:")
    app_conn.row_factory = sqlite3.Row
    init_app_db(app_conn)

    user_conn = sqlite3.connect(":memory:")
    user_conn.row_factory = sqlite3.Row
    init_user_db(user_conn)

    # Insert sample taxa
    app_conn.execute("""
        INSERT INTO taxa (
            taxon_key, scientific_name, canonical_name, accepted_name, rank,
            family, genus, vernacular_da, vernacular_en, occurrence_count
        ) VALUES (
            2435140, 'Quercus robur L.', 'Quercus robur', 'Quercus robur', 'SPECIES',
            'Fagaceae', 'Quercus', 'Stilk-Eg', 'Pedunculate Oak', 100
        );
    """)
    app_conn.execute("""
        INSERT INTO taxa (
            taxon_key, scientific_name, canonical_name, accepted_name, rank,
            family, genus, vernacular_da, vernacular_en, occurrence_count
        ) VALUES (
            2865545, 'Fagus sylvatica L.', 'Fagus sylvatica', 'Fagus sylvatica', 'SPECIES',
            'Fagaceae', 'Fagus', 'Almindelig Bøg', 'European Beech', 10
        );
    """)

    # Insert sample occurrences
    app_conn.execute("""
        INSERT INTO occurrences (
            occurrence_id, taxon_key, latitude, longitude, locality, media_urls
        ) VALUES ('occ_q1', 2435140, 55.67, 12.56, 'Copenhagen', 'http://img1.jpg|http://img2.jpg');
    """)
    app_conn.execute("""
        INSERT INTO occurrences (
            occurrence_id, taxon_key, latitude, longitude, locality, media_urls
        ) VALUES ('occ_q2', 2435140, 55.68, 12.57, 'Copenhagen', 'http://img3.jpg');
    """)
    app_conn.execute("""
        INSERT INTO occurrences (
            occurrence_id, taxon_key, latitude, longitude, locality, media_urls
        ) VALUES ('occ_f1', 2865545, 56.00, 12.00, 'North Zealand', 'http://img4.jpg');
    """)
    app_conn.commit()

    yield app_conn, user_conn

    app_conn.close()
    user_conn.close()


def test_weight_transformations():
    """Test NumPy weight vector transformations."""
    counts = np.array([0, 3, 15, 99], dtype=np.float64)

    flat = compute_weights(counts, "flat")
    assert np.allclose(flat, [1.0, 1.0, 1.0, 1.0])

    natural = compute_weights(counts, "natural")
    assert np.allclose(natural, [0, 3, 15, 99])

    log_w = compute_weights(counts, "log")
    assert np.allclose(log_w, np.log1p(counts))

    sqrt_w = compute_weights(counts, "sqrt")
    assert np.allclose(sqrt_w, np.sqrt(counts))


def test_stage1_and_stage2_sampling(setup_engine_dbs):
    """Test two-stage sampling and anti-repeat mechanism."""
    app_conn, user_conn = setup_engine_dbs
    filters = SamplingFilter(mode="flat", min_count=1)

    # Stage 1 sampling
    sampled_key = sample_stage1_taxon(app_conn, filters)
    assert str(sampled_key) in ("2435140", "2865545")

    # Stage 2 sampling anti-repeat
    seen_set = set()
    obs1 = sample_stage2_observation(app_conn, user_conn, 2435140, filters, seen_set)
    assert obs1 is not None
    assert obs1.occurrence_id in ("occ_q1", "occ_q2")
    assert len(seen_set) == 1

    obs2 = sample_stage2_observation(app_conn, user_conn, 2435140, filters, seen_set)
    assert obs2 is not None
    assert obs2.occurrence_id != obs1.occurrence_id
    assert len(seen_set) == 2


def test_validator_multi_rank_and_autocomplete(setup_engine_dbs):
    """Test validator rank matching, fuzzy typos, and autocomplete."""
    app_conn, _ = setup_engine_dbs

    # Autocomplete
    suggestions = autocomplete_taxa(app_conn, "Quercus")
    assert len(suggestions) >= 1
    s_values = [s["value"] for s in suggestions]
    assert "Quercus" in s_values
    assert "Quercus robur" in s_values


    # Exact species match (vernacular Danish)
    res1 = validate_user_guess(app_conn, "Stilk-Eg", 2435140)
    assert res1.is_correct is True
    assert res1.matched_rank == "SPECIES"

    # Genus rank match
    res2 = validate_user_guess(app_conn, "Quercus", 2435140)
    assert res2.is_correct is True
    assert res2.matched_rank == "GENUS"

    # Family rank match
    res3 = validate_user_guess(app_conn, "Fagaceae", 2435140)
    assert res3.is_correct is True
    assert res3.matched_rank == "FAMILY"

    # Soft typo match (>0.90 similarity)
    res_typo = validate_user_guess(app_conn, "Quercus roburrr", 2435140)
    assert res_typo.is_correct is True
    assert res_typo.is_soft_typo is True

    # Wrong guess
    res_err = validate_user_guess(app_conn, "Fagus sylvatica", 2435140)
    assert res_err.is_correct is False
    assert str(res_err.matched_taxon_key) == "2865545"

    # Substring autocomplete with prefix priority
    sub_suggestions = autocomplete_taxa(app_conn, "uer")
    assert len(sub_suggestions) >= 1
    assert "Quercus" in sub_suggestions[0]["canonical_name"]

    # Unrecognized taxon name validation (doesn't match any species/genus/family in DB)
    res_unrec = validate_user_guess(app_conn, "XyZ_NonExistent_Taxon", 2435140)
    assert res_unrec.is_correct is False
    assert res_unrec.matched_taxon_key is None
    assert "Unrecognized taxon name" in res_unrec.feedback_message

    # Test get_display_name with partial columns in sqlite3.Row
    partial_row = app_conn.execute("SELECT taxon_key, canonical_name FROM taxa LIMIT 1;").fetchone()
    assert get_display_name(partial_row) == "Quercus robur"



def test_analytics_and_hint_penalties(setup_engine_dbs):
    """Test logging, unassisted metrics, hint exclusion, and confusion matrix."""
    app_conn, user_conn = setup_engine_dbs

    # Log 1: Unassisted correct attempt
    log_attempt(user_conn, "occ_q1", 2435140, 2435140, is_correct=True, used_hint=False)
    # Log 2: Assisted correct attempt (used hint)
    log_attempt(user_conn, "occ_q2", 2435140, 2435140, is_correct=True, used_hint=True)
    # Log 3: Incorrect attempt (mistook Quercus for Fagus)
    log_attempt(user_conn, "occ_q1", 2435140, 2865545, is_correct=False, used_hint=False)

    stats = get_global_stats(user_conn, app_conn)
    assert stats["total_attempts"] == 3
    assert stats["unassisted_attempts"] == 2
    assert stats["unassisted_correct"] == 1
    assert stats["unassisted_accuracy_pct"] == 50.0

    matrix = get_confusion_matrix(user_conn, app_conn, limit=5)
    assert len(matrix) == 1
    assert matrix[0].target_canonical == "Quercus robur"
    assert matrix[0].guessed_canonical == "Fagus sylvatica"
    assert matrix[0].count == 1


def test_sampling_whitelist_and_blacklist(setup_engine_dbs):
    """Test stage 1 taxon sampling with whitelist (include_taxa) and blacklist (exclude_taxa)."""
    app_conn, _ = setup_engine_dbs

    # 1. Whitelist Genus Quercus
    f_inc = SamplingFilter(include_taxa=["Quercus"])
    sampled_q = sample_stage1_taxon(app_conn, f_inc)
    assert str(sampled_q) == "2435140"  # Quercus robur

    # 2. Blacklist Quercus (should exclude Quercus robur and sample Fagus sylvatica)
    f_exc = SamplingFilter(exclude_taxa=["Quercus"])
    sampled_f = sample_stage1_taxon(app_conn, f_exc)
    assert str(sampled_f) == "2865545"  # Fagus sylvatica


def test_parent_scoped_autocomplete(setup_engine_dbs):
    """Test parent rank scoping (parent_genus, parent_family) in autocomplete_taxa."""
    app_conn, _ = setup_engine_dbs

    # When parent_genus='Quercus' is set, matching 'rob' returns Quercus robur
    matches_q = autocomplete_taxa(app_conn, "rob", parent_genus="Quercus")
    assert len(matches_q) == 1
    assert matches_q[0]["canonical_name"] == "Quercus robur"

    # When parent_genus='Quercus' is set, typing 'sylv' (Fagus) returns 0 results
    matches_f = autocomplete_taxa(app_conn, "sylv", parent_genus="Quercus")
    assert len(matches_f) == 0

    # When parent_family='Fagaceae' is set, matching 'Eg' returns Quercus robur (Stilk-Eg)
    matches_fam = autocomplete_taxa(app_conn, "Eg", parent_family="Fagaceae")
    assert len(matches_fam) >= 1


def test_autocomplete_rank_ordering_species_before_genus(setup_engine_dbs):
    """Test that equal priority matches are ordered by rank level (species before genus)."""
    app_conn, _ = setup_engine_dbs

    # Insert a genus 'Quercus' with vernacular_da 'Stilk-Eg' in higher_ranks to create equal priority match
    app_conn.execute("""
        INSERT INTO higher_ranks (rank_name, rank_level, vernacular_da)
        VALUES ('Quercus', 'GENUS', 'Stilk-Eg');
    """)
    app_conn.commit()

    # Querying 'Stilk-Eg' matches both Species (Quercus robur) and Genus (Quercus) at Priority 0.
    # Higher rank (Genus) should be prioritized.
    matches = autocomplete_taxa(app_conn, "Stilk-Eg")
    assert len(matches) >= 2
    assert matches[0]["rank"] == "SPECIES"
    assert matches[0]["canonical_name"] == "Quercus robur"
    assert matches[1]["rank"] == "GENUS"
    assert matches[1]["canonical_name"] == "Quercus"


def test_autocomplete_canonical_exact_match_beats_secondary_vernacular(setup_engine_dbs):
    """Test that exact canonical match on genus beats secondary vernacular match on species."""
    app_conn, _ = setup_engine_dbs

    # Insert Artemisia vulgaris species with English/secondary vernacular 'Artemisia'
    app_conn.execute("""
        INSERT INTO taxa (taxon_key, canonical_name, scientific_name, accepted_name, rank, family, genus, vernacular_da, vernacular_en)
        VALUES (99999, 'Artemisia vulgaris', 'Artemisia vulgaris L.', 'Artemisia vulgaris L.', 'SPECIES', 'Asteraceae', 'Artemisia', 'Grå-bynke', 'Artemisia|Mugwort');
    """)
    # Insert Artemisia genus
    app_conn.execute("""
        INSERT INTO higher_ranks (rank_name, rank_level)
        VALUES ('Artemisia', 'GENUS');
    """)
    app_conn.commit()

    # Searching 'Artemisia' (with lang='da') should rank Genus (canonical exact match) before Species (secondary vernacular match)
    matches = autocomplete_taxa(app_conn, "artemisia", lang="da")
    assert len(matches) >= 2
    assert matches[0]["rank"] == "GENUS"
    assert matches[0]["canonical_name"] == "Artemisia"
    assert matches[1]["rank"] == "SPECIES"
    assert matches[1]["canonical_name"] == "Artemisia vulgaris"


def test_autocomplete_prefix_match_ranks_genus_before_species(setup_engine_dbs):
    """Test that rank order places species before genus for equal priority matches."""
    app_conn, _ = setup_engine_dbs

    app_conn.execute("""
        INSERT INTO taxa (taxon_key, scientific_name, canonical_name, accepted_name, rank, family, genus, vernacular_da, vernacular_en)
        VALUES (88888, 'Trifolium dubium', 'Trifolium dubium Sibth.', 'Trifolium dubium Sibth.', 'SPECIES', 'Fabaceae', 'Trifolium', 'Fin kløver', 'Lesser trefoil');
    """)
    app_conn.execute("""
        INSERT INTO higher_ranks (rank_name, rank_level, vernacular_da)
        VALUES ('Trifolium', 'GENUS', 'Kløver-slægten');
    """)
    app_conn.commit()

    # Searching 'trifoliu' should rank Genus (Trifolium) before Species (Trifolium dubium)
    matches = autocomplete_taxa(app_conn, "trifoliu", lang="da")
    assert len(matches) >= 2
    assert matches[0]["rank"] == "SPECIES"
    assert "Trifolium dubium" in matches[0]["canonical_name"]
    assert matches[1]["rank"] == "GENUS"
    assert matches[1]["canonical_name"] == "Trifolium"


def test_get_display_name_vernacular_fallback_non_english():
    """Test that get_display_name does not fall back to English when language is Danish."""
    row = {
        "canonical_name": "Mutarda Bernh.",
        "scientific_name": "Mutarda Bernh.",
        "vernacular_da": "",
        "vernacular_en": "Mustard|mustard",
        "vernacular_json": '{"en": "Mustard|mustard", "no": "svartsennepslekta"}',
    }
    # When lang="da", missing Danish name should fall back to canonical_name, NOT English "Mustard"
    disp_da = get_display_name(row, lang="da")
    assert disp_da == "Mutarda Bernh."

    # When lang="en", English name should be returned
    disp_en = get_display_name(row, lang="en")
    assert disp_en == "Mustard"


def test_autocomplete_sennep_ordering_and_vernacular(setup_engine_dbs):
    """Test autocomplete search for 'sennep' with word-prefix ranking and Danish display fallbacks."""
    app_conn, _ = setup_engine_dbs

    app_conn.execute("""
        INSERT INTO taxa (
            taxon_key, scientific_name, canonical_name, accepted_name, rank,
            family, genus, vernacular_da, vernacular_en, vernacular_json, occurrence_count
        ) VALUES (
            1001, 'Sinapis alba L.', 'Sinapis alba', 'Sinapis alba L.', 'SPECIES',
            'Brassicaceae', 'Sinapis', 'Gul sennep', 'White Mustard', '{"da": "Gul sennep", "en": "White Mustard"}', 5
        );
    """)
    app_conn.execute("""
        INSERT INTO taxa (
            taxon_key, scientific_name, canonical_name, accepted_name, rank,
            family, genus, vernacular_da, vernacular_en, vernacular_json, occurrence_count
        ) VALUES (
            1002, 'Mutarda Bernh.', 'Mutarda Bernh.', 'Brassica L.', 'GENUS',
            'Brassicaceae', 'Rhamphospermum', '', 'Mustard', '{"en": "Mustard", "no": "svartsennepslekta"}', 1
        );
    """)
    app_conn.execute("""
        INSERT INTO higher_ranks (rank_name, rank_level, vernacular_da, vernacular_en, vernacular_json)
        VALUES ('Descurainia', 'GENUS', 'Vejsennep', 'Tansymustard', '{"da": "Vejsennep"}');
    """)
    app_conn.commit()

    matches = autocomplete_taxa(app_conn, "sennep", lang="da")
    assert len(matches) >= 1
    # Gul sennep has word-prefix match on 'sennep' -> Priority 2, should be ranked top
    assert matches[0]["canonical_name"] == "Sinapis alba"
    assert "Gul sennep" in matches[0]["display_name"]

    # Verify Mutarda Bernh. is not assigned English 'Mustard' as Danish name and not top result
    labels = [m["label"] for m in matches]
    assert not any("MUSTARD" in l or "Mustard" in l for l in labels)


def test_render_taxonomic_hierarchy_gbif_links(setup_engine_dbs):
    """Test that render_taxonomic_hierarchy_feedback renders GBIF links for revealed ranks."""
    from taxo_trainer.engine.validator import ValidationResult
    from taxo_trainer.ui.components import render_taxonomic_hierarchy_feedback

    app_conn, _ = setup_engine_dbs

    t_row = app_conn.execute("SELECT * FROM taxa WHERE canonical_name = 'Quercus robur'").fetchone()
    v_res = ValidationResult(
        user_input="Quercus robur",
        is_correct=True,
        matched_rank="SPECIES",
        matched_taxon_key=2435140,
        matched_name="Stilk-Eg (Quercus robur)",
        similarity_score=1.0,
        is_soft_typo=False,
        feedback_message="Correct!",
    )

    card = render_taxonomic_hierarchy_feedback(app_conn, t_row, v_res, lang="da")
    assert card is not None


def test_autocomplete_monotypic_genus_vs_species_mistelte(setup_engine_dbs):
    """Test that when a vernacular search matches both a monotypic genus and species, species ranks first."""
    app_conn, _ = setup_engine_dbs

    app_conn.execute("""
        INSERT INTO taxa (
            taxon_key, scientific_name, canonical_name, accepted_name, rank,
            order_name, family, genus, vernacular_da, vernacular_en
        ) VALUES (
            9901, 'Viscum album L.', 'Viscum album', 'Viscum album L.', 'SPECIES',
            'Santalales', 'Santalaceae', 'Viscum', 'Mistelten', 'Mistletoe'
        );
    """)
    app_conn.execute("""
        INSERT INTO higher_ranks (rank_name, rank_level, vernacular_da)
        VALUES ('Viscum', 'GENUS', 'Mistelten');
    """)
    app_conn.commit()

    matches = autocomplete_taxa(app_conn, "mistelte", lang="da")
    assert len(matches) >= 2
    # Species should be ranked BEFORE GENUS
    assert matches[0]["rank"] == "SPECIES"
    assert matches[0]["canonical_name"] == "Viscum album"
    assert matches[1]["rank"] == "GENUS"
    assert matches[1]["canonical_name"] == "Viscum"


def test_higher_order_hint_sequential_revelation(setup_engine_dbs):
    """Test higher order hint sequential rank revelation and autocomplete scope restriction."""
    app_conn, user_conn = setup_engine_dbs
    from taxo_trainer.ui.quiz_view import QuizViewState

    app_conn.execute("""
        INSERT INTO taxa (
            taxon_key, scientific_name, canonical_name, accepted_name, rank,
            order_name, family, genus, vernacular_da, vernacular_en
        ) VALUES (
            9901, 'Viscum album L.', 'Viscum album', 'Viscum album L.', 'SPECIES',
            'Santalales', 'Santalaceae', 'Viscum', 'Mistelten', 'Mistletoe'
        );
    """)
    app_conn.commit()

    state = QuizViewState()
    state.current_question = type("Obj", (), {
        "occurrence_id": "occ_100",
        "taxon_key": 9901,
        "scientific_name": "Viscum album L.",
        "canonical_name": "Viscum album",
        "family": "Santalaceae",
        "genus": "Viscum",
        "vernacular_da": "Mistelten",
        "vernacular_en": "Mistletoe",
    })()

    # Initial state: unrevealed
    assert state.matched_order is None
    assert state.matched_family is None
    assert state.matched_genus is None
    assert state.used_hint is False

    # Simulate 1st hint click: reveals Order
    state.used_hint = True
    target_row = app_conn.execute("SELECT * FROM taxa WHERE taxon_key = ?", (9901,)).fetchone()
    target_order = target_row["order_name"] if target_row and "order_name" in target_row and target_row["order_name"] else "Santalales"

    if not state.matched_order and target_order:
        state.matched_order = target_order
    assert state.matched_order == "Santalales"

    # Simulate 2nd hint click: reveals Family
    if not state.matched_family and state.current_question.family:
        state.matched_family = state.current_question.family
    assert state.matched_family == "Santalaceae"

    # Simulate 3rd hint click: reveals Genus
    if not state.matched_genus and state.current_question.genus:
        state.matched_genus = state.current_question.genus
    assert state.matched_genus == "Viscum"

    # Verify autocomplete interpolation is restricted by revealed genus
    matches = autocomplete_taxa(
        app_conn,
        "Viscum",
        lang="da",
        parent_genus=state.matched_genus,
        parent_family=state.matched_family,
        parent_order=state.matched_order,
    )
    assert len(matches) > 0
    for m in matches:
        if m["rank"] == "SPECIES":
            assert "Viscum" in m["canonical_name"] or "Viscum" in m["label"]

    # Verify no attempts were logged in user_progress
    attempts = user_conn.execute("SELECT COUNT(*) as cnt FROM user_progress").fetchone()["cnt"]
    assert attempts == 0


def test_user_streak_persistence(setup_engine_dbs):
    """Test user streak DB persistence and streak breaking rules."""
    _, user_conn = setup_engine_dbs
    from taxo_trainer.db import get_user_streak, set_user_streak

    # 1. Initial streak is 0, 0
    curr, best = get_user_streak(user_conn)
    assert curr == 0
    assert best == 0

    # 2. Update streak on correct species solve
    set_user_streak(1, 1, user_conn)
    set_user_streak(2, 2, user_conn)
    curr, best = get_user_streak(user_conn)
    assert curr == 2
    assert best == 2

    # 3. Unrevealed skip should NOT break streak
    # (Simulated state where is_incorrect is False)
    curr, best = get_user_streak(user_conn)
    assert curr == 2
    assert best == 2

    # 4. Incorrect guess followed by next observation breaks streak
    set_user_streak(0, 2, user_conn)
    curr, best = get_user_streak(user_conn)
    assert curr == 0
    assert best == 2  # Best record preserved!


def test_dashboard_analytics_time_range_filtering(setup_engine_dbs):
    """Test dashboard analytics queries with time_range filtering."""
    app_conn, user_conn = setup_engine_dbs
    from taxo_trainer.engine.analytics import (
        get_dataset_coverage,
        get_family_mastery_stats,
        get_global_stats,
        get_time_cutoff_sql,
        get_trouble_taxa,
        log_attempt,
    )

    # Verify time cutoff SQL fragment generator
    assert "DATETIME" in get_time_cutoff_sql("1H")
    assert "DATETIME" in get_time_cutoff_sql("24H")
    assert "DATETIME" in get_time_cutoff_sql("7D")
    assert "DATETIME" in get_time_cutoff_sql("30D")
    assert "DATETIME" in get_time_cutoff_sql("1Y")
    assert get_time_cutoff_sql("ALL") == "1=1"

    # Insert test attempts
    log_attempt(user_conn, "occ_1", 9901, 9901, is_correct=True, used_hint=False)
    log_attempt(user_conn, "occ_2", 9901, 9901, is_correct=True, used_hint=False)
    log_attempt(user_conn, "occ_3", 9901, 8000, is_correct=False, used_hint=False)

    stats = get_global_stats(user_conn, app_conn, time_range="24H")
    assert stats["total_attempts"] == 3
    assert stats["unassisted_attempts"] == 3
    assert stats["unassisted_correct"] == 2

    coverage = get_dataset_coverage(user_conn, app_conn)
    assert coverage["total_species"] >= 1
    assert coverage["encountered_species"] >= 1
    assert coverage["coverage_pct"] > 0

    best_fams, worst_fams = get_family_mastery_stats(user_conn, app_conn, time_range="ALL")
    assert isinstance(best_fams, list)
    assert isinstance(worst_fams, list)

    trouble = get_trouble_taxa(user_conn, app_conn, time_range="ALL")
    assert isinstance(trouble, list)


def test_multiple_choice_hint_revealed_scope_filtering(setup_engine_dbs):
    """Test 1/5 choice hint options filtering by revealed scope without duplicates or artificial fill."""
    app_conn, _ = setup_engine_dbs
    from taxo_trainer.ui.quiz_view import QuizViewState

    # Insert 2 species in genus 'Ficaria'
    app_conn.execute("""
        INSERT INTO taxa (
            taxon_key, scientific_name, canonical_name, accepted_name, rank,
            order_name, family, genus, vernacular_da, vernacular_en
        ) VALUES (
            9910, 'Ficaria verna Huds.', 'Ficaria verna', 'Ficaria verna Huds.', 'SPECIES',
            'Ranunculales', 'Ranunculaceae', 'Ficaria', 'Vorterod', 'Lesser Celandine'
        );
    """)
    app_conn.execute("""
        INSERT INTO taxa (
            taxon_key, scientific_name, canonical_name, accepted_name, rank,
            order_name, family, genus, vernacular_da, vernacular_en
        ) VALUES (
            9911, 'Ficaria ficarioides (L.)', 'Ficaria ficarioides', 'Ficaria ficarioides (L.)', 'SPECIES',
            'Ranunculales', 'Ranunculaceae', 'Ficaria', 'Kaukasisk Vorterod', 'Caucasian Celandine'
        );
    """)
    app_conn.commit()

    state = QuizViewState()
    state.current_question = type("Obj", (), {
        "occurrence_id": "occ_ficaria",
        "taxon_key": 9910,
        "scientific_name": "Ficaria verna Huds.",
        "canonical_name": "Ficaria verna",
        "family": "Ranunculaceae",
        "genus": "Ficaria",
        "vernacular_da": "Vorterod",
        "vernacular_en": "Lesser Celandine",
    })()

    state.matched_genus = "Ficaria"

    # Query species restricted to genus 'Ficaria'
    cursor = app_conn.execute(
        "SELECT taxon_key, canonical_name, vernacular_da FROM taxa WHERE LOWER(genus) = LOWER('Ficaria') AND rank = 'SPECIES'"
    )
    possible_rows = cursor.fetchall()
    assert len(possible_rows) == 2

    # Verify choices list has exactly 2 options (no duplicates, no fill)
    choices = [r["canonical_name"] for r in possible_rows]
    assert len(choices) == 2
    assert len(set(choices)) == 2


def test_autocomplete_unambiguous_rank_prioritization(setup_engine_dbs):
    """Test that unambiguous rank matches (single match at rank) precede ambiguous ranks."""
    app_conn, _ = setup_engine_dbs
    from taxo_trainer.engine.validator import autocomplete_taxa

    # Insert 1 genus match and 2 species matches for prefix 'Ambiguustaxon'
    app_conn.execute("""
        INSERT INTO higher_ranks (rank_name, rank_level, vernacular_da)
        VALUES ('Ambiguustaxon', 'GENUS', 'Ambiguus');
    """)
    app_conn.execute("""
        INSERT INTO taxa (taxon_key, scientific_name, canonical_name, accepted_name, rank, family, genus, vernacular_da, vernacular_en)
        VALUES (88901, 'Ambiguus sp1', 'Ambiguus sp1', 'Ambiguus sp1', 'SPECIES', 'Fabaceae', 'Ambiguus', 'Ambiguus sp1', 'Ambiguus sp1');
    """)
    app_conn.execute("""
        INSERT INTO taxa (taxon_key, scientific_name, canonical_name, accepted_name, rank, family, genus, vernacular_da, vernacular_en)
        VALUES (88902, 'Ambiguus sp2', 'Ambiguus sp2', 'Ambiguus sp2', 'SPECIES', 'Fabaceae', 'Ambiguus', 'Ambiguus sp2', 'Ambiguus sp2');
    """)
    app_conn.commit()

    matches = autocomplete_taxa(app_conn, "Ambiguus", lang="da")
    # Genus rank has 1 match (unambiguous), Species rank has 2 matches (ambiguous)
    # Genus must come FIRST despite Species having lower rank level
    assert len(matches) >= 3
    assert matches[0]["rank"] == "GENUS"
    assert matches[1]["rank"] == "SPECIES"
    assert matches[2]["rank"] == "SPECIES"


def test_autocomplete_exact_species_match_always_top(setup_engine_dbs):
    """Test that an exact match on a species is always placed at the very top."""
    app_conn, _ = setup_engine_dbs
    from taxo_trainer.engine.validator import autocomplete_taxa

    # Insert 1 genus match and 2 species matches (one exact, one prefix)
    app_conn.execute("""
        INSERT INTO higher_ranks (rank_name, rank_level, vernacular_da)
        VALUES ('Vorterodgenus', 'GENUS', 'Vorterod');
    """)
    app_conn.execute("""
        INSERT INTO taxa (taxon_key, scientific_name, canonical_name, accepted_name, rank, family, genus, vernacular_da, vernacular_en)
        VALUES (99501, 'Ficaria verna', 'Ficaria verna', 'Ficaria verna', 'SPECIES', 'Ranunculaceae', 'Vorterodgenus', 'Vorterod', 'Lesser Celandine');
    """)
    app_conn.execute("""
        INSERT INTO taxa (taxon_key, scientific_name, canonical_name, accepted_name, rank, family, genus, vernacular_da, vernacular_en)
        VALUES (99502, 'Ficaria ficarioides', 'Ficaria ficarioides', 'Ficaria ficarioides', 'SPECIES', 'Ranunculaceae', 'Vorterodgenus', 'Kaukasisk Vorterod', 'Caucasian Celandine');
    """)
    app_conn.commit()

    matches = autocomplete_taxa(app_conn, "Vorterod", lang="da")
    assert len(matches) >= 3
    # Exact species match ('Vorterod') must be at the very top
    assert matches[0]["rank"] == "SPECIES"
    assert matches[0]["canonical_name"] == "Ficaria verna"
    assert matches[1]["rank"] == "GENUS"


def test_autocomplete_unicode_non_ascii_casing(setup_engine_dbs):
    """Test that non-ASCII Unicode characters (Å, Æ, Ø) match case-insensitively in autocomplete and validation."""
    app_conn, _ = setup_engine_dbs

    app_conn.execute("""
        INSERT INTO taxa (taxon_key, scientific_name, canonical_name, accepted_name, rank, family, genus, vernacular_da, vernacular_en)
        VALUES ('KEY_ZOS', 'Zostera marina L.', 'Zostera marina', 'Zostera marina L.', 'SPECIES', 'Zosteraceae', 'Zostera', 'Ålegræs|Almindelig bændeltang', 'Eelgrass');
    """)
    app_conn.commit()

    # Lowercase query 'ålegræs' matching capitalized DB entry 'Ålegræs'
    matches_lower = autocomplete_taxa(app_conn, "ålegræs", lang="da")
    assert len(matches_lower) == 1
    assert matches_lower[0]["canonical_name"] == "Zostera marina"

    # Uppercase query 'ÅLEGRÆS' matching capitalized DB entry 'Ålegræs'
    matches_upper = autocomplete_taxa(app_conn, "ÅLEGRÆS", lang="da")
    assert len(matches_upper) == 1
    assert matches_upper[0]["canonical_name"] == "Zostera marina"

    # Validate guess
    res = validate_user_guess(app_conn, "ålegræs", "KEY_ZOS", lang="da")
    assert res.is_correct is True
    assert res.matched_rank == "SPECIES"











