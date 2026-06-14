# AI Transcripts

This submission was built with heavy assistance from Claude (Anthropic),
used in two ways as suggested by the assignment:

## 1. Understanding the problem (web chat)

I used Claude.ai to read through the BhuMe assignment site and the
candidate preparation document, clarify terminology (7/12, hissa,
pot-kharaba, area-ratio triage, IoU/AUC/calibration), and plan an approach
before writing any code.

**Share link:** _[paste your Claude.ai share link here — click "Share" on
the conversation, copy the public link, and paste it in this line]_

## 2. Building the solution (this same conversation)

The same conversation was used to:
- Inspect the provided starter kit (`bhume/io.py`, `bhume/geo.py`,
  `bhume/score.py`, `bhume/baseline.py`, `quickstart.py`, `CONTRACT.md`).
- Inspect `input.geojson` (2,457 plots, Vadnerbhairav) and the imagery GeoTIFF.
- Diagnose that the downloaded `imagery.tif` and `boundaries.tif` were
  partial downloads (`.crdownload` files) — `imagery.tif` was 58% readable,
  `boundaries.tif` was unreadable.
- Iteratively design, test, and debug `correct.py`:
  - Area-ratio triage thresholds.
  - Sobel edge detection + FFT cross-correlation of a polygon-boundary
    template against the edge image, to estimate per-plot (dx, dy) shifts.
  - A bug in an f-string format specifier that was silently causing every
    successful alignment to be miscounted — found and fixed.
  - Spatial-consensus refinement (KDTree over neighbouring plots' shifts)
    to catch and correct outlier correlations.
  - Inverse-distance-weighted interpolation for plots outside the imagery
    extent, replacing a single flat village-wide shift.
  - A three-component confidence formula (correlation SNR, area-ratio
    agreement, spatial consensus) instead of a flat number.
- Generate visual before/after diagnostics overlaying official (red) vs.
  corrected (green) boundaries on the satellite imagery to sanity-check
  the method.
- Validate the output schema (`predictions.geojson`, 2,457 features, 0
  invalid geometries after repairing one self-intersecting input polygon).

**Full transcript:** _[export or share-link this conversation and paste it
here, per the instructions in the main assignment doc — Claude.ai: Share →
copy public link]_

## What I'd flag if reviewing this myself

- The pipeline runs on partial imagery (58% of the village). With the full
  `imagery.tif` re-downloaded, re-running `correct.py` should directly align
  more of the 1,306 currently-interpolated plots — I'd expect this to be the
  single biggest improvement available without changing the method.
- The 36% outlier-replacement rate in the spatial-consensus step suggests the
  raw per-plot correlation is noisier than I'd like; I discuss possible causes
  and fixes in the main `README.md`.
