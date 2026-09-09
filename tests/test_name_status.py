"""Language-aware name coverage and nontechnical lookup feedback."""

import sqlite3

import pytest

from taxo_trainer.db import init_app_db
from taxo_trainer.ingestion.taxonomy_builder import GBIFRequestError
from taxo_trainer.ui.name_status import (
    name_coverage_summary,
    name_lookup_failure_message,
)


@pytest.fixture
def names_db():
    """Dataset with names in different languages and incomplete name data."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_app_db(conn)
    conn.executemany(
        """INSERT INTO taxa (taxon_key, scientific_name, canonical_name, accepted_name,
           rank, vernacular_da, vernacular_en, vernacular_json)
           VALUES (?, 'Species name', 'Species name', 'Species name', ?, ?, ?, ?)""",
        [
            ("1", "SPECIES", "Dansk navn", None, '{"de":"Deutscher Name"}'),
            ("2", "SPECIES", None, "English name", '{"fr":"Nom français"}'),
            ("3", "SPECIES", " ", None, '{"de":" | ","en":"English JSON name"}'),
            ("4", "SPECIES", None, None, '[]'),
            ("5", "GENUS", None, None, '{"de":"Gattung"}'),
        ],
    )
    conn.commit()
    yield conn
    conn.close()


@pytest.mark.parametrize("language,label,named", [("da", "Danish", 1), ("de", "German", 1), ("en", "English", 2), ("fr", "French", 1), ("sv", "Swedish", 0)])
def test_coverage_counts_selected_language_without_fallback(names_db, language, label, named):
    summary = name_coverage_summary(names_db, language)
    assert f"{label} names available for {named} of 4 species" in summary
    assert f"{4 - named} still without" in summary
    assert "continue training" in summary


def test_scientific_mode_does_not_present_missing_vernaculars_as_problem(names_db):
    summary = name_coverage_summary(names_db, "la")
    assert "Scientific names are selected" in summary
    assert "optional" in summary
    assert "without" not in summary


def test_empty_dataset_explains_next_action(names_db):
    names_db.execute("DELETE FROM taxa")
    assert name_coverage_summary(names_db, "de") == "Import a dataset to look up species names."


def test_failure_feedback_keeps_diagnostics_out_of_user_message():
    message = name_lookup_failure_message(GBIFRequestError("HTTP 429 cached endpoint detail", retry_after_seconds=120))
    assert "about 2 minutes" in message
    assert "Names already saved are kept" in message
    assert "429" not in message
    assert "cached" not in message
    assert "SQLite" not in name_lookup_failure_message(RuntimeError("SQLite error"))


def test_language_selection_persists_and_refreshes_summary(names_db, monkeypatch):
    from nicegui import ui

    from taxo_trainer.engine.sampling import SamplingFilter
    from taxo_trainer.ui import settings_view

    monkeypatch.setattr(settings_view, "get_db_connection", lambda *a: names_db)
    monkeypatch.setattr(ui, "notify", lambda *a, **k: None)
    filters = SamplingFilter(language="da")
    with ui.column() as container:
        settings_view.render_settings_view(filters, lambda: None, ui.dark_mode())
    try:
        elements = list(container.descendants())
        selector = next(element for element in elements if isinstance(element, ui.select) and element._props.get("label") == "Primary Display Language")
        selector.set_value("de")
        assert filters.language == "de"
        assert names_db.execute("SELECT val FROM app_metadata WHERE key='language_preference'").fetchone()[0] == "de"
        assert any(isinstance(element, ui.label) and "German names available for 1 of 4 species" in element.text for element in elements)
    finally:
        container.delete()
