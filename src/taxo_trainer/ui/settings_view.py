"""Settings, sampling controls, and dataset ingestion view for taxo-trainer.

Provides user controls for Stage 1 weight transformation modes, cutoffs,
taxonomic filters, and DwC occurrence.txt file ingestion.
"""

import asyncio
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
    default_dataset_zip = DATA_DIR / "datasets" / "danske_planter_2026.zip"
    default_path_str = (
        str(default_dataset_zip)
        if default_dataset_zip.exists()
        else str(DATA_DIR / "datasets" / "")
    )
    taxa_cnt = app_conn.execute("SELECT COUNT(*) FROM taxa;").fetchone()[0]
    occ_cnt = app_conn.execute("SELECT COUNT(*) FROM occurrences;").fetchone()[0]
    da_cnt = app_conn.execute(
        "SELECT COUNT(*) FROM taxa WHERE vernacular_da IS NOT NULL AND vernacular_da != '';"
    ).fetchone()[0]

    saved_dwc_path = get_app_metadata("active_dwc_path", "", conn=app_conn)
    ingest_input_path = saved_dwc_path if saved_dwc_path else default_path_str

    if taxa_cnt > 0:
        active_path = saved_dwc_path if saved_dwc_path else default_path_str
    else:
        active_path = "None (No dataset ingested. Ingest a DarwinCore file below to get started)"


    # Query discarded vs active taxa based on active min_count cutoff
    min_cutoff = active_filters.min_count
    active_taxa_cnt = app_conn.execute(
        "SELECT COUNT(*) FROM taxa WHERE occurrence_count >= ?;", (min_cutoff,)
    ).fetchone()[0]
    discarded_taxa_cnt = taxa_cnt - active_taxa_cnt

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
                        f"{active_taxa_cnt:,} Active ({discarded_taxa_cnt:,} Discarded)",
                        icon="filter_alt",
                        color="amber",
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
                        # Preserve user preferences (theme, language, min_count, active_tab) across dataset clearing
                        theme_pref = get_app_metadata("theme_preference", conn=app_conn)
                        lang_pref = get_app_metadata("language_preference", conn=app_conn)
                        min_pref = get_app_metadata("min_count", conn=app_conn)
                        tab_pref = get_app_metadata("active_tab", conn=app_conn)

                        with app_conn:
                            app_conn.execute("DELETE FROM occurrences;")
                            app_conn.execute("DELETE FROM taxa;")
                            try:
                                app_conn.execute("DELETE FROM higher_ranks;")
                            except sqlite3.OperationalError:
                                pass
                            app_conn.execute("DELETE FROM app_metadata;")

                            # Restore preserved user settings into app_metadata
                            if theme_pref:
                                app_conn.execute(
                                    "INSERT OR REPLACE INTO app_metadata (key, val) VALUES ('theme_preference', ?);",
                                    (theme_pref,),
                                )
                            if lang_pref:
                                app_conn.execute(
                                    "INSERT OR REPLACE INTO app_metadata (key, val) VALUES ('language_preference', ?);",
                                    (lang_pref,),
                                )
                            if min_pref:
                                app_conn.execute(
                                    "INSERT OR REPLACE INTO app_metadata (key, val) VALUES ('min_count', ?);",
                                    (min_pref,),
                                )
                            if tab_pref:
                                app_conn.execute(
                                    "INSERT OR REPLACE INTO app_metadata (key, val) VALUES ('active_tab', ?);",
                                    (tab_pref,),
                                )

                        rebuild_indices(app_conn)
                        ui.notify(
                            "Data source cleared successfully. Database reset.",
                            type="warning",
                        )
                        on_filters_changed()
                        ui.navigate.reload()
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

        # 1.2 Minimum Occurrences per Taxon Card
        with ui.card().classes("w-full bg-gray-800 p-6 rounded-lg shadow-md mb-6"):
            ui.label("Minimum Occurrences per Taxon").classes(
                "text-lg font-bold text-yellow-300 mb-2"
            )
            ui.label(
                "Set the minimum occurrence limit per taxon used in the quiz. Taxa with fewer occurrences than this threshold are omitted from quiz sampling, autocomplete suggestions, and input interpolation to filter out spurious/rare taxa."
            ).classes("text-xs text-gray-400 mb-4")

            with ui.column().classes("w-full space-y-3"):
                with ui.row().classes("w-full gap-4 items-center flex-wrap"):
                    cutoff_input_main = (
                        ui.number(
                            label="Minimum Occurrence Threshold",
                            value=active_filters.min_count,
                            min=1,
                            step=1,
                        )
                        .classes("w-72 text-white")
                        .props("outlined dark")
                    )

                stats_row = ui.row().classes("gap-3 text-xs flex-wrap items-center mt-1")

                def refresh_cutoff_stats(mc: int) -> None:
                    stats_row.clear()
                    act_c = app_conn.execute(
                        "SELECT COUNT(*) FROM taxa WHERE occurrence_count >= ?;", (mc,)
                    ).fetchone()[0]
                    disc_c = taxa_cnt - act_c
                    pct_act = (act_c / taxa_cnt * 100) if taxa_cnt else 0
                    pct_disc = (disc_c / taxa_cnt * 100) if taxa_cnt else 0

                    with stats_row:
                        ui.chip(
                            f"✓ {act_c:,} Taxa Retained ({pct_act:.1f}%)",
                            icon="check_circle",
                            color="positive",
                        ).props("dense dark")
                        ui.chip(
                            f"🚫 {disc_c:,} Taxa Discarded ({pct_disc:.1f}%)",
                            icon="block",
                            color="negative" if disc_c > 0 else "grey",
                        ).props("dense dark")
                        ui.label(
                            f"Taxa with fewer than {mc} occurrences are omitted."
                        ).classes("text-xs text-gray-400 italic flex-align-center")

                refresh_cutoff_stats(active_filters.min_count)

                def update_cutoff_main(val: float | None) -> None:
                    if val is not None and int(val) >= 1:
                        c_val = int(val)
                        active_filters.min_count = c_val
                        set_app_metadata("min_count", str(c_val), conn=app_conn)
                        refresh_cutoff_stats(c_val)
                        on_filters_changed()
                        ui.notify(
                            f"Minimum occurrence limit set to {c_val} per taxon",
                            type="positive",
                        )

                cutoff_input_main.on_value_change(
                    lambda e: update_cutoff_main(e.value)
                )

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
        # 2. DarwinCore (DwC) Occurrence Ingestion Card
        with ui.card().classes("w-full bg-gray-800 p-6 rounded-lg shadow-md mb-6"):
            ui.label("DarwinCore (DwC) Occurrence Ingestion").classes(
                "text-lg font-bold text-yellow-300 mb-2"
            )
            ui.label(
                "Ingest DarwinCore .zip (ZIP-file) or occurrence.txt (TSV) file into SQLite database app_data.db."
            ).classes("text-xs text-gray-400 mb-4")

            saved_max_occ = get_app_metadata("max_occurrences_per_taxon", "1000", conn=app_conn)
            try:
                init_max_occ = int(saved_max_occ)
            except ValueError:
                init_max_occ = 1000

            with ui.row().classes("w-full gap-4 items-center flex-wrap mb-3"):
                max_occ_input = (
                    ui.number(
                        label="Max Occurrences Per Taxon",
                        value=init_max_occ,
                        min=0,
                        step=100,
                    )
                    .classes("w-72 text-white")
                    .props("outlined dark dense")
                )
                ui.label(
                    "Threshold cap per raw taxon during ingestion (default: 1000). Set to 0 for unlimited."
                ).classes("text-xs text-gray-400 italic")

            def save_max_occ(val: float | None) -> None:
                if val is not None:
                    set_app_metadata("max_occurrences_per_taxon", str(int(val)), conn=app_conn)

            max_occ_input.on_value_change(lambda e: save_max_occ(e.value))

            dwc_path_input = (
                ui.input(
                    label="Path or URL to DarwinCore dataset (.zip / occurrence.txt)",
                    value=ingest_input_path,
                    placeholder="e.g. src/data/datasets/danske_planter_2026.zip or https://api.gbif.org/v1/...",
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
                if txt.strip().lower().startswith(("http://", "https://")):
                    path_suggestions_box.classes(add="hidden")
                    return
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

            if taxa_cnt > 0:
                init_ingest_text = f"✓ Ingestion Active — {occ_cnt:,} occurrences loaded across {taxa_cnt:,} taxa."
                init_ingest_class = "text-sm text-green-400 font-bold mb-3"
                ingest_btn_label = "Re-Ingest Dataset"
            else:
                init_ingest_text = "Ready for DarwinCore ingestion."
                init_ingest_class = "text-sm text-gray-300 font-semibold mb-3"
                ingest_btn_label = "Start Ingestion"

            with ui.row().classes("items-center gap-2 mb-3"):
                ingest_spinner = ui.spinner("dots", size="md", color="primary").classes("hidden")
                status_label = ui.label(init_ingest_text).classes(init_ingest_class)

            async def run_ingestion() -> None:
                raw_target = dwc_path_input.value.strip()
                if not raw_target:
                    status_label.set_text("Please enter a file path or URL.")
                    ui.notify("Please enter a file path or URL!", type="negative")
                    return

                is_remote = raw_target.lower().startswith(("http://", "https://"))
                if not is_remote:
                    target_file = Path(raw_target)
                    if not target_file.exists():
                        status_label.set_text(f"File not found: {target_file}")
                        ui.notify("DwC file not found!", type="negative")
                        return

                ingest_btn.disable()
                ingest_spinner.classes(remove="hidden")
                status_label.set_text(
                    "Downloading dataset..." if is_remote else "Ingesting DarwinCore TSV stream..."
                )
                ui.notify("Started dataset ingestion process...", type="info")

                max_occ_val = int(max_occ_input.value) if max_occ_input.value is not None else 1000

                def on_progress(info: int | str) -> None:
                    if isinstance(info, str):
                        status_label.set_text(info)
                    else:
                        status_label.set_text(f"Ingested {info:,} occurrences...")

                try:
                    occ_cnt, taxa_cnt = await run.io_bound(
                        ingest_dwc_file,
                        raw_target,
                        APP_DB_PATH,
                        10000,
                        max_occ_val,
                        on_progress,
                    )
                    await run.io_bound(rebuild_indices)
                    status_label.set_text(
                        f"Complete! Ingested {occ_cnt:,} occurrences across {taxa_cnt:,} taxa."
                    )
                    ui.notify(
                        f"Ingestion successful ({occ_cnt:,} records). Reloading UI...", type="positive"
                    )
                    on_filters_changed()
                    ui.navigate.reload()
                except (sqlite3.Error, OSError, ValueError, RuntimeError) as ex:
                    status_label.set_text(f"Ingestion Error: {ex}")
                    ui.notify(f"Ingestion failed: {ex}", type="negative")
                finally:
                    ingest_btn.enable()
                    ingest_spinner.classes(add="hidden")

            ingest_btn = ui.button(
                ingest_btn_label, color="primary", on_click=run_ingestion
            ).classes("px-6")



        # 3. Vernacular Name Enrichment Engine Card
        with ui.card().classes("w-full bg-gray-800 p-6 rounded-lg shadow-md mb-6"):
            ui.label("GBIF Vernacular Name Enrichment").classes(
                "text-lg font-bold text-yellow-300 mb-2"
            )
            ui.label(
                "Query the GBIF Species API (api.gbif.org) to fetch missing Danish and English vernacular names for taxa and higher taxonomic ranks (Genera & Families) with persistent disk caching."
            ).classes("text-xs text-gray-400 mb-4")


            saved_enrich_status = get_app_metadata("gbif_enrichment_status", "", conn=app_conn)

            if saved_enrich_status:
                init_enrich_text = f"✓ GBIF Vernacular Name Enrichment Active — {saved_enrich_status}"
                init_enrich_class = "text-sm text-green-400 font-bold mb-3"
                enrich_btn_label = "Re-Fetch Danish Names from GBIF API"
            else:
                init_enrich_text = "Ready for GBIF API enrichment."
                init_enrich_class = "text-sm text-gray-300 font-semibold mb-3"
                enrich_btn_label = "Fetch Danish Names from GBIF API"

            enrich_status = ui.label(init_enrich_text).classes(init_enrich_class)
            progress_bar = (
                ui.linear_progress(value=0.0, show_value=False)
                .props("size=10px stripe rounded color=primary")
                .classes("w-full mb-4 hidden")
            )
            progress_state: dict = {"curr": 0, "total": 0, "status": init_enrich_text}

            def safe_ui_update(fn: Callable[[], None]) -> None:
                try:
                    fn()
                except RuntimeError:
                    pass

            def tick_progress() -> None:
                def _do_tick() -> None:
                    curr = progress_state["curr"]
                    tot = progress_state["total"]
                    st = progress_state.get("status")
                    if tot > 0:
                        pct = min(curr / tot, 1.0)
                        pct_str = f"{pct * 100:.1f}%"
                        progress_bar.set_value(pct)
                        if st:
                            enrich_status.set_text(f"{st} ({pct_str})")
                        else:
                            enrich_status.set_text(f"Checked {curr}/{tot} taxa ({pct_str})...")
                safe_ui_update(_do_tick)

            async def run_enrichment() -> None:
                safe_ui_update(enrich_button.disable)
                progress_state["curr"] = 0
                progress_state["total"] = 0
                progress_state["status"] = "Fetching Danish vernacular names from GBIF API..."
                safe_ui_update(lambda: progress_bar.set_value(0.0))
                safe_ui_update(lambda: progress_bar.classes(remove="hidden"))
                safe_ui_update(lambda: enrich_status.classes(replace="text-sm text-gray-300 font-semibold mb-3"))
                safe_ui_update(lambda: enrich_status.set_text(
                    "Fetching Danish vernacular names from GBIF Species API..."
                ))
                safe_ui_update(lambda: ui.notify(
                    "Starting GBIF API enrichment in background thread...", type="info"
                ))

                timer = ui.timer(0.1, tick_progress)

                def sync_worker() -> int:
                    def update_progress(curr: int, tot: int, status_msg: str | None = None) -> None:
                        progress_state["curr"] = curr
                        progress_state["total"] = tot
                        if status_msg:
                            progress_state["status"] = status_msg

                    return enrich_vernacular_names_from_gbif(
                        progress_callback=update_progress
                    )

                try:
                    updated = await run.io_bound(sync_worker)
                    t_cnt = app_conn.execute("SELECT COUNT(*) FROM taxa;").fetchone()[0]
                    d_cnt = app_conn.execute(
                        "SELECT COUNT(*) FROM taxa WHERE vernacular_da IS NOT NULL AND vernacular_da != '';"
                    ).fetchone()[0]
                    c_pct = int(d_cnt / t_cnt * 100) if t_cnt else 0
                    status_summary = f"{d_cnt:,}/{t_cnt:,} taxa populated with Danish vernacular names ({c_pct}%)."
                    set_app_metadata("gbif_enrichment_status", status_summary, conn=app_conn)

                    safe_ui_update(timer.cancel)
                    safe_ui_update(lambda: progress_bar.set_value(1.0))
                    safe_ui_update(lambda: enrich_status.classes(replace="text-sm text-green-400 font-bold mb-3"))
                    safe_ui_update(lambda: enrich_status.set_text(
                        f"✓ GBIF Enrichment Complete! Updated {updated} species — {status_summary}"
                    ))
                    safe_ui_update(lambda: ui.notify(
                        f"✓ GBIF API Enrichment Complete! Updated {updated} species names.",
                        type="positive",
                        timeout=5000,
                    ))
                    on_filters_changed()
                    await asyncio.sleep(1.0)
                    safe_ui_update(ui.navigate.reload)

                except (sqlite3.Error, OSError, RuntimeError, ValueError) as ex:

                    safe_ui_update(timer.cancel)
                    err_msg = str(ex)
                    safe_ui_update(lambda: enrich_status.classes(replace="text-sm text-red-400 font-bold mb-3"))
                    safe_ui_update(lambda: enrich_status.set_text(f"Enrichment Error: {err_msg}"))
                    safe_ui_update(lambda: ui.notify(f"Enrichment failed: {err_msg}", type="negative"))
                finally:
                    safe_ui_update(timer.cancel)
                    safe_ui_update(enrich_button.enable)

            enrich_button = ui.button(
                enrich_btn_label,
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
