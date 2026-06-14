# Video walkthrough — talking points (aim for ~5 minutes)

Not a script to read verbatim — just a structure so you don't ramble or
forget a section. Show your screen: code, a diagnostic image or two, and the
terminal output of `correct.py`.

## 1. The problem, in your own words (30s)

"Each plot's official outline has drifted off the real field because of how
the old paper maps were georeferenced. I need to figure out, per plot,
whether I can tell where it should actually go — and how confident I am."

## 2. What I was given vs. what I actually had (30s)

Be upfront: your `imagery.tif` and `boundaries.tif` downloads were partial
(`.crdownload` files). `imagery.tif` ended up 58% readable, `boundaries.tif`
was unreadable. Mention this — it's honest, and it sets up why some plots
fall back to interpolation.

## 3. Triage step (30s)

Show the area-ratio calculation. Explain: "If the drawn area is wildly
different from the recorded area, no amount of sliding the polygon around
will fix it — that's a record/area problem, not a placement problem. I flag
those (~5% of plots) and move on."

## 4. The core method: cross-correlation (60–90s)

Show a diagnostic image (e.g. `plot_107_corrected_0.55.png`).
- "Red is the official boundary, green is my correction."
- Explain: Sobel edges → find where the image has sharp colour changes
  (bunds, road edges, crop-line boundaries).
- Rasterise a thin ring around the official polygon — that's my template.
- FFT cross-correlate the template against the edge image within ±55m.
- The peak location is my shift; how *sharp* that peak is (SNR) becomes part
  of my confidence.

## 5. Spatial consensus — the part I'm proudest of (60s)

"Drift isn't random — it varies smoothly across the village because it comes
from a handful of georeferencing control points. So I check: does this
plot's shift roughly agree with its neighbours'? If a plot's own correlation
disagrees a lot with 3+ nearby plots, it probably locked onto the wrong edge
— I replace it with the neighbourhood median instead."

Mention the number: "About a third of my direct correlations got
overridden this way — which tells me the raw correlation alone is noisier
than I'd like, but the consensus check catches it."

## 6. Interpolation for the rest of the village (30s)

"My imagery only covered part of this 54 km² village. For plots outside
that area, instead of one flat shift for everything, I interpolate from the
nearest aligned plots — distance-weighted, capped at a lower confidence."

## 7. Confidence — why it's not flat (45s)

Show the formula. "Confidence is built from three things I can actually
measure: how sharp the correlation peak was, how well the area matches the
record, and how much my neighbours agree with me. None of these are flat, so
confidence should track real accuracy — that's the metric BhuMe said they
watch most."

## 8. Results summary + honest limitations (45s)

Show the terminal output table (corrected/flagged counts, confidence
distribution). Then: "If I had more time, the biggest win would be
re-downloading the *complete* imagery — right now over half my 'corrected'
plots are interpolated rather than directly observed. After that, I'd add a
small rotation search, and try blending in `boundaries.tif` once I have a
working copy of it."

## 9. Close (10s)

"That's the method — happy to walk through any part of the code."

---

### Screen-recording checklist
- [ ] Show `correct.py` briefly (scroll through the docstring + key functions)
- [ ] Show 2-3 images from `data/<village>/diagnostics/`
- [ ] Run `uv run correct.py data/<village>` (or show prior output) so they
      see it actually executes
- [ ] Mention the imagery/boundaries download issue once, briefly, don't dwell
- [ ] Keep it to ~5 minutes — rough is fine, this isn't a polished demo
