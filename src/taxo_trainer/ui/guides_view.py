"""Interactive Data-Driven Guides View for taxo-trainer.

Renders guide menu catalog, step-by-step screenshot walkthroughs, forward/backward navigation,
and keyboard bindings (Arrow keys, A/D, Esc).
"""

from nicegui import ui

from taxo_trainer.engine.guides import (
    GUIDE_REGISTRY,
    Guide,
    get_guide_by_id,
)


class GuidesViewState:
    """State wrapper for GuidesView connection."""

    def __init__(self, initial_guide_id: str | None = None) -> None:
        self.selected_guide_id: str | None = initial_guide_id
        self.current_step_idx: int = 0

    def select_guide(self, guide_id: str) -> None:
        """Select active guide and reset step index to start."""
        self.selected_guide_id = guide_id
        self.current_step_idx = 0

    def return_to_menu(self) -> None:
        """Return to guide menu list view."""
        self.selected_guide_id = None
        self.current_step_idx = 0

    def next_step(self) -> None:
        """Advance to next step if available."""
        if not self.selected_guide_id:
            return
        guide = get_guide_by_id(self.selected_guide_id)
        if guide and self.current_step_idx < len(guide.steps) - 1:
            self.current_step_idx += 1

    def prev_step(self) -> None:
        """Go back to previous step if available."""
        if self.selected_guide_id and self.current_step_idx > 0:
            self.current_step_idx -= 1


def render_guides_view(
    state: GuidesViewState,
    on_navigate_tab: callable | None = None,
) -> None:
    """Render interactive data-driven guides catalog and step-by-step viewer.

    Args:
        state: Connection-scoped GuidesViewState instance.
        on_navigate_tab: Optional callback to switch main app tab (e.g. 'quiz' or 'settings').
    """
    container = ui.column().classes(
        "w-full h-full p-4 overflow-y-auto max-w-7xl mx-auto space-y-4"
    )

    def handle_key_event(e) -> None:
        """Keyboard navigation handler for guide step viewer."""
        if not e.action.keydown:
            return

        key = str(e.key)

        # 1. Escape key returns to guide menu from any step
        if key in ("Escape", "Esc"):
            if state.selected_guide_id is not None:
                state.return_to_menu()
                refresh_view()
            return

        # If in active guide step viewer, handle next / prev step shortcuts
        if state.selected_guide_id is not None:
            if key in ("ArrowRight", "d", "D"):
                state.next_step()
                refresh_view()
            elif key in ("ArrowLeft", "a", "A"):
                state.prev_step()
                refresh_view()

    ui.keyboard(on_key=handle_key_event)

    def refresh_view() -> None:
        container.clear()
        with container:
            if state.selected_guide_id is None:
                render_guide_menu()
            else:
                guide = get_guide_by_id(state.selected_guide_id)
                if not guide:
                    state.return_to_menu()
                    render_guide_menu()
                else:
                    render_guide_step_viewer(guide)

    def render_guide_menu() -> None:
        """Render catalog menu of all available guides."""
        # Top Header Banner
        with ui.row().classes(
            "w-full justify-between items-center bg-tt-surface p-5 rx-12 rounded-xl border border-tt-border shadow-lg mb-2"
        ):
            with ui.row().classes("items-center gap-3"):
                ui.icon("menu_book", size="md").classes("text-tt-primary")
                with ui.column().classes("gap-0"):
                    ui.label("Interactive Application Guides").classes(
                        "text-2xl font-bold tracking-tight text-tt-main"
                    )
                    ui.label(
                        "Learn how to configure datasets, practice identification, and use all Taxo-Trainer features."
                    ).classes("text-sm text-tt-muted")

            ui.chip("⌨️ Nav: Arrow Keys / A-D | Menu: Esc", color="primary").classes(
                "text-xs text-tt-primary"
            )

        # Featured / Onboarding Hero Banner
        with (
            ui.card().classes(
                "w-full p-5     rounded-xl border border-tt-primary shadow-xl"
            ),
            ui.row().classes("w-full justify-between items-center gap-4"),
            ui.row().classes("items-center gap-4 flex-1"),
        ):
            ui.icon("rocket_launch", size="lg").classes("text-tt-warning")
            with ui.column().classes("gap-1"):
                ui.label("First Session? Start Here!").classes(
                    "text-lg font-bold text-tt-main"
                )
                ui.label(
                    "Follow the 'Initial Default Dataset Setup' guide to configure species data and start your first quiz session."
                ).classes("text-sm text-tt-main")

            ui.button(
                "Start Initial Setup Guide ▶",
                color="warning",
                on_click=lambda: (
                    state.select_guide("initial_dataset_setup"),
                    refresh_view(),
                ),
            ).classes("font-bold text-sm px-4 py-2 shadow-md")

        # Group Guides by Category
        categories: dict[str, list[Guide]] = {}
        for guide in GUIDE_REGISTRY:
            categories.setdefault(guide.category, []).append(guide)

        for category_name, guides in categories.items():
            ui.label(category_name).classes(
                "text-lg font-bold text-tt-main mt-4 border-b border-tt-border pb-1 w-full"
            )

            with ui.grid().classes(
                "w-full grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4"
            ):
                for g in guides:
                    with (
                        ui.card()
                        .classes(
                            "w-full p-4 bg-tt-surface hover:bg-tt-raised rounded-xl border border-tt-border shadow-md flex flex-col justify-between space-y-3 cursor-pointer transition-all hover:border-tt-primary"
                        )
                        .on(
                            "click",
                            lambda _, gid=g.id: (
                                state.select_guide(gid),
                                refresh_view(),
                            ),
                        )
                    ):
                        with ui.column().classes("w-full gap-2"):
                            with ui.row().classes(
                                "w-full justify-between items-center"
                            ):
                                ui.icon(g.icon, size="sm").classes("text-tt-primary")
                                ui.badge(
                                    f"{len(g.steps)} Steps", color="secondary"
                                ).classes(
                                    "text-xs text-tt-main border border-tt-border"
                                )

                            ui.label(g.title).classes(
                                "text-base font-bold text-tt-main"
                            )
                            ui.label(g.description).classes(
                                "text-xs text-tt-muted line-clamp-3 leading-relaxed"
                            )

                        with ui.row().classes("w-full justify-end pt-2"):
                            ui.button(
                                "Start Guide ▶",
                                color="primary",
                                on_click=lambda _, gid=g.id: (
                                    state.select_guide(gid),
                                    refresh_view(),
                                ),
                            ).classes("text-xs font-bold py-1 px-3")

    def render_guide_step_viewer(guide: Guide) -> None:
        """Render active step screen for a selected guide."""
        step_idx = state.current_step_idx
        step = guide.steps[step_idx]
        total_steps = len(guide.steps)
        is_first = step_idx == 0
        is_last = step_idx == total_steps - 1

        # Top Navigation Bar
        with ui.row().classes(
            "w-full justify-between items-center bg-tt-surface p-4 rounded-xl stroke-gray-800 border border-tt-border shadow-md"
        ):
            ui.button(
                "← Return to Guide Menu",
                color="secondary",
                on_click=lambda: (state.return_to_menu(), refresh_view()),
            ).classes("text-xs font-bold border border-tt-border hover:bg-tt-raised")

            with ui.row().classes("items-center gap-2"):
                ui.icon(guide.icon, size="xs").classes("text-tt-primary")
                ui.label(guide.title).classes("text-base font-bold text-tt-main")

            ui.chip(f"Step {step_idx + 1} of {total_steps}", color="primary").classes(
                "text-xs text-tt-primary font-bold"
            )

        # Main Step Content Card
        with ui.card().classes(
            "w-full p-5 bg-tt-surface rounded-xl border border-tt-border shadow-xl space-y-4"
        ):
            # Step Title & Description
            with ui.row().classes("w-full items-start gap-3"):
                ui.badge(f"{step.step_number}", color="warning").classes(
                    "text-sm font-bold px-3 py-1 rounded-full text-tt-main"
                )
                with ui.column().classes("gap-1 flex-1"):
                    ui.label(step.title).classes("text-xl font-bold text-tt-main")
                    ui.label(step.description).classes(
                        "text-sm text-tt-main leading-relaxed"
                    )

            # Only show an image when the guide supplies a current illustration.
            if step.image_path:
                with ui.column().classes(
                    "w-full items-center justify-center bg-tt-page p-2 rounded-lg border border-tt-border overflow-hidden shadow-inner"
                ):
                    ui.image(step.image_path).props("fit=contain img-class=object-contain").classes(
                        "w-full max-h-[500px] object-contain rounded"
                    )

            # Step Navigation Control Bar
            with ui.row().classes(
                "w-full justify-between items-center pt-2 border-t border-tt-border"
            ):
                ui.button(
                    "◀ Previous [ A / ← ]",
                    color="secondary",
                    on_click=lambda: (state.prev_step(), refresh_view()),
                ).classes("text-xs font-bold text-tt-main").set_visibility(
                    not is_first
                )

                ui.button(
                    "Guide Menu [ Esc ]",
                    color="secondary",
                    on_click=lambda: (state.return_to_menu(), refresh_view()),
                ).classes("text-xs font-bold text-tt-muted border border-tt-border")

                if not is_last:
                    ui.button(
                        "Next ▶ [ D / → ]",
                        color="primary",
                        on_click=lambda: (state.next_step(), refresh_view()),
                    ).classes("text-xs font-bold px-4")
                else:
                    ui.button(
                        "🎉 Return to Guide Menu",
                        color="positive",
                        on_click=lambda: (state.return_to_menu(), refresh_view()),
                    ).classes("text-xs font-bold px-4")

        # Completion Banner on Final Step
        if is_last:
            with (
                ui.card().classes(
                    "w-full p-4 bg-tt-positive-soft border border-tt-positive rounded-xl shadow-lg"
                ),
                ui.row().classes("w-full justify-between items-center gap-4"),
            ):
                with ui.row().classes("items-center gap-3 flex-1"):
                    ui.icon("check_circle", size="md").classes("text-tt-positive")
                    with ui.column().classes("gap-0"):
                        ui.label("Guide Complete!").classes(
                            "text-base font-bold text-tt-positive"
                        )
                        ui.label(
                            "You have completed all steps in this guide. You can return to the guide menu or jump straight into practicing!"
                        ).classes("text-xs text-tt-positive")

                with ui.row().classes("items-center gap-2"):
                    if guide.id == "initial_dataset_setup" and on_navigate_tab:
                        ui.button(
                            "🚀 Go to Settings & Ingest",
                            color="warning",
                            on_click=lambda: on_navigate_tab("settings"),
                        ).classes("text-xs font-bold py-1 px-3")

                    ui.button(
                        "Return to Guide Menu",
                        color="positive",
                        on_click=lambda: (state.return_to_menu(), refresh_view()),
                    ).classes("text-xs font-bold py-1 px-3")

    refresh_view()
