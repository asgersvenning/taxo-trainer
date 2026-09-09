# Development roadmap

Reviewed 2026-09-09 against checkout `c80a59b`. This is a prioritized backlog,
not authorization to implement every item or change product policy.
All paths in links are relative to this document. Function names are the stable
navigation anchors; line numbers may change as work lands.

## Direction

### Progress update: quiz accounting

The user clarified that deliberate manual outcome overrides are appropriate for
personal training with potentially mislabeled GBIF images. Preserve that control;
do not treat it as cheating or introduce stricter scoring policy as cleanup.
Automatic diagnostic-photo accounting and accidental duplicate successes were
confirmed as bugs and fixed in separate implementation commits.

The UI now calls a testable production `submit_guess` action. An available
diagnostic photo marks subsequent guesses assisted without rewriting the original
incorrect attempt; no-photo cases remain unassisted. A separate per-question
success flag prevents repeated successful submissions from adding history rows,
including after an answer reveal. It resets when loading the next question.
The existing report-misidentified action remains unchanged; a general editable
outcome/undo workflow has not been implemented.

Regression tests reproduced both failures before their fixes. Latest verification:
53 tests passed, Ruff passed for changed Python files, and diff whitespace passed.
Tests invoke production submission logic with SQLite; browser interaction and
next-question UI wiring were inspected but not browser-tested. Item 1's two
concrete accounting fixes are complete; broader UI lifecycle coverage remains
under item 5. The sampling-cap follow-up is recorded below.

### Progress update: full observation coverage

Removed the normal-mode `LIMIT 200` from candidate lookup. Stage 2 now considers
every eligible observation for the selected species before resetting its eligible
seen pool. Weight formulas and filtered Stage 1 retry behavior are unchanged.

A regression fixture with 201 eligible observations reproduced early repetition
in normal and month-filtered modes before the fix. It now verifies complete
coverage before any repeat and preserves seen entries for another species and
observations outside the active filter during exhaustion reset. The same test
covers review-only mode, which already used the full pool.

Verification: 56 tests passed in 2.77s with isolated application data, Ruff passed
for changed Python files, and diff whitespace passed. Candidate rows are still
materialized for the selected species; memory and query cost therefore scale
with its eligible observation count. Large-dataset performance was not measured
and remains item 6 work, rather than a reason to silently truncate coverage.

Item 2's coverage/reset fix is complete. Sparse filtered-sampling retries and
large review-history parameter lists remain separate work. The next recommended
independent patch was item 3's interrupted-download/cache recovery, now completed
as recorded below.

### Progress update: download-cache recovery

Remote downloads now use SHA-256 of the full trimmed URL (including query
parameters) to isolate cache directories while retaining the original filename
and extension. They stream to unique `.part` files in the destination directory,
check for nonempty content and matching Content-Length when supplied, close file
and response handles, then atomically replace the final cache entry. Exceptions
clean up temporary files; retries start fresh and completed entries are reused.
Legacy basename-only files remain untouched but are not reused for URL requests,
because their URL identity and completeness cannot be established. Explicit
local-file inputs still resolve as before.

Verification: 61 tests passed; Ruff passed for changed files; diff whitespace
passed. Offline tests cover a transfer interrupted after receiving bytes, short
responses, empty responses, callback failure, retry and cache reuse, no-length
responses, matching basenames across hosts/query strings, and legacy-cache
isolation. Native Windows and live GBIF downloads were not exercised. Without
Content-Length, transfer completion relies on normal EOF; this is not validation
of archive contents or DarwinCore semantics. A forcibly terminated process may
leave an unused `.part` file, which is never considered a cache entry.

Item 3's download portion is complete. Next: malformed-row/media validation and
usable-observation cap accounting, followed separately by recoverable dataset
activation. Partial database imports are not addressed by this download fix.

Prioritize trustworthy training results, complete observation coverage, and
recoverable dataset operations. These directly support the README's emphasis
on a functional, fast, reliable application without unnecessary dependencies.
The application already has substantial quiz, analytics, guide, and packaging
functionality. Finish and protect those workflows before adding more themes,
gamification, or new taxonomy infrastructure.

Keep NiceGUI, SQLite, NumPy, uv, and the existing two-stage sampling equations.
The design specification remains authoritative. Do not change scoring policy,
taxonomy authority, or deployment architecture as incidental cleanup.

## Review evidence and limits

Reviewed the README and design specification, agent rules, database setup,
sampling engine, ingestion/download paths, taxonomy enrichment, validation and
analytics queries, quiz/settings event handling, resource helpers, packaging
configuration, CI, and existing tests. Inspection was targeted at critical
workflows; this is not an exhaustive line-by-line audit.

- `uv run --no-sync --offline pytest -q`: **49 passed in 3.72s** using the
  existing environment, with `XDG_DATA_HOME` redirected to a fresh temporary
  directory and `UV_CACHE_DIR=/tmp/taxo-trainer-uv-cache`.
- `uv run --no-sync --offline ruff check src tests scripts --output-format
  concise --statistics`: **passed**, using the same temporary uv cache.
- In-memory sampling probe: inserted 201 observations for one taxon; candidate
  lookup returned 200. Marking that pool seen caused a repeat while the 201st
  observation remained unseen.
- Temporary ingestion probe: a two-row TSV, `batch_size=1`, valid first row,
  invalid second latitude. Import raised `ValueError`, but one occurrence and
  the new `active_dwc_path` remained committed.
- UI findings below are source-based, not browser-reproduced. No native installer
  was built or launched, no real GBIF service was exercised, and no representative
  dataset performance benchmark was run. Passing tests do not establish those
  acceptance criteria.

## Ranked work queue

Effort is relative: S = a focused patch; M = several related changes; L = split
into multiple independently verified patches. These are not time estimates.

| Order | Target | Payoff | Effort | Dependency |
| --- | --- | --- | --- | --- |
| 1 | Quiz hint accounting and submission lifecycle | Trustworthy accuracy and history | S–M | None |
| 2 | Observation coverage and filtered sampling | More useful practice; no false exhaustion | M | None |
| 3 | Download and ingestion recovery | Reliable first run and dataset changes | M–L | Split download/parser fixes from activation |
| 4 | Dataset identity and bad-observation handling | Preserve and isolate user progress | M | Coordinate with 3 |
| 5 | Testable UI actions and resource lifecycle | Catch interaction bugs the current suite misses | M | Start narrowly with 1; expand after 3–4 |
| 6 | Measured ingestion and interaction performance | Responsiveness on real datasets | M | Establish correctness first |
| 7 | Observable, conservative taxonomy enrichment | Explain failures and avoid opaque data loss | M | Recovery approach from 3 |
| 8 | Runtime, distribution, and user documentation alignment | Repeatable installation and accurate guidance | M | Runtime/license decisions where noted |

### 1. Quiz hint accounting and submission lifecycle

**Evidence:** In [quiz_view.py](../src/taxo_trainer/ui/quiz_view.py),
`handle_submit_guess` populates `diagnostic_photo_url` following an incorrect
recognized guess, but does not set `used_hint`. A subsequent correct species
guess passes the unchanged flag to `log_attempt`. That contradicts the design's
rule for reference comparison photos. Also, `if not state.solved` guards streak
updates but not the successful `log_attempt` call, so repeated handler invocations
can record duplicate successes. Whether normal UI interaction reaches the latter
path needs reproduction.

**First patch:** Mark assistance when a diagnostic reference is actually revealed,
and exercise the production action rather than setting state manually in a test.
Keep the original incorrect guess's pre-hint status intact; subsequent assisted
success must not count as unassisted. Make successful submission idempotent for
the current question. Do not redesign streak or attempt-denominator policy.

**Acceptance:** Wrong recognized species -> comparison photo -> correct species
records assisted success; explicit rank/multiple-choice hints remain assisted;
new question resets assistance; repeated submission cannot add extra successful
attempts. Verify persisted rows and dashboard metrics. Existing
`test_analytics_and_hint_penalties` tests flags supplied by the caller, not this
UI-to-database sequence.

### 2. Observation coverage and filtered sampling

**Evidence:** [sampling.py](../src/taxo_trainer/engine/sampling.py),
`get_candidate_observations`, applies an unordered `LIMIT 200` in normal mode.
The probe above reproduces premature repetition. `sample_next_question` retries
Stage 1 only 20 times, although Stage 1 does not account for month or review-only
eligibility. Sparse eligible observations can therefore produce `None` even when
a valid question exists. Review-only lookup also builds an `IN` parameter list
from all incorrect occurrence IDs without a data-source condition.

**Patches:** First restore reachability of every eligible observation and reset
seen tracking only after true per-species exhaustion. Then address filtered
eligibility and large review histories without changing the weight formulas.
Preserve bounded resource use; do not substitute a permanent arbitrary subset.

**Acceptance:** A deterministic fixture with more than 200 observations reaches
the previously excluded observation before repeating; exhausted-species reset
leaves other species' seen state intact. Sparse month/review fixtures distinguish
an empty eligible set from unlucky retries. Exercise include/exclude filters and
review histories large enough to expose parameter-limit assumptions. Coordinate
data-source filtering with item 4.

### 3. Download and ingestion recovery

**Evidence:** [dwc_parser.py](../src/taxo_trainer/ingestion/dwc_parser.py),
`resolve_dwc_source_path`, caches by URL basename and accepts any existing nonempty
file. Downloads write directly to that final filename: interrupted downloads can
be reused, and different URLs with the same basename can collide. `ingest_dwc_file`
sets active metadata before parsing and commits each batch. Invalid latitude or
longitude raises during `float` conversion. The failed-import probe confirms
partial persistence. The per-taxon cap is incremented before media validation,
so unusable records consume the cap. A record-page URL may also be treated as a
photo fallback. [settings_view.py](../src/taxo_trainer/ui/settings_view.py),
`run_ingestion`, reports an error but does not restore the previous dataset.

**Separate patches:**

1. Use collision-resistant URL cache identity and temporary download files;
   publish the cache entry only after successful completion/validation.
2. Define explicit rejected-row diagnostics, robust optional numeric parsing,
   and count usable observations toward the cap. Distinguish record links from
   image media. Preserve streaming and 10,000-row transaction batches.
3. Stage a replacement dataset and validate it before activation, or implement
   an explicit recoverable import state. Coordinate live SQLite connections and
   WAL files; a blind filesystem swap is not a sufficient activation design.
   Keep the previously usable dataset and user history available after failure.

**Acceptance:** Tests cover interrupted download then retry, equal basenames from
different URLs, malformed coordinates, missing media before valid media at the
cap, failure after a committed batch, and a successful retry. Activation updates
source metadata only with a usable dataset, and success counts reflect stored
unique records. Use injected failures and temporary files; do not depend on GBIF.

### 4. Dataset identity and bad-observation handling

**Evidence:** [db.py](../src/taxo_trainer/db.py), `get_active_data_source`, uses
`active_dwc_path` as the identity returned to progress consumers. Moving a file
can change that identity; replacing data at the same path can retain it.
Ingestion upserts into existing tables, so review the distinction between
re-ingestion and replacement before changing activation. In
`handle_report_bad_observation`, the UI promises exclusion from future sessions,
but only updates the session `seen_set`, which can reset, and deletes history by
occurrence ID without a data-source predicate. There is no persistent exclusion
in that handler.

**Scope:** First specify and test existing dataset-switch semantics. Make the
bad-observation message truthful; persistent exclusion and undo are a separate
product decision if extending the current behavior. Scope history operations to
the relevant dataset. Propose stable dataset IDs and a migration only after
deciding what should happen for moved files, changed URLs, and reimports.

**Acceptance:** A/B dataset tests with overlapping occurrence IDs preserve A's
history while operating on B. Clear/reimport preserves the intended preferences
and progress. Any persistent exclusion survives restart and exhaustion and can
be reversed; otherwise the UI explicitly describes session-only behavior.
Existing saved databases remain readable after any migration.

### 5. Testable UI actions and resource lifecycle

**Evidence:** `render_quiz_view` owns nested transition handlers and opens two
database connections without explicit closure in that function. Some tests,
including `test_higher_order_hint_sequential_revelation` in
[test_engine.py](../tests/test_engine.py), simulate transitions by assigning
fields rather than invoking production handlers. The pipeline integration test
calls backend functions directly. Ingestion progress mutates UI from the worker
callback; enrichment uses a different progress update approach. These are
coverage/lifecycle concerns, not demonstrated browser failures.

**Scope:** Extract only the quiz actions needed for item 1 behind a small state
and persistence boundary. Reuse that boundary for later actions; avoid a full UI
rewrite. Define connection ownership and cleanup on refresh/disconnect, and
one consistent worker-to-UI progress mechanism after checking installed NiceGUI
behavior. Exercise dataset changes while views are active.

**Acceptance:** Production-action tests cover hint, submit, skip, report, and
dataset-switch sequences. A small UI smoke suite checks keyboard focus, repeated
rendering, two independent clients, tab navigation, and worker completion after
disconnect. Demonstrate cleanup instead of inferring a leak from missing `close`.

### 6. Measured performance improvements

**Candidates, not measured bottlenecks:** `_flush_batch` rebuilds/upserts the full
accumulated taxonomy dictionary for every occurrence batch; multimedia loading
builds a full in-memory index. `autocomplete_taxa` in
[validator.py](../src/taxo_trainer/engine/validator.py) uses multiple transformed
name/JSON searches followed by Python ranking and `fetchall`. Stage 1 reloads
taxa and weights on each question. Analytics repeatedly initializes schema and
runs aggregate queries. Indices alone do not establish constant-time behavior.

**First deliverable:** A reproducible baseline on the bundled plant/butterfly
archives and a larger representative input. Record input sizes, row/taxon counts,
environment, import wall time/peak memory, and p50/p95 autocomplete, next-question,
and dashboard latency. Keep network enrichment timings separate. Compare repeated
fresh runs and check equivalent database contents and ranking outputs.

**Then:** Optimize the largest measured cost in a focused patch, such as dirty-taxa
batch updates or query/index changes supported by `EXPLAIN QUERY PLAN`. Preserve
Unicode names, exact-match ordering, filters, and sampling semantics. Add caching
only with explicit invalidation for filters, ingestion, and enrichment. Do not
claim the specification's throughput target has been met until measured.

### 7. Observable, conservative taxonomy enrichment

**Evidence:** [taxonomy_builder.py](../src/taxo_trainer/ingestion/taxonomy_builder.py)
maps network/JSON failures to `None` in `fetch_gbif_raw_api`; several worker error
paths are swallowed. `consolidate_synonyms_with_gbif` deletes occurrences/taxa for
higher-rank matches and merges synonym taxa, while progress resides separately.
The existing synonym test covers a mocked success path, not the full recovery
and history implications.

**Scope:** Report fetched/cached/unchanged/failed/merged counts; distinguish an
unavailable response from a valid no-match. Add bounded retries and resumable
failed work, and verify connection cleanup. Before changing matching policy,
test conservative handling of ambiguous/higher-rank results and propose a
reviewable, reversible transformation approach. Keep GBIF as the authority;
do not invent a new taxonomy resolver.

**Acceptance:** Mock timeouts, malformed responses, rate limiting, higher-rank
matches, and partial completion. Verify repeatability, vernacular precedence,
foreign-key integrity, occurrence counts, and interpretation of historical
taxon keys after merges. No silent success message when enrichment failed.

### 8. Runtime, distribution, and documentation alignment

**Evidence:** `pyproject.toml` declares Python >=3.10, the specification requires
3.12+, and `.python-version` pins 3.14. CI uses `uv sync` without a lock-enforcement
flag and tests only Ubuntu in the ordinary workflow. Packaging tests simulate
frozen resource paths; they do not launch a built app. Wheel configuration includes
`src/taxo_trainer`, while runtime resources are resolved from repository-root
`assets` and dataset directories. This warrants a clean installed-wheel check;
source checkout tests can hide missing resources. The README leaves keyboard
shortcuts partly undocumented and ends with an unfinished packaging/license item;
no repository license file was found.

**Scope:** Resolve the supported Python range explicitly, then align metadata,
interpreter selection, and CI. Add clean wheel/resource and native bundle smoke
checks; validate startup, guide assets, initial data, and persisted progress on
the supported operating systems. Enforce the lockfile for reproducible CI without
expanding every pull request into a full installer build. Preserve agent-only
path exclusions. Document actual keyboard behavior, data location, recovery,
and platform setup once checked. License selection requires the owner's choice;
do not choose one on their behalf.

**Acceptance:** Clean installation outside the source tree resolves needed assets;
chosen Python/OS combinations pass; built artifacts start and retain progress
after restart. README commands match those verified workflows. Record untested
platforms explicitly rather than implying native compatibility from mocked tests.

## Recommended execution sequence

Start with diagnostic-hint accounting and a production-action regression test.
Follow with the independently reproducible 200-observation sampling fix, then
download-cache recovery. These provide useful, narrowly reviewable improvements
without first requiring a broad architecture or product-policy decision.

Next split ingestion validation from dataset activation, settle dataset identity,
and expand interaction coverage as those paths change. Establish performance
baselines before selecting optimizations. Runtime alignment is a small decision
to settle early, while full distribution validation can follow the core fixes.

Defer cosmetic themes, more gamification, new external services, broad framework
refactors, and scoring-policy changes. New dependencies should have a concrete
demonstrated need. Each implemented target should include relevant regression
tests, full-suite/Ruff results, and explicit remaining limitations.

Keep roadmap updates, findings, and handoffs under `.agents/`. Commit them only
in dedicated `agent:` commits, separate from implementation, tests, CI, and
product documentation. Update this roadmap with evidence as targets are completed;
do not mark source-inspection hypotheses as confirmed fixes without verification.
