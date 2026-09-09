"""Keep dashboard summaries, trends, names, and refresh behavior consistent."""

import json
import sqlite3

import pytest
from nicegui import ui

from taxo_trainer.db import init_app_db, init_user_db, set_app_metadata
from taxo_trainer.engine.analytics import (
    get_accuracy_over_time,
    get_confusion_matrix,
    get_global_stats,
    get_rank_mastery_stats,
    get_trouble_taxa,
    log_attempt,
)
from taxo_trainer.ui import dashboard_view


@pytest.fixture
def history():
    app = sqlite3.connect(':memory:')
    user = sqlite3.connect(':memory:')
    for conn in (app, user):
        conn.row_factory = sqlite3.Row
    init_app_db(app)
    init_user_db(user)
    for key, name, english in [('A1', 'Species alpha', 'English alpha'), ('B2', 'Species beta', 'English beta')]:
        app.execute("INSERT INTO taxa (taxon_key, scientific_name, canonical_name, accepted_name, rank, family_key, family, vernacular_da, vernacular_en, vernacular_json) VALUES (?, ?, ?, ?, 'SPECIES', 'F1', 'Family example', 'Danish name', ?, ?)", (key, name, name, name, english, json.dumps({'en': english})))
    app.commit()
    yield app, user
    app.close()
    user.close()


def add_attempts(app, user):
    for correct, hinted in [(True, False), (True, True), (False, False), (False, True)]:
        log_attempt(user, 'photo', 'A1', 'A1' if correct else 'B2', correct, hinted, app_conn=app)


def test_rank_and_trend_use_same_unassisted_attempts_as_summary(history):
    app, user = history
    add_attempts(app, user)
    summary = get_global_stats(user, app)
    best, _ = get_rank_mastery_stats(user, app, rank_level='SPECIES')
    trend = get_accuracy_over_time(user, app, window_size=1)
    assert summary['unassisted_attempts'] == best[0].total_attempts == len(trend) == 2
    assert summary['unassisted_correct'] == best[0].correct_attempts == 1
    assert [p.ema_accuracy for p in trend] == [100.0, 0.0]
    assert get_trouble_taxa(user, app)[0].accuracy_pct == 50.0


def test_dashboard_names_follow_language_without_changing_ids(history):
    app, user = history
    add_attempts(app, user)
    best, _ = get_rank_mastery_stats(user, app, rank_level='SPECIES', language='en')
    assert (best[0].taxon_key, best[0].display_name) == ('A1', 'English alpha')
    pair = get_confusion_matrix(user, app, language='en')[0]
    assert (pair.target_taxon_key, pair.target_display, pair.guessed_display) == ('A1', 'English alpha', 'English beta')
    assert get_trouble_taxa(user, app, language='en')[0].display_name == 'English alpha'


def test_dashboard_empty_accuracy_and_refresh(history, monkeypatch):
    app, user = history
    monkeypatch.setattr(dashboard_view, 'get_db_connection', lambda path: user if path == dashboard_view.USER_DB_PATH else app)
    with ui.column() as container:
        refresh = dashboard_view.render_dashboard_view()
    try:
        labels = [e.text for e in container.descendants() if isinstance(e, ui.label)]
        assert '—' in labels
        assert 'No unassisted attempts in this period' in labels
        add_attempts(app, user)
        set_app_metadata('language_preference', 'en', conn=app)
        refresh()
        labels = [e.text for e in container.descendants() if isinstance(e, ui.label)]
        assert '50.0%' in labels
        rank_select = next(e for e in container.descendants() if isinstance(e, ui.select) and 'SPECIES' in e.options)
        rank_select.set_value('SPECIES')
        rows = [r for e in container.descendants() if isinstance(e, ui.table) for r in e.rows]
        assert any(r.get('taxon_key') == 'A1' and r['display_name'] == 'English alpha' for r in rows)
        assert not any(isinstance(e, ui.label) and e.text.startswith('Trouble Taxa') for e in container.descendants())
    finally:
        container.delete()
