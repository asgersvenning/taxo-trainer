# Photo inspection and reference gallery

Implemented in `bb064e8` (zoom, pan, place retention, loading/recovery) and
`bdb3289` (reference gallery and user instructions).

- Browser-local transforms are keyed by per-client viewer UUID and question
  generation. Selection and framing survive genus answers and settings redraws;
  new observations reset them. Fit, wheel/button zoom, drag, and touch handlers
  live in the custom NiceGUI component. The PyInstaller specification includes
  its JavaScript asset.
- Loading and failure states offer Retry and Try another photo. Retry preserves
  the original URL, including signed query parameters. Stale load events cannot
  replace a newly selected image.
- Incorrect recognized guesses open a second independently inspectable viewer.
  References include distinct URLs from every locally imported observation of
  the guessed canonical taxon ID. No new taxonomy or free-text API calls occur.
  Observer and source follow the selected record. Hide/reopen retains selection.
  A subsequent guess without images clears the previous reference.
- Existing assistance policy remains: showing references marks assisted;
  browsing photographs adds no attempts. Personal overrides remain available.
- Two viewers sit side by side on wide windows and stack on narrower windows.
  Both use the shared semantic palette. README and quiz guide text explain the
  controls; historical guide screenshots have not been regenerated.

## Verification

Final full suite: **173 passed in 13.39s**. Changed-file Ruff and diff whitespace
checks passed. Tests exercise actual navigation callbacks, answer/settings
retention, reference deduplication/provenance, no extra attempts, assistance,
and clearing stale references.

Chromium used isolated temporary databases and deterministic SVG photo fixtures,
with no changes to personal training data. Checks covered zoom/drag, exact framing
across genus answers and settings, reset on advancement, retry after failure,
slow-image navigation, six reference photos spanning three observations,
independent selection/zoom, hide/reopen, and reference failure recovery. Layouts
were inspected at 1440x1000 and 1024x820, plus dark high-contrast error controls.
No browser page errors or server callback errors remained. Visual inspection
caught and fixed narrow-layout width collapse. Earlier ResizeObserver warnings
were fixed with absolute image positioning and scheduled resize handling.

Native installers and real-device touch gestures were not exercised. Browser
checks use synthetic fixtures rather than claiming real-network availability or
comprehensive accessibility certification. Reference availability depends on the
loaded dataset; the gallery does not fetch additional observations from GBIF.
