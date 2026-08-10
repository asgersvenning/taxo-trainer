"""Analytics and confusion matrix dashboard view for taxo-trainer.

Renders user accuracy metrics, mastery stats, and pairwise misidentification lookalikes.
"""


from nicegui import ui

from src.db import APP_DB_PATH, USER_DB_PATH, get_db_connection
from src.engine.analytics import get_confusion_matrix, get_global_stats


def render_dashboard_view() -> None:
    """Render user analytics dashboard and taxonomic confusion matrix."""
    app_conn = get_db_connection(APP_DB_PATH)
    user_conn = get_db_connection(USER_DB_PATH)

    stats = get_global_stats(user_conn, app_conn)
    confusion = get_confusion_matrix(user_conn, app_conn, limit=10)

    container = ui.column().classes("w-full max-w-5xl mx-auto p-4 spacing-y-6 text-white")

    with container:
        ui.label("Analytics & Mastery Dashboard").classes("text-2xl font-bold mb-4 text-primary")

        # Metric summary cards grid
        with ui.row().classes("w-full gap-4 justify-between"):
            with ui.card().classes("flex-1 bg-gray-800 p-4 rounded-lg shadow-md border-l-4 border-blue-500 text-center"):
                ui.label("Total Attempts").classes("text-xs text-gray-400 font-semibold uppercase")
                ui.label(str(stats["total_attempts"])).classes("text-3xl font-bold mt-1 text-white")

            with ui.card().classes("flex-1 bg-gray-800 p-4 rounded-lg shadow-md border-l-4 border-green-500 text-center"):
                ui.label("Unassisted Accuracy").classes("text-xs text-gray-400 font-semibold uppercase")
                ui.label(f"{stats['unassisted_accuracy_pct']}%").classes("text-3xl font-bold mt-1 text-green-400")
                ui.label(f"({stats['unassisted_correct']} / {stats['unassisted_attempts']} questions)").classes("text-xs text-gray-500 mt-1")

            with ui.card().classes("flex-1 bg-gray-800 p-4 rounded-lg shadow-md border-l-4 border-yellow-500 text-center"):
                ui.label("Mastered Species").classes("text-xs text-gray-400 font-semibold uppercase")
                ui.label(str(stats["mastered_species_count"])).classes("text-3xl font-bold mt-1 text-yellow-400")
                ui.label("≥90% accuracy over ≥5 attempts").classes("text-xs text-gray-500 mt-1")

        # Confusion Matrix Table Card
        with ui.card().classes("w-full bg-gray-800 p-6 rounded-lg shadow-md mt-6"):
            ui.label("Top Taxonomic Lookalikes (Confusion Matrix)").classes("text-lg font-bold text-yellow-300 mb-2")
            ui.label("Pairwise misidentifications logged during quiz attempts.").classes("text-xs text-gray-400 mb-4")

            if not confusion:
                ui.label("No misidentifications recorded yet. Keep practicing!").classes("text-sm text-gray-500 italic py-6 text-center w-full")
            else:
                columns = [
                    {"name": "target", "label": "Target Species", "field": "target_display", "align": "left"},
                    {"name": "target_sci", "label": "Scientific Name", "field": "target_canonical", "align": "left"},
                    {"name": "guessed", "label": "Mistaken For", "field": "guessed_display", "align": "left"},
                    {"name": "guessed_sci", "label": "Guessed Scientific", "field": "guessed_canonical", "align": "left"},
                    {"name": "count", "label": "Frequency", "field": "count", "align": "center"},
                ]
                rows = [
                    {
                        "target_display": c.target_display,
                        "target_canonical": c.target_canonical,
                        "guessed_display": c.guessed_display,
                        "guessed_canonical": c.guessed_canonical,
                        "count": f"{c.count} time(s)",
                    }
                    for c in confusion
                ]
                ui.table(columns=columns, rows=rows, row_key="target_canonical").classes("w-full bg-gray-900 text-white rounded-md").props("dark flat bordered")
