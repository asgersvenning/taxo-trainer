# SOFTWARE DESIGN SPECIFICATION

**Project Title:** Modernized Taxonomic Recognition & Training Engine (`taxo-trainer`)

**Target File:** `DESIGN_SPEC.md`

**Purpose:** Technical specification for an AI-assisted or manual build of a local-first, DarwinCore-backed species identification trainer.

**Relationship to Legacy System:** Complete replacement and modernization of the *Species Identification* component (Section 2.2) of the legacy R/Shiny repository located in `old_reference/Dansk-Flora-App`.

---

## 1. Vision & Qualitative Goals

### 1.1 Core Mission

To provide naturalists, ecologists, and biology students with a high-efficiency visual training environment that builds genuine, non-AI-assisted field identification skills. The system bridges the gap between field guide memorization and real-world encounters by training the user's eye on crowd-sourced, uncurated field observations.

### 1.2 Target Audience

* **Qualified Naturalists & Ecologists:** Requiring precise control over geographic, seasonal, and taxonomic subsets (e.g., practicing difficult genera like *Carex*, *Hieracium*, or *Salix*).
* **Advanced Biology Students:** Preparing for field identification exams or bioblitzes without being restricted to static textbook photo assets.
* **Technical Users:** Comfortable with cloning git repositories, managing local Python environments via `uv`, and exporting custom datasets from GBIF.

### 1.3 Pedagogical Philosophy

1. **Active Visual Discrimination:** Real-world field photos contain bad lighting, partial occlusions, varying growth stages, and awkward angles. Training on unfiltered field observations builds robust recognition heuristics.
2. **Flexible Mental Models:** Taxonomists do not think in fixed multiple-choice options. The interface must allow top-down, bottom-up, or rank-skipping identification (e.g., recognizing Family immediately, then refining to Genus or Species).
3. **Transparent & Controllable Bias:** Rather than relying on black-box spaced-repetition algorithms, the user explicitly controls sampling probabilities (flat, natural, log-transformed) and difficulty cutoffs.

---

## 2. Hard Architectural Rules & Constraints

| Constraint | Requirement Specification |
| --- | --- |
| **Language & Tooling** | **Python 3.12+** managed strictly via **`uv`**. Run locally via `uv run app.py`. |
| **Web Framework** | **NiceGUI** (built on FastAPI, Starlette, and Quasar/Vue). No Streamlit, Dash, or Shiny. |
| **Database & Engine** | **Native `sqlite3**` in WAL mode. **STRICT PROHIBITION: NO Pandas or Polars.** All table transformations and dictionary mappings must use standard library primitives (`dict`, `list`, `set`), `csv.DictReader`, and `numpy` arrays. |
| **Backend Data Standard** | **DarwinCore (DwC)** tab-delimited exports (`occurrence.txt` via GBIF). The app ingests DwC directly to avoid re-inventing regional or temporal selection UI. |
| **Deployment Model** | Local-first desktop app. Executed on the user's local machine; non-server-deployed. All runtime state stored in a local SQLite file (`user_data.db`). |
| **Code Organization** | Clean, modular, human-readable scripts under logical subdirectories (`ingestion/`, `engine/`, `ui/`). |

---

## 3. Data Schema & Ingestion Pipeline

### 3.1 DarwinCore (DwC) Ingest Engine

The app ingests standard GBIF occurrences (`occurrence.txt`). Data is streamed directly into an indexed SQLite database using Python's `csv.DictReader` inside an explicit transaction block, achieving $>50,000$ records/second without high RAM usage.

```
┌────────────────────────┐
│  GBIF DarwinCore TSV   │
│   (occurrence.txt)     │
└───────────┬────────────┘
            │ csv.DictReader
            ▼
┌────────────────────────┐
│   sqlite3 (WAL Mode)   │
│     app_data.db        │
└────────────────────────┘

```

### 3.2 Relational SQLite Schema

```sql
-- 1. Normalized Taxonomic Tree & Vernacular Dictionary
CREATE TABLE IF NOT EXISTS taxa (
    taxon_key INTEGER PRIMARY KEY,         -- GBIF taxonID / acceptedTaxonKey
    scientific_name TEXT NOT NULL,         -- Full binomial + author e.g. "Quercus robur L."
    canonical_name TEXT NOT NULL,          -- Clean binomial e.g. "Quercus robur"
    accepted_name TEXT NOT NULL,
    rank TEXT NOT NULL,                    -- SPECIES, GENUS, FAMILY, ORDER, etc.
    kingdom TEXT, phylum TEXT, class TEXT, 
    order_name TEXT, family TEXT, genus TEXT, -- Denormalized hierarchy for fast filtering
    vernacular_da TEXT,                    -- Danish common name
    vernacular_en TEXT,                    -- English fallback name
    occurrence_count INTEGER DEFAULT 0     -- Pre-computed count for Stage 1 sampling
);

-- 2. Occurrence Records & Associated Media
CREATE TABLE IF NOT EXISTS occurrences (
    occurrence_id TEXT PRIMARY KEY,        -- DwC gbifID
    taxon_key INTEGER REFERENCES taxa(taxon_key),
    latitude REAL,
    longitude REAL,
    locality TEXT,                         -- Verbatim locality string
    event_date TEXT,
    month INTEGER,                         -- Phenology context (1-12)
    media_urls TEXT NOT NULL,              -- Pipe-separated ('|') image URLs
    coordinate_uncertainty_m REAL
);

-- 3. Persistent User Progress & History (Req #4, #6)
CREATE TABLE IF NOT EXISTS user_progress (
    attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
    occurrence_id TEXT REFERENCES occurrences(occurrence_id),
    target_taxon_key INTEGER REFERENCES taxa(taxon_key),
    guessed_taxon_key INTEGER,             -- Logged for confusion matrix
    is_correct BOOLEAN NOT NULL,
    used_hint BOOLEAN NOT NULL DEFAULT 0,  -- Flags hint usage (Req #9c)
    attempt_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for instant sampling and dynamic filtering
CREATE INDEX IF NOT EXISTS idx_taxa_hierarchy ON taxa(family, genus, rank);
CREATE INDEX IF NOT EXISTS idx_taxa_names ON taxa(canonical_name, vernacular_da);
CREATE INDEX IF NOT EXISTS idx_occ_sampling ON occurrences(taxon_key, month);

```

---

## 4. Sampling Mechanics & Algorithmic Logic

Sampling operates via a **Two-Stage Architecture**, completely decoupling species weight transformations from observation selection.

```
┌─────────────────────────────────────────────────────────┐
│ STAGE 1: Taxon Selection                                │
│ Compute probabilities -> Sample target taxon_key         │
└──────────────────────────┬──────────────────────────────┘
                           │ taxon_key
                           ▼
┌─────────────────────────────────────────────────────────┐
│ STAGE 2: Observation Selection                          │
│ Filter (unseen / misidentified) -> Sample occurrence    │
└─────────────────────────────────────────────────────────┘

```

### 4.1 Stage 1: Taxon Weight Transformation (Req #3a, #3b, #5)

Let $c_i$ be the occurrence count of species $i$ in the active dataset. Probability $p_i$ is computed across all valid taxa satisfying the minimum cutoff threshold ($c_i \ge C_{\text{min}}$) and active taxonomic filters:

$$\text{Flat Mode:} \quad w_i = 1$$

$$\text{Natural Mode:} \quad w_i = c_i$$

$$\text{Log Transformation:} \quad w_i = \log(1 + c_i)$$

$$\text{Square-Root Transformation:} \quad w_i = \sqrt{c_i}$$

$$\text{Normalized Probability:} \quad p_i = \frac{w_i}{\sum_{j=1}^{N} w_j}$$

*Implementation:* NumPy executes vector operations over the extracted key-count arrays.

### 4.2 Stage 2: Observation Selection & Anti-Repeat (Req #4, #4a)

Given the selected `taxon_key`:

1. Retrieve candidate occurrence records from SQLite.
2. **Misidentified-Only Mode (Req #4a):** If enabled, restrict candidates strictly to `occurrence_id`s previously logged as incorrect in `user_progress`.
3. **Anti-Repeat Mode (Req #4):** Exclude `occurrence_id`s present in the current session's `seen_set` (or persistent `user_progress` table).
4. **Fallback:** If all candidates for a species have been seen, reset the seen tracking for that specific species to maintain playability.

---

## 5. Functional Requirements & User Experience

### 5.1 Flexible Identification & Autocomplete (Req #7, #7a, #7b, #7c)

* **Unconstrained Taxonomic Order:** The user can submit a guess at any rank (e.g., inputting `Fabaceae` first, then `Trifolium`, then `Trifolium repens`).
* **Multi-Nomenclature Parsing:** Input accepts either canonical scientific names (*"Poa pratensis"*) or Danish/English vernacular names (*"Eng-Rapgræs"*).
* **Fuzzy Autocomplete & Typo Tolerance:** NiceGUI's autocomplete component queries SQLite with prefix matching (`LIKE 'query%'`). Submissions are scored using standard library `difflib.SequenceMatcher`. Similarity $>90\%$ prompts a soft correction rather than a penalizing failure.
* **Localization Fallback Chain (Req #2):** `Danish Vernacular` $\rightarrow$ `Local Custom JSON Dictionary` $\rightarrow$ `English Vernacular` $\rightarrow$ `Scientific Name`.

```
User Input: "Trifolium"
  ├── Scientific Match: Genus Trifolium (Correct Rank: Genus)
  └── UI State: Marks Genus as correct. Prompts for Species level.

```

### 5.2 Media, Phenology & Map Presentation (Req #1, #8)

* **Multi-Photo Inspection (Req #1):** If `associatedMedia` contains multiple pipe-separated URLs, render thumbnail controls or a carousel toggle ("Photo 1 of 3").
* **Phenological Context:** Display observation month and day (e.g., *"Observed: May 14"*). Never reveal identity, but provide vital seasonal context for flora, fungi, and insects.
* **Satellite Location Context (Req #8):** Embed a Leaflet widget (`ui.leaflet`) set to satellite imagery (`Esri.WorldImagery`) displaying a marker at `(latitude, longitude)`. Annotate with locality metadata from DwC (`locality`).

### 5.3 Hint Mechanics & Penalty Rules (Req #9, #9a, #9b, #9c, #9d)

Users can request hints during an active question:

* **Taxonomic Higher-Order Hint (9a):** Reveals the higher taxon rank (e.g., *"Family: Caryophyllaceae"*).
* **Multiple Choice Hint (9b):** Generates 5 candidate choices containing the target taxon and 4 phylogenetically close distractors (same Family/Genus).
* **Side-by-Side Diagnostic Hint (9d):** On an incorrect guess, renders a reference image of the *guessed* species directly adjacent to the *target* observation photo to highlight field diagnostic marks.
* **Penalty Rule (9c):** Triggering any hint automatically flags `used_hint = 1` in `user_progress`. The attempt **cannot** be logged as a successful unassisted identification in user analytics.

### 5.4 Analytics Dashboard & Confusion Matrix (Req #6)

The persistent dashboard tracks:

1. **Global & Per-Species Accuracy:** Total attempts, pass rate percentage, and count of currently "Mastered" species ($\ge 90\%$ accuracy over $\ge 5$ attempts).
2. **Taxonomic Confusion Matrix:** Logs pairwise misidentifications (`target_taxon_key` vs `guessed_taxon_key`). Renders a top-10 table of visual lookalikes (e.g., *"Mistook Cirsium palustre for Cirsium vulgare 4 times"*).

---

## 6. Comparison & Modernization Matrix

This app replaces Section 2.2 of `old_reference/Dansk-Flora-App`. The table below outlines how key drawbacks of the legacy codebase have been resolved.

| Feature / Aspect | Legacy R/Shiny (`Dansk-Flora-App`) | Modernized Engine (`taxo-trainer`) |
| --- | --- | --- |
| **Data Format** | Hardcoded R data frames / custom API queries | Standardized **DarwinCore TSV** exports via GBIF |
| **Taxonomic Scope** | Fixed curriculum subset (previous year's course) | **Unlimited**; driven by whatever DwC archive the user loads |
| **Input Flexibility** | Manual reveal ("Afslør arten!") / self-policed | Interactive autocomplete, multi-rank validation, typo tolerance |
| **Sampling Logic** | Manual 1-4 difficulty multiplier updates | Mathematical **Two-Stage Sampling** (Flat, Natural, Log, Sqrt) |
| **Analytics & State** | Volatile session state | Persistent **SQLite database** tracking overall progress & confusion matrices |
| **Media Handling** | Single image display | **Multi-photo carousel** per observation + **Satellite map** context |
| **Dependencies** | R, Shiny, custom web scraping, Wikipedia iframe | Clean **Python 3.12+**, `uv`, NiceGUI, SQLite, NumPy (Zero-Pandas) |

---

## 7. Project Structure & Implementation Layout

```text
taxo-trainer/
├── DESIGN_SPEC.md                 # This specification document
├── pyproject.toml                 # uv project configuration
├── README.md                      # Quickstart guide
├── data/
│   ├── raw/                       # Place DarwinCore occurrence.txt here
│   ├── app_data.db                # SQLite database (auto-generated on ingest)
│   └── user_data.db               # SQLite user progress state
├── old_reference/                 # Preserved legacy repository reference
│   └── Dansk-Flora-App/
└── src/
    ├── __init__.py
    ├── app.py                     # Main NiceGUI entry point (run via `uv run python -m src.app`)
    ├── db.py                      # SQLite connection management & WAL setup
    ├── ingestion/
    │   ├── dwc_parser.py          # Zero-Pandas TSV stream parser via csv.DictReader
    │   └── taxonomy_builder.py    # Generates normalized taxa table
    ├── engine/
    │   ├── sampling.py            # Stage 1 (NumPy weights) & Stage 2 (Obs lookup)
    │   ├── validator.py           # Autocomplete, difflib fuzzy match, multi-rank logic
    │   └── analytics.py           # Metrics, accuracy scores, and confusion matrix
    └── ui/
        ├── components.py          # Custom Leaflet satellite map & multi-photo widgets
        ├── quiz_view.py           # Core flashcard & identification interface
        ├── dashboard_view.py      # Analytics & confusion matrix UI
        └── settings_view.py       # Weighting mode, cutoffs, and taxo filter controls

```

---

## 8. Verification & Acceptance Test Checklist

When executing an automated or manual build of this repository, the implementation is considered complete when all test criteria pass:

* [ ] **Ingestion:** Successfully ingests a $>100\,\text{MB}$ GBIF `occurrence.txt` file into `app_data.db` using `sqlite3` and `csv.DictReader` in $<10$ seconds without raising memory errors or importing Pandas.
* [ ] **Two-Stage Sampling:** Verified that changing sampling modes (`flat` $\leftrightarrow$ `log` $\leftrightarrow$ `natural`) alters species selection frequencies according to the mathematical definitions in Section 4.1.
* [ ] **Guessing Logic:** Entering a valid Danish vernacular name, English common name, or binomial correctly validates against the target species regardless of rank sequence.
* [ ] **Map & Media:** Observations with multiple images allow switching between photos; the Leaflet satellite view centers accurately on the observation coordinates.
* [ ] **Hint Enforcement:** Utilizing any hint flags `used_hint = 1` in `user_progress` and prevents the question from contributing to positive accuracy counts.
* [ ] **Persistence:** Closing and restarting the NiceGUI app retains user accuracy metrics, review queues for misidentified images, and confusion matrix stats.