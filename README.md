# `Taxo-Trainer`

`Taxo-Trainer` is a desktop web application for practicing plant and wildlife identification using GBIF DarwinCore occurrence datasets. It features interactive photo quiz workflows, multi-rank taxonomic validation, structured hints, dataset filtering, and detailed analytics.

---

## Features

### Quiz & Identification Interface
- **Photo Inspection Canvas**: High-resolution image canvas with keyboard-driven carousel navigation (`Alt+←` / `Alt+→`), photo attribution credits, and external links to original GBIF/Catalogue of Life taxonomy records.
- **Taxonomic Hierarchy Breakdown**: Visual breakdown displaying Order, Family, Genus, and Species ranks. Highlights correct rank matches, incorrect guesses, and unrevealed ranks.
- **Streak & Record Tracker**: Tracks consecutive correct species identifications (🔥 active streak and 🏆 all-time record) persisted in SQLite. The streak resets only when proceeding to a new observation following an uncorrected error.
- **Keyboard Navigation**:
  - `Ctrl + Right Arrow`: Next observation
  - `Alt + Left / Right Arrow`: Navigate photo carousel
  - `Enter`: Submit selected autocomplete suggestion or typed guess

### Autocomplete & Name Validation
- **Multi-Rank Autocomplete**: Searches scientific names (binomials, genera, families) and vernacular names across 13+ languages (Danish, English, German, Swedish, Norwegian, Finnish, Polish, Czech, French, Spanish, Italian, Portuguese, Dutch, etc.).
- **Context-Aware Rank Prioritization**: Sorts search candidates by match quality, giving top priority to exact species matches, unambiguous rank matches, and hierarchical order (Species $\rightarrow$ Genus $\rightarrow$ Family).
- **Taxonomic Scope Interpolation**: Guessing or revealing a higher rank (e.g. Family or Genus) automatically constrains autocomplete suggestions to that specific rank scope.

### Guided Hints & Assistance
- **Higher-Order Rank Hint**: Sequentially reveals the highest unrevealed rank (Order $\rightarrow$ Family $\rightarrow$ Genus $\rightarrow$ Species), updating the hierarchy breakdown and restricting input interpolation accordingly.
- **1/5 Multiple Choice Hint**: Generates multiple choice options restricted strictly to candidates within the currently revealed scope without duplicates or artificial random fill.

### Analytics & Mastery Dashboard
- **Time-Range Filters**: Filter analytics by time window (1 Hour, 24 Hours, 7 Days, 30 Days, 1 Year, or All Time).
- **Core Performance Metrics**: Tracks total attempts, unassisted accuracy percentage, active/best streaks, and mastered species counts ($\ge 90\%$ accuracy over $\ge 5$ attempts).
- **Dataset Coverage**: Tracks the percentage of dataset species encountered during training sessions.
- **Family Mastery Breakdown**: Side-by-side analysis highlighting highest accuracy plant families and families needing practice.
- **Trouble Taxa Table**: Identifies species with the lowest unassisted accuracy ($\ge 2$ attempts).
- **Taxonomic Confusion Matrix**: Logs pairwise misidentifications to identify common lookalike species pairs.

### Dataset Ingestion & Filtering
- **DarwinCore Stream Ingestion**: Fast streaming parser for GBIF occurrence archives (`occurrence.txt`) with an interactive file selector.
- **Taxa Whitelist & Blacklist Filtering**: Restrict training sessions to specific target families, genera, or species, or exclude non-native taxa.

---

## Installation

Ensure you have [`uv`](https://docs.astral.sh/uv/) installed.

```bash
git clone https://github.com/asgersvenning/taxo-trainer.git
cd taxo-trainer
uv sync
```

---

## Running the Application

Launch the application locally:

```bash
uv run taxo-trainer
```

Open a web browser and navigate to `http://127.0.0.1:8080`.

---

## Running Tests

Execute the automated test suite with `pytest`:

```bash
uv run pytest
```

---

## Custom datasets

The app is built around the `DarwinCore` archive format with the `Multimedia` extension and will *(should)* work with any dataset in this format.

### Using GBIF to create custom datasets for `Taxo-Trainer`

| step | action                                                                                                                                                                                                                                                                                         | example                                               |
| ---- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------- |
| 1    | Navigate to the desired dataset on the [GBIF website](https://www.gbif.org) and click `"Occurrences"` in the top menu.                                                                                                                                                                         | ![](./assets/dataset_guide/frontpage.png)             |
| 2    | Select filters for the dataset, the highlighted filters are strongly recommended. Dataset size `<1,000,000` observations are recommended.                                                                                                                                                      | ![](./assets/dataset_guide/occ_search.png)            |
| 3    | Go to the `"Download"` tab and select `"DarwinCore Archive"` and click `"Configure"`.                                                                                                                                                                                                          | ![](./assets/dataset_guide/occ_download_archive.png)  |
| 4    | In the `"Format"` section scroll down until you see the `"Multimedia"` extension.                                                                                                                                                                                                              | ![](./assets/dataset_guide/occ_download_config_1.png) |
| 5    | Select the `"Multimedia"` extension and click `"Continue to Terms"`.                                                                                                                                                                                                                           | ![](./assets/dataset_guide/occ_download_config_2.png) |
| 6    | Acknowledge the terms and click `"Create Download"`.                                                                                                                                                                                                                                           | ![](./assets/dataset_guide/occ_download_terms.png)    |
| 7    | Wait for the download to be ready, and right-click the `"Download archive"` button and select `"Copy link address"` to copy the download link.                                                                                                                                                 | ![](./assets/dataset_guide/occ_download_link.png)     |
| 8    | In the `taxo-trainer` app, navigate to the `"Settings & Data"` tab and click `"Clear current data source"`.                                                                                                                                                                                    | ![](./assets/dataset_guide/source_clear.png)          |
| 9    | In the `"DarwinCore (DwC) Occurrence Ingestion"` box, paste the link into the input field and click `"[Re-]Ingest dataset"`. When this step has finished, go to the `"GBIF Vernacular Name Enrichment"` box and click `"[Re-]Fetch [danish] names from GBIF API"` and wait for it to complete. | ![](./assets/dataset_guide/archive_import.png)        |
