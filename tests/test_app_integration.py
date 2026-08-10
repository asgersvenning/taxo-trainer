"""Full end-to-end integration tests for taxo-trainer pipeline."""

import sqlite3

from src.db import init_user_db
from src.engine.analytics import get_global_stats, log_attempt
from src.engine.sampling import SamplingFilter, sample_next_question
from src.engine.validator import validate_user_guess
from src.ingestion.dwc_parser import ingest_dwc_file
from src.ui.quiz_view import QuizViewState


def test_full_pipeline_integration(tmp_path):
    """Test full pipeline: TSV ingestion -> Two-stage sampling -> Guess validation -> Analytics update."""
    # 1. Create sample DwC file
    tsv_file = tmp_path / "occurrence.txt"
    tsv_content = (
        "gbifID\tacceptedTaxonKey\tscientificName\tcanonicalName\tdecimalLatitude\tdecimalLongitude\tlocality\teventDate\tmonth\tassociatedMedia\tfamily\tgenus\tvernacularName\n"
        "101\t2435140\tQuercus robur L.\tQuercus robur\t55.67\t12.56\tCopenhagen\t2023-06-10\t6\thttp://example.com/q1.jpg\tFagaceae\tQuercus\tStilk-Eg\n"
        "102\t2865545\tFagus sylvatica L.\tFagus sylvatica\t56.00\t12.00\tNorth Zealand\t2023-05-01\t5\thttp://example.com/f1.jpg\tFagaceae\tFagus\tAlmindelig Bøg\n"
    )
    tsv_file.write_text(tsv_content, encoding="utf-8")

    app_db = tmp_path / "app_data.db"
    user_db = tmp_path / "user_data.db"

    # Ingest
    ingest_dwc_file(tsv_file, db_path=app_db)

    app_conn = sqlite3.connect(str(app_db))
    app_conn.row_factory = sqlite3.Row

    user_conn = sqlite3.connect(str(user_db))
    user_conn.row_factory = sqlite3.Row
    init_user_db(user_conn)

    # 2. Sample question
    filters = SamplingFilter(mode="flat", min_count=1)
    seen_set = set()
    obs = sample_next_question(app_conn, user_conn, filters, seen_set)

    assert obs is not None
    assert str(obs.taxon_key) in ("2435140", "2865545")

    # 3. Validate guess
    val_res = validate_user_guess(app_conn, obs.canonical_name, obs.taxon_key)
    assert val_res.is_correct is True

    # 4. Log attempt
    log_attempt(user_conn, obs.occurrence_id, obs.taxon_key, val_res.matched_taxon_key, is_correct=True, used_hint=False)

    # 5. Check stats
    stats = get_global_stats(user_conn, app_conn)
    assert stats["total_attempts"] == 1
    assert stats["unassisted_accuracy_pct"] == 100.0

    # 6. Test QuizViewState
    state = QuizViewState()
    assert state.filters.mode == "log"
    assert state.used_hint is False

    app_conn.close()
    user_conn.close()
