"""Data-driven guides models and registry for taxo-trainer.

Provides structured definitions for in-app setup guides, dataset creation guides,
and application page walkthroughs.
"""

from dataclasses import dataclass, field


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


# ==============================================================================
# IN-APP GUIDES REGISTRY
# ==============================================================================

INITIAL_DATASET_SETUP_GUIDE = Guide(
    id="initial_dataset_setup",
    title="Initial Default Dataset Setup",
    description="Step-by-step walkthrough for configuring and ingesting the default species dataset on a fresh clone.",
    category="Setup & Onboarding",
    icon="rocket_launch",
    steps=[
        GuideStep(
            step_number=1,
            title="Welcome & Database Status",
            description="When first launching Taxo-Trainer on a fresh clone, no observation dataset is loaded yet. Taxo-Trainer relies on GBIF DarwinCore occurrence archives to present real-world visual identification questions.",
            image_path="assets/guides/setup_step1.png",
        ),
        GuideStep(
            step_number=2,
            title="Navigate to Settings & Data",
            description="Locate the top navigation header bar and click on the 'Settings & Data' tab (gear icon). This tab contains all dataset management and ingestion tools.",
            image_path="assets/guides/setup_step2.png",
        ),
        GuideStep(
            step_number=3,
            title="Ingest Default DarwinCore Dataset",
            description="In the 'DarwinCore (DwC) Occurrence Ingestion' card, the default curated Nordic flora dataset download URL is pre-filled. Click 'Start Ingestion' (or 'Re-Ingest Dataset') to stream occurrence records directly into local SQLite database (app_data.db).",
            image_path="assets/guides/setup_step3.png",
        ),
        GuideStep(
            step_number=4,
            title="Fetch Vernacular Name Enrichment",
            description="Once ingestion completes, scroll down to the 'GBIF Vernacular Name Enrichment' card and click 'Fetch Vernacular Names from GBIF API'. This populates Danish and English common names for all species and genera.",
            image_path="assets/guides/setup_step4.png",
        ),
        GuideStep(
            step_number=5,
            title="Ready to Practice!",
            description="Switch back to the 'Quiz' tab.",
            image_path="assets/guides/setup_step5.png",
        ),
        GuideStep(
            step_number=6,
            title="Practice with High-Resolution Photos",
            description="Practice multi-rank taxonomic identification using high-resolution observation photos.",
            image_path="assets/guides/setup_step6.png",
        ),
    ],
)

ADDING_CUSTOM_DATASETS_GUIDE = Guide(
    id="adding_custom_datasets",
    title="Adding Custom GBIF Datasets",
    description="Guide on how to export, configure, and ingest custom DarwinCore occurrence datasets directly from GBIF.org.",
    category="Data Management",
    icon="add_chart",
    steps=[
        GuideStep(
            step_number=1,
            title="Navigate to GBIF Occurrences Search",
            description="Open GBIF.org in your web browser, navigate to the desired dataset search, and click 'Occurrences' in the top main navigation menu.",
            image_path="assets/dataset_guide/frontpage.png",
        ),
        GuideStep(
            step_number=2,
            title="Filter Target Area and Taxa",
            description="Apply filters for your target geographic region, seasonality, or taxonomic groups. Keeping dataset size under 1,000,000 observations is recommended for desktop performance.",
            image_path="assets/dataset_guide/occ_search.png",
        ),
        GuideStep(
            step_number=3,
            title="Select DarwinCore Archive Download",
            description="Select the 'Download' tab, choose 'DarwinCore Archive', and click 'Configure' to open archive export options.",
            image_path="assets/dataset_guide/occ_download_archive.png",
        ),
        GuideStep(
            step_number=4,
            title="Locate Multimedia Extension",
            description="In the archive configuration panel, scroll down to locate the 'Format' section and the 'Multimedia' extension list.",
            image_path="assets/dataset_guide/occ_download_config_1.png",
        ),
        GuideStep(
            step_number=5,
            title="Enable Multimedia Extension",
            description="Select the 'Multimedia' extension checkbox (required for field photo URLs) and click 'Continue to Terms'.",
            image_path="assets/dataset_guide/occ_download_config_2.png",
        ),
        GuideStep(
            step_number=6,
            title="Acknowledge Terms & Create Download",
            description="Review the GBIF Data License terms (CC BY 4.0), check the agreement box, and click 'Create Download'. GBIF will prepare the export archive.",
            image_path="assets/dataset_guide/occ_download_terms.png",
        ),
        GuideStep(
            step_number=7,
            title="Copy Archive Download Link",
            description="Once the export is ready, right-click the 'Download archive' button and select 'Copy link address' to copy the direct ZIP download URL to your clipboard.",
            image_path="assets/dataset_guide/occ_download_link.png",
        ),
        GuideStep(
            step_number=8,
            title="Clear Current Data Source (Optional)",
            description="In Taxo-Trainer, open 'Settings & Data' tab. If replacing an existing dataset, click 'Clear current data source' to purge previous records.",
            image_path="assets/dataset_guide/source_clear.png",
        ),
        GuideStep(
            step_number=9,
            title="Import Archive & Enrich Names",
            description="Paste the copied ZIP URL into the DwC Ingestion input box and click 'Start Ingestion'. Afterward, click 'Fetch Danish Names from GBIF API' to enrich common names.",
            image_path="assets/dataset_guide/archive_import.png",
        ),
    ],
)

QUIZ_PAGE_WALKTHROUGH_GUIDE = Guide(
    id="quiz_page_walkthrough",
    title="Quiz & Identification View",
    description="Walkthrough of the core interactive photo quiz canvas, keyboard shortcuts, multi-rank validation, and structured hint mechanics.",
    category="Page Walkthroughs",
    icon="quiz",
    steps=[
        GuideStep(
            step_number=1,
            title="Photo Inspection Canvas & Map Toggle",
            description=(
                "Inspect high-resolution field photos. Use keyboard shortcuts (Left Arrow / Right "
                "Arrow) to cycle through observation photos. Click 'Toggle Satellite Map' to inspect "
                "observation coordinates on Esri satellite (or view the small map in the bottom "
                "right). You can also see additional information about the observation, such as the "
                "number of images, the place-name, when it was taken, and by whom."
            ),
            image_path="assets/guides/quiz_step1.png",
        ),
        GuideStep(
            step_number=2,
            title="Interactive Multi-Word Autocomplete",
            description=(
                'Select the "Identify Taxon" input field either by clicking it or '
                "pressing ESC (ESC again to deselect). Type taxa names (e.g. species, genus, or family) in "
                "scientific or vernacular languages (Danish/English). Autocomplete matches "
                "space-separated prefix tokens (e.g. 'alm fred' matches 'Almindelig Fredløs')."
            ),
            image_path="assets/guides/quiz_step2.png",
        ),
        GuideStep(
            step_number=3,
            title="Multi-Rank Taxonomic Hierarchy Feedback",
            description=(
                "Guesses can be submitted at any rank (Family, Genus, Species). The visual "
                "hierarchy feedback tree highlights correct rank matches (green), incorrect guesses "
                "(red), and unrevealed scope."
            ),
            image_path="assets/guides/quiz_step3.png",
        ),
        GuideStep(
            step_number=4,
            title="Structured Hints & Diagnostic Comparisons",
            description="Request higher-order rank hints or 1/5 multiple choice candidates.",
            image_path="assets/guides/quiz_step4.png",
        ),
        GuideStep(
            step_number=5,
            title="Streak & Record Tracking",
            description=(
                "Track your current unassisted identification streak (🔥) and personal best record (🏆). "
                "The streak is broken only when you go to the next observation while the taxonomic "
                "breakdown contains an incorrect taxon. For convenience this means that subsequent guesses "
                "can override an inconvenient guess. This feature is included mainly due to the "
                "frustration that can be had when a guess is registered as wrong because of a number "
                "of invalid reasons including: incorrect taxon labels on GBIF (e.g. from incorrect "
                "identifications in iNaturalist) or ambiguous photos with multiple species. This also "
                "means that you can simply choose to skip an image if you don't want to try and identify "
                "it because the quality is poor, or the taxon is simply too exotic for you yet."
            ),
            image_path="assets/guides/quiz_step5.png",
        ),
        GuideStep(
            step_number=6,
            title="Next observation",
            description=(
                'The next observation can be triggered by either clicking the "Next Observation" '
                "button or pressing the Ctrl + Right Arrow key. "
                'Keep in mind that key-bindings only work when the "Identify Taxon" input field '
                "is deselected, which can be done by pressing the 'Esc' key."
            ),
            image_path="assets/guides/quiz_step6.png",
        ),
    ],
)

DASHBOARD_PAGE_WALKTHROUGH_GUIDE = Guide(
    id="dashboard_page_walkthrough",
    title="Analytics & Mastery Dashboard",
    description="Walkthrough of the analytics dashboard, performance metrics, family mastery breakdowns, and confusion matrix.",
    category="Page Walkthroughs",
    icon="insights",
    steps=[
        GuideStep(
            step_number=1,
            title="Core Mastery & Accuracy Metrics",
            description="View overall training performance statistics: Total Attempts, Unassisted Accuracy percentage, Active/Best Streaks, and Mastered Species count (≥90% accuracy over ≥5 attempts).",
            image_path="assets/guides/dashboard_step1.png",
        ),
        GuideStep(
            step_number=2,
            title="Time-Range Metrics Filtering",
            description="Filter accuracy metrics across specific time frames: 1 Hour, 24 Hours, 7 Days, 30 Days, 1 Year, or All Time to monitor your learning curve over time.",
            image_path="assets/guides/dashboard_step2.png",
        ),
        GuideStep(
            step_number=3,
            title="Accuracy over time",
            description="Track your accuracy over time with the EMA (Exponential Moving Average) accuracy line. You can adjust the time-window displayed in the graph at the bottom and change the number of items used in the EMA average.",
            image_path="assets/guides/dashboard_step3.png",
        ),
        GuideStep(
            step_number=4,
            title="Taxa Mastery & Trouble Taxa",
            description="Identify taxa where your identification accuracy is highest and lowest, which can be helpful when choosing what to practice next. You can change both the taxonomic level which is displayed and how many taxa are shown.",
            image_path="assets/guides/dashboard_step4.png",
        ),
        GuideStep(
            step_number=5,
            title="Taxonomic Confusion Matrix",
            description="Inspect pairwise misidentification logs (e.g. mistaking Cirsium palustre for Cirsium vulgare) to identify common visual lookalike pairs and target weak points.",
            image_path="assets/guides/dashboard_step5.png",
        ),
    ],
)

# Complete list of available in-app guides
GUIDE_REGISTRY: list[Guide] = [
    INITIAL_DATASET_SETUP_GUIDE,
    ADDING_CUSTOM_DATASETS_GUIDE,
    QUIZ_PAGE_WALKTHROUGH_GUIDE,
    DASHBOARD_PAGE_WALKTHROUGH_GUIDE,
]


def get_guide_by_id(guide_id: str) -> Guide | None:
    """Retrieve a guide from the registry by its unique identifier.

    Args:
        guide_id: Unique string identifier of the guide.

    Returns:
        Guide object if found, otherwise None.
    """
    for guide in GUIDE_REGISTRY:
        if guide.id == guide_id:
            return guide
    return None
