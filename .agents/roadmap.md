# Development roadmap

Reviewed 2026-09-09 against checkout `c80a59b`. This is a prioritized backlog,
not authorization to implement every item or change product policy.
All paths in links are relative to this document. Function names are the stable
navigation anchors; line numbers may change as work lands.

## Direction

### Hard boundary: GBIF identity, never free-text API resolution

The user's clarification after the contribution review supersedes any proposal
below to improve free-text matching: canonical class/species references must be
GBIF IDs everywhere in the app and in API queries. NEVER query free-text APIs,
including GBIF name match/search/suggest endpoints. Names remain display/input
aliases. Taxonomic ambiguity and delayed local-name integration are inherent;
complete resolution or coverage is not an acceptance criterion. See the
[canonical identity rule](README.md#canonical-identity-and-api-boundary-hard-user-requirement).

Source inspection confirms the existing code violates this boundary:
`taxonomy_builder.py` calls `/species/match?name=...` for species, derived base
names, higher ranks, and synonym consolidation. Consolidation also finds the
accepted local record by canonical-name equality. These paths must be replaced
with GBIF-ID-based retrieval and explicit ID relationships, not improved text
matching. Review ingestion, higher-rank storage, local validation, and history
identity together so the restriction applies inside the app as well as on the
network. Missing IDs must remain unresolved without free-text fallback.

This compliance work takes precedence within the proposed taxonomy target;
preserving existing language entries remains useful within that boundary.
Regression coverage should reject free-text request paths and name-derived
canonical identities while preserving local alias-based user input. This update
records the rule and source findings only; existing application paths have not
yet been changed, and no API requests were made during the review.

### Current priorities: README contribution review

Re-reviewed against `274123b` on 2026-09-09. This section supersedes the original
ranking and execution sequence below; numbered items remain historical backlog
references. The README's contribution list explicitly has no ordering. The
priority recommendations here are judgments based on product value and the user's
subsequent steering, not priorities attributed to that list.

The original roadmap overemphasized internal reliability and underrepresented
several explicitly welcomed contributions. The completed accounting, import, and
lookup fixes are useful foundations, but finishing every remaining edge case is
not a prerequisite for taxonomy, session usability, documentation, or styling work.
The user has also deprioritized sparse filtered sampling, cross-dataset history
edge cases, and speculative performance work. Optional usability feedback on the
name card is not a prerequisite for further development.

| README contribution request | Current implementation and roadmap fit | Revised treatment |
| --- | --- | --- |
| Taxonomic issue detection and resolution | Synonym consolidation and rank handling exist; item 7 buried correctness beneath request reliability. | Highest-value investigation: verify that matching preserves biological identity, useful observations, names, and progress. |
| Better vernacular resolution | Multilingual lookup, scoring, cache recovery, and coverage feedback exist. Recent work mostly improved transport and presentation, not matching quality. | Prioritize correct taxon/rank association, retained language coverage, and accepted aliases; keep GBIF as authority. |
| Cross-platform compatibility | Three-OS packaging workflow exists; ordinary CI is Ubuntu-only and packaging tests simulate resources. Item 8 covers this. | Concrete clean-install and native launch checks remain valuable; do not infer working installers from configuration. |
| Performance | Candidate costs are recorded in item 6; no user-observed general slowdown. | Measure reported loading/name-resolution delays first, respecting cache reuse and API cooldowns. |
| More test coverage | Recent regression work expanded backend and some production-action coverage. Item 5 covers remaining interactions. | Add tests alongside meaningful workflows, especially taxonomy and restart persistence; avoid coverage for its own sake. |
| UI, app-state, and database consistency | Items 4–5 cover technical concerns but understate everyday settings consistency. | Prefer small fixes to shared preference handling over broad refactoring or migrations. |
| Gamification and metrics | Streaks, mastery, trouble taxa, and confusion pairs already exist; initial roadmap mostly addressed accounting. | Retain as an eligible contribution area, with learning value and user-controlled outcomes ahead of extra rewards. README calls it secondary. |
| State consistency across sessions | Language/theme/cutoff and some filters persist, but settings callbacks are inconsistent. | Explicit near-term target: settings should survive reopening consistently. |
| Documentation and guides | Existing illustrated guides are substantial, but README and onboarding still reference old name-lookup labels and Danish/English-only wording. | Small, concrete follow-up: align instructions with the selected-language workflow; inspect screenshots before claiming they are current. |
| Themes and styling | Light/dark/system modes exist; hardcoded dark styles are counteracted by a large light-mode override block in app.py. | Legitimate contribution area, not categorically deferred until all internals are fixed. Start with consistency/readability if pursued. |
| Packaging and license | Build scripts and installers exist; no license file found. Item 8 bundles several separate concerns. | Split packaging verification from the owner's license choice; do not select a license incidentally. |

Recommended next target: **taxonomy and vernacular correctness during name
enrichment**, starting with a bounded set of regression cases rather than a new
resolver or more status controls. Source inspection found:

- `enrich_vernacular_names_from_gbif` gathers names from several returned keys
  without explicit match-confidence/rank validation at that collection step.
  Test species versus higher-rank matches and synonym relationships before
  choosing changes to matching policy.
- Its species update replaces `vernacular_json` wholesale whenever any names are
  returned. A later response containing fewer languages can therefore discard
  previously stored language entries; higher-rank updates already merge JSON.
  Preserving languages absent from a later response is a focused first candidate.
- The same lookup runs `consolidate_synonyms_with_gbif`, whose higher-rank branch
  deletes the species and its observations. An uncertain name match can therefore
  affect what remains available for practice. Synonym merges also warrant tests
  for name aliases, occurrence counts, and historical taxon references. Do not
  treat a higher-rank result as evidence that an observation is mislabeled.
- Vernacular scoring contains Nordic source preferences and rank suffix rules,
  including a Danish-specific acceptance threshold. Audit representative supported
  languages; these heuristics are not by themselves proof of incorrect results.

These are source-confirmed mechanisms and proposed regression targets, not newly
reproduced failures against live GBIF data. Preserve the README's boundary: improve
use of GBIF results rather than attempting to resolve disagreements among external
taxonomic authorities. User-approved matching-policy changes should be explicit.

Next alternatives are session preference consistency and guide refresh. For
example, quiz initialization reads `sampling_mode`, but the settings mode callback
only updates in-memory filters; two cutoff controls also differ in persistence.
Reproduce the relevant restart flow before implementing a shared fix.

Review validation: inspected README, rules/specification, roadmap, taxonomy and
settings code, tests, resources, guides, and CI/packaging configuration. No live API,
browser, installer, or performance validation was performed for this review.
Documentation-only changes require path/link and whitespace checks, not a test run.

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

Item 3's download portion is complete. Its row/media validation follow-up is
recorded below. Partial database imports are not addressed by the download fix.

### Progress update: optional coordinates and media eligibility

Malformed, blank, nonfinite, and out-of-range latitude/longitude values now become
NULL rather than interrupting ingestion or reaching the map. Valid coordinates,
including zero and geographic boundaries, are retained independently.

The per-taxon cap increments only after media eligibility checks. Occurrence
record identifiers/references are no longer promoted to photo URLs. Explicit
associatedMedia/accessURI fields and multimedia identifier/accessURI fields
accept HTTP(S) URLs with a host, trim whitespace, and deduplicate. Dynamic URLs
without image extensions remain supported. Local TSV imports now discover sibling
multimedia.txt (including verbatim/multimedia.txt); the former filename condition
missed the standard occurrence.txt name. ZIP media loading remains supported.

Eleven regression cases cover coordinate failures/boundaries, media eligibility,
cap accounting across transaction batches, and direct, sidecar, and ZIP media.
Nine failed against the prior implementation. Final verification: 72 tests passed
in 4.11s, Ruff passed for changed files, and diff whitespace passed. An initial
full-suite run exhausted temporary disk through repeated bundled-data seeding;
the new parser tests now bypass that unrelated seeding and our temporary
application-data directories were cleaned before the successful rerun.

These checks establish syntactic media eligibility, not remote availability or
actual image content. Invalid-coordinate/rejected-row summary diagnostics,
duplicate-record accounting, and atomic dataset activation remain separate work.
The recoverable activation follow-up is recorded below. Keep it separate from
user scoring and taxonomy-policy changes.

### Progress update: recoverable import publication

The public importer now parses into a disposable SQLite database using the
existing transaction batches. Only a nonempty prepared import reaches activation.
A single transaction copies prepared taxa/observations and active-source metadata
into the live database and runs index maintenance. Publication uses SQLite with
the existing live file, not a file replacement that could strand open connections
or WAL files. Setup and multimedia-loading failures also close the staging
connection. The UI reports preparation counts and no longer performs separate
post-publication index maintenance.

This deliberately retains the existing add/update behavior: importing another
source does not automatically delete old records, and the explicit clear action
remains separate. It is not a dataset-replacement policy or multi-dataset storage
redesign. Existing preferences and the separate user database are preserved.
Dataset identity and the consequences of mixing sources remain item 4 work.

Four injected-failure scenarios cover a callback error after a staging batch,
a SQLite trigger abort midway through live publication, an empty import, and a
malformed ZIP. Tests compare the live database dump before/after failure, retry
successfully, and use the same open reader connection to verify committed data,
metadata, preferences, integrity, and foreign keys. Final verification: 76 tests
passed in 6.15s; Ruff and diff whitespace passed. Native UI behavior, concurrent
writers, process termination, and large-import performance were not exercised.
Staging requires additional temporary disk space and activation holds a write
transaction while publishing; those costs need representative measurements.

Next recommended target: dataset-isolation tests around overlapping occurrence
IDs and the report-misidentified action, followed by a narrowly scoped fix for
cross-dataset history deletion. Stable dataset identity and replace-versus-merge
semantics should be settled explicitly before broader migration work.

Prioritize trustworthy training results, complete observation coverage, and
recoverable dataset operations. These directly support the README's emphasis
on a functional, fast, reliable application without unnecessary dependencies.
The application already has substantial quiz, analytics, guide, and packaging
functionality. Improve these workflows according to the current contribution
review above; remaining internal fixes do not block other welcomed contributions.

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

## Original ranked work queue and implementation evidence

The current-priorities review above supersedes this ordering. Evidence in the
original numbered descriptions describes the initial review; progress updates
record fixes and their verification.

Priority steering: the user has not experienced general performance problems and
deprioritized the cross-dataset history edge case. Focus loading/name resolution
work on reliability and cache reuse, not a broad performance campaign or increased
API concurrency. GBIF request limits depend on server load; see the
[official rate-limit guidance](https://techdocs.gbif.org/en/openapi/#rate-limits).

### Progress update: GBIF cache and visible failures

Fresh cached JSON objects, including valid no-match/empty-name responses, are
reused. Expired, malformed, and wrong-shaped cache entries trigger a fresh lookup.
Network/HTTP/decoding failures now raise a distinct GBIFRequestError instead of
returning None and being confused with missing names. Failed responses are not
cached; cache-write failures log a warning but retain the successful response.

HTTP 429 establishes a shared in-process cooldown for uncached requests across
enrichment workers and retries. Retry-After seconds and HTTP dates are supported;
missing/invalid headers use a 60-second fallback. Fresh cache hits remain available
during cooldown. No automatic retry loop or increase in worker concurrency was
introduced. The UI offers a manual retry, which reuses completed cache entries.
The cooldown is not persisted across process restarts; requests already in flight
when a 429 arrives cannot be recalled.

Species, higher-rank, and synonym phases now propagate worker failures and cancel
queued futures where possible. Successful updates already committed are retained.
The settings view saves an incomplete-run error, displays it after reload, and
clears it only after successful enrichment, avoiding a false completion banner.
This is run-level error reporting, not a per-taxon status inventory; cached versus
fetched counters and detailed no-name/failure summaries remain follow-up work.

Verification: 95 tests passed and Ruff passed for changed files. Nineteen new
offline cases cover cache reuse/expiry/corruption, empty results, malformed
responses, cache-write failure, cooldown and delayed retry, and outage propagation
from all three production enrichment phases. Browser rendering, actual GBIF
requests, and sustained concurrent load were not tested. Matching/ranking policy
and the existing 30-worker configuration remain unchanged.

The summary follow-up is completed below. Measure loading only where the user
observes a delay; do not prioritize speculative optimization.

### Progress update: expert-user feedback and configurable name language

The user clarified that interface feedback should serve nontechnical biological
experts, and that vernacular language is configurable, not limited to Danish.
The name card now reports species coverage in the selected language and how many
still lack names in that language. Another-language fallback does not count as
coverage. Scientific-name mode describes vernacular lookup as optional; empty
datasets prompt import. Absence is described as availability in the dataset, not
proof that a species has no vernacular name.

The existing language selector now persists its preference and refreshes coverage
immediately. Old Danish-specific dataset badges and lookup labels were removed.
All supported languages remain part of enrichment. Genus/family lookup no longer
skips records merely because they have Danish names; updates preserve names in
other languages. Successful rechecks of unchanged species names return zero
updates rather than an inflated count. UI completion messages focus on current
name availability instead of this developer-oriented write count.

Run-level cache hits, HTTP requests, failures, cooldown skips, and cache-write
failures are recorded through the taxonomy_builder logger at INFO level (enable
that level in backend logging to view the summary). Exceptions/tracebacks go to
backend logging; the UI gives a plain-language retry action and approximate wait
after a GBIF pause. Later lookup phases use indeterminate progress instead of
showing 100 percent while more work remains. Request concurrency is unchanged.

Verification: 106 tests passed in 6.17s; Ruff and diff whitespace passed. New cases
cover five selected languages, scientific/empty modes, plain-language errors,
the actual settings language-selection callback and saved preference, multilingual
species/higher-rank results, unchanged cached rechecks, and backend counters.
Native/browser visual inspection and live GBIF calls were not performed. This
change configures preferred taxon names; it does not translate the whole UI.

Next useful step: have the user try the names card in their preferred language
before adding more statistics or controls. Any remaining name-resolution examples
can then guide focused fixes rather than speculative enrichment changes.

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

## Original execution sequence (superseded)

Start with diagnostic-hint accounting and a production-action regression test.
Follow with the independently reproducible 200-observation sampling fix, then
download-cache recovery. These provide useful, narrowly reviewable improvements
without first requiring a broad architecture or product-policy decision.

Next split ingestion validation from dataset activation, settle dataset identity,
and expand interaction coverage as those paths change. Establish performance
baselines before selecting optimizations. Runtime alignment is a small decision
to settle early, while full distribution validation can follow the core fixes.

The initial blanket deferral of themes and gamification is superseded by the
README contribution review above. New external services, broad framework
refactors, and scoring-policy changes require a concrete purpose and scope.
New dependencies should have a concrete
demonstrated need. Each implemented target should include relevant regression
tests, full-suite/Ruff results, and explicit remaining limitations.

Keep roadmap updates, findings, and handoffs under `.agents/`. Commit them only
in dedicated `agent:` commits, separate from implementation, tests, CI, and
product documentation. Update this roadmap with evidence as targets are completed;
do not mark source-inspection hypotheses as confirmed fixes without verification.
