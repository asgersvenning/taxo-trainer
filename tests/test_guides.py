"""Unit tests for taxo-trainer interactive guides data and view state."""

import os

import pytest
from nicegui import ui

from taxo_trainer.engine.guides import (
    GUIDE_REGISTRY,
    Guide,
    GuideStep,
    get_guide_by_id,
)
from taxo_trainer.ui.guides_view import GuidesViewState, render_guides_view


def test_guide_registry_integrity() -> None:
    """Verify that all guides in GUIDE_REGISTRY are valid and non-empty."""
    assert len(GUIDE_REGISTRY) >= 4

    guide_ids = set()
    for guide in GUIDE_REGISTRY:
        assert isinstance(guide, Guide)
        assert guide.id not in guide_ids, f"Duplicate guide ID: {guide.id}"
        guide_ids.add(guide.id)

        assert guide.title
        assert guide.description
        assert guide.category
        assert guide.icon
        assert len(guide.steps) > 0

        # Verify sequential step numbering and image path existence
        for idx, step in enumerate(guide.steps, start=1):
            assert isinstance(step, GuideStep)
            assert step.step_number == idx
            assert step.title
            assert step.description
            if step.image_path:
                assert os.path.exists(step.image_path), f"Asset missing for step: {step.image_path}"


@pytest.mark.parametrize("guide_id", ["settings_page_walkthrough", "quiz_page_walkthrough"])
def test_guide_steps_render_with_optional_images(guide_id: str) -> None:
    """Text-only steps remain readable and navigable without broken images."""
    guide = get_guide_by_id(guide_id)
    assert guide is not None
    with ui.column() as container:
        render_guides_view(GuidesViewState(guide_id))
    try:
        elements = list(container.descendants())
        assert any(isinstance(e, ui.label) and e.text == guide.steps[0].description for e in elements)
        images = [e for e in elements if isinstance(e, ui.image)]
        assert [e.source for e in images] == ([guide.steps[0].image_path] if guide.steps[0].image_path else [])
        next_button = next(e for e in elements if isinstance(e, ui.button) and e.text == "Next ▶ [ D / → ]")
        next(listener.handler for listener in next_button._event_listeners.values() if listener.type == "click")(None)
        assert any(isinstance(e, ui.label) and e.text == guide.steps[1].description for e in container.descendants())
    finally:
        container.delete()


def test_get_guide_by_id() -> None:
    """Test retrieving guides by ID."""
    guide = get_guide_by_id("initial_dataset_setup")
    assert guide is not None
    assert guide.title == "Initial Default Dataset Setup"

    non_existent = get_guide_by_id("invalid_guide_id_12345")
    assert non_existent is None


def test_guides_view_state_navigation() -> None:
    """Test state transitions for GuidesViewState."""
    state = GuidesViewState()
    assert state.selected_guide_id is None
    assert state.current_step_idx == 0

    state.select_guide("quiz_page_walkthrough")
    assert state.selected_guide_id == "quiz_page_walkthrough"
    assert state.current_step_idx == 0

    # Advance steps
    guide = get_guide_by_id("quiz_page_walkthrough")
    assert guide is not None
    total_steps = len(guide.steps)

    for i in range(1, total_steps):
        state.next_step()
        assert state.current_step_idx == i

    # Boundary check: calling next_step at end should stay at last step
    state.next_step()
    assert state.current_step_idx == total_steps - 1

    # Go back
    state.prev_step()
    assert state.current_step_idx == total_steps - 2

    # Return to menu
    state.return_to_menu()
    assert state.selected_guide_id is None
    assert state.current_step_idx == 0
