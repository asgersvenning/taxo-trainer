# Autocomplete, appearance, and practice follow-up

## Scope and checkpoints

The user authorized: restore higher-rank autocomplete and ranking, add themes
including higher contrast, connect statistics to focused practice, synchronize
training settings, and make Ignore observation reversible.

- `d5ca80e`: exact aliases first and combined word edit distance.
- `ab03b10`: restore imported rank IDs through explicit GBIF classifications.
- `caea378`: Warm paper, Neutral, High contrast; Amber, Rose, Slate accents.
- `c736947`: dashboard practice actions and synchronized training controls.
- `99d4ca2`: normalize individual aliases; count matching IDs for ambiguity.
- `e74e8f5`: Undo ignore with exact history and current-question preservation.

## Findings and behavior

Local Prunus species had CoL IDs but NULL genus/family keys and no Prunus rank
row. Ranking alone could not restore a selectable genus. Read-only inspection
and occurrence 6470706609 confirmed the explicit CoL relationship from species
4N93X to genus 6Y6H and family FTK. A live lookup against an isolated fixture
restored Prunus as the first suggestion and validated the genus ID.

Missing hierarchy links are repaired in the background after page load, including
import reloads. The worker reuses ID-addressed caching and rate-limit handling,
uses four workers, and excludes overlapping jobs. Typing stays local. No
free-text APIs, name-derived IDs, or numeric CoL casts were introduced. Missing
or ambiguous classifications remain unresolved. User history was not modified
by verification.

Autocomplete retains local prefix/multiword/substring candidate discovery.
Exact normalized aliases at every supported rank precede nonexact matches.
Exact ties retain primary/scientific versus secondary-alias preference and
lowest-rank preference. Otherwise the lowest unambiguous matching rank comes
before ambiguous ranks, and combined word Levenshtein distance replaces display
length as the main similarity ordering. IDs determine ambiguity. Arbitrary fuzzy
query discovery was not added.

Four palettes combine with light/dark/system appearance and six accents. High
contrast has at least 7:1 main, muted, and feedback text against base surfaces
in both modes. All accents meet 4.5:1 text contrast on all base surfaces. Palette
and accent persist and survive dataset clearing.

Dashboard group and confusion tables expose Practise actions using IDs. Temporary
practice overrides normal taxonomic inclusion/exclusion and family/genus filters,
plus misidentified-only mode. Normal selection remains intact. Minimum count,
weighting, and other applicable sampling preferences still apply. Return to
previous practice restores normal sampling. An unavailable selection leaves the
current question intact. Order IDs now participate in include/exclude filtering.
Temporary scope is client-local and does not overwrite persisted normal filters.

Settings refresh preserves the question and draft guess. Changed training
criteria apply to the next observation, with a short indication in Quiz. Answer
validation and Enter retain the question's original cutoff. Group chips refresh
in both directions and after Settings edits. Quiz shortcuts run only on the Quiz
tab; Escape remains a focus toggle. Empty filtered pools are distinguished from
missing imported data.

Undo retains the latest ignore snapshot in the client session. DELETE RETURNING
captures exact removed rows atomically. Restoration inserts original IDs,
timestamps, flags, and dataset associations without replacing intervening rows.
Repeated Ignore clicks retain the snapshot. Undo after advancing preserves the
new question. Manual correction policy and the existing ignore scope are retained.

## Verification

- Full suite: **168 passed in 7.37s**; changed-file Ruff and whitespace checks passed.
- Regression coverage: word-distance ordering; exact higher-rank and whitespace/
  pipe-alias matching; CoL repair without name lookup; palettes, accents, and
  persistence; temporary scope restoration; original-question cutoff; unavailable
  scope; order IDs; Settings chips; exact Undo and Undo after advancing.
- Chromium used isolated training/history data. Standard, Warm paper, and Neutral
  combinations passed with an active quiz. All twelve High contrast mode/accent
  combinations passed across all four views after transitions settled. These
  are sampled rendered checks, not a comprehensive accessibility certification.
- End-to-end browser checks: single species and confusion-pair practice, return,
  cutoff change with a pending question, empty pool feedback, both Escape
  directions, both directions of group synchronization, Undo after advancing.
  Exact before/after history hashes matched on Undo. No page errors.
- Verification corrections: a fixture inherited cutoff 15 while taxa had ten
  observations; the cutoff was corrected and active-quiz checks repeated. A
  transient theme-transition color required settled-state verification. Chip
  disappearance required waiting for the server response.

## Follow-up boundary

The authorized sequence is complete. Do not resume packaging or speculative
performance work without new direction. Keep agent notes under .agents and
commit them separately with agent: messages.
