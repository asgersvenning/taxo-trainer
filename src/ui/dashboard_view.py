"""Analytics and confusion matrix dashboard view for taxo-trainer.

Renders user accuracy metrics, time-windowed stats, mastery breakdown, trouble taxa, and confusion matrix.
"""

from nicegui import ui

from src.db import APP_DB_PATH, USER_DB_PATH, get_db_connection
from src.engine.analytics import (
    get_confusion_matrix,
    get_dataset_coverage,
    get_family_mastery_stats,
    get_global_stats,
    get_trouble_taxa,
)


def render_dashboard_view() -> None:
    """Render user analytics dashboard with time-range filtering and rich mastery stats."""
    app_conn = get_db_connection(APP_DB_PATH)
    user_conn = get_db_connection(USER_DB_PATH)

    selected_range = ["ALL"]

    container = ui.column().classes("w-full max-w-6xl mx-auto p-4 space-y-6 text-white")

    with container:
        # Header & Time Filter Bar
        with ui.card().classes("w-full bg-gray-800 p-4 rounded-lg shadow-md border border-gray-700"), ui.row().classes("w-full justify-between items-center flex-wrap gap-3"):
            with ui.column().classes("gap-0"):
                ui.label("Analytics & Mastery Dashboard").classes("text-2xl font-bold text-primary")
                ui.label("Track your species identification progress, streaks, and taxonomic mastery over time.").classes("text-xs text-gray-400")

            # Time Range Filter Buttons
            with ui.row().classes("items-center gap-1.5 bg-gray-900 p-1.5 rounded-lg border border-gray-700"):
                    ui.label("Time Range:").classes("text-xs font-bold text-gray-400 mr-1")

                    ranges = [
                        ("1H", "Past Hour"),
                        ("24H", "24 Hours"),
                        ("7D", "7 Days"),
                        ("30D", "30 Days"),
                        ("1Y", "Past Year"),
                        ("ALL", "All Time"),
                    ]

                    btn_widgets = {}

                    def set_range(val: str) -> None:
                        selected_range[0] = val
                        for key, btn in btn_widgets.items():
                            if key == val:
                                btn.props("color=primary").classes("font-bold")
                            else:
                                btn.props("color=secondary").classes("font-normal")
                        refresh_dashboard()

                    for key, label_text in ranges:
                        b = ui.button(
                            label_text,
                            on_click=lambda k=key: set_range(k),
                        ).props("dense size=sm " + ("color=primary" if key == "ALL" else "color=secondary")).classes("text-xs px-2.5")
                        btn_widgets[key] = b

        # Dynamic Content Container
        content_container = ui.column().classes("w-full space-y-6")

        def refresh_dashboard() -> None:
            content_container.clear()
            r_val = selected_range[0]

            stats = get_global_stats(user_conn, app_conn, time_range=r_val)
            coverage = get_dataset_coverage(user_conn, app_conn)
            best_fams, worst_fams = get_family_mastery_stats(user_conn, app_conn, time_range=r_val, limit=4)
            trouble_taxa = get_trouble_taxa(user_conn, app_conn, time_range=r_val, limit=5)
            confusion = get_confusion_matrix(user_conn, app_conn, time_range=r_val, limit=10)

            with content_container:
                # 1. Summary Metrics Cards Grid (4 Cards)
                with ui.row().classes("w-full gap-4 justify-between flex-wrap"):
                    with ui.card().classes("flex-1 min-w-[200px] bg-gray-800 p-4 rounded-lg shadow-md border-l-4 border-blue-500 text-center"):
                        ui.label("Total Attempts").classes("text-xs text-gray-400 font-semibold uppercase")
                        ui.label(str(stats["total_attempts"])).classes("text-3xl font-bold mt-1 text-white")
                        ui.label(f"Filter: {r_val}").classes("text-[10px] text-gray-500 mt-1")

                    with ui.card().classes("flex-1 min-w-[200px] bg-gray-800 p-4 rounded-lg shadow-md border-l-4 border-green-500 text-center"):
                        ui.label("Unassisted Accuracy").classes("text-xs text-gray-400 font-semibold uppercase")
                        ui.label(f"{stats['unassisted_accuracy_pct']}%").classes("text-3xl font-bold mt-1 text-green-400")
                        ui.label(f"({stats['unassisted_correct']} / {stats['unassisted_attempts']} unassisted)").classes("text-[10px] text-gray-400 mt-1")

                    with ui.card().classes("flex-1 min-w-[200px] bg-gray-800 p-4 rounded-lg shadow-md border-l-4 border-amber-500 text-center"):
                        ui.label("Active / Best Streak").classes("text-xs text-gray-400 font-semibold uppercase")
                        with ui.row().classes("justify-center items-center gap-2 mt-1"):
                            ui.label(f"🔥 {stats['current_streak']}").classes("text-2xl font-bold text-amber-400")
                            ui.label("|").classes("text-gray-600")
                            ui.label(f"🏆 {stats['best_streak']}").classes("text-2xl font-bold text-yellow-300")
                        ui.label("Current streak | All-time record").classes("text-[10px] text-gray-400 mt-1")

                    with ui.card().classes("flex-1 min-w-[200px] bg-gray-800 p-4 rounded-lg shadow-md border-l-4 border-purple-500 text-center"):
                        ui.label("Mastered Species").classes("text-xs text-gray-400 font-semibold uppercase")
                        ui.label(str(stats["mastered_species_count"])).classes("text-3xl font-bold mt-1 text-purple-400")
                        ui.label("≥90% accuracy over ≥5 attempts").classes("text-[10px] text-gray-400 mt-1")

                # 2. Dataset Species Coverage Meter
                with ui.card().classes("w-full bg-gray-800 p-4 rounded-lg shadow-md border border-gray-700"):
                    with ui.row().classes("w-full justify-between items-center mb-1"):
                        ui.label("Dataset Species Coverage").classes("text-xs font-bold text-gray-300 uppercase tracking-wider")
                        ui.label(f"{coverage['encountered_species']} / {coverage['total_species']} species encountered ({coverage['coverage_pct']}%)").classes("text-xs font-bold text-blue-400")
                    ui.linear_progress(value=coverage["coverage_pct"] / 100.0, show_value=False).props("color=primary stripe rounded").classes("h-2.5 w-full")

                # 3. Family Mastery Breakdown Grid (Top Mastered vs Struggling Families)
                with ui.row().classes("w-full gap-4 justify-between flex-wrap"):
                    # Best Performing Families
                    with ui.card().classes("flex-1 min-w-[320px] bg-gray-800 p-4 rounded-lg shadow-md border border-gray-700 space-y-2"):
                        with ui.row().classes("items-center gap-2"):
                            ui.icon("verified", color="green-400").classes("text-base")
                            ui.label("Top Mastered Plant Families").classes("text-sm font-bold text-green-400")
                        if not best_fams:
                            ui.label("No family attempts recorded yet.").classes("text-xs text-gray-500 italic py-2")
                        else:
                            with ui.column().classes("w-full gap-1.5"):
                                for f in best_fams:
                                    with ui.row().classes("w-full justify-between items-center bg-gray-900 px-3 py-1.5 rounded border border-gray-800"):
                                        ui.label(f.display_name).classes("text-xs font-medium text-white truncate max-w-[200px]")
                                        ui.label(f"{f.accuracy_pct}% ({f.correct_attempts}/{f.total_attempts})").classes("text-xs font-bold text-green-400")

                    # Struggling Families
                    with ui.card().classes("flex-1 min-w-[320px] bg-gray-800 p-4 rounded-lg shadow-md border border-gray-700 space-y-2"):
                        with ui.row().classes("items-center gap-2"):
                            ui.icon("warning", color="amber-400").classes("text-base")
                            ui.label("Families Needing Practice").classes("text-sm font-bold text-amber-400")
                        if not worst_fams:
                            ui.label("No weak family patterns identified yet!").classes("text-xs text-gray-500 italic py-2")
                        else:
                            with ui.column().classes("w-full gap-1.5"):
                                for f in worst_fams:
                                    with ui.row().classes("w-full justify-between items-center bg-gray-900 px-3 py-1.5 rounded border border-gray-800"):
                                        ui.label(f.display_name).classes("text-xs font-medium text-white truncate max-w-[200px]")
                                        ui.label(f"{f.accuracy_pct}% ({f.correct_attempts}/{f.total_attempts})").classes("text-xs font-bold text-amber-400")

                # 4. Trouble Taxa List Card
                if trouble_taxa:
                    with ui.card().classes("w-full bg-gray-800 p-4 rounded-lg shadow-md border border-gray-700 space-y-2"):
                        with ui.row().classes("items-center gap-2"):
                            ui.icon("priority_high", color="red-400").classes("text-base")
                            ui.label("Trouble Taxa (Lowest Accuracy Species)").classes("text-sm font-bold text-red-400")

                        t_columns = [
                            {"name": "species", "label": "Species", "field": "display_name", "align": "left"},
                            {"name": "canonical", "label": "Scientific Name", "field": "canonical_name", "align": "left"},
                            {"name": "family", "label": "Family", "field": "family", "align": "left"},
                            {"name": "accuracy", "label": "Accuracy", "field": "acc_str", "align": "center"},
                        ]
                        t_rows = [
                            {
                                "display_name": tt.display_name,
                                "canonical_name": tt.canonical_name,
                                "family": tt.family,
                                "acc_str": f"{tt.accuracy_pct}% ({tt.correct_attempts}/{tt.total_attempts})",
                            }
                            for tt in trouble_taxa
                        ]
                        ui.table(columns=t_columns, rows=t_rows, row_key="canonical_name").classes("w-full bg-gray-900 text-white rounded-md").props("dark flat bordered dense")

                # 5. Pairwise Lookalikes (Confusion Matrix) Table Card
                with ui.card().classes("w-full bg-gray-800 p-5 rounded-lg shadow-md border border-gray-700 space-y-2"):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("compare_arrows", color="yellow-400").classes("text-base")
                        ui.label("Top Taxonomic Lookalikes (Confusion Matrix)").classes("text-sm font-bold text-yellow-300")
                    ui.label("Pairwise misidentifications logged during quiz attempts.").classes("text-xs text-gray-400 mb-2")

                    if not confusion:
                        ui.label("No misidentifications recorded in this time period. Keep practicing!").classes("text-xs text-gray-500 italic py-4 text-center w-full")
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
                        ui.table(columns=columns, rows=rows, row_key="target_canonical").classes("w-full bg-gray-900 text-white rounded-md").props("dark flat bordered dense")

        # Initial dashboard load
        refresh_dashboard()
