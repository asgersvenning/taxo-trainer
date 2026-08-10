"""Unit tests for taxo-trainer core sampling, validator, and analytics engine."""

import sqlite3

import numpy as np
import pytest

from src.db import init_app_db, init_user_db
from src.engine.analytics import get_confusion_matrix, get_global_stats, log_attempt
from src.engine.sampling import (
    SamplingFilter,
    compute_weights,
    sample_stage1_taxon,
    sample_stage2_observation,
)
from src.engine.validator import (
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

