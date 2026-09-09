"""Exercise settings callbacks and restoration with freshly opened databases."""

import sqlite3

import pytest
from nicegui import ui

from taxo_trainer.db import init_app_db, init_user_db
from taxo_trainer.engine.sampling import SamplingFilter
from taxo_trainer.ui import quiz_view, settings_view


@pytest.fixture
def settings(tmp_path, monkeypatch):
    app_path = tmp_path / "app.db"
    conn = sqlite3.connect(app_path)
    conn.row_factory = sqlite3.Row
    init_app_db(conn)
    conn.executemany(
        "INSERT INTO taxa (taxon_key,scientific_name,canonical_name,accepted_name,rank,occurrence_count) VALUES (?, 'Fixture species', 'Fixture species', 'Fixture species', 'SPECIES', ?)",
        [("67S22", 1), ("75R3T", 10)],
    )
    conn.commit()
    user = sqlite3.connect(":memory:")
    user.row_factory = sqlite3.Row
    init_user_db(user)
    monkeypatch.setattr(settings_view, "get_db_connection", lambda *a: conn)
    monkeypatch.setattr(ui, "notify", lambda *a, **k: None)
    monkeypatch.setattr(ui.navigate, "reload", lambda: None)
    filters = SamplingFilter()
    changes = []
    with ui.column() as container:
        settings_view.render_settings_view(
            filters,
            lambda: changes.append((filters.mode, filters.min_count)),
            ui.dark_mode(),
        )
    yield conn, user, app_path, filters, container, changes
    container.delete()
    conn.close()
    user.close()


@pytest.mark.parametrize(
    "first_label", ["Minimum Occurrence Threshold", "Minimum Occurrence Cutoff (C_min)"]
)
def test_sampling_settings_sync_and_restore_after_reopening(
    settings, monkeypatch, first_label
):
    conn, user, path, filters, container, changes = settings
    elements = list(container.descendants())
    cutoffs = [
        e
        for e in elements
        if isinstance(e, ui.number)
        and e._props.get("label")
        in ("Minimum Occurrence Threshold", "Minimum Occurrence Cutoff (C_min)")
    ]
    first = next(e for e in cutoffs if e._props["label"] == first_label)
    mode = next(
        e for e in elements if isinstance(e, ui.radio) and "natural" in e.options
    )
    mode.set_value("natural")
    first.set_value(7)
    assert filters.mode == "natural"
    assert filters.min_count == 7
    assert [e.value for e in cutoffs] == [7, 7]
    assert changes == [("natural", 1), ("natural", 7)]
    assert any(
        isinstance(e, ui.chip) and e.text == "1 Active (1 Discarded)" for e in elements
    )
    assert any(
        isinstance(e, ui.label) and "fewer than 7 occurrences" in e.text
        for e in container.descendants()
    )
    assert dict(
        conn.execute(
            "SELECT key,val FROM app_metadata WHERE key IN ('min_count','sampling_mode')"
        )
    ) == {"min_count": "7", "sampling_mode": "natural"}

    # Restore through the production quiz initialization, using a new connection/state.
    reopened = sqlite3.connect(path)
    reopened.row_factory = sqlite3.Row
    monkeypatch.setattr(
        quiz_view,
        "get_db_connection",
        lambda p: reopened if p == quiz_view.APP_DB_PATH else user,
    )
    state = quiz_view.QuizViewState()
    with ui.column() as quiz_container:
        quiz_view.render_quiz_view(state, lambda *a: None)
    try:
        assert state.filters.mode == "natural"
        assert state.filters.min_count == 7
    finally:
        quiz_container.delete()
        reopened.close()


def test_sampling_mode_survives_clearing_dataset(settings):
    conn, _, _, _, container, _ = settings
    mode = next(
        e
        for e in container.descendants()
        if isinstance(e, ui.radio) and "natural" in e.options
    )
    mode.set_value("sqrt")
    button = next(
        e
        for e in container.descendants()
        if isinstance(e, ui.button) and e.text == "Clear Current Data Source"
    )
    listener = next(e for e in button._event_listeners.values() if e.type == "click")
    listener.handler(None)
    assert (
        conn.execute(
            "SELECT val FROM app_metadata WHERE key='sampling_mode'"
        ).fetchone()[0]
        == "sqrt"
    )


@pytest.mark.parametrize("invalid", [None, 0, 2.5])
def test_incomplete_or_invalid_cutoff_does_not_replace_saved_choice(settings, invalid):
    conn, _, _, filters, container, changes = settings
    cutoff = next(
        e
        for e in container.descendants()
        if isinstance(e, ui.number)
        and e._props.get("label") == "Minimum Occurrence Threshold"
    )
    cutoff.set_value(7)
    cutoff.set_value(invalid)
    assert filters.min_count == 7
    assert (
        conn.execute("SELECT val FROM app_metadata WHERE key='min_count'").fetchone()[0]
        == "7"
    )
    assert changes == [("log", 7)]
