# AI Transcript — Claude (Anthropic)

This is a condensed transcript of the conversation used to understand the
BhuMe assignment and build this solution. The full live conversation (with
all tool calls, intermediate code, and debug output) is also available via
share link — see `transcripts/README.md`.

---

## Turn 1 — Initial analysis request

**User:** Shared two links — `hiring.bhume.in` and a tinyurl pointing to a
Google Doc — and asked for an analysis of the assignment and reference
document.

**Claude:** Attempted to fetch both URLs; `hiring.bhume.in` blocked automated
access (robots.txt) and the Google Doc required sign-in. Pulled what was
available from search snippets and gave a preliminary analysis identifying
this as a geospatial boundary-alignment task, with a placeholder for full
analysis once the actual document was shared.

---

## Turn 2 — Full preparation document shared

**User:** Uploaded the full "BhuMe Take-Home Candidate Preparation Document"
(21-page PDF) and asked for the analysis + a full roadmap.

**Claude:** Read the entire document and produced an interactive roadmap
covering:
- The core task: decide per-plot whether the official boundary can be
  "nudged" onto the real field, and if so, how, plus a confidence score.
- Key vocabulary: plot, 7/12 extract, survey/hissa/holding, recorded area
  vs. pot-kharaba, BhuNaksha, MRSAC georeferencing, drift.
- The crucial distinction: **placement problems** (fixable by moving) vs.
  **area problems** (geometry disagrees with the record — moving won't help),
  with the `drawn_area / recorded_area` ratio as the triage signal.
- The starter-kit helpers (`load`, `patch_for_plot`, `lonlat_to_pixel`,
  `score`, `write_predictions`, `global_median_shift`) and what each does.
- The output contract (`predictions.geojson`: `plot_number`, `status`,
  `confidence`, `method_note`, `geometry`).
- The scoring rubric (Bronze/Silver/Gold/Platinum tiers; accuracy via IoU
  and centroid error; **confidence calibration via AUC — watched most**;
  restraint).
- A 5-phase roadmap: setup → understand the data → build the method →
  score/iterate → package and submit, with the Tue Jun 16 evening IST
  deadline for the Wed Jun 17 review.

---

## Turn 3 — "Build this whole project for me"

**User:** Asked Claude to build the whole project.

**Claude:** Explained what data files were needed (input.geojson,
imagery.tif, boundaries.tif, example_truths.geojson, starter kit) and asked
the user to download them from hiring.bhume.in/start.

---

## Turn 4 — Data files uploaded; pipeline construction begins

**User:** Uploaded `input.geojson`, `bhume-starter-kit.zip`, three
`.crdownload` files, the PDF again, and an unrelated image (a screenshot of
an RSSB recruitment notice, which Claude correctly ignored as irrelevant).

**Claude's process (the bulk of the work):**

1. **Diagnosed the `.crdownload` files.** Read their magic bytes — all three
   were valid TIFF headers (`II*\x00...`). Opened them with `rasterio`:
   - Two single-band 3776×4340 files (likely boundary-hint related, but
     turned out unreadable/corrupted on full read).
   - One 3-band 7552×8680 file = the satellite imagery, **but only 58% of
     rows (5024/8680) were readable** — the rest of the strip-encoded TIFF
     was missing because the download was incomplete.

2. **Inspected `input.geojson`**: 2,457 plots for Vadnerbhairav, CRS
   `OGC:CRS84` (lon/lat), fields `plot_number`, `map_area_sqm`,
   `recorded_area_sqm`, `recorded_area_ha`, `pot_kharaba_ha`, `surveys`.
   2,446/2,457 plots had recorded area.

3. **Computed area-ratio distribution**: median ratio 1.011 (most plots are
   placement problems, not area problems), with ~1,633 plots in a "likely
   placement" band of 0.8–1.25.

4. **Extracted and read the starter kit** (`bhume/io.py`, `bhume/geo.py`,
   `bhume/score.py`, `bhume/baseline.py`, `quickstart.py`, `CONTRACT.md`) to
   understand `load()`, `patch_for_plot()`, coordinate conversions, and the
   exact output schema.

5. **Set up the project structure** (`bhume-submission/`) with the data
   copied into `data/34855_vadnerbhairav_chandavad_nashik/`.

6. **Iteratively designed the alignment method**, with live debugging in the
   sandbox:
   - First attempt: filled-polygon mask + dense edge image cross-correlation.
     Confidence values came out very low (0.005–0.15) — too weak a signal.
   - Second attempt: switched the template from a *filled* mask to a thin
     *boundary ring* (dilate − filled), and used FFT cross-correlation
     (`scipy.signal.fftconvolve`) instead of `correlate2d` for speed (0.03s
     vs. multi-second per plot). This produced SNR values around 3–5, with a
     visible coherent drift direction (~dx=-35m on an early sample of 10
     plots).
   - Ran a 300-plot test and got a result that looked wrong (0 plots
     "image-aligned" despite the global shift apparently being computed from
     26 plots). **Found and fixed a bug**: an invalid nested f-string format
     specifier (`f"...{ar:.2f if ar else 'N/A'}..."`) was raising a
     `ValueError` that got silently caught by the surrounding `except`
     block, miscounting every successful alignment as "flagged". Fixed by
     precomputing the string before interpolation.

7. **Designed and implemented spatial-consensus refinement**: built a
   `cKDTree` over aligned plots' centroids; for each plot, compared its
   estimated shift to the median shift of neighbours within 300m. Agreement
   → keep + boost confidence; mild disagreement → keep, lower confidence;
   strong disagreement (>45m) → replace with the neighbourhood median and cap
   confidence (handles cases where a correlation locked onto the wrong edge,
   e.g. a road or a neighbouring plot's boundary).

8. **Designed interpolation for plots outside the imagery extent**:
   inverse-distance-weighted shift from the nearest aligned plots (≤8,
   within 3km), with confidence capped at 0.45 and reduced by distance and
   by how much those neighbours disagree among themselves. A small remainder
   with no aligned neighbour within 3km falls back to the village-wide
   median shift at very low confidence.

9. **Built the three-signal confidence formula**:
   `confidence = 0.45 * corr_SNR_signal + 0.20 * area_ratio_signal + 0.35 * spatial_consensus_signal`
   (different weights for interpolated plots — see `README.md`).

10. **Validated output**: ran the full pipeline on all 2,457 plots —
    647 direct image-aligned (231 of those replaced via consensus as
    outliers), 1,306 interpolated, 293 global-fallback, 127 flagged for area
    mismatch, 84 flagged for weak signal. Found and repaired one
    self-intersecting input polygon (plot 1064) using `shapely.make_valid`
    so all 2,457 output geometries are valid.

11. **Generated visual diagnostics** (`make_diagnostics.py`): overlaid
    official (red) and corrected (green) boundaries on the satellite patch
    for sample plots in each category, to sanity-check the method visually
    before finalising it.

12. **Wrote supporting docs**: `README.md` (full method + honest
    limitations — partial imagery, 36% outlier-replacement rate, no
    rotation/affine search, `boundaries.tif` unused due to corruption),
    `VIDEO_SCRIPT.md` (talking points for the 5-minute video), and this
    transcripts folder.

13. **Packaged everything** into `bhume-submission.zip` and explained
    remaining steps (re-download complete imagery, self-score, record video,
    push to GitHub, submit form).

---

## Turn 5 — Video script request

**User:** Asked for "the script of the video and other things I need to do."

**Claude:** Wrote a near-verbatim 5-minute script structured around: the
problem statement, the honest caveat about partial imagery downloads, the
area-ratio triage step, the cross-correlation method (with a diagnostic image
cue), the spatial-consensus refinement ("the part I'm proudest of"), the
interpolation step, and the confidence formula — plus a full checklist of
remaining submission steps and the deadline reminder (Tue Jun 16 evening IST
/ Wed Jun 17 review).

---

## Turn 6 — Self-score result

**User:** Uploaded a screenshot of the Test page's self-score output:
Median IoU 0.765 vs. official 0.612 (+0.152 improvement), 83% of plots at
IoU≥0.5, median centroid error 12.2m, but **Calibration AUC = 0.200** (below
0.5 = random).

**Claude:** Flagged that accuracy looks solid (Silver-tier), but AUC=0.2 is
worse than random and calibration is the most-weighted metric — worth
investigating. Also noted the important caveat: with only 6 example truths,
AUC is extremely fragile — a single misranked plot can swing it from 0.2 to
0.8, and the assignment doc explicitly warns not to over-index on this tiny
set. Asked the user to upload `example_truths.geojson` and the current
`predictions.geojson` to diagnose whether this is a one-off or a systematic
pattern, and to upload complete `imagery.tif`/`boundaries.tif` if available
since the original run used only 58% of the imagery.

---

## Turn 7 — This transcript request

**User:** Shared a screenshot of the "AI transcripts" requirement section
and asked Claude to make an AI transcript.

**Claude:** Wrote this file and updated `transcripts/README.md` with
instructions for also adding the live share-link (recommended, since it
captures the full tool-call detail this summary necessarily condenses).

