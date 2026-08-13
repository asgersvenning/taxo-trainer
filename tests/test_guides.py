"""Unit tests for taxo-trainer interactive guides data and view state."""

import os

from taxo_trainer.ui.guides_data import (
    GUIDE_REGISTRY,
    Guide,
    GuideStep,
    get_guide_by_id,
)
from taxo_trainer.ui.guides_view import GuidesViewState


def test_guide_registry_integrity() -> None:
    """Verify that all guides in GUIDE_REGISTRY are valid and non-empty."""
    assert len(GUIDE_REGISTRY) >= 5

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
            assert step.image_path
            assert os.path.exists(step.image_path), f"Asset missing for step: {step.image_path}"


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
