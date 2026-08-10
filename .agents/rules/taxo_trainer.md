---
trigger: always_on
description: System instructions and hard implementation rules for building the taxo-trainer app
globs: ["src/**/*.py", "pyproject.toml", "DESIGN_SPEC.md"]
---

# AGENT RULESET: Taxo-Trainer Development (`.agents/rules/taxo_trainer.md`)

## 1. Primary Operating Directive
You are an expert Python systems architect and software engineer implementing the **Modernized Taxonomic Recognition & Training Engine (`taxo-trainer`)**.

**Your absolute single source of truth is `DESIGN_SPEC.md`.**
* Read and strictly adhere to every architecture rule, data schema, sampling equation, and functional requirement detailed in `DESIGN_SPEC.md`.
* Do NOT deviate from the specified architecture, tech stack, or feature set without explicit user instruction.
* If any trade-off or ambiguity arises, resolve it strictly in favor of the constraints in `DESIGN_SPEC.md`.

---

## 2. Hard Technical Guardrails (NON-NEGOTIABLE)

### 🚫 STRICT PROHIBITIONS
1. **NO PANDAS / NO POLARS:** Under no circumstances should `pandas`, `polars`, `dask`, or any heavy dataframe library be added to `pyproject.toml` or imported in any file.
   * *Required Alternative:* Use Python standard library primitives (`dict`, `list`, `set`, `tuple`), `csv.DictReader`, `sqlite3`, and `numpy` arrays.
2. **NO ALTERNATIVE FRAMEWORKS:** Do not use Streamlit, Dash, Gradio, FastHTML, or Shiny. The web framework **must be NiceGUI**.
3. **NO GLOBAL STATE IN UI WRAPPERS:** Do not store session-specific play state in global module-level variables. Wrap user session state cleanly within NiceGUI state objects or class instances.
4. **NO DESTRUCTIVE AGENT MODIFICATIONS:** Do not alter or delete `DESIGN_SPEC.md` or files inside `old_reference/`.

### ✅ MANDATORY STACK REQUIREMENTS
* **Python 3.12+** managed exclusively with **`uv`**.
* **Database Engine:** Native `sqlite3` running in `WAL` mode (`PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;`).
* **Numeric Computations:** `numpy` for vector weight calculations and sampling probability arrays.
* **Fuzzy String Matching:** Standard library `difflib.SequenceMatcher`.

---

## 3. Mandatory Directory Structure

You must strictly maintain the following project layout as specified in `DESIGN_SPEC.md`:

```text
taxo-trainer/
├── DESIGN_SPEC.md
├── .agents/
│   └── rules/
│       └── taxo_trainer.md       # This rule file
├── pyproject.toml
├── README.md
├── data/
│   ├── raw/                       # Holds GBIF occurrence.txt
│   ├── app_data.db                # DarwinCore occurrence & taxa database
│   └── user_data.db               # User progress & history stats
├── old_reference/
│   └── Dansk-Flora-App/           # This folder is not included in the git repository
└── src/
    ├── __init__.py
    ├── app.py                     # NiceGUI main entry point
    ├── db.py                      # SQLite WAL connections & schema setup
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

## 4. Subsystem Implementation Rules

### 4.1 Ingestion & SQLite Engine (`src/ingestion/`, `src/db.py`)
* Use `csv.DictReader(f, delimiter="\t")` to stream multi-megabyte `occurrence.txt` files.
* Execute database writes in explicit transaction batches (`10,000` rows per batch) for optimal throughput.
* Build and verify indices (`idx_taxa_hierarchy`, `idx_taxa_names`, `idx_occ_sampling`) after data ingestion to guarantee $O(1)$ runtime queries during quiz play.

### 4.2 Core Logic & Two-Stage Sampling (`src/engine/sampling.py`)
Implement the exact two-stage sampling mechanism described in Section 4 of `DESIGN_SPEC.md`:
1. **Stage 1 (Taxon Weighting):** Extract `(taxon_key, occurrence_count)` pairs into NumPy arrays. Compute transformed weights (`flat`, `natural`, `log`, `sqrt`) vectorially and sample the target `taxon_key` using `np.random.choice(keys, p=probabilities)`.
2. **Stage 2 (Observation Selection):** Retrieve candidate observations for the chosen `taxon_key`. Filter out seen observations (`seen_set`) and apply `misidentified_only` filters if enabled. Fall back gracefully if all candidate photos for a species have been viewed.

### 4.3 Identification, Autocomplete & Validation (`src/engine/validator.py`)
* Implement prefix-matching SQL autocomplete across `canonical_name` and `vernacular_da`/`vernacular_en`.
* Accept user guesses at **any taxonomic rank** (Family, Genus, Species) and in either **scientific** or **vernacular** names.
* Use `difflib.SequenceMatcher` to allow soft typo forgiveness (similarity score $>0.90$).
* Apply the vernacular fallback chain: `Danish Vernacular` $\rightarrow$ `Local JSON Dictionary` $\rightarrow$ `English Vernacular` $\rightarrow$ `Scientific Name`.

### 4.4 Interface & Reactive State (`src/ui/`)
* **NiceGUI State Isolation:** Keep session state isolated per client/connection. Re-render UI components using NiceGUI's native reactivity or explicit `.clear()` / `.refresh()` calls.
* **Map Rendering:** Embed `ui.leaflet` with `Esri.WorldImagery` tiles for satellite visuals. Do not call external JS files directly when standard NiceGUI bindings exist.
* **Hint Rules:** If the user triggers any hint (Higher-order rank, 50/50 options, or reference comparison photo), explicitly set `used_hint = True` on the attempt state so it is **never** logged as an unassisted successful identification in `user_data.db`.

---

## 5. Phased Build Order

When executing tasks or generating files, follow this sequence:

1. **Phase 1:** Setup `pyproject.toml` with `uv` (`nicegui`, `numpy`) and create `src/db.py` schema migrations.
2. **Phase 2:** Build `src/ingestion/dwc_parser.py` using `csv.DictReader` and auto-index creation.
3. **Phase 3:** Write engine modules (`src/engine/sampling.py`, `validator.py`, `analytics.py`).
4. **Phase 4:** Construct UI components and views in `src/ui/`.
5. **Phase 5:** Wire up `src/app.py` entry point and execute self-verification pass.

---

## 6. Self-Verification Checklist

Before marking any task complete, perform this automated mental audit:

* [ ] **No Pandas Check:** Confirm no file imports `pandas` or `polars`.
* [ ] **UV Execution Check:** Ensure code runs via `uv run python -m src.app`.
* [ ] **Data Ingest Check:** Verify parameterized SQL queries (`?`) are used everywhere.
* [ ] **Hint Enforcement Check:** Verify that using hints sets `used_hint = 1` and excludes the attempt from positive unassisted metrics.
* [ ] **Anti-Repeat Check:** Ensure seen `occurrence_id` values are tracked in memory and excluded during Stage 2 sampling.