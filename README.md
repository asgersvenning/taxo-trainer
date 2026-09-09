# `Taxo-Trainer`

`Taxo-Trainer` is a desktop web application for practicing plant and wildlife identification using GBIF DarwinCore occurrence datasets. It features interactive photo quiz workflows, multi-rank taxonomic validation, structured hints, dataset filtering, and detailed analytics.

_**Note**: `taxo-trainer` is built around a "bring-your-own" data model. Review the licenses for the datasets and photographs you use._

---

## Features

### Quiz & Identification Interface

- **Photo Inspection Canvas**: High-resolution image viewer with keyboard-driven photo carousel (`Alt+Left` / `Alt+Right`), satellite map toggle (`Esri.WorldImagery`), observer attribution, and links to GBIF occurrence records.
- **Taxonomic Hierarchy Breakdown**: Visual hierarchy displaying Order, Family, Genus, and Species. Highlights correct rank matches, incorrect guesses, and unrevealed ranks.
- **Streak & Record Tracker**: Tracks active identification streaks (🔥) and personal best records (🏆) stored per dataset in SQLite.
- **Keyboard Shortcuts**:
  - `Ctrl + Right Arrow` or `n`: Advance to next observation
  - `Left / Right Arrow` or `a` / `d`: Navigate photo carousel
  - `Esc`: Leave the identification input (or focus it when it is not selected)
  - `Enter`: Select the first autocomplete candidate, or submit the typed guess if no candidate is shown
  - `/`, `F2`, or `Ctrl+K`: Focus the identification input

Photo and observation navigation shortcuts work when the identification input is not selected. Press `Esc` to leave it first.

### Autocomplete & Name Validation

- **Multi-Word Per-Word Prefix Autocomplete**: Matches space-separated tokens as prefix filters across species, genus, and family names (e.g. typing `"alm fred"` matches `"Almindelig Fredløs"`).
- **Multi-Rank & Multi-Language Support**: Accepts guesses at any rank level (Family, Genus, Species) in scientific names or vernacular names in the available supported languages; choose your preferred display language in Settings & Data.
- **Taxonomic Scope Interpolation**: Revealing or correctly guessing a higher rank (e.g. Family or Genus) automatically constrains autocomplete suggestions to taxa within that rank scope.

### Guided Hints & Assistance

- **Higher-Order Rank Hint**: Reveals the next unrevealed taxonomic rank (Order $\rightarrow$ Family $\rightarrow$ Genus $\rightarrow$ Species), updating the hierarchy display and scoping autocomplete choices.
- **1/5 Multiple Choice Hint**: Displays up to five candidate species choices strictly sampled from within the currently revealed taxonomic scope.
- **Unassisted Metric Enforcement**: Using any hint marks the attempt as assisted so it is excluded from unassisted accuracy metrics.

### Analytics & Mastery Dashboard

- **Time-Range Filters**: View performance statistics over 1 Hour, 24 Hours, 7 Days, 30 Days, 1 Year, or All Time.
- **Core Performance Metrics**: Tracks total attempts, unassisted accuracy percentage, active/best streaks, and mastered species counts ($\ge 90\%$ accuracy over $\ge 5$ attempts).
- **Family Mastery Breakdown**: Identifies highest-accuracy plant families and families requiring additional practice.
- **Trouble Taxa Table**: Highlights species with the lowest unassisted identification accuracy.
- **Taxonomic Confusion Matrix**: Logs pairwise misidentifications to highlight common lookalike species pairs.

### Dataset Ingestion & Filtering

- **Local File & Direct URL Ingestion**: Ingest DarwinCore archives from local `.zip` / `occurrence.txt` files or directly from GBIF HTTP(S) download URLs with automatic local caching and live progress updates.
- **GBIF Vernacular Name Enrichment**: Look up available species, genus, and family names from GBIF, with cached results and availability summaries in your selected language.
- **Taxa Filtering**: Restrict training sessions to target families, genera, or species, or exclude taxa you select (for example, non-native species you do not want to practise).

### Interactive In-App Guides & Onboarding

- **Data-Driven Interactive Guides**: Built-in step-by-step guides with screenshots where applicable, step descriptions, and forward/backward navigation for initial dataset setup, custom GBIF dataset creation, and page walkthroughs (Quiz, Dashboard, Settings).
- **First-Time Setup Assistance**: Offers an initial setup guide when no observations are available. Name lookup is optional; you can practise using scientific names.
- **Keyboard-Driven Guide Navigation**:
  - `Right Arrow` or `d`: Advance to next step
  - `Left Arrow` or `a`: Return to previous step
  - `Esc`: Return to guide menu catalog from any step

---

## Installation & Execution

`Taxo-Trainer` can be run either as a standalone native desktop application or directly from source using Python.

### Option A: Standalone Desktop Application (Recommended)

Download the latest installer or executable bundle for your platform from the [GitHub Releases](https://github.com/asgersvenning/taxo-trainer/releases) page:

- **Windows**: Download `TaxoTrainerSetup.exe` and run the setup wizard. It creates desktop and Start Menu shortcuts.
- **macOS**: Download `TaxoTrainer-macOS.dmg`, open the disk image, and drag **Taxo-Trainer** into your `Applications` folder.
- **Linux**: Download `TaxoTrainer-Linux-x64.tar.gz`, extract the archive, and run `./taxo-trainer`.

*The packaged desktop application runs as a dedicated native window without requiring Python or an external browser.*

---

### Option B: Running from Source (Developers)

Ensure you have [`uv`](https://docs.astral.sh/uv/) installed.

```bash
git clone https://github.com/asgersvenning/taxo-trainer.git
cd taxo-trainer
uv sync --locked
```

#### Launching the Application

Run directly using Python / `uv`:

```bash
# Standard launch (uses native mode when available, otherwise browser mode)
uv run taxo-trainer

# Force web browser mode
uv run python main.py --browser

# Force native desktop window mode
uv run python main.py --native
```

When running in browser mode, navigate to `http://127.0.0.1:8080`.

---

### Building the Desktop Executable Bundle Locally

Developers can build the standalone directory-based executable bundle locally using PyInstaller:

```bash
uv run python scripts/build_desktop.py
```

The output executable directory will be created under `dist/taxo-trainer`.

---

## First session

1. Open **Settings & Data**. If observations are already available, you can go straight to **Quiz**.
2. In **DarwinCore (DwC) Occurrence Ingestion**, select a local archive or paste a direct download URL. A bundled dataset path is prefilled when that file is available; otherwise, supply your own file or URL. Click **Start Ingestion** or **Re-Ingest Dataset** and wait for completion.
3. Choose **Primary Display Language**. Danish is the default; English, German, Swedish, Norwegian, Finnish, Polish, Czech, French, Spanish, Italian, Portuguese, and Dutch are also supported. Choose **Scientific Binomial (Latin)** for scientific names. This changes taxon names, not the English interface labels.
4. Under **Species Names**, click **Look Up Names** to retrieve available vernacular names. You can continue training during lookup, or skip it when using scientific names.
5. Open **Quiz**, inspect a photo, and enter a species, genus, or family name. Select an autocomplete suggestion to submit it. The **Guides** tab explains the quiz, dashboard, datasets, and training preferences.

### Names and lookup progress

**Species Names** shows availability in your selected language. A fallback name in another language does not count as coverage in the selected language. Missing results do not establish that a local name does not exist: GBIF coverage, taxonomic ambiguity, and delays in incorporating local names remain limitations.

Use **Check for Names Again** to revisit available names, or **Retry Name Lookup** after an incomplete lookup. Successful responses are cached. If GBIF asks the app to pause, wait for the time shown before retrying; repeated clicking will not bypass the pause.

After upgrading from older versions, reselect saved training groups if prompted. Re-ingesting the archive or running name lookup can restore missing higher-rank information where GBIF provides the necessary identifiers. Neither can guarantee a complete hierarchy or naming coverage.

### Choose what to practise

| Setting | Effect |
| --- | --- |
| **Minimum Occurrence Threshold** | Omit taxa with fewer retained observations from training and autocomplete. Raising it narrows the pool; it does not delete data. |
| **Minimum Occurrence Cutoff (C_min)** | The same threshold, also shown under **Stage 1 Sampling & Probability Weights**. Both controls stay synchronized. |
| **Flat** sampling | Give each eligible taxon equal weight. |
| **Natural** sampling | Favour taxa in proportion to their retained observation counts. These counts describe the imported data, not biological abundance. |
| **Log Transformed** / **Square-Root Transformed** | Soften the influence of observation counts compared with Natural sampling. |
| Family and taxon filters | Focus on selected groups, or exclude groups you choose. |
| **Practice Misidentified Photos Only** | Revisit photos you previously misidentified. |

Display language, theme, sampling mode, and minimum-occurrence threshold are saved automatically across launches and when clearing a dataset. Family and misidentified-only filters are session controls.

GBIF photographs can be ambiguous or incorrectly labelled. You can manually override how an observation is counted for your own training. Hints and diagnostic comparisons mark an attempt as assisted and exclude it from unassisted success metrics.

## Custom Datasets

Export occurrences from the [GBIF website](https://www.gbif.org/occurrence/search), filtering for the region and taxonomic groups you want to learn. Choose a **Darwin Core Archive** with multimedia information, rather than a species list. GBIF describes the archive's `occurrence.txt` and `multimedia.txt` files in its [download format documentation](https://techdocs.gbif.org/en/data-use/download-formats). Review the download terms and the licenses associated with its datasets and photographs.

Once the export is ready, download the ZIP or copy its direct archive download link. In **Settings & Data**, paste the local file path or direct URL into **Path or URL to DarwinCore dataset (.zip / occurrence.txt)**, then click **Start Ingestion** or **Re-Ingest Dataset**. Prefer the complete ZIP so its multimedia information stays with the observations. The in-app **Adding Custom GBIF Datasets** guide includes example GBIF screens; website layouts can change.

**Max Occurrences Per Taxon** limits the number of observations retained per taxon during import (`0` means unlimited). It is separate from the minimum-occurrence threshold used to choose taxa for training.

Imports **add or update records** in the current data source. They do not automatically replace it. To start with only a new dataset, use **Clear Current Data Source** first. Clearing removes the current observation data, while retaining user progress and the preferences listed above. A failed import leaves the data present immediately before that import intact; it does not undo a separate clearing action.

After import, use **Species Names** for optional name lookup and return to **Quiz**.

## For developers

### Introduction

This app (`taxo-trainer`) is meant to be functional, fast and reliable, and is a spare-time project I built using AI to help me more easily and efficiently practice and learn identifying plants and insects primarily.

The features are meant to be easy to use and intuitive for most people, without needing a lot of instructions, and the desktop installer does not require terminal commands. Running from source uses the commands above.
`taxo-trainer` also contains some "gamification" features to make the learning process more engaging, and allow users to track their progress over time, but these are meant as quality of life features, and are not the primary focus of the app.

To make it useful for more people `taxo-trainer` attempts to resolve ambiguities in taxonomy and integration of both scientific and vernacular names across different languages. This is a slightly complicated task to automate as the taxonomy is constantly being updated and vernacular names are not always well-maintained or standardized. To make this as simple as possible `taxo-trainer` relies on GBIF as a authority for both scientific and vernacular names, but sometimes local authorities have more accurate, complete, or simply different naming conventions than GBIF, or they haven't yet been incorporated into GBIF. `taxo-trainer` does not attempt to solve this problem, but relies on the hope that the community will naturally improve this over time.

Canonical taxon references must always be GBIF IDs, including GBIF's Catalogue of Life identifiers. Preserve numeric and alphanumeric IDs as strings, with checklist context where available; a digits-only ID does not establish its checklist. Names are display and local input aliases, never identity keys. All API requests must use ID-addressed records and explicit ID relationships. Never use free-text matching, search, or suggest APIs, including as fallbacks for missing identifiers.

### Contributing

Feel free to contribute to the `taxo-trainer` app, I won't set high standards and feel free to use any tools including AI, but try not to introduce new dependencies, make the app slower, or break existing functionality.

Development items that help would be appreciated for include (in no particular order):

* Taxonomic handling:
  * Detection and resolution of taxonomic issues.
  * Better resolution of vernacular names.
* Performance and technical debt improvements:
  * Cross-platform compatibility.
  * Performance improvements.
  * More test coverage.
  * Consistency refactoring, especially around the UI, app state, and database structure.
* Better UI/UX:
  * Improved "gamification" features and metrics.
  * More consistent state management across sessions.
  * Documentation and guides.
  * More themes and styling options.
* Packaging and license
