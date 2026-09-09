"""Exercise dashboard scope actions and settings against real quiz state."""

import sqlite3

import pytest
from nicegui import ui

from taxo_trainer.db import init_app_db, init_user_db
from taxo_trainer.engine.sampling import SamplingFilter, sample_stage1_taxon
from taxo_trainer.ui import quiz_view


@pytest.fixture
def quiz(monkeypatch):
    app = sqlite3.connect(':memory:')
    user = sqlite3.connect(':memory:')
    for conn in (app, user):
        conn.row_factory = sqlite3.Row
    init_app_db(app)
    init_user_db(user)
    for key in ('A1', 'B2'):
        app.execute("""INSERT INTO taxa(taxon_key,scientific_name,canonical_name,accepted_name,rank,
            genus,genus_key,family,family_key,order_name,order_key,occurrence_count)
            VALUES(?,?,?,?,'SPECIES','Example','G1','Family','F1','Order','O1',10)""",
            (key, 'Example '+key, 'Example '+key, 'Example '+key))
        app.execute("INSERT INTO occurrences(occurrence_id,taxon_key,media_urls) VALUES(?,?,?)", (key, key, 'https://photo.example/a.jpg'))
    for key, name, rank in [('G1','Example','GENUS'),('F1','Family','FAMILY'),('O1','Order','ORDER')]:
        app.execute("INSERT INTO higher_ranks(taxon_key,rank_name,rank_level) VALUES(?,?,?)", (key,name,rank))
    app.commit()
    monkeypatch.setattr(quiz_view, 'get_db_connection', lambda path: user if path == quiz_view.USER_DB_PATH else app)
    state = quiz_view.QuizViewState()
    with ui.column() as container:
        controller = quiz_view.render_quiz_view(state)
    yield app, user, state, controller, container
    container.delete()
    app.close()
    user.close()


def test_temporary_practice_and_return_preserve_normal_filters(quiz):
    app, _, state, controller, container = quiz
    state.filters.include_taxa = ['B2']
    state.filters.exclude_taxa = ['A1']
    assert controller.practise(['A1'])
    assert state.current_question.taxon_key == 'A1'
    assert state.filters.include_taxa == ['B2']
    assert state.filters.exclude_taxa == ['A1']
    assert state.practice_taxa == ['A1']
    button = next(e for e in container.descendants() if isinstance(e, ui.button) and e.text == 'Return to previous practice')
    next(e for e in button._event_listeners.values() if e.type == 'click').handler(None)
    assert state.practice_taxa == []
    assert state.current_question.taxon_key == 'B2'
    assert app.execute("SELECT val FROM app_metadata WHERE key LIKE 'whitelist_ids_%'").fetchone() is None


def test_settings_refresh_preserves_question_and_its_answer_eligibility(quiz):
    app, user, state, controller, container = quiz
    question = state.current_question
    state.draft_guess = 'Exam'
    state.filters.min_count = 100
    state.filters.language = 'en'
    controller.refresh()
    assert state.current_question is question
    assert any(isinstance(e, ui.input) and e.value == 'Exam' for e in container.descendants())
    assert any(isinstance(e, ui.label) and e.text == 'Training changes apply to your next observation.' for e in container.descendants())
    quiz_view.submit_guess(state, app, user, 'default', str(question.taxon_key))
    assert state.success_recorded


def test_unavailable_practice_does_not_replace_current_question(quiz):
    _, _, state, controller, _ = quiz
    question = state.current_question
    assert not controller.practise(['missing-ID'])
    assert state.current_question is question
    assert state.practice_taxa == []


def test_order_scope_uses_canonical_ids(quiz):
    app, _, _, _, _ = quiz
    assert sample_stage1_taxon(app, SamplingFilter(include_taxa=['O1'])) in ('A1', 'B2')
    assert sample_stage1_taxon(app, SamplingFilter(exclude_taxa=['O1'])) is None
