# Repository agent instructions

## Required context

Before making changes, read these files in full:

1. [Python and package rules](rules/code.md).
2. [Taxo-Trainer development rules](rules/taxo_trainer.md).
3. [Design specification](../DESIGN_SPEC.md).

Treat both rule files as always applicable, regardless of whether your agent
supports their `trigger` or `globs` front matter. The root `AGENTS.md` directs
agents here; the linked files remain the canonical rules, not optional context.
The heading in `code.md` mentions `uv.md`; the actual file is `code.md`.

Follow system/developer instructions and explicit user instructions first.
Within repository guidance, `DESIGN_SPEC.md` is authoritative for architecture,
schemas, sampling equations, and functional requirements. Use the rule files
to apply it and this file to navigate the current checkout. Read `README.md`
for the current user workflows, then inspect the relevant implementation and
tests. Do not infer permission to change policy from existing implementation
drift. Surface conflicts relevant to the task; continue unaffected work.

Do not alter or delete `DESIGN_SPEC.md` or anything in `old_reference/` unless
the user explicitly instructs that change.

## Agent documentation and commits

Store all agent-specific documentation, development notes, plans, investigation
reports, and handoff context under `.agents/`. Use primarily Markdown (`.md`)
files and organize subfolders as needed, such as `rules/`, `notes/`, and `plans/`.
Paths in this guide are relative to the repository root unless used in a
Markdown link.

Keep root `AGENTS.md` only as the minimal discovery entry point linking here.
Keep substantive agent guidance in `.agents/`. Product documentation such as
`README.md` and `DESIGN_SPEC.md` retains its existing location; documentation
is agent-specific based on its purpose, not whether an agent wrote it.

Always commit agent documentation separately from application code, tests,
dependencies, packaging, CI, and product documentation. Every commit containing
agent documentation must contain only agent documentation changes and have a
message starting with `agent:`, for example `agent: document ingestion findings`.
This includes changes to the root `AGENTS.md` discovery entry point and additions,
edits, moves, or deletions of agent documentation within `.agents/`.

When a task changes both agent documentation and other files, stage explicit
paths and create separate commits. Inspect the staged diff before each commit
to verify the separation. Do not mix these categories when squashing commits.
This convention governs commits when requested or otherwise authorized; it does
not require creating a commit for every documentation edit.

## Project and current layout

Taxo-Trainer is a local-first NiceGUI desktop/browser application for learning
species identification from GBIF DarwinCore observations. It uses SQLite for
occurrences and user progress, NumPy for sampling, and native desktop packaging.

| Location | Responsibility |
| --- | --- |
| `src/taxo_trainer/app.py`, `main.py` | App composition, session initialization, launch options |
| `src/taxo_trainer/db.py` | SQLite connections, schemas, user data paths, cache |
| `src/taxo_trainer/ingestion/` | Streaming DarwinCore ingestion and taxonomy enrichment |
| `src/taxo_trainer/engine/` | Sampling, validation, analytics, guide definitions |
| `src/taxo_trainer/ui/` | Quiz, dashboard, settings, guides, shared components |
| `src/taxo_trainer/resources.py` | Resource lookup for source and frozen builds |
| `tests/` | Pytest unit and integration tests |
| `assets/`, `src/data/datasets/` | Guide assets and bundled datasets |
| `scripts/build_desktop.py`, `taxo_trainer.spec`, `installer/` | Desktop build and installers |
| `.github/workflows/` | Test CI and desktop packaging/release workflows |

Known discrepancies to account for:

- The specification and rules show modules directly under `src/`; the current
  installable package is `src/taxo_trainer/`. Resolve conceptual module paths
  there. Do not move the package merely to match the original diagram.
- The old `uv run python -m src.app` command does not match this checkout.
  Use the current entry points below.
- Rules and specification require Python 3.12+, while `pyproject.toml` currently
  declares `>=3.10` and `.python-version` selects `3.14`. Use Python 3.12+ for
  development; report this discrepancy when relevant and do not silently change
  the supported runtime range or interpreter pin.
- Runtime databases currently live in the OS application data directory via
  `platformdirs`, rather than the specification's repository `data/` directory.
  Use `db.py` and `resources.py` to resolve paths. Tests must use temporary data,
  not the user's actual progress database.
- The rules mention a 50/50 hint, but specification section 5.3 requires five
  choices (one target and four distractors). Follow the specification.

## Development guardrails

- Use `uv` exclusively for Python execution and dependency management. Run
  scripts through `uv run`; use `uv add`/`uv remove` for intentional dependency
  changes and keep `uv.lock` consistent. Use Google-style docstrings.
- Keep NiceGUI, native `sqlite3`, NumPy, and `difflib.SequenceMatcher`. Do not add
  pandas, polars, dask, heavy dataframe libraries, or alternative UI frameworks.
- Stream TSV input with `csv.DictReader`; preserve explicit batched transactions
  and the required indices. Use SQLite WAL and `synchronous=NORMAL`; bind SQL
  values with placeholders rather than interpolating user input.
- Preserve the specified two-stage sampling equations, active filters,
  misidentified-only behavior, and per-session anti-repeat tracking/fallback.
- Preserve multi-rank scientific/vernacular validation, typo tolerance, and
  the specified vernacular fallback chain.
- Keep play state per client/session. Every hint must mark the attempt assisted
  and exclude it from positive unassisted metrics. Use NiceGUI's Leaflet bindings
  for satellite maps.
- Keep changes focused, reuse existing modules, and avoid unnecessary
  dependencies. Preserve user changes and existing datasets. Do not commit
  generated environments, caches, runtime databases, or build output.

## Commands and verification

Run commands from the repository root:

```bash
uv sync --locked
uv run taxo-trainer
uv run python main.py --browser
uv run pytest
uv run ruff check path/to/changed.py
uv run python scripts/build_desktop.py
```

The Ruff path is a placeholder: supply the changed Python files. Ruff is
available in the dev group; the existing test CI runs `uv run pytest`.
Build desktop artifacts only for packaging work or when requested.

For each task, inspect `git status --short`, identify the affected subsystem,
and read its tests before editing. For new functionality, follow the rules'
dependency order: database, ingestion, engine, UI, then app integration; this
is an existing application, so do not restart the original scaffold phases.

Add minimal meaningful pytest coverage for behavior changes. Run affected tests
while iterating and the full suite for code changes before completion; check
changed Python files with Ruff. For documentation-only changes, verify links,
paths, commands against the checkout, and diff whitespace instead. Preserve
the existing GitHub Actions pipelines and update them when the task requires it.

Review the rule file's self-verification checklist for affected behavior,
especially hint accounting, anti-repeat, parameterized SQL, and prohibited
imports. Do not claim ingestion throughput from small fixtures; measure a
representative workload when making performance claims. Report what changed,
checks actually run, and any failures or unverified acceptance criteria.
