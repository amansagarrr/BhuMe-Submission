# BhuMe Take-Home — Plot Boundary Correction

This repo turns each village's `input.geojson` (official, drifted cadastral
boundaries) into `predictions.geojson` (best-guess corrected boundaries +
confidence), using satellite imagery as the primary signal.

## Quick start

```bash
uv sync
uv run correct.py data/34855_vadnerbhairav_chandavad_nashik
```

This writes `data/34855_vadnerbhairav_chandavad_nashik/predictions.geojson`
and (if `example_truths.geojson` is present in that folder) prints a
self-score. I did not have `example_truths.geojson` for this village when I
built this — download it from `hiring.bhume.in/start` and drop it into the
village folder to get the practice scoreboard.

To run on a subset first (useful while iterating):

```bash
uv run correct.py data/34855_vadnerbhairav_chandavad_nashik --limit 300
```

## The approach, in one paragraph

Most of a village's drift is a smooth, spatially-varying field — it comes from
a handful of control points used to warp an old paper sheet onto satellite
imagery, so nearby plots drift similarly and far-apart plots can drift quite
differently. So instead of one flat shift for the whole village (the
`global_median_shift` baseline), I estimate a shift **per plot** from the
imagery itself, then use **neighbouring plots' shifts to sanity-check and
interpolate**. Confidence is built from three independent, observable signals
— not a flat number — so it should actually track accuracy.

## Pipeline (see `correct.py` for the full version with comments)

**1. Triage by area ratio.**
`ratio = drawn_area / (recorded_area + pot_kharaba)`. If this is far from
1.0 (outside `[0.45, 2.8]`), the *shape* disagrees with the 7/12 record —
this is an "area problem", and moving the polygon won't fix it. These plots
are **flagged**, original geometry kept. ~127 plots (5%) fell here.

**2. Per-plot image alignment (cross-correlation).**
For each remaining plot that overlaps the downloaded imagery:
- Crop the satellite patch around the plot (`patch_for_plot`).
- Compute a Sobel edge-strength image of the patch (where do colours change
  sharply — likely a bund, road, or crop-line).
- Rasterise a thin ring around the plot's *official* boundary — this is the
  "template" we're trying to slide onto a real edge.
- FFT cross-correlate the template against the edge image within a ±55 m
  window. The peak location → candidate `(dx, dy)`. The peak's sharpness
  relative to the background (signal-to-noise ratio, SNR) → how trustworthy
  this looks.
- If SNR < 2.0 (no clear peak — e.g. the plot is under tree cover or next to
  buildings where `boundaries.tif` itself is unreliable, per the assignment
  notes), the plot is **flagged** rather than guessed.

647 plots (26%) got a direct image alignment this way.

**3. Spatial-consensus refinement.**
Because drift varies smoothly, a plot's own correlation should roughly agree
with its neighbours'. For each aligned plot, I look at other aligned plots
within 300 m:
- Agreement within 15 m → keep the plot's own shift, high consensus signal.
- Disagreement up to 45 m → keep own shift, but lower consensus signal.
- Disagreement beyond 45 m → the plot's own correlation likely locked onto
  the *wrong* edge (a neighbour's boundary, a road, etc.) — **replace** its
  shift with the neighbourhood median, and cap confidence accordingly.

231 of 647 (36%) were flagged as outliers this way and corrected via their
neighbours — visually, these tended to be small plots tucked next to roads or
other parcels, where the boundary ring is short and easily confused with a
nearby edge.

**4. Interpolation for plots without local imagery.**
The downloaded `imagery.tif` only covers part of this 54 km² village (~58%
of rows were fully downloaded). For the ~1,600 plots outside that area, I use
inverse-distance-weighted interpolation of the nearest aligned plots' shifts
(within 3 km, up to 8 neighbours) rather than one village-wide constant.
Confidence here is capped at 0.45 and decreases with distance to the nearest
aligned plot and with how much those neighbours disagree among themselves.
A small remainder (293 plots) had no aligned neighbour within 3 km at all and
fall back to the global median shift with very low confidence (~0.05–0.15).

## Confidence formula

```
confidence = 0.45 * corr_SNR_signal        # how sharp was the correlation peak?
            + 0.20 * area_ratio_signal     # does drawn area ≈ recorded area?
            + 0.35 * spatial_consensus_signal  # do neighbours agree?
```

For interpolated (no-imagery) plots, confidence is instead:

```
confidence = 0.10 * area_ratio_signal
            + 0.20 * distance_signal       # closer aligned neighbour = more trust
            + 0.15 * spread_signal         # tighter neighbour agreement = more trust
```
capped at 0.45.

All three/components are computed from data, not assumed — a flat confidence
(like the naive baseline's) scores ~0.5 AUC by definition; this is an attempt
to do meaningfully better.

## Results on this run (Vadnerbhairav, all 2,457 plots)

| Category | Count | % |
|---|---|---|
| Corrected — direct image alignment | 647 | 26% |
| Corrected — interpolated from neighbours | 1,306 | 53% |
| Corrected — village-wide fallback (very low conf) | 293 | 12% |
| Flagged — area/record mismatch | 127 | 5% |
| Flagged — no clear imagery signal | 84 | 3% |

Confidence distribution (corrected plots): min 0.09, median 0.29, max 0.76,
mean 0.30. Concentrated in 0.1–0.5 — honestly reflecting that most signals
here are *moderate*, not strong. I'd rather have a calibrated 0.3 that means
"30% chance this nails it" than an inflated 0.8 across the board.

## Known limitations / what I'd do with more time

- **Translation only.** I only estimate `(dx, dy)`; the assignment notes that
  some plots may need rotation or local stretch too. A natural next step is
  to also search a small rotation range (±2–3°) around the plot's centroid in
  the cross-correlation step.
- **`boundaries.tif` unused.** My downloaded `boundaries.tif` was corrupted
  (an incomplete download), so this run relies entirely on raw imagery edges
  via Sobel. The assignment notes `boundaries.tif` is an ML edge signal that's
  strong on open fields — if available, blending it into the edge image
  (e.g. averaging Sobel output with the boundary raster) would likely sharpen
  correlation peaks and reduce the 36% outlier-replacement rate.
- **Imagery coverage.** Only 58% of `imagery.tif`'s rows were usable (again,
  an incomplete download on my end) — 1,306 plots rely on interpolation rather
  than direct evidence. With the full image this would likely fall to a small
  fraction.
- **Outlier rate (36%) is high.** This may mean the ±55 m search window is too
  wide for small plots (picks up unrelated edges), or that the boundary-ring
  template is too thin to be distinctive. Worth investigating: scale the
  search radius and ring thickness by plot size.
- **No rotation/affine fitting** for plots whose shape itself looks rotated
  vs. the field (visible in some samples) — only whole-polygon translation.

## Files

```
correct.py              — the pipeline (read this first; heavily commented)
bhume/                   — provided starter-kit helpers (load, patch_for_plot, score, ...)
data/<village>/
  input.geojson          — official plots (provided)
  imagery.tif            — satellite mosaic (provided; partially downloaded, see above)
  predictions.geojson    — OUTPUT of correct.py
transcripts/             — AI chat transcripts (see transcripts/README.md)
```
