# Background taxonomy repair checklist handling

User reported `GBIFRequestError: Conflicting checklist identity for higher rank`
from startup repair. Fixed in `5ef7f05`.

The existing-rank fast path can supply an unknown checklist (None) while a stored
rank already has known CoL provenance. The old comparison treated that as a
confirmed conflict and aborted the whole pass. Read-only aggregate inspection of
the local database found unknown species checklists linked to known CoL ranks
(7 genus links, 12 family links, 12 order links), without confirmed mismatches in
those joins. No personal database was modified.

Repair now distinguishes missing metadata from explicit namespace disagreement.
Known rank metadata is retained; no namespace is inferred from names or ID shape.
Every candidate rank is checked before any writes for that taxon. Confirmed
collisions skip the whole taxon, log the IDs/checklists in the backend, and allow
other taxa to continue. Unresolved no-op rows no longer count as repaired.
Network failure handling and the separate vernacular enrichment path are unchanged.

Two regression cases reproduced the original exception before the fix. Coverage
now includes missing namespace metadata, a real conflict with no partial writes
and continued repair of another taxon, and no-op counting. Final verification:
176 tests passed in 8.66s; changed-file Ruff and whitespace checks passed.
The repair also completed on an in-memory backup of the actual database with
remote resolution disabled. This checks the local fast path, not live GBIF
responses. Runtime reload/restart is needed to pick up the new code.
