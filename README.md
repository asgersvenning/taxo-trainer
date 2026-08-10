# Taxo-Trainer

**Taxo-Trainer** is a modernized, high-performance species and higher-rank taxonomy training engine built with **Python 3.10+**, **NiceGUI**, and **SQLite**. Powered by GBIF DarwinCore occurrence datasets, it helps naturalists, students, and researchers practice species identification across field photos, satellite maps, and multi-level taxonomic hierarchies.

---

## 🌟 Key Features

* **📷 75% / 25% Split Interface:** 75% width canvas reserved for whole-photo inspection with interactive carousel controls, photo credits (`👤 Photo by`), and direct external links to original observation records (`🔗 View Source / GBIF Obs ↗`).
* **🏛️ Taxonomic Hierarchy Breakdown:** Displays dynamic, color-coded level badges (**Order**, **Family**, **Genus**, **Species**) for every guess, providing instant feedback on which taxonomic levels were correctly identified.
* **🔍 Multi-Language & Higher-Rank Autocomplete:** Full support for scientific binomials, higher rank names (Genus & Family), and vernacular names across 8+ languages (Danish, English, German, Swedish, Norwegian, French, Spanish, Dutch). Symmetric matching ignores spaces and dashes while prioritizing exact exact matches.
* **🎯 Taxa Whitelist & Blacklist Filtering:** Filter training sessions to specific target taxa at any rank level (Species, Genus, Family). Whitelist specific genera to practice focused groups or blacklist non-native taxa.
* **💡 Hints & Diagnostic References:** Includes Taxonomic Rank hints, Multiple Choice (1/5) distractor options, misidentification reporting, and side-by-side diagnostic reference photos when guessing real species.
* **📂 DarwinCore (DwC) Ingestion:** Fast zero-pandas streaming TSV parser for GBIF occurrence archives with an interactive directory/file selector and multi-language taxonomy enrichment.
* **📊 Analytics Dashboard:** Performance metrics, monthly phenology heatmaps, and diagnostic review tools for tracking learning progress over time.

---

## ⌨️ Keyboard Shortcuts

| Shortcut             | Action                                              |
| :------------------- | :-------------------------------------------------- |
| `CTRL + Right Arrow` | Load Next Target Observation                        |
| `ALT + Right Arrow`  | Next Photo in Carousel                              |
| `ALT + Left Arrow`   | Previous Photo in Carousel                          |
| `Enter`              | Submit Top Autocomplete Suggestion or Guessed Taxon |

---

## 🚀 Installation

Ensure you have **Python 3.10+** and [`uv`](https://github.com/astral-sh/uv) installed on your system.

1. **Clone the Repository:**

   ```bash
   git clone https://github.com/user/taxo-trainer.git
   cd taxo-trainer
   ```

2. **Install Dependencies with UV:**

   ```bash
   uv sync
   ```

---

## 🏃 Running the Application

Launch the desktop web application interface locally:

### Option 1: Via Python Module

```bash
uv run python -m src.app
```

### Option 2: Via UV Script Entry Point

```bash
uv run taxo-trainer
```

Open your browser and navigate to **`http://127.0.0.1:8080`**.

---

## 🧪 Running Unit Tests

Execute the automated test suite with `pytest`:

```bash
uv run pytest
```

---

## 🛠️ Technology Stack

* **UI Framework:** [NiceGUI](https://nicegui.io/) (Quasar & TailwindCSS wrapper)
* **Package & Environment Manager:** [uv](https://github.com/astral-sh/uv)
* **Storage Engine:** SQLite (WAL mode)
* **Taxonomy & Occurrence Standards:** [GBIF DarwinCore (DwC)](https://www.gbif.org/dwc)
* **Language Support:** Multi-language GBIF Vernacular Name API integration
