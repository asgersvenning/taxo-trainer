"""Data-driven guides models and dynamic file loader engine for taxo-trainer.

Provides structured definitions for in-app setup guides, dataset creation guides,
and application page walkthroughs loaded dynamically from JSON files in assets/guides/.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class GuideStep:
    """Represents a single step within an interactive in-app guide.

    Attributes:
        step_number: 1-indexed step number.
        title: Concise title of the step.
        description: Detailed explanation of actions or features in this step.
        image_path: Path to annotated screenshot or diagram asset.
    """

    step_number: int
    title: str
    description: str
    image_path: str


@dataclass
class Guide:
    """Represents a complete structured interactive guide.

    Attributes:
        id: Unique string identifier for the guide.
        title: Human-readable guide title.
        description: Short summary of what the guide covers.
        category: Grouping category (e.g. "Setup & Onboarding", "Page Walkthroughs", "Data Management").
        icon: NiceGUI / Quasar icon name.
        steps: List of ordered GuideStep objects.
    """

    id: str
    title: str
    description: str
    category: str
    icon: str
    steps: list[GuideStep] = field(default_factory=list)


def load_guide_from_directory(guide_dir: Path) -> Guide | None:
    """Load a Guide object from a guide directory containing guide.json.

    Args:
        guide_dir: Path object pointing to directory containing guide.json.

    Returns:
        Guide object if guide.json exists and is valid, otherwise None.
    """
    json_path = guide_dir / "guide.json"
    if not json_path.exists():
        return None

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        steps = []
        for s in data.get("steps", []):
            img_filename = s.get("image_filename", "")
            img_path = str((guide_dir / img_filename).as_posix()) if img_filename else ""
            steps.append(
                GuideStep(
                    step_number=s.get("step_number", len(steps) + 1),
                    title=s.get("title", ""),
                    description=s.get("description", ""),
                    image_path=img_path,
                )
            )

        return Guide(
            id=data.get("id", guide_dir.name),
            title=data.get("title", guide_dir.name.replace("_", " ").title()),
            description=data.get("description", ""),
            category=data.get("category", "General"),
            icon=data.get("icon", "help"),
            steps=steps,
        )
    except (json.JSONDecodeError, OSError) as err:
        print(f"Error loading guide from {json_path}: {err}")
        return None


def load_all_guides(base_dir: str = "assets/guides") -> list[Guide]:
    """Scan base_dir for guide subdirectories and dynamically load all valid guides.

    Args:
        base_dir: Path to base directory containing guide subdirectories.

    Returns:
        Ordered list of Guide objects.
    """
    base_path = Path(base_dir)
    if not base_path.exists():
        return []

    # Preferred order of guide IDs for catalog presentation
    preferred_order = [
        "initial_dataset_setup",
        "adding_custom_datasets",
        "quiz_page_walkthrough",
        "dashboard_page_walkthrough",
    ]

    guides_by_id: dict[str, Guide] = {}
    for entry in base_path.iterdir():
        if entry.is_dir():
            guide = load_guide_from_directory(entry)
            if guide:
                guides_by_id[guide.id] = guide

    ordered_guides = []
    for gid in preferred_order:
        if gid in guides_by_id:
            ordered_guides.append(guides_by_id.pop(gid))

    # Append any additional discovered guides
    ordered_guides.extend(guides_by_id.values())
    return ordered_guides


# Dynamically loaded registry of guides
GUIDE_REGISTRY: list[Guide] = load_all_guides()


def get_guide_by_id(guide_id: str) -> Guide | None:
    """Retrieve a guide from the registry by its unique identifier.

    Args:
        guide_id: Unique string identifier of the guide.

    Returns:
        Guide object if found, otherwise None.
    """
    for guide in load_all_guides():
        if guide.id == guide_id:
            return guide
    return None
