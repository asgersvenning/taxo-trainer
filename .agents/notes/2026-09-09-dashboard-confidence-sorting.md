# Restore confidence-aware dashboard sorting

The user reported that Accuracy by group had reverted to raw accuracy sorting.
The engine still calculated the existing Bayesian score, `(correct + 1) /
(attempts + 2)`, and supplied the initial practice order. The UI omitted that
score from table rows: clicking the accuracy header sorted raw percentages,
and pagination state retained that raw sort across refreshes.

The table now carries the engine score and uses it in the accuracy column's
client-side comparator. Default pagination explicitly sorts that column ascending;
binary sorting reverses the practice order without a third unsorted state.
Displayed percentages and attempt counts remain factual. The helper text explains
that practice order considers accuracy and number of attempts. No changes were
made to the statistical formula, prior, assistance accounting, or taxon identities.

The regression fixture contrasts one incorrect attempt (0/1) with one correct
out of ten (1/10), proving that raw percentage and practice order differ. It
checks score propagation, default sorting, and retention of reverse sorting.
Full suite: **170 tests passed in 11.47s**; Ruff and whitespace checks passed.

Chromium verified the real comparator in both directions, sample-count tie
ordering, refresh, changing Species to Genus, and ordinary attempt-count sorting.
The isolated six-taxon fixture also contrasts 1/1 with 9/10 and 1/2 with 10/20.
The final server log contained only startup, with no callback errors. Preview
setup initially needed an explicit page route to avoid rerunning fixture inserts;
the browser locator was corrected using inspected header markup. No user data
was changed by verification.
