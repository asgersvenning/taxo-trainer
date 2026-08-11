"""Core flashcard and identification quiz view for taxo-trainer.

Provides multi-rank identification, interactive autocomplete, satellite map context,
and hint options with strict penalty enforcement.
"""

import random

from nicegui import ui

from src.db import (
    APP_DB_PATH,
    USER_DB_PATH,
    get_db_connection,
    get_user_streak,
    set_user_streak,
)
from src.engine.analytics import log_attempt
from src.engine.sampling import SamplingFilter, TargetObservation, sample_next_question
from src.engine.validator import (
    autocomplete_taxa,
    get_display_name,
    validate_user_guess,
)
from src.ui.components import (
    render_phenology_badge,
    render_photo_viewer,
    render_satellite_map,
    render_taxa_filter_controls,
    render_taxonomic_hierarchy_feedback,
)


class QuizViewState:
    """Session state wrapper for QuizView client connection."""

    def __init__(self) -> None:
        self.filters: SamplingFilter = SamplingFilter(mode="log", min_count=1)
        self.seen_set: set[str] = set()
        self.current_question: TargetObservation | None = None
        self.used_hint: bool = False
        self.solved: bool = False
        self.last_feedback: dict[str, str] | None = None
        self.last_validation_result = None
        self.diagnostic_photo_url: str | None = None
        self.diagnostic_guessed_name: str | None = None
        self.matched_genus: str | None = None
        self.matched_family: str | None = None
        self.matched_order: str | None = None
        self.current_streak: int = 0
        self.best_streak: int = 0
        self.streak_initialized: bool = False
        self.is_incorrect: bool = False


def render_quiz_view(state: QuizViewState) -> None:
    """Render core quiz identification view.

    Layout structure:
      Top Header H
      Image Display I (75% width left canvas) | User Interface U (25% width right sidebar)

    Args:
        state: Per-client QuizViewState instance.
    """
    app_conn = get_db_connection(APP_DB_PATH)
    user_conn = get_db_connection(USER_DB_PATH)

    main_container = ui.column().classes("w-full h-full flex-1 min-h-0 p-1 space-y-2 overflow-hidden")

    if not state.streak_initialized:
        curr, best = get_user_streak(user_conn)
        state.current_streak = curr
        state.best_streak = best
        state.streak_initialized = True

    def load_new_question() -> None:
        """Sample next target observation question and refresh UI."""
        if state.is_incorrect and not state.solved:
            state.current_streak = 0
            set_user_streak(0, state.best_streak, user_conn)

        state.is_incorrect = False
        state.used_hint = False
        state.solved = False
        state.last_feedback = None
        state.last_validation_result = None
        state.diagnostic_photo_url = None
        state.diagnostic_guessed_name = None
        state.matched_genus = None
        state.matched_family = None
        state.matched_order = None
        state.current_question = sample_next_question(
            app_conn, user_conn, state.filters, state.seen_set
        )
        refresh_quiz_ui()

    def handle_submit_guess(guess_text: str) -> None:
        """Validate user guess and update progress."""
        if not state.current_question or not guess_text or not guess_text.strip():
            return

        res = validate_user_guess(
            app_conn,
            guess_text,
            state.current_question.taxon_key,
            lang=state.filters.language,
        )
        state.last_validation_result = res

        if res.is_correct and res.matched_rank == "SPECIES":
            if not state.solved:
                state.solved = True
                state.is_incorrect = False
                state.current_streak += 1
                if state.current_streak > state.best_streak:
                    state.best_streak = state.current_streak
                set_user_streak(state.current_streak, state.best_streak, user_conn)

            state.matched_genus = state.current_question.genus
            state.matched_family = state.current_question.family
            log_attempt(
                user_conn,
                state.current_question.occurrence_id,
                state.current_question.taxon_key,
                res.matched_taxon_key or state.current_question.taxon_key,
                is_correct=True,
                used_hint=state.used_hint,
            )
            state.last_feedback = {
                "type": "success",
                "message": res.feedback_message,
            }
        elif res.is_correct:
            # Correct Family or Genus rank (allow user to refine to Species)
            target_row = app_conn.execute(
                "SELECT order_name FROM taxa WHERE taxon_key = ?",
                (state.current_question.taxon_key,),
            ).fetchone()
            target_order_val = target_row["order_name"] if target_row and "order_name" in target_row.keys() and target_row["order_name"] else None

            if res.matched_rank == "GENUS":
                state.matched_genus = state.current_question.genus
                state.matched_family = state.current_question.family
                if target_order_val:
                    state.matched_order = target_order_val
            elif res.matched_rank == "FAMILY":
                state.matched_family = state.current_question.family
                if target_order_val:
                    state.matched_order = target_order_val
            elif res.matched_rank == "ORDER":
                if target_order_val:
                    state.matched_order = target_order_val

            state.last_feedback = {
                "type": "info",
                "message": res.feedback_message,
            }
        else:
            state.is_incorrect = True
            if res.matched_taxon_key is not None:
                # Incorrect guess against a real species -> Log attempt and show diagnostic photo
                log_attempt(
                    user_conn,
                    state.current_question.occurrence_id,
                    state.current_question.taxon_key,
                    res.matched_taxon_key,
                    is_correct=False,
                    used_hint=state.used_hint,
                )
                state.last_feedback = {
                    "type": "error",
                    "message": res.feedback_message,
                }

                if res.matched_rank in ("GENUS", "FAMILY"):
                    state.diagnostic_guessed_name = res.matched_name
                else:
                    guessed_row = app_conn.execute("SELECT * FROM taxa WHERE taxon_key = ?", (res.matched_taxon_key,)).fetchone()
                    if guessed_row:
                        g_disp = get_display_name(guessed_row, lang=state.filters.language)
                        g_sci = guessed_row["canonical_name"]
                        state.diagnostic_guessed_name = f"{g_disp} ({g_sci})" if g_disp != g_sci else g_sci
                    else:
                        state.diagnostic_guessed_name = res.matched_name or guess_text

                diag_cursor = app_conn.execute(
                    "SELECT media_urls FROM occurrences WHERE taxon_key = ? LIMIT 1",
                    (res.matched_taxon_key,),
                )
                diag_row = diag_cursor.fetchone()
                if diag_row and diag_row["media_urls"]:
                    state.diagnostic_photo_url = diag_row["media_urls"].split("|")[0].strip()
            else:
                # Unrecognized taxon name (e.g. typing error) -> Warning message, do NOT log attempt
                state.last_feedback = {
                    "type": "warning",
                    "message": res.feedback_message,
                }

        refresh_quiz_ui()


    def handle_report_bad_observation() -> None:
        """Flag current observation as misidentified, omit from user statistics, and mark as seen."""
        if not state.current_question:
            return

        occ_id = state.current_question.occurrence_id
        state.seen_set.add(occ_id)

        # Delete any logged attempts for this occurrence_id from user_progress DB
        user_conn.execute("DELETE FROM user_progress WHERE occurrence_id = ?", (occ_id,))
        user_conn.commit()

        state.solved = True
        state.last_feedback = {
            "type": "warning",
            "message": "Flagged observation as misidentified. Omitted from user statistics and excluded from future sessions.",
        }
        refresh_quiz_ui()

    def handle_higher_order_hint() -> None:
        """Trigger higher order taxonomic rank hint.

        Reveals the highest unrevealed taxonomic rank (Order -> Family -> Genus -> Species),
        updates the taxonomic breakdown, restricts autocomplete interpolation, and flags hint usage
        without logging a user guess.
        """
        if not state.current_question:
            return

        state.used_hint = True

        target_row = app_conn.execute(
            "SELECT * FROM taxa WHERE taxon_key = ?",
            (state.current_question.taxon_key,),
        ).fetchone()

        target_order = (
            target_row["order_name"]
            if target_row and "order_name" in target_row.keys() and target_row["order_name"]
            else None
        )
        target_family = state.current_question.family
        target_genus = state.current_question.genus

        revealed_desc = None

        if not state.matched_order and target_order:
            state.matched_order = target_order
            revealed_desc = f"Order '{target_order}'"
        elif not state.matched_family and target_family:
            state.matched_family = target_family
            if target_order:
                state.matched_order = target_order
            revealed_desc = f"Family '{target_family}'"
        elif not state.matched_genus and target_genus:
            state.matched_genus = target_genus
            state.matched_family = target_family
            if target_order:
                state.matched_order = target_order
            revealed_desc = f"Genus '{target_genus}'"
        elif not state.solved:
            state.solved = True
            state.matched_genus = target_genus
            state.matched_family = target_family
            if target_order:
                state.matched_order = target_order
            revealed_desc = f"Species '{state.current_question.canonical_name}'"

        if revealed_desc:
            msg = f"Taxonomic Hint: Revealed {revealed_desc}"
        else:
            msg = "All taxonomic ranks for this observation have already been revealed!"

        state.last_feedback = {
            "type": "warning",
            "message": msg,
        }
        refresh_quiz_ui()

    def handle_multiple_choice_hint() -> None:
        """Trigger 1/5 distractor multiple choice hint."""
        if not state.current_question:
            return
        state.used_hint = True

        dist_cursor = app_conn.execute(
            """
            SELECT taxon_key, canonical_name, scientific_name, vernacular_da, vernacular_en
            FROM taxa
            WHERE taxon_key != ? AND (family = ? OR genus = ?)
            ORDER BY RANDOM()
            LIMIT 4;
            """,
            (
                state.current_question.taxon_key,
                state.current_question.family,
                state.current_question.genus,
            ),
        )
        distractors = list(dist_cursor.fetchall())

        if len(distractors) < 4:
            needed = 4 - len(distractors)
            exclude_keys = [state.current_question.taxon_key] + [d["taxon_key"] for d in distractors]
            placeholders = ",".join("?" for _ in exclude_keys)
            fallback_cursor = app_conn.execute(
                f"""
                SELECT taxon_key, canonical_name, scientific_name, vernacular_da, vernacular_en
                FROM taxa
                WHERE taxon_key NOT IN ({placeholders})
                ORDER BY RANDOM()
                LIMIT ?;
                """,
                exclude_keys + [needed],
            )
            distractors.extend(fallback_cursor.fetchall())

        choices = [
            get_display_name({
                "vernacular_da": state.current_question.vernacular_da,
                "vernacular_en": state.current_question.vernacular_en,
                "canonical_name": state.current_question.canonical_name,
                "scientific_name": state.current_question.scientific_name,
            })
        ]
        for d in distractors:
            choices.append(get_display_name(d))

        random.shuffle(choices)
        state.last_feedback = {
            "type": "choices",
            "message": "Multiple Choice Options (1/5):",
            "choices": choices,
        }
        refresh_quiz_ui()

    nav_callbacks: dict = {}
    active_input: list = [None]
    is_input_focused: list[bool] = [False]

    def handle_key_event(e) -> None:
        """Global keyboard shortcut handler for observation and photo navigation."""
        if not e.action.keydown:
            return

        ctrl = getattr(e.modifiers, "ctrl", False)
        alt = getattr(e.modifiers, "alt", False)

        if isinstance(e.modifiers, (list, set, tuple)):
            mod_set = {str(m).lower() for m in e.modifiers}
            ctrl = ctrl or ("control" in mod_set or "ctrl" in mod_set)
            alt = alt or ("alt" in mod_set)

        inp = active_input[0]

        # 1. Escape key toggles/defocuses input field
        if e.key == "Escape":
            if inp:
                if is_input_focused[0]:
                    inp.run_method("blur")
                else:
                    inp.run_method("focus")
            return

        # 2. Focus shortcuts when input is NOT focused: '/', 'F2', or 'Ctrl+K'
        key_str = str(e.key).lower()
        if (key_str in ("/", "f2") or (ctrl and key_str == "k")) and not is_input_focused[0]:
            if inp:
                inp.run_method("focus")
            return

        # 3. Global navigation actions (only when input field is NOT focused)
        if not is_input_focused[0]:
            if (ctrl and e.key == "ArrowRight") or e.key in ("n", "N"):
                load_new_question()
            elif (e.key == "ArrowRight" or e.key in ("d", "D") or (alt and e.key == "ArrowRight")) and nav_callbacks.get("next"):
                nav_callbacks["next"]()
            elif (e.key == "ArrowLeft" or e.key in ("a", "A") or (alt and e.key == "ArrowLeft")) and nav_callbacks.get("prev"):
                nav_callbacks["prev"]()


    ui.keyboard(on_key=handle_key_event)

    def refresh_quiz_ui() -> None:
        """Re-render reactive quiz interface using 75% Image / 25% UI layout."""
        is_input_focused[0] = False
        main_container.clear()
        with main_container:
            if not state.current_question:
                ui.label("No observations available matching active dataset/filters.").classes("text-xl text-yellow-400 text-center py-12")
                ui.button("Load Observation", on_click=load_new_question, color="primary").classes("mx-auto")
                return

            # Main split container: 75% Image Display (I) | 25% User Interface (U)
            with ui.row().classes("w-full h-full gap-3 no-wrap items-stretch"):
                # =========================================================
                # LEFT COLUMN (I): 75% Width Reserved for Whole Image Display
                # =========================================================
                with ui.column().classes("w-[75%] h-full flex flex-col flex-grow justify-between"):
                    render_photo_viewer(
                        state.current_question.media_urls,
                        latitude=state.current_question.latitude,
                        longitude=state.current_question.longitude,
                        locality=state.current_question.locality,
                        nav_callbacks=nav_callbacks,
                        recorded_by=state.current_question.recorded_by,
                        references=state.current_question.references,
                    )



                # =========================================================
                # RIGHT COLUMN (U): 25% Width User Interface Controls Sidebar
                # =========================================================
                with ui.column().classes("w-[25%] min-w-[280px] h-full bg-gray-900 rounded-lg p-3 space-y-3 overflow-y-auto shadow-xl border border-gray-800"):
                    # 1. Phenology & Context Info
                    with ui.row().classes("w-full justify-between items-center bg-gray-800 p-2 rounded-md"):
                        render_phenology_badge(state.current_question.month, state.current_question.event_date)
                        ui.label(f"Rank: {state.filters.rank}").classes("text-xs text-gray-300 font-bold")

                    # 2. Next Observation & Streak Controls
                    with ui.column().classes("w-full gap-1.5"):
                        with ui.row().classes("w-full justify-between items-center bg-gray-800 border border-gray-700 px-3 py-1.5 rounded-md shadow-sm"):
                            with ui.row().classes("items-center gap-1.5"):
                                ui.icon("whatshot", color="amber-500").classes("text-sm")
                                ui.label(f"Streak: {state.current_streak}").classes("text-xs font-bold text-amber-400")
                            with ui.row().classes("items-center gap-1.5"):
                                ui.icon("emoji_events", color="yellow-400").classes("text-sm")
                                ui.label(f"Record: {state.best_streak}").classes("text-xs font-bold text-yellow-300")

                        with ui.row().classes("w-full justify-between items-center gap-1"):
                            ui.button(
                                "Next Observation ▶  [ n ]",
                                color="positive" if (state.solved or state.last_feedback) else "primary",
                                on_click=load_new_question,
                            ).classes("w-full font-bold text-xs py-1 shadow")

                    # Taxa Whitelist / Blacklist Filter Drawer
                    with ui.expansion("Taxa Scope (Whitelist / Blacklist)", icon="filter_alt").classes("w-full bg-gray-800 text-xs text-yellow-300 rounded-md border border-gray-700 p-0"):
                        render_taxa_filter_controls(
                            app_conn,
                            state.filters,
                            on_changed=load_new_question,
                        )

                    # 3. Input & Guess Submission Box
                    with ui.card().classes("w-full p-3 bg-gray-800 text-white rounded-md shadow-sm border border-gray-700 space-y-2"):
                        with ui.row().classes("w-full justify-between items-center"):
                            ui.label("Identify Taxon:").classes("font-bold text-xs text-gray-200")
                            ui.label("Focus: / or Esc | Blur: Esc").classes("text-[10px] text-yellow-400 font-mono")

                        input_field = ui.input(
                            placeholder="Type species, genus, family... (/ to focus, Esc to blur)",
                        ).classes("w-full text-xs text-white").props("outlined dark dense clearable")

                        active_input[0] = input_field

                        # Dynamic Autocomplete Suggestion Chips
                        suggestions_container = ui.column().classes("w-full gap-1 hidden max-h-36 overflow-y-auto")

                        def on_focus() -> None:
                            is_input_focused[0] = True

                        def on_blur() -> None:
                            is_input_focused[0] = False

                        input_field.on("focus", on_focus)
                        input_field.on("blur", on_blur)
                        input_field.on("keydown.escape", lambda: input_field.run_method("blur"))

                        def update_suggestions(e) -> None:
                            text = e.value
                            if not text or len(text.strip()) < 2:
                                suggestions_container.classes(add="hidden")
                                return
                            matches = autocomplete_taxa(
                                app_conn,
                                text,
                                limit=5,
                                lang=state.filters.language,
                                parent_genus=state.matched_genus,
                                parent_family=state.matched_family,
                                parent_order=state.matched_order,
                            )
                            suggestions_container.clear()
                            if matches:
                                suggestions_container.classes(remove="hidden")
                                with suggestions_container:
                                    for m in matches:
                                        label_txt = m["label"]
                                        val_txt = m["value"]
                                        ui.button(
                                            label_txt,
                                            on_click=lambda v=val_txt: handle_submit_guess(v),
                                        ).props("outline dense color=accent").classes("text-[10px] w-full text-left truncate")

                        input_field.on_value_change(update_suggestions)

                        # Handle Enter key submission (takes top autocomplete suggestion if available)
                        def handle_enter_submission() -> None:
                            val = input_field.value
                            if not val or not val.strip():
                                return
                            matches = autocomplete_taxa(
                                app_conn,
                                val,
                                limit=1,
                                lang=state.filters.language,
                                parent_genus=state.matched_genus,
                                parent_family=state.matched_family,
                                parent_order=state.matched_order,
                            )
                            if matches:
                                handle_submit_guess(matches[0]["value"])
                            else:
                                handle_submit_guess(val)

                        input_field.on("keydown.enter", handle_enter_submission)

                        with ui.row().classes("w-full justify-between items-center gap-1 mt-1"):
                            ui.button("Submit", color="primary", on_click=handle_enter_submission).classes("w-full font-bold text-xs")

                    # 4. Hints Controls Card & Misidentification Flag
                    with ui.card().classes("w-full p-2 bg-gray-800 text-white rounded-md shadow-sm border border-gray-700"):
                        ui.label("Hints & Feedback").classes("text-xs font-bold text-gray-400 mb-1")
                        with ui.row().classes("w-full justify-between gap-1"):
                            ui.button("Higher-Order Rank", on_click=handle_higher_order_hint, color="warning").props("flat dense").classes("text-[11px]")
                            ui.button("1/5 Choice", on_click=handle_multiple_choice_hint, color="warning").props("flat dense").classes("text-[11px]")
                        
                        ui.button(
                            "Report Misidentified Obs",
                            on_click=handle_report_bad_observation,
                            color="negative",
                            icon="report_problem",
                        ).props("flat dense").classes("text-[10px] w-full text-red-400 hover:text-red-200 mt-1")

                    # 5. Feedback Message Banner & Multi-Rank Hierarchy Breakdown
                    if state.last_feedback:
                        fb_type = state.last_feedback.get("type", "info")
                        bg_cls = "bg-green-900 text-white" if fb_type == "success" else ("bg-red-900 text-white" if fb_type == "error" else ("bg-blue-900 text-white" if fb_type == "info" else "bg-yellow-900 text-white"))

                        with ui.card().classes(f"w-full p-3 text-center rounded-md shadow-md {bg_cls}"):
                            ui.label(state.last_feedback["message"]).classes("text-xs font-bold")

                            # Render Multiple Choice (1/5) Buttons if active
                            if fb_type == "choices" and "choices" in state.last_feedback:
                                with ui.column().classes("w-full gap-1 mt-2"):
                                    for choice_label in state.last_feedback["choices"]:
                                        ui.button(
                                            choice_label,
                                            on_click=lambda l=choice_label: handle_submit_guess(l),
                                            color="secondary",
                                        ).props("outline dense").classes("bg-gray-800 text-white font-medium text-xs w-full")

                        # Multi-Level Taxonomic Hierarchy Feedback (Order, Family, Genus, Species)
                        target_row_query = app_conn.execute("SELECT * FROM taxa WHERE taxon_key = ?", (state.current_question.taxon_key,)).fetchone()
                        if target_row_query:
                            render_taxonomic_hierarchy_feedback(
                                app_conn,
                                target_row_query,
                                state.last_validation_result,
                                lang=state.filters.language,
                                revealed_order=state.matched_order,
                                revealed_family=state.matched_family,
                                revealed_genus=state.matched_genus,
                                is_solved=state.solved,
                            )

                    # 6. Diagnostic Reference Photo (on wrong guess)
                    if state.diagnostic_photo_url:
                        with ui.card().classes("w-full p-3 bg-gray-800 text-white rounded-md shadow-sm border border-gray-700"):
                            diag_label = f"Diagnostic Reference (Guessed '{state.diagnostic_guessed_name}'):" if state.diagnostic_guessed_name else "Diagnostic Reference (Guessed Species):"
                            ui.label(diag_label).classes("font-bold text-[11px] text-yellow-300 mb-1")

                            ui.element("img").props(f'src="{state.diagnostic_photo_url}"').style(
                                "max-width: 100%; max-height: 128px; object-fit: scale-down; display: block; margin: auto; border-radius: 4px;"
                            )

                    # 7. Compact Location Satellite Map Card
                    render_satellite_map(
                        state.current_question.latitude,
                        state.current_question.longitude,
                        state.current_question.locality,
                    )

    # Initial render load
    if not state.current_question:
        load_new_question()
    else:
        refresh_quiz_ui()
