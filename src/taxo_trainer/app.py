"""Main entry point for Modernized Taxonomic Recognition & Training Engine (taxo-trainer).

Launches local NiceGUI desktop application with reactive tabbed navigation.
Run via: uv run python -m taxo_trainer.app
"""

from nicegui import app, ui

from taxo_trainer.db import (
    get_app_metadata,
    get_db_connection,
    init_databases,
    set_app_metadata,
)
from taxo_trainer.ui.dashboard_view import render_dashboard_view
from taxo_trainer.ui.guides_view import GuidesViewState, render_guides_view
from taxo_trainer.ui.quiz_view import QuizViewState, render_quiz_view
from taxo_trainer.ui.settings_view import render_settings_view

app.add_static_files("/assets", "assets")


@ui.page("/")
def index_page() -> None:
    """Render main application page layout."""
    init_databases()
    quiz_state = QuizViewState()
    guides_state = GuidesViewState()

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

    ui.colors(primary="#2563eb", secondary="#4f46e5", accent="#f59e0b", dark="#111827")
    # Inject global CSS: reset nicegui-content padding + light-mode color remapping
    ui.add_head_html("""<style>
/* Reset NiceGUI default content padding */
.nicegui-content { padding: 0 !important; margin: 0 !important; }

/* Quasar q-img helper for object-contain */
.q-img.object-contain .q-img__image {
  object-fit: contain !important;
}

/* Base layout reset: zero margins edge-to-edge */
html, body, .q-layout, .q-page-container, .q-page {
  margin: 0 !important; padding: 0 !important;
  height: 100vh !important; width: 100vw !important;
  overflow: hidden !important;
}
body.body--dark, body.body--dark .q-layout,
body.body--dark .q-page-container, body.body--dark .q-page,
body.body--dark .nicegui-content {
  background-color: #030712 !important;
}

/* ══════════════════════════════════════════════════════════════ */
/*  LIGHT MODE — comprehensive color remapping                  */
/*  Quasar adds body--light / body--dark to <body>.             */
/*  Our UI uses hardcoded dark Tailwind classes; these rules     */
/*  remap them when light mode is active.                       */
/* ══════════════════════════════════════════════════════════════ */

/* ── Root & layout backgrounds ─────────────────────────────── */
body.body--light { background-color: #f8fafc !important; color: #1e293b !important; }
body.body--light .q-layout,
body.body--light .q-page-container,
body.body--light .q-page,
body.body--light .nicegui-content { background-color: #f8fafc !important; }

/* ── Tailwind backgrounds ──────────────────────────────────── */
/* Triple specificity (body.body--light.body--light) to beat      */
/* Tailwind v4 JIT which generates styles AFTER this stylesheet. */
body.body--light.body--light .bg-gray-950  { background-color: #f8fafc !important; }
body.body--light.body--light .bg-gray-900  { background-color: #f1f5f9 !important; }
body.body--light.body--light .bg-gray-800  { background-color: #e2e8f0 !important; }
body.body--light.body--light .bg-gray-700  { background-color: #cbd5e1 !important; }
body.body--light.body--light .bg-black     { background-color: #e2e8f0 !important; }

/* ── Tailwind text ─────────────────────────────────────────── */
body.body--light.body--light .text-white    { color: #000000 !important; }
body.body--light .text-gray-200 { color: #334155 !important; }
body.body--light .text-gray-300 { color: #475569 !important; }
body.body--light .text-gray-400 { color: #64748b !important; }
body.body--light .text-gray-500 { color: #78716c !important; }
body.body--light .text-gray-600 { color: #475569 !important; }

/* Accent text: shift bright-on-dark → rich-on-light */
body.body--light .text-yellow-200 { color: #92400e !important; }
body.body--light .text-yellow-300 { color: #b45309 !important; }
body.body--light .text-yellow-400 { color: #d97706 !important; }
body.body--light .text-green-200  { color: #166534 !important; }
body.body--light .text-green-300  { color: #16a34a !important; }
body.body--light .text-green-400  { color: #15803d !important; }
body.body--light .text-amber-400  { color: #d97706 !important; }
body.body--light .text-amber-500  { color: #b45309 !important; }
body.body--light .text-red-200    { color: #991b1b !important; }
body.body--light .text-red-300    { color: #dc2626 !important; }
body.body--light .text-red-400    { color: #b91c1c !important; }
body.body--light .text-blue-400   { color: #2563eb !important; }
body.body--light .text-purple-400 { color: #7c3aed !important; }

/* ── Tailwind borders ──────────────────────────────────────── */
body.body--light .border-gray-700  { border-color: #cbd5e1 !important; }
body.body--light .border-gray-800  { border-color: #e2e8f0 !important; }
body.body--light .border-green-700 { border-color: #86efac !important; }
body.body--light .border-green-500 { border-color: #22c55e !important; }
body.body--light .border-red-800   { border-color: #fca5a5 !important; }
body.body--light .border-red-600   { border-color: #ef4444 !important; }
body.body--light .border-yellow-700 { border-color: #fcd34d !important; }
body.body--light .border-yellow-500 { border-color: #f59e0b !important; }
body.body--light .border-amber-500  { border-color: #f59e0b !important; }
body.body--light .border-blue-500   { border-color: #3b82f6 !important; }
body.body--light .border-purple-500 { border-color: #8b5cf6 !important; }

/* ── Feedback / status card backgrounds ────────────────────── */
body.body--light .bg-green-950  { background-color: #f0fdf4 !important; }
body.body--light .bg-green-900  { background-color: #dcfce7 !important; }
body.body--light .bg-red-950    { background-color: #fef2f2 !important; }
body.body--light .bg-red-900    { background-color: #fee2e2 !important; }
body.body--light .bg-yellow-950 { background-color: #fefce8 !important; }
body.body--light .bg-yellow-900 { background-color: #fef9c3 !important; }
body.body--light .bg-blue-900   { background-color: #eff6ff !important; }

/* ── Shadows: softer on light backgrounds ──────────────────── */
body.body--light .shadow-md  { box-shadow: 0 4px 6px -1px rgba(0,0,0,0.08), 0 2px 4px -2px rgba(0,0,0,0.05) !important; }
body.body--light .shadow-xl  { box-shadow: 0 20px 25px -5px rgba(0,0,0,0.08), 0 8px 10px -6px rgba(0,0,0,0.04) !important; }
body.body--light .shadow-2xl { box-shadow: 0 25px 50px -12px rgba(0,0,0,0.1) !important; }

/* ══════════════════════════════════════════════════════════════ */
/*  Quasar component overrides for light mode                   */
/* ══════════════════════════════════════════════════════════════ */

/* Tabs */
body.body--light .q-tab { color: #475569 !important; }
body.body--light .q-tab--active { color: #1e293b !important; }
body.body--light .q-tab__indicator { background-color: #2563eb !important; }

/* Cards — override Quasar's dark card styling */
body.body--light .q-card { background-color: #ffffff !important; color: #1e293b !important; }
body.body--light .q-card--dark { background-color: #ffffff !important; color: #1e293b !important; }

/* Expansion panels */
body.body--light .q-expansion-item { color: #1e293b !important; }
body.body--light .q-expansion-item__container { background-color: #f1f5f9 !important; }
body.body--light .q-item__label { color: #1e293b !important; }

/* Radio buttons & labels */
body.body--light .q-radio__label { color: #1e293b !important; }
body.body--light .q-radio__inner { color: #2563eb !important; }

/* Toggle / switch labels */
body.body--light .q-toggle__label { color: #1e293b !important; }

/* Input fields & selects — subtle gray background to distinguish from card */
body.body--light .q-field--outlined .q-field__control {
  background-color: #f1f5f9 !important;
  border-color: #cbd5e1 !important;
}
body.body--light .q-field__native,
body.body--light .q-field__prefix,
body.body--light .q-field__suffix,
body.body--light .q-field__input { color: #1e293b !important; }
body.body--light .q-field__label { color: #64748b !important; }
body.body--light .q-field--dark .q-field__control {
  background-color: #f1f5f9 !important;
  border-color: #cbd5e1 !important;
}
body.body--light .q-field--dark .q-field__native { color: #1e293b !important; }
body.body--light .q-field--dark .q-field__label { color: #64748b !important; }

/* Menu / dropdown popups */
body.body--light .q-menu { background-color: #ffffff !important; color: #1e293b !important; }
body.body--light .q-item { color: #1e293b !important; }
body.body--light .q-item--active { background-color: #e2e8f0 !important; }

/* Chips */
body.body--light .q-chip--dark { background-color: #e2e8f0 !important; color: #1e293b !important; }

/* Buttons — ensure flat/text buttons are readable */
body.body--light .q-btn--flat { color: #1e293b !important; }

/* Separators */
body.body--light .q-separator { background-color: #cbd5e1 !important; }
body.body--light .bg-gray-700.q-separator,
body.body--light hr.bg-gray-700 { background-color: #cbd5e1 !important; }

/* Notifications / toast */
body.body--light .q-notification { color: #1e293b !important; }

/* Number input spinners */
body.body--light .q-field__append .q-icon { color: #64748b !important; }

/* Progress bars */
body.body--light .q-linear-progress__track { background-color: #e2e8f0 !important; }

/* ── Quasar tables with dark prop ─────────────────────────── */
body.body--light .q-table--dark,
body.body--light .q-table--dark .q-table__top,
body.body--light .q-table--dark .q-table__bottom,
body.body--light .q-table--dark thead,
body.body--light .q-table--dark tbody,
body.body--light .q-table--dark tr,
body.body--light .q-table--dark th,
body.body--light .q-table--dark td {
  background-color: #f8fafc !important;
  color: #1e293b !important;
  border-color: #e2e8f0 !important;
}
body.body--light .q-table--dark thead th {
  background-color: #e2e8f0 !important;
  color: #334155 !important;
  font-weight: 600;
}
body.body--light .q-table--dark tbody tr:nth-child(even) {
  background-color: #f1f5f9 !important;
}
body.body--light .q-table--dark tbody tr:hover {
  background-color: #e2e8f0 !important;
}
</style>""")
    ui.query(".q-tab-panel").style(
        "padding: 0 !important; height: 100%; overflow: auto;"
    )


    with ui.column().classes(
        "w-full h-screen overflow-hidden bg-gray-950 text-white p-0 space-y-0 no-wrap flex flex-col"
    ):
        # Header bar cleanly aligned
        with ui.row().classes(
            "w-full bg-gray-900 text-white shadow-md px-6 py-0 flex justify-between items-center h-[48px] flex-none z-20 border-b border-gray-800"
        ):
            with ui.row().classes("items-center gap-3"):
                ui.icon("nature_people", size="md").classes("text-green-400")
                ui.label("Taxo-Trainer").classes(
                    "text-xl font-bold tracking-wide text-black dark:!bg-gray-900/80 dark:!text-white"
                )

            saved_tab = get_app_metadata("active_tab", "quiz", conn=app_conn)

            with ui.tabs(value=saved_tab).classes("text-white").props("inline-label") as tabs:
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

            tabs.on_value_change(on_tab_change)

        # Tab panels filling remaining vertical height edge-to-edge
        with ui.tab_panels(tabs, value=saved_tab).classes(
            "w-full flex-1 min-h-0 bg-gray-950 text-white p-0 overflow-hidden flex flex-col"
        ):
            with ui.tab_panel("quiz").classes(
                "w-full h-full p-0 flex flex-col overflow-hidden flex-1 min-h-0"
            ):
                render_quiz_view(state=quiz_state, on_navigate_tab=navigate_to_tab)

            with ui.tab_panel("dashboard").classes("w-full h-full p-4 overflow-y-auto"):
                render_dashboard_view()

            with ui.tab_panel("guides").classes("w-full h-full p-4 overflow-y-auto"):
                render_guides_view(state=guides_state, on_navigate_tab=navigate_to_tab)

            with ui.tab_panel("settings").classes(
                "w-full h-full p-4 overflow-y-auto"
            ):
                render_settings_view(
                    active_filters=quiz_state.filters,
                    on_filters_changed=lambda: None,
                    dark_mode=dark_mode,
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
