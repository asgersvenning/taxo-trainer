"""Core flashcard and identification quiz view for taxo-trainer.

Provides multi-rank identification, interactive autocomplete, satellite map context,
and hint options with strict penalty enforcement.
"""

import random
import sqlite3
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, replace

from nicegui import ui

from taxo_trainer.db import (
    APP_DB_PATH,
    USER_DB_PATH,
    get_active_data_source,
    get_app_metadata,
    get_db_connection,
    get_user_streak,
    set_user_streak,
)
from taxo_trainer.engine.analytics import log_attempt
from taxo_trainer.engine.sampling import (
    SamplingFilter,
    TargetObservation,
    sample_next_question,
)
from taxo_trainer.engine.validator import (
    autocomplete_taxa,
    get_display_name,
    validate_user_guess,
)
from taxo_trainer.ui.components import (
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
        self.success_recorded: bool = False
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
        self.practice_taxa: list[str] = []
        self.question_filters: SamplingFilter | None = None
        self.draft_guess = ""

    def effective_filters(self) -> SamplingFilter:
        """Apply a temporary dashboard scope without changing saved preferences."""
        if not self.practice_taxa:
            return deepcopy(self.filters)
        return replace(self.filters, include_taxa=list(self.practice_taxa),
                       exclude_taxa=[], family=None, genus=None, misidentified_only=False)


@dataclass
class QuizController:
    """Client-local actions shared by Settings, Dashboard, and Quiz."""

    refresh: Callable[[], None]
    practise: Callable[[list[str]], bool]



def submit_guess(
    state: QuizViewState,
    app_conn: sqlite3.Connection,
    user_conn: sqlite3.Connection,
    active_ds: str,
    guess_text: str,
) -> None:
    """Validate a quiz submission and persist its outcome.

    Args:
        state: Current client quiz state.
        app_conn: Dataset connection used for validation and reference photos.
        user_conn: Connection used to record progress and streaks.
        active_ds: Dataset identifier for progress isolation.
        guess_text: Scientific or vernacular name submitted by the user.
    """
    if not state.current_question or not guess_text or not guess_text.strip():
        return

    res = validate_user_guess(
        app_conn,
        guess_text,
        state.current_question.taxon_key,
        lang=state.filters.language,
        min_count=(state.question_filters or state.filters).min_count,
    )
    state.last_validation_result = res

    if res.is_correct and res.matched_rank == "SPECIES":
        if state.success_recorded:
            return
        if not state.solved:
            state.solved = True
            state.is_incorrect = False
            state.current_streak += 1
            state.best_streak = max(state.best_streak, state.current_streak)
            set_user_streak(
                state.current_streak,
                state.best_streak,
                user_conn,
                data_source=active_ds,
            )

        state.matched_genus = state.current_question.genus
        state.matched_family = state.current_question.family
        log_attempt(
            user_conn,
            state.current_question.occurrence_id,
            state.current_question.taxon_key,
            res.matched_taxon_key or state.current_question.taxon_key,
            is_correct=True,
            used_hint=state.used_hint,
            data_source=active_ds,
        )
        state.success_recorded = True
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
        target_order_val = (
            target_row["order_name"]
            if target_row
            and "order_name" in target_row
            and target_row["order_name"]
            else None
        )

        if res.matched_rank == "GENUS":
            state.matched_genus = state.current_question.genus
            state.matched_family = state.current_question.family
        elif res.matched_rank == "FAMILY":
            state.matched_family = state.current_question.family
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
                data_source=active_ds,
            )
            state.last_feedback = {
                "type": "error",
                "message": res.feedback_message,
            }

            if res.matched_rank in ("GENUS", "FAMILY"):
                state.diagnostic_guessed_name = res.matched_name
            else:
                guessed_row = app_conn.execute(
                    "SELECT * FROM taxa WHERE taxon_key = ?",
                    (res.matched_taxon_key,),
                ).fetchone()
                if guessed_row:
                    g_disp = get_display_name(
                        guessed_row, lang=state.filters.language
                    )
                    g_sci = guessed_row["canonical_name"]
                    state.diagnostic_guessed_name = (
                        f"{g_disp} ({g_sci})" if g_disp != g_sci else g_sci
                    )
                else:
                    state.diagnostic_guessed_name = res.matched_name or guess_text

            diag_cursor = app_conn.execute(
                "SELECT media_urls FROM occurrences WHERE taxon_key = ? LIMIT 1",
                (res.matched_taxon_key,),
            )
            diag_row = diag_cursor.fetchone()
            if diag_row and diag_row["media_urls"]:
                state.diagnostic_photo_url = (
                    diag_row["media_urls"].split("|")[0].strip()
                )
                if state.diagnostic_photo_url:
                    state.used_hint = True
        else:
            # Unrecognized taxon name (e.g. typing error) -> Warning message, do NOT log attempt
            state.last_feedback = {
                "type": "warning",
                "message": res.feedback_message,
            }


def render_quiz_view(
    state: QuizViewState,
    on_navigate_tab: callable | None = None,
    is_active: Callable[[], bool] | None = None,
) -> QuizController:
    """Render core quiz identification view.

    Layout structure:
      Top Header H
      Image Display I (75% width left canvas) | User Interface U (25% width right sidebar)

    Args:
        state: Per-client QuizViewState instance.
        on_navigate_tab: Optional callback to switch main app tab or open guide.
    """
    app_conn = get_db_connection(APP_DB_PATH)
    user_conn = get_db_connection(USER_DB_PATH)
    active_ds = get_active_data_source(app_conn)

    main_container = ui.column().classes(
        "w-full h-full flex-1 min-h-0 p-1 space-y-2 overflow-hidden"
    )

    if not state.streak_initialized:
        curr, best = get_user_streak(user_conn, data_source=active_ds)
        state.current_streak = curr
        state.best_streak = best
        state.streak_initialized = True

        # Load persistent filters from database metadata
        saved_min = get_app_metadata("min_count", "1", conn=app_conn)
        try:
            state.filters.min_count = max(1, int(saved_min))
        except ValueError:
            pass
        saved_mode = get_app_metadata("sampling_mode", "log", conn=app_conn)
        if saved_mode in ("flat", "natural", "log", "sqrt"):
            state.filters.mode = saved_mode
        saved_lang = get_app_metadata("language_preference", "da", conn=app_conn)
        if saved_lang:
            state.filters.language = saved_lang

        # Old name-only filters are retained for recovery, but cannot identify taxa.
        needs_scope_selection = any(
            get_app_metadata(f"{kind}_{active_ds}", "", conn=app_conn)
            and get_app_metadata(f"{kind}_ids_{active_ds}", "__missing__", conn=app_conn) == "__missing__"
            for kind in ("whitelist", "blacklist")
        )
        if needs_scope_selection:
            ui.notify("Please reselect your saved training groups after this update.", type="info")

        # Load persistent Whitelist (include_taxa) and Blacklist (exclude_taxa) per data_source
        saved_whitelist = get_app_metadata(f"whitelist_ids_{active_ds}", "", conn=app_conn)
        if saved_whitelist:
            state.filters.include_taxa = [
                t.strip() for t in saved_whitelist.split("|") if t.strip()
            ]
        else:
            state.filters.include_taxa = []

        saved_blacklist = get_app_metadata(f"blacklist_ids_{active_ds}", "", conn=app_conn)
        if saved_blacklist:
            state.filters.exclude_taxa = [
                t.strip() for t in saved_blacklist.split("|") if t.strip()
            ]
        else:
            state.filters.exclude_taxa = []

        state.streak_initialized = True

    def set_new_question(question: TargetObservation | None = None) -> None:
        """Sample next target observation question and refresh UI."""
        if state.is_incorrect and not state.solved:
            state.current_streak = 0
            set_user_streak(0, state.best_streak, user_conn, data_source=active_ds)

        state.is_incorrect = False
        state.used_hint = False
        state.solved = False
        state.success_recorded = False
        state.last_feedback = None
        state.last_validation_result = None
        state.diagnostic_photo_url = None
        state.diagnostic_guessed_name = None
        state.matched_genus = None
        state.matched_family = None
        state.matched_order = None
        state.draft_guess = ""
        state.question_filters = state.effective_filters()
        state.current_question = question or sample_next_question(
            app_conn, user_conn, state.question_filters, state.seen_set
        )
        refresh_quiz_ui()

    def load_new_question() -> None:
        set_new_question()

    def practise(keys: list[str]) -> bool:
        previous = state.practice_taxa
        state.practice_taxa = list(dict.fromkeys(str(key) for key in keys))
        if not state.practice_taxa:
            return False
        next_seen = set(state.seen_set)
        question = sample_next_question(app_conn, user_conn, state.effective_filters(), next_seen)
        if question is None:
            state.practice_taxa = previous
            ui.notify("No observations available for this selection at your current minimum observation count.", type="info")
            return False
        state.seen_set = next_seen
        set_new_question(question)
        return True

    def end_practice() -> None:
        state.practice_taxa = []
        load_new_question()

    def settings_changed() -> None:
        if state.current_question is None:
            load_new_question()
        else:
            refresh_quiz_ui()

    def handle_submit_guess(guess_text: str) -> None:
        """Apply the submission and refresh the quiz view."""
        state.draft_guess = ""
        submit_guess(state, app_conn, user_conn, active_ds, guess_text)
        refresh_quiz_ui()

    def handle_report_bad_observation() -> None:
        """Flag current observation as misidentified, omit from user statistics, and mark as seen."""
        if not state.current_question:
            return

        occ_id = state.current_question.occurrence_id
        state.seen_set.add(occ_id)

        # Delete any logged attempts for this occurrence_id from user_progress DB
        user_conn.execute(
            "DELETE FROM user_progress WHERE occurrence_id = ?", (occ_id,)
        )
        user_conn.commit()

        state.solved = True
        state.last_feedback = {
            "type": "warning",
            "message": "Saved attempts for this observation were removed. It may appear again in a later session.",
        }
        refresh_quiz_ui()

    def get_target_order(question) -> str:
        if not question:
            return ""
        q_key = str(question.taxon_key)
        r = app_conn.execute(
            "SELECT order_name FROM taxa WHERE taxon_key = ? OR taxon_key = ?",
            (question.taxon_key, q_key),
        ).fetchone()
        if r and r["order_name"]:
            return r["order_name"].strip()
        return ""

    def scope_key(rank: str) -> str | None:
        if not state.current_question:
            return None
        row = app_conn.execute(f"SELECT {rank}_key FROM taxa WHERE taxon_key=?",
                               (state.current_question.taxon_key,)).fetchone()
        return row[0] if row else None

    def handle_higher_order_hint() -> None:
        """Trigger sequential higher order rank revelation hint, revealing the highest current hidden rank."""
        if not state.current_question:
            return

        state.used_hint = True

        target_order = get_target_order(state.current_question)
        target_family = (state.current_question.family or "").strip()
        target_genus = (state.current_question.genus or "").strip()

        revealed_desc = None

        if target_order and not state.matched_order:
            state.matched_order = target_order
            revealed_desc = f"Order '{target_order}'"
        elif target_family and not state.matched_family:
            state.matched_family = target_family
            revealed_desc = f"Family '{target_family}'"
        elif target_genus and not state.matched_genus:
            state.matched_genus = target_genus
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
        """Trigger 1/5 distractor multiple choice hint restricted by revealed taxonomic scope."""
        if not state.current_question:
            return
        state.used_hint = True

        # Build SQL filter restricted to revealed taxonomic scope
        where_clauses = ["rank = 'SPECIES'"]
        params = []

        if state.matched_genus:
            where_clauses.append("genus_key = ?")
            params.append(scope_key("genus"))
        elif state.matched_family:
            where_clauses.append("family_key = ?")
            params.append(scope_key("family"))
        elif state.matched_order:
            where_clauses.append("order_key = ?")
            params.append(scope_key("order"))

        where_sql = " AND ".join(where_clauses)

        cursor = app_conn.execute(
            f"""
            SELECT taxon_key, canonical_name, scientific_name, vernacular_da, vernacular_en, vernacular_json
            FROM taxa
            WHERE {where_sql}
            """,
            params,
        )
        possible_rows = list(cursor.fetchall())

        target_key_str = str(state.current_question.taxon_key)
        target_row = app_conn.execute(
            "SELECT * FROM taxa WHERE taxon_key = ?",
            (target_key_str,),
        ).fetchone()

        target_disp = (
            get_display_name(target_row, lang=state.filters.language)
            if target_row
            else state.current_question.canonical_name
        )

        seen_names = {
            target_disp.lower(),
            state.current_question.canonical_name.lower(),
        }
        distractor_choices = []

        random.shuffle(possible_rows)

        for row in possible_rows:
            if str(row["taxon_key"]) == target_key_str:
                continue
            disp = get_display_name(row, lang=state.filters.language)
            c_name = row["canonical_name"].lower()
            if disp.lower() not in seen_names and c_name not in seen_names:
                seen_names.add(disp.lower())
                seen_names.add(c_name)
                distractor_choices.append((str(row["taxon_key"]), disp))
                if len(distractor_choices) >= 4:
                    break

        choices = [(target_key_str, target_disp)] + distractor_choices
        random.shuffle(choices)

        count_label = f"1/{len(choices)}"
        state.last_feedback = {
            "type": "choices",
            "message": f"Multiple Choice Options ({count_label}):",
            "choices": choices,
        }
        refresh_quiz_ui()

    nav_callbacks: dict = {}
    active_input: list = [None]
    is_input_focused: list[bool] = [False]

    def handle_key_event(e) -> None:
        """Global keyboard shortcut handler for observation and photo navigation."""
        if (is_active is not None and not is_active()) or not e.action.keydown:
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
        if (
            key_str in ("/", "f2") or (ctrl and key_str == "k")
        ) and not is_input_focused[0]:
            if inp:
                inp.run_method("focus")
            return

        # 3. Global navigation actions (only when input field is NOT focused)
        if not is_input_focused[0]:
            if (ctrl and e.key == "ArrowRight") or e.key in ("n", "N"):
                load_new_question()
            elif (
                e.key == "ArrowRight"
                or e.key in ("d", "D")
                or (alt and e.key == "ArrowRight")
            ) and nav_callbacks.get("next"):
                nav_callbacks["next"]()
            elif (
                e.key == "ArrowLeft"
                or e.key in ("a", "A")
                or (alt and e.key == "ArrowLeft")
            ) and nav_callbacks.get("prev"):
                nav_callbacks["prev"]()

    ui.keyboard(on_key=handle_key_event)

    def refresh_quiz_ui() -> None:
        """Re-render reactive quiz interface using 75% Image / 25% UI layout."""
        is_input_focused[0] = False
        main_container.clear()
        with main_container:
            if state.practice_taxa:
                names = []
                for key in state.practice_taxa:
                    row = app_conn.execute("SELECT * FROM taxa WHERE taxon_key=?", (key,)).fetchone()
                    if row is None:
                        row = app_conn.execute("SELECT * FROM higher_ranks WHERE taxon_key=?", (key,)).fetchone()
                    names.append(get_display_name(row, state.filters.language))
                with ui.row().classes("w-full items-center justify-between bg-tt-raised p-2"):
                    ui.label("Practising: " + " / ".join(names)).classes("text-sm text-tt-main")
                    ui.button("Return to previous practice", on_click=end_practice).props("flat dense")
            if state.current_question and state.question_filters and replace(state.question_filters, language=state.filters.language) != state.effective_filters():
                ui.label("Training changes apply to your next observation.").classes("text-sm text-tt-muted")
            if not state.current_question:
                with (
                    ui.column().classes(
                        "w-full h-full items-center justify-center p-6 max-w-3xl mx-auto text-center my-auto"
                    ),
                    ui.card().classes(
                        "w-full p-8     border border-tt-primary rounded-2xl shadow-2xl space-y-6 items-center"
                    ),
                ):
                    ui.icon("nature_people", size="xl").classes("text-tt-positive")
                    has_data = app_conn.execute("SELECT 1 FROM taxa LIMIT 1").fetchone() is not None
                    ui.label("No matching observations" if has_data else "Welcome to Taxo-Trainer! 🌿").classes(
                        "text-3xl font-extrabold text-tt-main tracking-tight"
                    )
                    ui.label(
                        "Your current training settings do not match any available observations." if has_data else "No species observation dataset is currently loaded in your database."
                    ).classes("text-base text-tt-main font-medium")
                    ui.label(
                        "Adjust your training groups or minimum observations per taxon in Settings & Data." if has_data else "Taxo-Trainer requires species observation data from GBIF DarwinCore archives to generate identification flashcards. Get started quickly by following the initial setup guide!"
                    ).classes("text-sm text-tt-muted max-w-xl leading-relaxed")

                    with ui.row().classes("gap-4 pt-4 justify-center items-center"):
                        if on_navigate_tab:
                            ui.button(
                                "📖 Start Initial Setup Guide",
                                color="warning",
                                on_click=lambda: on_navigate_tab(
                                    "guides", "initial_dataset_setup"
                                ),
                            ).classes("font-bold text-sm px-6 py-2 shadow-lg")
                            ui.button(
                                "⚙️ Go to Settings & Data",
                                color="primary",
                                on_click=lambda: on_navigate_tab("settings"),
                            ).classes(
                                "font-bold text-sm px-6 py-2 border border-tt-primary"
                            )
                        else:
                            ui.button(
                                "Load Observation",
                                on_click=load_new_question,
                                color="primary",
                            ).classes("font-bold text-sm px-6 py-2")
                return

            # Main split container: 75% Image Display (I) | 25% User Interface (U)
            with ui.row().classes("w-full h-full gap-3 no-wrap items-stretch"):
                # =========================================================
                # LEFT COLUMN (I): 75% Width Reserved for Whole Image Display
                # =========================================================
                with ui.column().classes(
                    "w-[75%] h-full flex flex-col flex-grow justify-between"
                ):
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
                with ui.column().classes(
                    "w-[25%] min-w-[280px] h-full bg-tt-surface rounded-lg p-3 space-y-3 overflow-y-auto shadow-xl border border-tt-border"
                ):
                    # Phenology & Context Info
                    with ui.row().classes(
                        "w-full justify-between items-center bg-tt-raised p-2 rounded-md"
                    ):
                        render_phenology_badge(
                            state.current_question.month,
                            state.current_question.event_date,
                        )
                        ui.label(f"Rank: {state.filters.rank}").classes(
                            "text-xs text-tt-main font-bold"
                        )

                    # Next Observation
                    with ui.row().classes("w-full justify-between items-center gap-1"):
                        ui.button(
                            "Next Observation ▶  [ n ]",
                            color="positive"
                            if (state.solved or state.last_feedback)
                            else "primary",
                            on_click=load_new_question,
                        ).classes("w-full font-bold text-xs py-1 shadow")

                    # Input & Guess Submission Box
                    with ui.card().classes(
                        "w-full p-3 bg-tt-raised text-tt-main rounded-md shadow-sm border border-tt-border space-y-2"
                    ):
                        # Streak Info
                        with ui.row().classes("w-full justify-between items-center"):
                            with ui.row().classes("items-center gap-1.5"):
                                ui.icon("whatshot", color="warning").classes(
                                    "text-sm"
                                )
                                ui.label(f"Streak: {state.current_streak}").classes(
                                    "text-xs font-bold text-tt-warning"
                                )
                            with ui.row().classes("items-center gap-1.5"):
                                ui.icon("emoji_events", color="warning").classes(
                                    "text-sm"
                                )
                                ui.label(f"Record: {state.best_streak}").classes(
                                    "text-xs font-bold text-tt-warning"
                                )

                        with ui.row().classes("w-full justify-between items-center"):
                            ui.label("Identify Taxon:").classes(
                                "font-bold text-xs text-tt-main"
                            )
                            ui.label("Esc: focus / defocus").classes(
                                "text-xs text-tt-warning font-mono"
                            )

                        input_field = (
                            ui.input(
                                value=state.draft_guess,
                                placeholder="Species, genus, or family",
                            )
                            .classes("w-full text-xs text-tt-main")
                            .props('outlined dense clearable aria-label="Identify Taxon"')
                        )

                        active_input[0] = input_field

                        # Dynamic Autocomplete Suggestion Chips
                        suggestions_container = ui.column().classes(
                            "w-full gap-1 hidden max-h-36 overflow-y-auto"
                        )

                        def on_focus() -> None:
                            is_input_focused[0] = True

                        def on_blur() -> None:
                            is_input_focused[0] = False

                        input_field.on("focus", on_focus)
                        input_field.on("blur", on_blur)
                        input_field.on(
                            "keydown.escape", lambda: input_field.run_method("blur")
                        )

                        def update_suggestions(e) -> None:
                            text = e.value
                            state.draft_guess = text or ""
                            if not text or len(text.strip()) < 2:
                                suggestions_container.classes(add="hidden")
                                return
                            matches = autocomplete_taxa(
                                app_conn,
                                text,
                                limit=5,
                                min_count=(state.question_filters or state.filters).min_count,
                                lang=state.filters.language,
                                parent_genus=scope_key("genus") if state.matched_genus else None,
                                parent_family=scope_key("family") if state.matched_family else None,
                                parent_order=scope_key("order") if state.matched_order else None,
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
                                            on_click=lambda v=val_txt: (
                                                handle_submit_guess(v)
                                            ),
                                        ).props("outline dense color=accent").classes(
                                            "text-xs w-full text-left truncate"
                                        )

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
                                parent_genus=scope_key("genus") if state.matched_genus else None,
                                parent_family=scope_key("family") if state.matched_family else None,
                                parent_order=scope_key("order") if state.matched_order else None,
                            )
                            if matches:
                                handle_submit_guess(matches[0]["value"])
                            else:
                                handle_submit_guess(val)

                        input_field.on("keydown.enter", handle_enter_submission)

                        with ui.row().classes(
                            "w-full justify-between items-center gap-1 mt-1"
                        ):
                            ui.button(
                                "Submit",
                                color="primary",
                                on_click=handle_enter_submission,
                            ).classes("w-full font-bold text-xs")

                    # Hints Controls Card & Misidentification Flag
                    with ui.card().classes(
                        "w-full p-2 bg-tt-raised text-tt-main rounded-md shadow-sm border border-tt-border"
                    ):
                        ui.label("Hints & Feedback").tooltip("Hints mark the observation as assisted and exclude it from unassisted accuracy.").classes(
                            "text-xs font-bold text-tt-muted mb-1"
                        )
                        with ui.row().classes("w-full justify-between gap-1"):
                            ui.button(
                                "Reveal next rank",
                                on_click=handle_higher_order_hint,
                                color="warning",
                            ).props("flat dense").classes("text-xs")
                            ui.button(
                                "Multiple choice",
                                on_click=handle_multiple_choice_hint,
                                color="warning",
                            ).props("flat dense").classes("text-xs")

                        ui.button(
                            "Ignore observation",
                            on_click=handle_report_bad_observation,
                            color="negative",
                            icon="report_problem",
                        ).props("flat dense").classes(
                            "text-xs w-full text-tt-negative mt-1"
                        ).tooltip("Remove this observation's saved attempts from your statistics. No report is sent to GBIF.")

                    # Feedback Message Banner & Multi-Rank Hierarchy Breakdown
                    if state.last_feedback:
                        fb_type = state.last_feedback.get("type", "info")
                        bg_cls = (
                            "bg-tt-positive-soft text-tt-main"
                            if fb_type == "success"
                            else (
                                "bg-tt-negative-soft text-tt-main"
                                if fb_type == "error"
                                else (
                                    "bg-tt-primary-soft text-tt-main"
                                    if fb_type == "info"
                                    else "bg-tt-warning-soft text-tt-main"
                                )
                            )
                        )

                        with ui.card().classes(
                            f"w-full p-3 text-center rounded-md shadow-md {bg_cls}"
                        ):
                            ui.label(state.last_feedback["message"]).classes(
                                "text-xs font-bold"
                            )

                            # Render Multiple Choice (1/5) Buttons if active
                            if (
                                fb_type == "choices"
                                and "choices" in state.last_feedback
                            ):
                                with ui.column().classes("w-full gap-1 mt-2"):
                                    for choice_key, choice_label in state.last_feedback["choices"]:
                                        ui.button(
                                            choice_label,
                                            on_click=lambda l=choice_key: (
                                                handle_submit_guess(l)
                                            ),
                                            color="secondary",
                                        ).props("outline dense").classes(
                                            "bg-tt-raised text-tt-main font-medium text-xs w-full"
                                        )

                        # Multi-Level Taxonomic Hierarchy Feedback (Order, Family, Genus, Species)
                        target_row_query = app_conn.execute(
                            "SELECT * FROM taxa WHERE taxon_key = ?",
                            (state.current_question.taxon_key,),
                        ).fetchone()
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

                    # Diagnostic Reference Photo (on wrong guess)
                    if state.diagnostic_photo_url:
                        with ui.card().classes(
                            "w-full p-3 bg-tt-raised text-tt-main rounded-md shadow-sm border border-tt-border"
                        ):
                            diag_label = (
                                f"Diagnostic Reference (Guessed '{state.diagnostic_guessed_name}'):"
                                if state.diagnostic_guessed_name
                                else "Diagnostic Reference (Guessed Species):"
                            )
                            ui.label(diag_label).classes(
                                "font-bold text-xs text-tt-warning mb-1"
                            )

                            ui.element("img").props(
                                f'src="{state.diagnostic_photo_url}"'
                            ).style(
                                "max-width: 100%; max-height: 128px; object-fit: scale-down; display: block; margin: auto; border-radius: 4px;"
                            )

                    # Compact Location Satellite Map Card
                    render_satellite_map(
                        state.current_question.latitude,
                        state.current_question.longitude,
                        state.current_question.locality,
                    )

                    if not state.practice_taxa:
                        # Taxa Whitelist / Blacklist Filter Drawer
                        with ui.expansion(
                            "Training groups", icon="filter_alt"
                        ).classes(
                            "w-full bg-tt-raised text-xs text-tt-warning rounded-md border border-tt-border p-0"
                        ):
                            render_taxa_filter_controls(
                                app_conn,
                                state.filters,
                                on_changed=load_new_question,
                            )

    # Initial render load
    if not state.current_question:
        load_new_question()
    else:
        refresh_quiz_ui()

    return QuizController(refresh=settings_changed, practise=practise)
