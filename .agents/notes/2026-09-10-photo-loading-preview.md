# Photo loading preview regression

User noticed slower image loading after the zoom/pan viewer was introduced.
Fixed the confirmed display delay in `234fcd9`.

The custom image was hidden until its load event (full download completion),
unlike the former plain image element. A local streaming JPEG response supplied
half of the existing quiz-guide JPEG immediately and delayed the remainder by
three seconds. Chromium reported naturalWidth=1065 and complete=false while the
old viewer kept visibility=hidden. This demonstrates a display delay, not slower
network throughput or a comprehensive diagnosis of external image hosts.

The image now remains visible during loading, with CSS scale-down sizing before
JavaScript dimensions become available. The loading label sits at the bottom;
zoom remains disabled until completion. Failed images still hide behind the
existing recovery controls. No prefetching, API calls, or dependencies were added.

## Verification

The same streaming fixture after the fix showed a visible partial image after
289 ms, with completion observed after 3712 ms (polling/screenshot overhead is
included; these are fixture timings, not a real-world speed claim). Assertions
checked incomplete-but-visible state, nonzero bounds, loading feedback, disabled
zoom until completion, then enabled and functioning zoom. The screenshot visibly
contained the partially decoded photo. No page errors occurred.

Existing isolated Chromium flows passed zoom/drag, answer/settings retention,
new-question reset, retry, navigation away from slow images, independent reference
viewers, six-photo provenance, hide/reopen, and wide/narrow layouts. Both local
server logs contained no callback errors. Full suite: 176 passed in 13.89s;
whitespace checks passed. No Python files changed. Browser fixture/scripts were
run from /tmp; no new frontend test framework was introduced for this small fix.
The fixture used the existing guide JPEG because Pillow is not installed; no
additional dependency was installed. Actual image hosts and native desktop
rendering were not benchmarked. Both isolated preview servers were stopped.
