"""Settings, sampling controls, and dataset ingestion view for taxo-trainer.

Provides user controls for Stage 1 weight transformation modes, cutoffs,
taxonomic filters, and DwC occurrence.txt file ingestion.
"""

import sqlite3
from collections.abc import Callable
from pathlib import Path

from nicegui import run, ui

from taxo_trainer.db import (
    APP_DB_PATH,
    DATA_DIR,
    get_app_metadata,
    get_db_connection,
    set_app_metadata,
)
from taxo_trainer.engine.sampling import SamplingFilter
from taxo_trainer.ingestion.dwc_parser import ingest_dwc_file
from taxo_trainer.ingestion.taxonomy_builder import (
    enrich_vernacular_names_from_gbif,
    rebuild_indices,
)
from taxo_trainer.ui.components import render_taxa_filter_controls


def get_path_suggestions(input_str: str, limit: int = 8) -> list[tuple[str, str, bool]]:
    """Return autocomplete suggestions for filesystem path typing.

    Returns list of tuples: (full_path_str, display_label, is_dir)
    """
    if not input_str:
        return []
    try:
        raw_path = Path(input_str)
        if input_str.endswith(("/", "\\")):
            parent = raw_path
            prefix = ""
        else:
            parent = raw_path.parent
            prefix = raw_path.name.lower()
        if not parent.exists() or not parent.is_dir():
            return []
        suggestions: list[tuple[str, str, bool]] = []
        for child in parent.iterdir():
            if child.name.startswith("."):
                continue
            if prefix and not child.name.lower().startswith(prefix):
                continue
            is_dir = child.is_dir()
            if is_dir or child.suffix.lower() in (
                ".txt",
                ".tsv",
                ".csv",
                ".dwca",
                ".zip",
            ):
                display = f"📁 {child.name}/" if is_dir else f"📄 {child.name}"
                full_path = str(child) + ("/" if is_dir else "")
                suggestions.append((full_path, display, is_dir))
        suggestions.sort(key=lambda x: (not x[2], x[1].lower()))
        return suggestions[:limit]
    except (OSError, PermissionError, ValueError):
        return []


def render_settings_view(
    active_filters: SamplingFilter,
    on_filters_changed: Callable[[], None],
    dark_mode: ui.dark_mode,
) -> None:
    """Render application settings, sampling controls, and dataset ingestion view.

    Args:
        active_filters: Active SamplingFilter configuration instance.
        on_filters_changed: Callback to notify quiz view when filters change.
    """
    app_conn = get_db_connection(APP_DB_PATH)

    # Query active dataset metadata & stats
    active_path = get_app_metadata(
        "active_dwc_path", str(DATA_DIR / "datasets" / "."), conn=app_conn
    )
    taxa_cnt = app_conn.execute("SELECT COUNT(*) FROM taxa;").fetchone()[0]
    occ_cnt = app_conn.execute("SELECT COUNT(*) FROM occurrences;").fetchone()[0]
    da_cnt = app_conn.execute(
        "SELECT COUNT(*) FROM taxa WHERE vernacular_da IS NOT NULL AND vernacular_da != '';"
    ).fetchone()[0]

    # Query distinct families for dropdown
    fam_cursor = app_conn.execute(
        "SELECT DISTINCT family FROM taxa WHERE family != '' ORDER BY family;"
    )
    families = ["All Families"] + [r["family"] for r in fam_cursor.fetchall()]

    container = ui.column().classes(
        "w-full max-w-5xl mx-auto p-4 spacing-y-6 text-white"
    )

    with container:
        ui.label("Settings & Data Controls").classes(
            "text-2xl font-bold mb-4 text-primary"
        )

        # 0. Active Data Source & Dataset Stats Card
        with ui.card().classes(
            "w-full bg-gray-900 border border-yellow-500/40 p-5 rounded-lg shadow-lg mb-6"
        ):
            with ui.row().classes(
                "w-full justify-between items-center flex-wrap gap-2 mb-2"
            ):
                ui.label("Current Active Data Source").classes(
                    "text-xs font-bold text-yellow-400 uppercase tracking-wider"
                )
                pct_da = int(da_cnt / taxa_cnt * 100) if taxa_cnt else 0
                ui.label(
                    f"Danish Vernacular Names: {da_cnt:,} / {taxa_cnt:,} ({pct_da}%)"
                ).classes("text-xs text-green-400 font-semibold")

            ui.label(f"📁 {active_path}").classes(
                "text-sm font-mono !text-black dark:!text-white break-all mb-3 bg-gray-800 p-2 rounded border border-gray-700"
            )

            with ui.row().classes(
                "gap-3 text-xs flex-wrap items-center justify-between w-full mt-1"
            ):
                with ui.row().classes("gap-3 text-xs flex-wrap"):
                    ui.chip(
                        f"{taxa_cnt:,} Taxa Registered",
                        icon="diversity_3",
                        color="indigo",
                    ).props("dense dark")
                    ui.chip(
                        f"{occ_cnt:,} Occurrences Loaded",
                        icon="photo_library",
                        color="teal",
                    ).props("dense dark")
                    ui.chip(
                        f"{da_cnt:,} Danish Names", icon="translate", color="green"
                    ).props("dense dark")

                def clear_data_source() -> None:
                    try:
                        with app_conn:
                            app_conn.execute("DELETE FROM occurrences;")
                            app_conn.execute("DELETE FROM taxa;")
                            app_conn.execute("DELETE FROM app_metadata;")
                        rebuild_indices(app_conn)
                        ui.notify(
                            "Data source cleared successfully. Database reset.",
                            type="warning",
                        )
                        on_filters_changed()
                    except (sqlite3.Error, OSError) as ex:
                        ui.notify(f"Clear Error: {ex}", type="negative")

                ui.button(
                    "Clear Current Data Source",
                    color="negative",
                    icon="delete_forever",
                    on_click=clear_data_source,
                ).props("outline dense").classes("text-xs")

        # 1. Preferred Vernacular Language Card
        with ui.card().classes("w-full bg-gray-800 p-6 rounded-lg shadow-md mb-6"):
            ui.label("Preferred Display Language").classes(
                "text-lg font-bold text-yellow-300 mb-2"
            )
            ui.label(
                "Select display language preference for species vernacular names. Entering names in ANY supported language will validate as correct."
            ).classes("text-xs text-gray-400 mb-4")

            lang_options = {
                "da": "🇩🇰 Danish (Dansk) [Default]",
                "en": "🇬🇧 English",
                "de": "🇩🇪 German (Deutsch)",
                "sv": "🇸🇪 Swedish (Svenska)",
                "no": "🇳🇴 Norwegian (Norsk)",
                "fi": "🇫🇮 Finnish (Suomi)",
                "pl": "🇵🇱 Polish (Polski)",
                "cs": "🇨🇿 Czech (Čeština)",
                "fr": "🇫🇷 French (Français)",
                "es": "🇪🇸 Spanish (Español)",
                "it": "🇮🇹 Italian (Italiano)",
                "pt": "🇵🇹 Portuguese (Português)",
                "nl": "🇳🇱 Dutch (Nederlands)",
                "la": "🏛️ Scientific Binomial (Latin)",
            }

            lang_select = (
                ui.select(
                    options=lang_options,
                    value=active_filters.language
                    if active_filters.language in lang_options
                    else "da",
                    label="Primary Display Language",
                )
                .classes("w-72 text-white")
                .props("outlined dark")
            )

            def update_language(val: str) -> None:
                active_filters.language = val
                on_filters_changed()
                ui.notify(
                    f"Display language set to {lang_options.get(val, val)}", type="info"
                )

            lang_select.on_value_change(lambda e: update_language(e.value))

        # 1.5 Theme & Appearance Card
        with ui.card().classes("w-full bg-gray-800 p-6 rounded-lg shadow-md mb-6"):
            ui.label("Theme & Appearance").classes(
                "text-lg font-bold text-yellow-300 mb-2"
            )
            ui.label(
                "Select UI color mode. System Default (Auto) automatically matches your operating system theme."
            ).classes("text-xs text-gray-400 mb-4")

            theme_options = {
                "auto": "🌗 System Default (Auto)",
                "dark": "🌙 Dark Mode",
                "light": "☀️ Light Mode",
            }

            curr_theme = get_app_metadata("theme_preference", "auto", conn=app_conn)

            theme_select = (
                ui.select(
                    options=theme_options,
                    value=curr_theme if curr_theme in theme_options else "auto",
                    label="Theme Preference",
                )
                .classes("w-72 text-white")
                .props("outlined dark")
            )

            def update_theme(val: str) -> None:
                set_app_metadata("theme_preference", val, conn=app_conn)
                if dark_mode:
                    if val == "dark":
                        dark_mode.enable()
                    elif val == "light":
                        dark_mode.disable()
                    else:
                        dark_mode.auto()
                ui.notify(
                    f"Theme preference set to {theme_options.get(val, val)}",
                    type="info",
                )

            theme_select.on_value_change(lambda e: update_theme(e.value))
        with ui.card().classes("w-full bg-gray-800 p-6 rounded-lg shadow-md mb-6"):
            ui.label("DarwinCore (DwC) Occurrence Ingestion").classes(
                "text-lg font-bold text-yellow-300 mb-2"
            )
            ui.label(
                "Ingest DarwinCore .zip (ZIP-file) or occurrence.txt (TSV) file into SQLite database app_data.db."
            ).classes("text-xs text-gray-400 mb-4")

            dwc_path_input = (
                ui.input(
                    label="Path to DarwinCore .zip or occurrence.txt",
                    value=active_path,
                )
                .classes("w-full text-white mb-1")
                .props("outlined dark dense clearable")
            )

            # Filesystem Prefix-Matching Autocomplete Suggestions Box
            path_suggestions_box = ui.row().classes(
                "w-full gap-1 hidden flex-wrap max-h-32 overflow-y-auto mb-4 bg-gray-900 p-2 rounded border border-gray-700"
            )

            def update_path_autocomplete(e) -> None:
                txt = e.value or ""
                suggs = get_path_suggestions(txt)
                path_suggestions_box.clear()
                if suggs:
                    path_suggestions_box.classes(remove="hidden")
                    with path_suggestions_box:
                        for p_full, p_label, is_dir in suggs:
                            ui.button(
                                p_label,
                                on_click=lambda target_p=p_full: (
                                    dwc_path_input.set_value(target_p)
                                ),
                            ).props(
                                "outline dense color="
                                + ("warning" if is_dir else "primary")
                            ).classes("text-xs py-0 px-2")
                else:
                    path_suggestions_box.classes(add="hidden")

            path_input_element = dwc_path_input
            path_input_element.on_value_change(update_path_autocomplete)

            status_label = ui.label("Ready for ingestion.").classes(
                "text-sm text-gray-300 font-semibold mb-3"
            )

            def run_ingestion() -> None:
                target_file = Path(dwc_path_input.value.strip())
                if not target_file.exists():
                    status_label.set_text(f"File not found: {target_file}")
                    ui.notify("DwC file not found!", type="negative")
                    return

                status_label.set_text(
                    "Ingesting DarwinCore TSV stream into app_data.db..."
                )
                ui.notify("Started ingestion batch process...", type="info")

                try:
                    occ_cnt, taxa_cnt = ingest_dwc_file(
                        target_file,
                        db_path=APP_DB_PATH,
                        progress_callback=lambda count: status_label.set_text(
                            f"Ingested {count} occurrences..."
                        ),
                    )
                    rebuild_indices()
                    status_label.set_text(
                        f"Complete! Ingested {occ_cnt} occurrences across {taxa_cnt} taxa."
                    )
                    ui.notify(
                        f"Ingestion successful ({occ_cnt} records).", type="positive"
                    )
                    on_filters_changed()
                except (sqlite3.Error, OSError, ValueError, RuntimeError) as ex:
                    status_label.set_text(f"Ingestion Error: {ex}")
                    ui.notify(f"Ingestion failed: {ex}", type="negative")

            ui.button(
                "Start Ingestion", color="primary", on_click=run_ingestion
            ).classes("px-6")

        # 3. Vernacular Name Enrichment Engine Card
        with ui.card().classes("w-full bg-gray-800 p-6 rounded-lg shadow-md mb-6"):
            ui.label("GBIF Vernacular Name Enrichment").classes(
                "text-lg font-bold text-yellow-300 mb-2"
            )
            ui.label(
                "Query GBIF Species API (api.gbif.org) to auto-fill missing Danish & English vernacular names with 1-week persistent disk caching."
                "\nOBS: Reload page after running this step."
            ).classes("text-xs text-gray-400 mb-4")

            enrich_status = ui.label("Ready for GBIF API enrichment.").classes(
                "text-sm text-gray-300 font-semibold mb-3"
            )
            progress_bar = ui.linear_progress(value=0.0).classes("w-full mb-4 hidden")

            async def run_enrichment() -> None:
                enrich_button.disable()
                progress_bar.set_value(0.0)
                progress_bar.classes(remove="hidden")
                enrich_status.set_text(
                    "Fetching Danish vernacular names from GBIF Species API..."
                )
                ui.notify(
                    "Starting GBIF API enrichment in background thread...", type="info"
                )

                def sync_worker() -> int:
                    def update_progress(curr: int, tot: int) -> None:
                        pct = curr / tot if tot > 0 else 1.0
                        progress_bar.set_value(round(pct, 4))
                        enrich_status.set_text(f"Checked {curr}/{tot} taxa...")

                    return enrich_vernacular_names_from_gbif(
                        progress_callback=update_progress
                    )

                try:
                    updated = await run.io_bound(sync_worker)
                    progress_bar.set_value(1.0)
                    enrich_status.set_text(
                        f"Enrichment Complete! Updated {updated} species with Danish/English vernacular names."
                    )
                    ui.notify(
                        f"Enriched {updated} species names from GBIF!", type="positive"
                    )
                    on_filters_changed()
                except (sqlite3.Error, OSError, RuntimeError, ValueError) as ex:
                    enrich_status.set_text(f"Enrichment Error: {ex}")
                    ui.notify(f"Enrichment failed: {ex}", type="negative")
                finally:
                    enrich_button.enable()

            enrich_button = ui.button(
                "Fetch Danish Names from GBIF API",
                color="secondary",
                on_click=run_enrichment,
            ).classes("px-6")

        # 4. Advanced Features Dropdown (Hidden by default at bottom of page)
        exp = ui.expansion(
            "Advanced Features", icon="settings_suggest", value=False
        ).classes(
            "w-full bg-gray-800 rounded-lg shadow-md border border-gray-700 text-yellow-300 font-bold mb-6"
        )
        with exp, ui.column().classes("w-full p-4 space-y-6 text-white"):
            # Stage 1 Sampling Mode & Cutoffs Card
            with ui.card().classes(
                "w-full bg-gray-900 p-6 rounded-lg border border-gray-700"
            ):
                ui.label("Stage 1 Sampling & Probability Weights").classes(
                    "text-lg font-bold text-yellow-300 mb-2"
                )

                ui.label(
                    "Control how species are selected during quiz questions."
                ).classes("text-xs text-gray-400 mb-4")

                with ui.row().classes("w-full gap-6 flex-wrap items-center"):
                    mode_radio = (
                        ui.radio(
                            options={
                                "flat": "Flat (Equal 1.0 probability)",
                                "natural": "Natural (Raw occurrence count)",
                                "log": "Log Transformed (log(1 + count)) [Recommended]",
                                "sqrt": "Square-Root Transformed (sqrt(count))",
                            },
                            value=active_filters.mode,
                        )
                        .props("dark")
                        .classes("text-white")
                    )

                    def update_mode(val: str) -> None:
                        active_filters.mode = val
                        on_filters_changed()
                        ui.notify(f"Sampling mode set to '{val}'", type="positive")

                    mode_radio.on_value_change(lambda e: update_mode(e.value))

                with ui.row().classes("w-full gap-6 mt-4 items-center"):
                    cutoff_input = (
                        ui.number(
                            label="Minimum Occurrence Cutoff (C_min)",
                            value=active_filters.min_count,
                            min=1,
                            step=1,
                        )
                        .classes("w-64 text-white")
                        .props("outlined dark")
                    )

                    def update_cutoff(val: int) -> None:
                        if val is not None and val >= 1:
                            active_filters.min_count = int(val)
                            on_filters_changed()
                            ui.notify(f"Minimum cutoff set to {val}", type="positive")

                    cutoff_input.on_value_change(lambda e: update_cutoff(e.value))

            # Taxonomic Scope & Filters Card
            with ui.card().classes(
                "w-full bg-gray-900 p-6 rounded-lg border border-gray-700"
            ):
                ui.label("Taxonomic Scope & Practice Filters").classes(
                    "text-lg font-bold text-yellow-300 mb-2"
                )

                with ui.row().classes("w-full gap-4 items-center flex-wrap"):
                    family_select = (
                        ui.select(
                            options=families,
                            value=active_filters.family or "All Families",
                            label="Filter by Family",
                        )
                        .classes("w-64 text-white")
                        .props("outlined dark")
                    )

                    def update_family(val: str) -> None:
                        active_filters.family = None if val == "All Families" else val
                        on_filters_changed()
                        ui.notify(f"Family filter updated: {val}", type="info")

                    family_select.on_value_change(lambda e: update_family(e.value))

                    misidentified_toggle = ui.switch(
                        "Practice Misidentified Photos Only",
                        value=active_filters.misidentified_only,
                    ).classes("text-white font-medium ml-4")

                    def update_misidentified(val: bool) -> None:
                        active_filters.misidentified_only = val
                        on_filters_changed()
                        ui.notify(
                            f"Misidentified practice mode: {'ON' if val else 'OFF'}",
                            type="info",
                        )

                    misidentified_toggle.on_value_change(
                        lambda e: update_misidentified(e.value)
                    )

                ui.separator().classes("bg-gray-700 my-4")

                render_taxa_filter_controls(
                    app_conn,
                    active_filters,
                    on_changed=on_filters_changed,
                )
