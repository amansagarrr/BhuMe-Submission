#!/usr/bin/env python3
"""
BhuMe Take-Home: Land Plot Boundary Correction
===============================================

METHOD
------
1. TRIAGE (area ratio)
   ratio = drawn_area / (recorded_area + pot_kharaba).
   Far from 1.0 → the geometry itself disagrees with the record; flag
   ("area problem", moving won't fix it). Near 1.0 → proceed.

2. PER-PLOT IMAGE ALIGNMENT (where imagery is available)
   - Crop the satellite patch around the plot (bhume.geo.patch_for_plot).
   - Build a Sobel edge-strength image of the patch.
   - Rasterise a thin ring around the plot's official boundary (the
     "template" — what we're trying to slide onto a real field edge).
   - FFT cross-correlate the template against the edge image within a
     ±55 m search window. The peak location gives a candidate (dx, dy);
     the peak's strength relative to background (SNR) is a confidence
     signal — a sharp, isolated peak means "this really looks like an
     edge"; a flat correlation surface means "no clear signal here".

3. SPATIAL-CONSENSUS REFINEMENT
   Georeferencing drift varies *smoothly* across a village (it comes from
   a handful of control points used to warp the whole sheet) — so a
   plot's shift should roughly agree with its neighbours' shifts. For
   each image-aligned plot:
   - Find nearby image-aligned plots (within ~300 m).
   - Compare this plot's (dx, dy) to the neighbourhood's median (dx, dy).
   - If they agree → keep this plot's own estimate, confidence goes up.
   - If they strongly disagree (likely a spurious correlation peak —
     e.g. it locked onto a road or a neighbouring plot's edge instead of
     its own) → replace this plot's shift with the neighbourhood median,
     and cap confidence lower (we're now trusting the neighbourhood, not
     this plot's own signal).

4. INTERPOLATION FOR PLOTS WITHOUT LOCAL IMAGERY
   Rather than one flat village-wide shift, each no-imagery plot is given
   the inverse-distance-weighted median (dx, dy) of the nearest
   image-aligned plots within 3 km. Confidence is capped lower than for
   directly-aligned plots, and decreases with distance to the nearest
   aligned neighbour and with how much those neighbours disagree among
   themselves.

CONFIDENCE
   confidence = 0.45 * corr_SNR_signal
              + 0.20 * area_ratio_signal
              + 0.35 * spatial_consensus_signal
   All three are observable, independent signals — none of them are flat,
   so confidence should actually track accuracy (the metric BhuMe weighs
   most heavily).

Run:
    python correct.py data/34855_vadnerbhairav_chandavad_nashik
    python correct.py data/34855_vadnerbhairav_chandavad_nashik --limit 300
"""
from __future__ import annotations

import argparse
import warnings
from pathlib import Path

import numpy as np
import geopandas as gpd
from shapely.affinity import translate

warnings.filterwarnings("ignore", category=UserWarning)

# ── Tunables ─────────────────────────────────────────────────────────────────
AREA_RATIO_FLAG_LOW   = 0.45   # ratio below this → area mismatch, flag
AREA_RATIO_FLAG_HIGH  = 2.8    # ratio above this → area mismatch, flag
SEARCH_RADIUS_M       = 55.0   # ±metres searched in cross-correlation
PAD_M                 = 70.0   # padding around plot when extracting patch
MIN_PLOT_AREA_SQM     = 250    # skip tiny/slivery plots
MIN_SNR_TO_CONSIDER   = 2.0    # below → correlation too weak to use at all

CONSENSUS_RADIUS_M    = 300.0  # neighbourhood radius for consensus check
CONSENSUS_MIN_NEIGH   = 3       # need this many neighbours to judge consensus
CONSENSUS_AGREE_M     = 15.0   # disagreement below this → high consensus conf
CONSENSUS_REPLACE_M   = 45.0   # disagreement above this → replace with neighbour median

INTERP_RADIUS_M       = 3000.0  # how far to look for aligned neighbours (no-imagery plots)
INTERP_K              = 8       # how many nearest aligned plots to use
# ────────────────────────────────────────────────────────────────────────────


def _utm_zone(lon: float) -> str:
    return f"EPSG:{32600 + int((lon + 180) // 6) + 1}"


def compute_area_ratio(row) -> float | None:
    rec = row.get("recorded_area_sqm")
    if not rec or rec <= 0:
        return None
    pot = (row.get("pot_kharaba_ha") or 0.0) * 10_000
    total = rec + pot
    return float(row["map_area_sqm"]) / total if total > 0 else None


def edge_image(rgb: np.ndarray) -> np.ndarray:
    """Sobel edge magnitude on luminance, normalised to [0,1]."""
    from scipy.ndimage import sobel
    lum = (0.299 * rgb[:, :, 0] + 0.587 * rgb[:, :, 1] + 0.114 * rgb[:, :, 2]).astype(np.float32) / 255.0
    mag = np.sqrt(sobel(lum, axis=1) ** 2 + sobel(lum, axis=0) ** 2)
    vmax = np.percentile(mag, 99)
    return np.clip(mag / vmax, 0, 1) if vmax > 0 else mag


def rasterise_boundary(geom_m, patch_transform, h, w) -> np.ndarray:
    """Thin ring of pixels along the polygon boundary (not filled)."""
    from rasterio.features import rasterize
    from scipy.ndimage import binary_dilation
    filled = rasterize([(geom_m, 1)], out_shape=(h, w),
                        transform=patch_transform, fill=0, dtype="uint8")
    dilated = binary_dilation(filled, iterations=2).astype(np.uint8)
    return (dilated - filled).astype(np.float32)


def cross_corr_shift(boundary: np.ndarray, edges: np.ndarray,
                      pixel_size_m: float, search_m: float) -> tuple[float, float, float]:
    """FFT cross-correlation; returns (dx_m, dy_m, snr)."""
    from scipy.signal import fftconvolve
    corr = fftconvolve(edges, boundary[::-1, ::-1], mode="same")
    h, w = corr.shape
    cy, cx = h // 2, w // 2
    sp = int(search_m / pixel_size_m)
    sub = corr[max(0, cy - sp):min(h, cy + sp + 1), max(0, cx - sp):min(w, cx + sp + 1)]
    py, px = np.unravel_index(np.argmax(sub), sub.shape)
    oy = (py + max(0, cy - sp)) - cy
    ox = (px + max(0, cx - sp)) - cx
    std = sub.std()
    snr = float((sub.max() - sub.mean()) / std) if std > 0 else 0.0
    return float(ox * pixel_size_m), float(-oy * pixel_size_m), snr


def align_plot(geom_4326, img_src) -> tuple[float, float, float]:
    """Return (dx_m, dy_m, snr) for one plot via boundary cross-correlation."""
    from bhume.geo import patch_for_plot, geom_to_imagery_crs
    patch = patch_for_plot(img_src, geom_4326, pad_m=PAD_M)
    geom_m = geom_to_imagery_crs(img_src, geom_4326)
    h, w = patch.image.shape[:2]
    ps = abs(patch.transform.a)
    boundary = rasterise_boundary(geom_m, patch.transform, h, w)
    if boundary.sum() < 4:
        raise ValueError("boundary rasterises to < 4 pixels")
    edges = edge_image(patch.image)
    return cross_corr_shift(boundary, edges, ps, SEARCH_RADIUS_M)


def snr_to_signal(snr: float) -> float:
    """SNR ~2 → ~0, SNR ~7+ → ~1. Below MIN_SNR_TO_CONSIDER we don't even get here."""
    return float(np.clip((snr - MIN_SNR_TO_CONSIDER) / 5.0, 0.0, 1.0))


def area_ratio_signal(ar: float | None) -> float:
    """Ratio==1.0 → 1.0; degrades as |log(ratio)| grows."""
    if ar is None:
        return 0.35
    return float(np.clip(1.0 - abs(np.log(ar)) / np.log(AREA_RATIO_FLAG_HIGH), 0.0, 1.0))


def find_readable_rows(src) -> int:
    """Return number of rows readable before the TIF is truncated (handles
    a partially-downloaded GeoTIFF gracefully)."""
    from rasterio.windows import Window
    H = src.height
    block_h = (src.block_shapes[0][0] if src.block_shapes else 256)
    last = 0
    for r in range(0, H, block_h):
        try:
            src.read(list(range(1, src.count + 1)), window=Window(0, r, src.width, min(block_h, H - r)))
            last = r + min(block_h, H - r)
        except Exception:
            break
    return last


def plot_has_imagery(geom_4326, img_src, readable_bottom_y: float) -> bool:
    from bhume.geo import geom_to_imagery_crs
    g = geom_to_imagery_crs(img_src, geom_4326)
    b = img_src.bounds
    minx, miny, maxx, maxy = g.bounds
    return maxx > b.left and minx < b.right and maxy > readable_bottom_y and miny < b.top


# ── Main pipeline ───────────────────────────────────────────────────────────

def process_village(village_dir: str, limit: int | None = None) -> gpd.GeoDataFrame:
    import rasterio
    from bhume.io import load
    from scipy.spatial import cKDTree

    print(f"\n{'=' * 60}")
    print("BhuMe boundary correction pipeline")
    print(f"Village: {village_dir}")
    village = load(village_dir)
    plots = village.plots.copy()
    print(f"  {len(plots)} total plots")

    utm = _utm_zone(plots.geometry.iloc[0].centroid.x)
    plots_utm = plots.to_crs(utm)

    img_src = rasterio.open(village.imagery_path)
    H = img_src.height
    readable_rows = find_readable_rows(img_src)
    pixel_height = (img_src.bounds.top - img_src.bounds.bottom) / H
    readable_bottom_y = img_src.bounds.top - readable_rows * pixel_height
    print(f"  Imagery readable: {readable_rows}/{H} rows ({readable_rows / H * 100:.0f}%)")

    plots_list = list(plots.iterrows())
    if limit:
        plots_list = plots_list[:limit]
    print(f"  Processing {len(plots_list)} plots...")

    # ── Pass 1: triage + raw image alignment ──────────────────────────────────
    finished = []        # final records for flagged/area-problem plots
    candidates = []      # dicts: pn, geom_utm, centroid, dx, dy, snr, ar
    deferred = []        # dicts: pn, geom_utm, geom_4326, centroid, ar

    n_area_flag = n_snr_flag = n_no_img = 0

    for i, (pn, row) in enumerate(plots_list):
        if i % 400 == 0:
            print(f"    [{i}/{len(plots_list)}]  candidates={len(candidates)}  "
                  f"deferred={len(deferred)}  area_flagged={n_area_flag}  snr_flagged={n_snr_flag}")

        geom_4326 = row.geometry
        geom_utm = plots_utm.loc[pn, "geometry"]
        centroid = np.array([geom_utm.centroid.x, geom_utm.centroid.y])
        map_area = float(row.get("map_area_sqm") or 0)
        ar = compute_area_ratio(row)

        if ar is not None and (ar < AREA_RATIO_FLAG_LOW or ar > AREA_RATIO_FLAG_HIGH):
            finished.append(_flag(pn, geom_4326,
                f"area_ratio={ar:.2f} outside [{AREA_RATIO_FLAG_LOW},{AREA_RATIO_FLAG_HIGH}] "
                f"— drawn area disagrees with the 7/12 record; this looks like an area "
                f"problem, not a placement drift, so moving it would not help"))
            n_area_flag += 1
            continue

        if map_area < MIN_PLOT_AREA_SQM:
            finished.append(_flag(pn, geom_4326,
                f"plot too small ({map_area:.0f} m²) to align reliably from imagery"))
            n_area_flag += 1
            continue

        if not plot_has_imagery(geom_4326, img_src, readable_bottom_y):
            deferred.append(dict(pn=pn, geom_utm=geom_utm, geom_4326=geom_4326,
                                  centroid=centroid, ar=ar))
            n_no_img += 1
            continue

        try:
            dx, dy, snr = align_plot(geom_4326, img_src)
        except Exception as e:
            finished.append(_flag(pn, geom_4326, f"imagery alignment failed: {e}"))
            n_snr_flag += 1
            continue

        if snr < MIN_SNR_TO_CONSIDER:
            finished.append(_flag(pn, geom_4326,
                f"cross-correlation SNR={snr:.2f} too weak (no clear field edge "
                f"found within {SEARCH_RADIUS_M:.0f} m) — flagged rather than guessed"))
            n_snr_flag += 1
            continue

        candidates.append(dict(pn=pn, geom_utm=geom_utm, geom_4326=geom_4326,
                                centroid=centroid, dx=dx, dy=dy, snr=snr, ar=ar))

    img_src.close()
    print(f"\n  Pass 1 done: {len(candidates)} candidates, {len(deferred)} deferred "
          f"(no imagery), {len(finished)} flagged so far")

    if not candidates:
        # Nothing to align against — flag everything deferred too
        for d in deferred:
            finished.append(_flag(d["pn"], d["geom_4326"], "no imagery and no aligned "
                                   "reference plots in this village"))
        return gpd.GeoDataFrame(finished, crs="EPSG:4326")

    # ── Pass 2: spatial-consensus refinement of candidates ────────────────────
    cand_xy = np.array([c["centroid"] for c in candidates])
    cand_shift = np.array([[c["dx"], c["dy"]] for c in candidates])
    tree = cKDTree(cand_xy)

    n_replaced = n_high_consensus = 0
    refined_shift = np.zeros_like(cand_shift)

    for idx, c in enumerate(candidates):
        nbr_idx = tree.query_ball_point(cand_xy[idx], r=CONSENSUS_RADIUS_M)
        nbr_idx = [j for j in nbr_idx if j != idx]

        own_dx, own_dy = c["dx"], c["dy"]

        if len(nbr_idx) >= CONSENSUS_MIN_NEIGH:
            nbr_shift = cand_shift[nbr_idx]
            med = np.median(nbr_shift, axis=0)
            disagreement = float(np.linalg.norm([own_dx, own_dy] - med))

            if disagreement <= CONSENSUS_AGREE_M:
                refined_shift[idx] = [own_dx, own_dy]
                cons_signal = float(np.clip(1.0 - disagreement / CONSENSUS_AGREE_M, 0, 1))
                n_high_consensus += 1
                c["consensus_note"] = f"agrees with {len(nbr_idx)} neighbours (Δ={disagreement:.1f}m)"
            elif disagreement <= CONSENSUS_REPLACE_M:
                refined_shift[idx] = [own_dx, own_dy]
                cons_signal = float(np.clip(1.0 - disagreement / CONSENSUS_REPLACE_M, 0, 0.5))
                c["consensus_note"] = f"mild disagreement with {len(nbr_idx)} neighbours (Δ={disagreement:.1f}m)"
            else:
                refined_shift[idx] = med
                cons_signal = 0.25  # trusting neighbourhood now, not own signal
                n_replaced += 1
                c["consensus_note"] = (f"own correlation looked like an outlier vs "
                                        f"{len(nbr_idx)} neighbours (Δ={disagreement:.1f}m) "
                                        f"— replaced with neighbourhood median shift")
        else:
            refined_shift[idx] = [own_dx, own_dy]
            cons_signal = 0.4  # not enough neighbours to judge; mildly neutral
            c["consensus_note"] = f"only {len(nbr_idx)} nearby aligned plots — consensus check skipped"

        c["dx"], c["dy"] = float(refined_shift[idx][0]), float(refined_shift[idx][1])
        c["consensus_signal"] = cons_signal

    print(f"  Pass 2 done: {n_high_consensus} high-consensus, {n_replaced} outliers "
          f"replaced with neighbourhood median")

    # Finalise candidate records
    for c in candidates:
        corr_sig = snr_to_signal(c["snr"])
        ar_sig = area_ratio_signal(c["ar"])
        cons_sig = c["consensus_signal"]
        conf = round(float(0.45 * corr_sig + 0.20 * ar_sig + 0.35 * cons_sig), 4)
        ar_str = f"{c['ar']:.2f}" if c["ar"] is not None else "N/A"
        new_geom = _shift_geom(c["geom_utm"], c["dx"], c["dy"], utm)
        note = (f"cross-corr shift dx={c['dx']:.1f}m dy={c['dy']:.1f}m "
                f"(SNR={c['snr']:.2f}, area_ratio={ar_str}); {c['consensus_note']}; "
                f"confidence={conf}")
        finished.append(_correct(c["pn"], new_geom, conf, note))

    # ── Pass 3: interpolate shift for plots without local imagery ─────────────
    refined_xy = np.array([c["centroid"] for c in candidates])
    refined_shifts = np.array([[c["dx"], c["dy"]] for c in candidates])
    tree2 = cKDTree(refined_xy)

    global_dx = float(np.median(refined_shifts[:, 0]))
    global_dy = float(np.median(refined_shifts[:, 1]))
    print(f"  Global median shift (fallback only): dx={global_dx:.1f}m dy={global_dy:.1f}m")

    n_interp = n_global_fallback = n_deferred_flag = 0
    for d in deferred:
        dist, idx = tree2.query(d["centroid"], k=min(INTERP_K, len(candidates)),
                                 distance_upper_bound=INTERP_RADIUS_M)
        dist = np.atleast_1d(dist)
        idx = np.atleast_1d(idx)
        valid = np.isfinite(dist)
        dist, idx = dist[valid], idx[valid]

        ar_sig = area_ratio_signal(d["ar"])

        if len(idx) >= 1:
            nb_shifts = refined_shifts[idx]
            # inverse-distance weights (avoid div-by-zero)
            w = 1.0 / np.maximum(dist, 1.0)
            w /= w.sum()
            interp_dx = float(np.sum(w * nb_shifts[:, 0]))
            interp_dy = float(np.sum(w * nb_shifts[:, 1]))

            # agreement among neighbours used (tighter spread → higher confidence)
            spread = float(np.std(nb_shifts, axis=0).mean()) if len(idx) > 1 else 20.0
            nearest_dist = float(dist.min())
            dist_sig = float(np.clip(1.0 - nearest_dist / INTERP_RADIUS_M, 0, 1))
            spread_sig = float(np.clip(1.0 - spread / 50.0, 0, 1))

            conf = round(float(0.10 * ar_sig + 0.20 * dist_sig + 0.15 * spread_sig), 4)
            conf = min(conf, 0.45)  # never as confident as a direct image alignment

            new_geom = _shift_geom(d["geom_utm"], interp_dx, interp_dy, utm)
            ar_str = f"{d['ar']:.2f}" if d["ar"] is not None else "N/A"
            note = (f"no local imagery — interpolated shift dx={interp_dx:.1f}m "
                    f"dy={interp_dy:.1f}m from {len(idx)} nearby aligned plots "
                    f"(nearest {nearest_dist:.0f}m, spread {spread:.1f}m, "
                    f"area_ratio={ar_str}); confidence={conf}")

            if conf < 0.08:
                finished.append(_flag(d["pn"], d["geom_4326"],
                    "no local imagery and nearby aligned plots too inconsistent — flagged"))
                n_deferred_flag += 1
            else:
                finished.append(_correct(d["pn"], new_geom, conf, note))
                n_interp += 1
        else:
            # Nothing within INTERP_RADIUS_M — fall back to global median, very low confidence
            conf = round(float(0.10 * ar_sig + 0.05), 4)
            if conf < 0.08:
                finished.append(_flag(d["pn"], d["geom_4326"],
                    "no imagery anywhere nearby and area record unreliable — flagged"))
                n_deferred_flag += 1
            else:
                new_geom = _shift_geom(d["geom_utm"], global_dx, global_dy, utm)
                note = (f"no aligned plots within {INTERP_RADIUS_M/1000:.0f}km — "
                        f"used village-wide median shift dx={global_dx:.1f}m "
                        f"dy={global_dy:.1f}m; confidence={conf}")
                finished.append(_correct(d["pn"], new_geom, conf, note))
                n_global_fallback += 1

    n_corrected = sum(1 for r in finished if r["status"] == "corrected")
    n_flagged = sum(1 for r in finished if r["status"] == "flagged")
    print(f"\n  Final summary:")
    print(f"    Image-aligned (consensus-refined): {len(candidates)}")
    print(f"    Interpolated (no local imagery):   {n_interp}")
    print(f"    Global-fallback (very few refs):   {n_global_fallback}")
    print(f"    Flagged — area problem:            {n_area_flag}")
    print(f"    Flagged — weak/no signal:          {n_snr_flag + n_deferred_flag}")
    print(f"    TOTAL corrected: {n_corrected}  |  TOTAL flagged: {n_flagged}  "
          f"|  TOTAL output: {len(finished)}")

    return gpd.GeoDataFrame(finished, crs="EPSG:4326")


def _shift_geom(geom_utm, dx, dy, utm):
    from shapely.validation import make_valid
    from shapely.geometry import GeometryCollection, MultiPolygon, Polygon
    shifted = translate(geom_utm, dx, dy)
    if not shifted.is_valid:
        shifted = make_valid(shifted)
        if isinstance(shifted, GeometryCollection):
            polys = [g for g in shifted.geoms if isinstance(g, (Polygon, MultiPolygon))]
            shifted = polys[0] if len(polys) == 1 else MultiPolygon(
                [p for g in polys for p in ([g] if isinstance(g, Polygon) else list(g.geoms))]
            )
    return gpd.GeoSeries([shifted], crs=utm).to_crs("EPSG:4326").iloc[0]


def _correct(pn, geom, conf, note):
    return {"plot_number": str(pn), "status": "corrected",
            "confidence": conf, "method_note": note, "geometry": geom}


def _flag(pn, geom, note):
    return {"plot_number": str(pn), "status": "flagged",
            "confidence": None, "method_note": note, "geometry": geom}


def main():
    parser = argparse.ArgumentParser(description="BhuMe boundary correction")
    parser.add_argument("village_dir")
    parser.add_argument("--limit", type=int, default=None,
                         help="Process only first N plots (testing)")
    args = parser.parse_args()

    vdir = Path(args.village_dir)
    preds = process_village(str(vdir), limit=args.limit)

    cols = [c for c in ["plot_number", "status", "confidence", "method_note", "geometry"]
            if c in preds.columns]
    out = vdir / "predictions.geojson"
    preds[cols].to_file(str(out), driver="GeoJSON")
    print(f"\nWrote {len(preds)} predictions -> {out}")

    from bhume.io import load
    village = load(str(vdir))
    if village.example_truths is not None:
        from bhume.score import score
        print(f"\n{score(preds[cols], village)}")
    else:
        print("\nNo example_truths.geojson in this folder — download it from "
              "hiring.bhume.in/start to self-score, or validate the schema at "
              "hiring.bhume.in/test")


if __name__ == "__main__":
    main()
