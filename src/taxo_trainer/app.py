"""Main entry point for Modernized Taxonomic Recognition & Training Engine (taxo-trainer).

Launches local NiceGUI desktop application with reactive tabbed navigation.
Run via: uv run python -m taxo_trainer.app
"""

import argparse
import logging

from nicegui import app, background_tasks, run, ui

from taxo_trainer.db import (
    get_app_metadata,
    get_db_connection,
    init_databases,
    set_app_metadata,
)
from taxo_trainer.resources import get_resource_path, is_frozen, is_native_gui_available
from taxo_trainer.ui.dashboard_view import render_dashboard_view
from taxo_trainer.ui.guides_view import GuidesViewState, render_guides_view
from taxo_trainer.ui.quiz_view import QuizViewState, render_quiz_view
from taxo_trainer.ui.settings_view import render_settings_view
from taxo_trainer.ui.theme import install_theme


async def repair_taxonomy_in_background() -> None:
    """Restore missing imported hierarchy links without delaying quiz use."""
    from taxo_trainer.ingestion.taxonomy_builder import repair_missing_taxonomy

    try:
        await run.io_bound(repair_missing_taxonomy)
    except Exception:
        logging.getLogger(__name__).exception("Taxonomy link repair did not finish; retry on next launch")


def start_taxonomy_repair() -> None:
    """Schedule ID-only taxonomy maintenance after launch or an import reload."""
    background_tasks.create(repair_taxonomy_in_background())


app.add_static_files("/assets", str(get_resource_path("assets")))


@ui.page("/")
def index_page() -> None:
    """Render main application page layout."""
    init_databases()
    start_taxonomy_repair()
    quiz_state = QuizViewState()
    guides_state = GuidesViewState()
    refresh_dashboard = None
    refresh_settings = None

    # Dark mode configuration (defaults to system preference "auto")
    app_conn = get_db_connection()
    theme_pref = get_app_metadata("theme_preference", "auto", conn=app_conn)
    dark_mode = ui.dark_mode()
    if theme_pref == "dark":
        dark_mode.enable()
    elif theme_pref == "light":
        dark_mode.disable()
    else:
        dark_mode.auto()

    install_theme(get_app_metadata("theme_accent", "blue", conn=app_conn),
                  get_app_metadata("surface_theme", "standard", conn=app_conn))
    ui.query(".q-tab-panel").style(
        "padding: 0 !important; height: 100%; overflow: auto;"
    )


    with ui.column().classes(
        "w-full h-screen overflow-hidden bg-tt-page text-tt-main p-0 space-y-0 no-wrap flex flex-col"
    ):
        # Header bar cleanly aligned
        with ui.row().classes(
            "w-full bg-tt-surface text-tt-main shadow-md px-6 py-0 flex justify-between items-center h-[48px] flex-none z-20 border-b border-tt-border"
        ):
            with ui.row().classes("items-center gap-3"):
                ui.icon("nature_people", size="md").classes("text-tt-positive")
                ui.label("Taxo-Trainer").classes(
                    "text-xl font-bold tracking-wide text-tt-main"
                )

            saved_tab = get_app_metadata("active_tab", "quiz", conn=app_conn)

            with ui.tabs(value=saved_tab).classes("text-tt-main").props("inline-label") as tabs:
                ui.tab("quiz", label="Quiz", icon="quiz")
                ui.tab("dashboard", label="Dashboard", icon="insights")
                ui.tab("guides", label="Guides", icon="menu_book")
                ui.tab("settings", label="Settings & Data", icon="settings")

            def navigate_to_tab(tab_name: str, guide_id: str | None = None) -> None:
                tabs.value = tab_name
                if guide_id:
                    guides_state.select_guide(guide_id)
                conn = get_db_connection()
                set_app_metadata("active_tab", tab_name, conn=conn)
                conn.close()

            def on_tab_change(e) -> None:
                if e.value:
                    conn = get_db_connection()
                    set_app_metadata("active_tab", str(e.value), conn=conn)
                    conn.close()
                    if e.value == "dashboard" and refresh_dashboard:
                        refresh_dashboard()
                    if e.value == "settings" and refresh_settings:
                        refresh_settings()

            tabs.on_value_change(on_tab_change)

        # Tab panels filling remaining vertical height edge-to-edge
        with ui.tab_panels(tabs, value=saved_tab).classes(
            "w-full flex-1 min-h-0 bg-tt-page text-tt-main p-0 overflow-hidden flex flex-col"
        ):
            with ui.tab_panel("quiz").classes(
                "w-full h-full p-0 flex flex-col overflow-hidden flex-1 min-h-0"
            ):
                quiz_controller = render_quiz_view(
                    state=quiz_state, on_navigate_tab=navigate_to_tab,
                    is_active=lambda: tabs.value == "quiz",
                )

            with ui.tab_panel("dashboard").classes("w-full h-full p-4 overflow-y-auto"):
                def practise_from_dashboard(keys: list[str]) -> None:
                    if quiz_controller.practise(keys):
                        navigate_to_tab("quiz")

                refresh_dashboard = render_dashboard_view(on_practise=practise_from_dashboard)

            with ui.tab_panel("guides").classes("w-full h-full p-4 overflow-y-auto"):
                render_guides_view(state=guides_state, on_navigate_tab=navigate_to_tab)

            with ui.tab_panel("settings").classes(
                "w-full h-full p-4 overflow-y-auto"
            ):
                refresh_settings = render_settings_view(
                    active_filters=quiz_state.filters,
                    on_filters_changed=quiz_controller.refresh,
                    dark_mode=dark_mode,
                )



def main() -> None:
    """Initialize application database schemas and start Taxo-Trainer."""
    init_databases()

    parser = argparse.ArgumentParser(description="Taxo-Trainer Desktop Application")
    parser.add_argument(
        "--native",
        action="store_true",
        default=is_frozen(),
        help="Force launch inside native window frame",
    )
    parser.add_argument(
        "--browser",
        action="store_true",
        help="Force launch in web browser mode",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reloading development server",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host IP address")
    parser.add_argument("--port", type=int, default=8080, help="Port number")

    args, _ = parser.parse_known_args()

    gui_available = is_native_gui_available()
    use_native = (args.native or is_frozen()) and not args.browser and gui_available
    frozen_mode = is_frozen()

    if args.native and not gui_available and not frozen_mode:
        print(
            "Native window framing requested, but native GUI extensions (GTK/Qt) "
            "are not available on this system. Running in web browser mode..."
        )

    if use_native:
        try:
            ui.run(
                title="Taxo-Trainer",
                host=args.host,
                port=args.port,
                native=True,
                window_size=(1280, 820),
                fullscreen=False,
                show=not frozen_mode,
                reload=False,
            )
            return
        except Exception as err:  # noqa: BLE001
            print(
                f"Native window framing unavailable ({err}); falling back to browser mode..."
            )

    ui.run(
        title="Taxo-Trainer",
        host=args.host,
        port=args.port,
        show=True,
        reload=args.reload,
    )


if __name__ in {"__main__", "__mp_main__"}:
    main()
