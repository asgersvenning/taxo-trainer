"""Reusable NiceGUI UI components for taxo-trainer.

Includes multi-photo inspection carousel, Esri satellite Leaflet widget,
and taxonomic badge components.
"""

from nicegui import ui


def render_photo_viewer(
    media_urls: list[str],
    latitude: float | None = None,
    longitude: float | None = None,
    locality: str = "",
    current_index: int = 0,
    nav_callbacks: dict | None = None,
    recorded_by: str = "",
    references: str = "",
) -> ui.column:
    """Render 75% width main image display panel with object-contain showing the whole photo,
    carousel controls, photo credits, source links, and a toggle between Field Photo and Satellite Map.

    Args:
        media_urls: List of image URLs.
        latitude: Optional decimal latitude.
        longitude: Optional decimal longitude.
        locality: Verbatim locality string.
        current_index: Active photo index.
        nav_callbacks: Optional dictionary to receive next/prev photo navigation functions.
        recorded_by: Optional observer / photo credit string.
        references: Optional observation reference source URL.

    Returns:
        ui.column: Column container holding image/map canvas and controls.
    """
    container = ui.column().classes(
        "w-full h-full bg-black text-white rounded-lg p-2 flex flex-col justify-between relative shadow-2xl border border-gray-800"
    )

    if not media_urls:
        with container:
            ui.label("No image available for this observation.").classes(
                "text-gray-400 italic m-auto text-center w-full text-lg"
            )
        return container

    state = {
        "index": min(current_index, len(media_urls) - 1),
        "view": "photo",  # "photo" or "map"
    }

    photo_count_label: ui.label | None = None

    def update_photo(step: int):
        state["index"] = (state["index"] + step) % len(media_urls)
        if photo_count_label:
            photo_count_label.set_text(
                f"Photo {state['index'] + 1} of {len(media_urls)}"
            )
        if state["view"] == "photo":
            refresh_canvas()

    if nav_callbacks is not None:
        nav_callbacks["next"] = lambda: update_photo(1) if len(media_urls) > 1 else None
        nav_callbacks["prev"] = lambda: (
            update_photo(-1) if len(media_urls) > 1 else None
        )

    with container:
        # Top toolbar over image
        with ui.row().classes(
            "w-full justify-between items-center bg-gray-900/80 backdrop-blur-md p-2 rounded-t-md z-10 border-b border-gray-800"
        ):
            with ui.row().classes("items-center gap-2"):
                ui.icon("photo_library", color="primary", size="sm")
                photo_count_label = ui.label(
                    f"Photo {state['index'] + 1} of {len(media_urls)}"
                ).classes("text-xs font-semibold text-gray-200")

            with ui.row().classes("gap-2 items-center"):
                photo_tab_btn = (
                    ui.button("Field Photo", color="primary")
                    .props("dense flat")
                    .classes("text-xs font-bold")
                )
                map_tab_btn = (
                    ui.button("Satellite Map", color="secondary")
                    .props("dense flat")
                    .classes("text-xs font-bold")
                )

        # Main viewport canvas
        canvas = ui.column().classes(
            "w-full flex-1 relative overflow-hidden items-center justify-center p-1 bg-black"
        )

        def refresh_canvas() -> None:
            canvas.clear()
            with canvas:
                if state["view"] == "photo":
                    ui.element("img").props(
                        f'src="{media_urls[state["index"]]}"'
                    ).style(
                        "max-width: 100%; max-height: 100%; object-fit: scale-down; display: block; margin: auto; border-radius: 4px;"
                    )
                else:
                    if latitude is not None and longitude is not None:
                        map_widget = ui.leaflet(
                            center=(latitude, longitude), zoom=14
                        ).classes("w-full h-full rounded-md")
                        map_widget.tile_layer(
                            url_template="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
                            options={
                                "attribution": "Tiles &copy; Esri",
                                "maxZoom": 18,
                            },
                        )
                        map_widget.marker(latlng=(latitude, longitude))
                    else:
                        ui.label(
                            "Geographic coordinates unavailable for this observation."
                        ).classes("text-sm text-gray-400 italic m-auto")

        def switch_to_photo():
            state["view"] = "photo"
            photo_tab_btn.props("color=primary")
            map_tab_btn.props("color=secondary")
            refresh_canvas()

        def switch_to_map():
            state["view"] = "map"
            photo_tab_btn.props("color=secondary")
            map_tab_btn.props("color=primary")
            refresh_canvas()

        photo_tab_btn.on_click(switch_to_photo)
        map_tab_btn.on_click(switch_to_map)

        refresh_canvas()

        # Bottom carousel navigation bar with photo credit & observation source link
        with ui.row().classes(
            "w-full justify-between items-center bg-gray-900/90 p-2 rounded-b-md z-10 border-t border-gray-800 flex-wrap gap-2"
        ):
            if len(media_urls) > 1:
                prev_btn = (
                    ui.button("◀ Previous Photo", color="primary", icon="chevron_left")
                    .props("flat dense")
                    .classes("text-xs")
                )
                prev_btn.on_click(lambda: update_photo(-1))

            # Metadata info container: Locality, Photo Credit, and Observation Source Link
            with ui.row().classes(
                "items-center gap-3 text-xs text-gray-300 mx-auto flex-wrap justify-center"
            ):
                loc_txt = locality or "Field Observation"
                ui.label(f"📍 {loc_txt}").classes(
                    "font-medium truncate max-w-xs text-gray-400"
                )

                if recorded_by:
                    ui.label(f"👤 Photo: {recorded_by}").classes(
                        "font-medium text-gray-300 bg-gray-800 px-2 py-0.5 rounded border border-gray-700"
                    )

                if references:
                    ui.link(
                        "🔗 View Source / GBIF Obs ↗", references, new_tab=True
                    ).classes(
                        "font-bold text-yellow-400 hover:text-yellow-200 underline text-xs"
                    )

            if len(media_urls) > 1:
                next_btn = (
                    ui.button("Next Photo ▶", color="primary", icon="chevron_right")
                    .props("flat dense")
                    .classes("text-xs")
                )
                next_btn.on_click(lambda: update_photo(1))

    return container


def render_satellite_map(
    latitude: float | None,
    longitude: float | None,
    locality: str = "",
    zoom: int = 12,
) -> ui.card:
    """Render compact sidebar satellite map card.

    Args:
        latitude: Decimal latitude.
        longitude: Decimal longitude.
        locality: Verbatim locality string.
        zoom: Map zoom level.

    Returns:
        ui.card: Card container holding satellite Leaflet view.
    """
    card = ui.card().classes(
        "w-full shadow-md p-2 bg-gray-900 text-white rounded-lg border border-gray-800"
    )

    with card:
        ui.label("Location Context").classes("text-xs font-bold text-gray-300 mb-1")
        if locality:
            ui.label(locality).classes("text-[10px] text-gray-400 mb-1 truncate")

        if latitude is not None and longitude is not None:
            map_widget = ui.leaflet(center=(latitude, longitude), zoom=zoom).classes(
                "w-full aspect-square max-h-64 rounded-md"
            )
            map_widget.tile_layer(
                url_template="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
                options={
                    "attribution": "Tiles &copy; Esri",
                    "maxZoom": 18,
                },
            )
            map_widget.marker(latlng=(latitude, longitude))
        else:
            ui.label("Coordinates unavailable.").classes(
                "text-[10px] text-gray-500 italic py-4 text-center w-full"
            )

    return card


def render_phenology_badge(month: int | None, event_date: str = "") -> None:
    """Render phenology observation date/month badge.

    Args:
        month: Month integer 1-12.
        event_date: Verbatim date string.
    """
    month_names = [
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ]
    month_str = month_names[month - 1] if month and 1 <= month <= 12 else ""

    text = f"Observed: {month_str}" if month_str else "Observed Date Unknown"
    if event_date and not month_str:
        text = f"Observed: {event_date}"

    ui.badge(text, color="secondary").classes(
        "text-xs px-2 py-1 font-semibold shadow-sm"
    )


def render_taxa_filter_controls(
    app_conn,
    filters,
    on_changed: callable,
) -> ui.card:
    """Render interactive Whitelist (include) and Blacklist (exclude) taxa filtering UI.

    Args:
        app_conn: SQLite connection to app_data.db.
        filters: SamplingFilter dataclass instance.
        on_changed: Callback function invoked when whitelist/blacklist is modified.

    Returns:
        ui.card: Container holding interactive whitelist & blacklist filtering controls.
    """
    from src.engine.validator import autocomplete_taxa

    card = ui.card().classes(
        "w-full bg-gray-900/90 p-3 rounded-lg border border-gray-700 space-y-3 shadow-md"
    )

    with card:
        with ui.row().classes("w-full justify-between items-center"):
            ui.label("Taxa Scope: Whitelist & Blacklist").classes(
                "text-xs font-bold text-yellow-400 uppercase tracking-wider"
            )
            active_cnt = len(filters.include_taxa) + len(filters.exclude_taxa)
            if active_cnt > 0:
                ui.badge(f"{active_cnt} active filters", color="primary").classes(
                    "text-[10px]"
                )

        # 1. Whitelist (Include) Input & Badges
        with ui.column().classes("w-full space-y-1"):
            ui.label("Whitelist (Include Taxa Only):").classes(
                "text-[11px] font-semibold text-green-400"
            )

            inc_input = (
                ui.input(
                    placeholder="Type species, genus, or family to whitelist...",
                )
                .classes("w-full text-xs text-white")
                .props("outlined dark dense clearable")
            )

            inc_suggestions = ui.column().classes(
                "w-full gap-1 hidden max-h-28 overflow-y-auto bg-gray-800 p-1 rounded border border-gray-700 z-10"
            )

            def update_inc_suggestions(e) -> None:
                txt = e.value or ""
                if len(txt.strip()) < 2:
                    inc_suggestions.classes(add="hidden")
                    return
                matches = autocomplete_taxa(app_conn, txt, limit=5)
                inc_suggestions.clear()
                if matches:
                    inc_suggestions.classes(remove="hidden")
                    with inc_suggestions:
                        for m in matches:
                            val_name = (
                                m["canonical_name"]
                                if m["rank"] == "SPECIES"
                                else m["value"]
                            )
                            lbl_name = m["label"]

                            def add_inc(val=val_name):
                                if val not in filters.include_taxa:
                                    filters.include_taxa.append(val)
                                    inc_input.value = ""
                                    inc_suggestions.classes(add="hidden")
                                    on_changed()

                            ui.button(f"+ {lbl_name}", on_click=add_inc).props(
                                "flat dense color=positive"
                            ).classes("text-[10px] w-full text-left truncate")

            inc_input.on_value_change(update_inc_suggestions)

            # Active Include Taxa Badges
            with ui.row().classes("w-full gap-1 flex-wrap items-center mt-1"):
                if not filters.include_taxa:
                    ui.label("All taxa included (no active whitelist)").classes(
                        "text-[10px] text-gray-500 italic"
                    )
                else:
                    for inc_t in list(filters.include_taxa):

                        def remove_inc(t=inc_t):
                            if t in filters.include_taxa:
                                filters.include_taxa.remove(t)
                                on_changed()

                        ui.chip(
                            f"✓ {inc_t}", color="positive", on_click=remove_inc
                        ).props("removable dense dark").classes("text-[10px]")

                    def clear_inc():
                        filters.include_taxa.clear()
                        on_changed()

                    ui.button("Clear Whitelist", on_click=clear_inc).props(
                        "flat dense color=warning"
                    ).classes("text-[9px]")

        # 2. Blacklist (Exclude) Input & Badges
        with ui.column().classes("w-full space-y-1 mt-2"):
            ui.label("Blacklist (Exclude Taxa):").classes(
                "text-[11px] font-semibold text-red-400"
            )

            exc_input = (
                ui.input(
                    placeholder="Type species, genus, or family to exclude...",
                )
                .classes("w-full text-xs text-white")
                .props("outlined dark dense clearable")
            )

            exc_suggestions = ui.column().classes(
                "w-full gap-1 hidden max-h-28 overflow-y-auto bg-gray-800 p-1 rounded border border-gray-700 z-10"
            )

            def update_exc_suggestions(e) -> None:
                txt = e.value or ""
                if len(txt.strip()) < 2:
                    exc_suggestions.classes(add="hidden")
                    return
                matches = autocomplete_taxa(app_conn, txt, limit=5)
                exc_suggestions.clear()
                if matches:
                    exc_suggestions.classes(remove="hidden")
                    with exc_suggestions:
                        for m in matches:
                            val_name = (
                                m["canonical_name"]
                                if m["rank"] == "SPECIES"
                                else m["value"]
                            )
                            lbl_name = m["label"]

                            def add_exc(val=val_name):
                                if val not in filters.exclude_taxa:
                                    filters.exclude_taxa.append(val)
                                    exc_input.value = ""
                                    exc_suggestions.classes(add="hidden")
                                    on_changed()

                            ui.button(f"- {lbl_name}", on_click=add_exc).props(
                                "flat dense color=negative"
                            ).classes("text-[10px] w-full text-left truncate")

            exc_input.on_value_change(update_exc_suggestions)

            # Active Exclude Taxa Badges
            with ui.row().classes("w-full gap-1 flex-wrap items-center mt-1"):
                if not filters.exclude_taxa:
                    ui.label("No taxa excluded").classes(
                        "text-[10px] text-gray-500 italic"
                    )
                else:
                    for exc_t in list(filters.exclude_taxa):

                        def remove_exc(t=exc_t):
                            if t in filters.exclude_taxa:
                                filters.exclude_taxa.remove(t)
                                on_changed()

                        ui.chip(
                            f"✕ {exc_t}", color="negative", on_click=remove_exc
                        ).props("removable dense dark").classes("text-[10px]")

                    def clear_exc():
                        filters.exclude_taxa.clear()
                        on_changed()

                    ui.button("Clear Blacklist", on_click=clear_exc).props(
                        "flat dense color=warning"
                    ).classes("text-[9px]")

    return card


def render_taxonomic_hierarchy_feedback(
    app_conn,
    target_row,
    validation_result,
    lang: str = "da",
    revealed_order: str | None = None,
    revealed_family: str | None = None,
    revealed_genus: str | None = None,
    is_solved: bool = False,
) -> ui.card:
    """Render multi-level taxonomic correctness feedback display (Order, Family, Genus, Species).

    Args:
        app_conn: SQLite connection to app_data.db.
        target_row: Target observation record from taxa table.
        validation_result: ValidationResult object from validator.py.
        lang: Language preference ("da", "en", etc.).
        revealed_order: Optional order_name revealed by hint or guess.
        revealed_family: Optional family revealed by hint or guess.
        revealed_genus: Optional genus revealed by hint or guess.
        is_solved: Flag indicating if the observation species has been solved/revealed.

    Returns:
        ui.card: Card component rendering colored level correctness badges.
    """
    if (
        validation_result is None
        and not (revealed_order or revealed_family or revealed_genus)
        and not is_solved
    ):
        return

    from src.engine.validator import get_display_name

    card = ui.card().classes(
        "w-full p-3 bg-gray-900 text-white rounded-md shadow-md border border-gray-700 space-y-1.5"
    )

    with card:
        ui.label("Taxonomic Hierarchy Breakdown:").classes(
            "text-[11px] font-bold text-gray-300 uppercase tracking-wider mb-1"
        )

        # 1. Fetch Target Rank Details
        row_keys = target_row.keys() if hasattr(target_row, "keys") else []
        target_order = (
            target_row["order_name"]
            if "order_name" in row_keys and target_row["order_name"]
            else ""
        ).strip()
        target_family = (
            target_row["family"]
            if "family" in row_keys and target_row["family"]
            else ""
        ).strip()
        target_genus = (
            target_row["genus"] if "genus" in row_keys and target_row["genus"] else ""
        ).strip()
        target_species_disp = get_display_name(target_row, lang=lang)
        target_sci = target_row["canonical_name"].strip()

        # Helper to get higher_ranks display string
        def get_hr_disp(rank_name: str) -> str:
            if not rank_name:
                return ""
            hr = app_conn.execute(
                "SELECT vernacular_da, vernacular_en FROM higher_ranks WHERE rank_name = ?",
                (rank_name,),
            ).fetchone()
            if hr:
                v_disp = get_display_name(hr, lang=lang)
                if v_disp and v_disp != rank_name:
                    return f"{v_disp} ({rank_name})"
            return rank_name

        family_disp = get_hr_disp(target_family)
        genus_disp = get_hr_disp(target_genus)

        # 2. Determine Guessed Taxon Row if available
        guessed_row = None
        if validation_result and validation_result.matched_taxon_key:
            guessed_row = app_conn.execute(
                "SELECT * FROM taxa WHERE taxon_key = ?",
                (str(validation_result.matched_taxon_key),),
            ).fetchone()

        m_rank = validation_result.matched_rank if validation_result else None
        is_corr = validation_result.is_correct if validation_result else False

        # Rank correctness logic
        order_ok = (
            (is_corr and m_rank in ("ORDER", "FAMILY", "GENUS", "SPECIES"))
            or (
                guessed_row
                and guessed_row["order_name"]
                and target_order
                and guessed_row["order_name"].lower() == target_order.lower()
            )
            or bool(
                revealed_order
                and target_order
                and revealed_order.lower() == target_order.lower()
            )
        )
        family_ok = (
            (is_corr and m_rank in ("FAMILY", "GENUS", "SPECIES"))
            or (
                guessed_row
                and guessed_row["family"]
                and target_family
                and guessed_row["family"].lower() == target_family.lower()
            )
            or bool(
                revealed_family
                and target_family
                and revealed_family.lower() == target_family.lower()
            )
        )
        genus_ok = (
            (is_corr and m_rank in ("GENUS", "SPECIES"))
            or (
                guessed_row
                and guessed_row["genus"]
                and target_genus
                and guessed_row["genus"].lower() == target_genus.lower()
            )
            or bool(
                revealed_genus
                and target_genus
                and revealed_genus.lower() == target_genus.lower()
            )
        )
        species_ok = bool((is_corr and m_rank == "SPECIES") or is_solved)

        # Determine which ranks should be hidden ("???").
        # If an incorrect guess was made (validation_result exists and is not correct),
        # all ranks are revealed as red incorrect boxes showing the true target ranks.
        is_incorrect_guess = bool(validation_result and not validation_result.is_correct)

        order_hidden = not order_ok and not is_solved and not is_incorrect_guess
        family_hidden = not family_ok and not is_solved and not is_incorrect_guess
        genus_hidden = not genus_ok and not is_solved and not is_incorrect_guess
        species_hidden = not species_ok and not is_solved and not is_incorrect_guess

        # Cache for GBIF keys
        if not hasattr(render_taxonomic_hierarchy_feedback, "_gbif_cache"):
            render_taxonomic_hierarchy_feedback._gbif_cache = {}
        gbif_cache = render_taxonomic_hierarchy_feedback._gbif_cache

        # Helper to resolve GBIF taxon key for a given rank & name
        def resolve_gbif_key(rank_lvl: str, raw_name: str) -> str | None:
            if not raw_name or raw_name.startswith("Unknown") or raw_name == "???":
                return None

            if rank_lvl == "Species":
                if target_row and "taxon_key" in target_row and target_row["taxon_key"]:
                    return str(target_row["taxon_key"])
                if (
                    guessed_row
                    and "taxon_key" in guessed_row
                    and guessed_row["taxon_key"]
                ):
                    return str(guessed_row["taxon_key"])

            if raw_name in gbif_cache:
                return gbif_cache[raw_name]

            # 1. Look up exact canonical_name and rank in taxa
            r = app_conn.execute(
                "SELECT taxon_key FROM taxa WHERE LOWER(canonical_name) = LOWER(?) AND LOWER(rank) = LOWER(?) AND taxon_key IS NOT NULL LIMIT 1",
                (raw_name, rank_lvl),
            ).fetchone()
            if r and r["taxon_key"]:
                key = str(r["taxon_key"])
                gbif_cache[raw_name] = key
                return key

            # 2. Query GBIF match API for exact rank key
            import json
            import urllib.parse
            import urllib.request

            try:
                url = f"https://api.gbif.org/v1/species/match?name={urllib.parse.quote(raw_name)}"
                req = urllib.request.Request(
                    url, headers={"User-Agent": "taxo-trainer/1.0"}
                )
                with urllib.request.urlopen(req, timeout=3) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    rank_key_map = {
                        "ORDER": data.get("orderKey"),
                        "FAMILY": data.get("familyKey"),
                        "GENUS": data.get("genusKey"),
                        "SPECIES": data.get("speciesKey") or data.get("usageKey"),
                    }
                    key = rank_key_map.get(rank_lvl.upper()) or data.get("usageKey")
                    if key:
                        gbif_cache[raw_name] = str(key)
                        return str(key)
            except Exception:
                pass

            return None

        # ranks_data: (label, display_name, is_correct, is_hidden, raw_name)
        ranks_data = [
            (
                "Order",
                target_order or "Unknown Order",
                order_ok,
                order_hidden,
                target_order,
            ),
            (
                "Family",
                family_disp or target_family or "Unknown Family",
                family_ok,
                family_hidden,
                target_family,
            ),
            (
                "Genus",
                genus_disp or target_genus or "Unknown Genus",
                genus_ok,
                genus_hidden,
                target_genus,
            ),
            (
                "Species",
                f"{target_species_disp} ({target_sci})"
                if target_species_disp != target_sci
                else target_sci,
                species_ok,
                species_hidden,
                target_sci,
            ),
        ]

        for rank_lvl, disp_name, is_ok, is_hidden, raw_name in ranks_data:
            if not disp_name:
                continue
            if is_hidden:
                # Yellow "???" unrevealed row (not a link)
                with ui.row().classes(
                    "w-full justify-between items-center text-xs p-1.5 rounded font-medium bg-yellow-950 text-yellow-300 border border-yellow-700"
                ):
                    with ui.row().classes("items-center gap-1 overflow-hidden"):
                        ui.icon("help_outline", color="warning", size="xs")
                        ui.label(f"[{rank_lvl}] ???").classes(
                            "truncate font-bold text-[11px]"
                        )
                    ui.label("? Unknown").classes(
                        "text-[10px] font-mono px-1 py-0.5 rounded bg-yellow-900 text-yellow-200"
                    )
            else:
                gbif_key = resolve_gbif_key(rank_lvl, raw_name)
                if gbif_key:
                    if str(gbif_key).isdigit():
                        gbif_url = f"https://www.gbif.org/species/{gbif_key}"
                    else:
                        gbif_url = f"https://www.gbif.org/taxon/{gbif_key}"
                else:
                    gbif_url = None

                box_cls = (
                    "w-full flex flex-row items-center justify-between text-xs p-1.5 rounded font-medium no-underline transition-all "
                    + (
                        "bg-green-950 text-green-300 border border-green-700 hover:bg-green-900 hover:border-green-500"
                        if is_ok
                        else "bg-red-950 text-red-300 border border-red-800 hover:bg-red-900 hover:border-red-600"
                    )
                )

                container = (
                    ui.link(target=gbif_url, new_tab=True).classes(box_cls)
                    if gbif_url
                    else ui.row().classes(box_cls)
                )

                with container:
                    with ui.row().classes("items-center gap-1 overflow-hidden"):
                        icon_str = "check_circle" if is_ok else "cancel"
                        icon_color = "positive" if is_ok else "negative"
                        ui.icon(icon_str, color=icon_color, size="xs")
                        ui.label(f"[{rank_lvl}] {disp_name}").classes(
                            "truncate font-bold text-[11px]"
                        )
                        if gbif_url:
                            ui.icon("open_in_new", size="xs").classes(
                                "text-[10px] opacity-70 ml-0.5"
                            )
                    ui.label("✓ Correct" if is_ok else "✕ Incorrect").classes(
                        "text-[10px] font-mono px-1 py-0.5 rounded "
                        + (
                            "bg-green-900 text-green-200"
                            if is_ok
                            else "bg-red-900 text-red-200"
                        )
                    )

    return card
