"""Main entry point for Modernized Taxonomic Recognition & Training Engine (taxo-trainer).

Launches local NiceGUI desktop application with reactive tabbed navigation.
Run via: uv run python -m src.app
"""

from nicegui import ui

from src.db import init_databases
from src.ui.dashboard_view import render_dashboard_view
from src.ui.quiz_view import QuizViewState, render_quiz_view
from src.ui.settings_view import render_settings_view


@ui.page("/")
def index_page() -> None:
    """Render main application page layout."""
    init_databases()
    quiz_state = QuizViewState()

    ui.colors(primary="#2563eb", secondary="#4f46e5", accent="#f59e0b", dark="#111827")
    ui.query("body").style("height: 100vh; overflow: hidden; margin: 0; padding: 0;")
    ui.query(".q-page-container").style("height: 100vh; overflow: hidden; padding: 0 !important;")
    ui.query(".q-tab-panel").style("padding: 0 !important; overflow: hidden; height: 100%;")

    with ui.column().classes("w-full h-screen overflow-hidden bg-gray-950 text-white p-0 space-y-0 no-wrap flex flex-col"):
        # Header bar in normal flex flow
        with ui.row().classes("w-full bg-gray-900 text-white shadow-md px-6 py-2 flex justify-between items-center h-[54px] flex-none z-20 border-b border-gray-800"):
            with ui.row().classes("items-center gap-3"):
                ui.icon("nature_people", size="md").classes("text-green-400")
                ui.label("Taxo-Trainer").classes("text-xl font-bold tracking-wide text-white")
                ui.label("Species Identification Engine").classes("text-xs text-gray-400 font-medium self-end mb-1")

            with ui.tabs().classes("text-white") as tabs:
                quiz_tab = ui.tab("Quiz", icon="quiz")
                dash_tab = ui.tab("Dashboard", icon="insights")
                settings_tab = ui.tab("Settings & Data", icon="settings")

        # Tab panels filling remaining vertical height
        with ui.tab_panels(tabs, value=quiz_tab).classes("w-full flex-1 min-h-0 bg-gray-950 text-white p-0 overflow-hidden flex flex-col"):
            with ui.tab_panel(quiz_tab).classes("w-full h-full p-2 flex flex-col overflow-hidden flex-1 min-h-0"):
                render_quiz_view(quiz_state)

            with ui.tab_panel(dash_tab).classes("w-full h-full p-4 overflow-y-auto"):
                render_dashboard_view()

            with ui.tab_panel(settings_tab).classes("w-full h-full p-4 overflow-y-auto"):
                render_settings_view(
                    quiz_state.filters,
                    on_filters_changed=lambda: None,
                )


def main() -> None:
    """Initialize application database schemas and start NiceGUI server."""
    init_databases()
    ui.run(
        title="Taxo-Trainer",
        host="127.0.0.1",
        port=8080,
        show=False,
        reload=False,
    )


if __name__ in {"__main__", "__mp_main__"}:
    main()

