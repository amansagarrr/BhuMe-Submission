#!/usr/bin/env python3
"""
Generate before/after comparison images: official boundary (red) vs.
corrected prediction (green) overlaid on satellite imagery.

Useful for the 5-minute walkthrough video — run this, then screen-record
flipping through a few of the saved PNGs while explaining the method.

Run:
    uv run make_diagnostics.py data/34855_vadnerbhairav_chandavad_nashik
"""
from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
from PIL import Image, ImageDraw

from bhume.io import load
from bhume.geo import patch_for_plot, geom_to_imagery_crs, open_imagery
from correct import plot_has_imagery, find_readable_rows


def to_px(geom_4326, src, patch):
    geom_m = geom_to_imagery_crs(src, geom_4326)
    geoms = list(geom_m.geoms) if geom_m.geom_type == "MultiPolygon" else [geom_m]
    rings = []
    for g in geoms:
        pts = []
        for x, y in g.exterior.coords:
            col = (x - patch.transform.c) / patch.transform.a
            row = (y - patch.transform.f) / patch.transform.e
            pts.append((col, row))
        rings.append(pts)
    return rings


def draw_compare(pn, official_geom, pred_geom, status, conf, src, out_dir):
    patch = patch_for_plot(src, official_geom, pad_m=60)
    img = Image.fromarray(patch.image).convert("RGB")
    draw = ImageDraw.Draw(img)

    for ring in to_px(official_geom, src, patch):
        draw.polygon(ring, outline=(255, 0, 0), width=2)
    if status == "corrected":
        for ring in to_px(pred_geom, src, patch):
            draw.polygon(ring, outline=(0, 255, 0), width=2)

    tag = f"{status}_{conf:.2f}" if (status == "corrected" and conf is not None) else status
    out = out_dir / f"plot_{pn}_{tag}.png"
    img.save(out)
    return out


def main(village_dir: str, n_each: int = 4):
    vdir = Path(village_dir)
    village = load(village_dir)
    plots = village.plots

    pred_path = vdir / "predictions.geojson"
    if not pred_path.exists():
        print(f"No predictions.geojson in {vdir} — run correct.py first")
        sys.exit(1)

    preds = gpd.read_file(pred_path)
    preds["plot_number"] = preds["plot_number"].astype(str)
    preds = preds.set_index("plot_number", drop=False)

    out_dir = vdir / "diagnostics"
    out_dir.mkdir(exist_ok=True)

    with open_imagery(village.imagery_path) as src:
        H = src.height
        readable_rows = find_readable_rows(src)
        pixel_height = (src.bounds.top - src.bounds.bottom) / H
        readable_bottom_y = src.bounds.top - readable_rows * pixel_height

        # Bucket plots by category, restricted to plots with usable imagery
        buckets: dict[str, list[str]] = {
            "direct_high_conf": [],
            "direct_low_conf": [],
            "interpolated": [],
            "flagged_area": [],
            "flagged_signal": [],
        }

        for pn, row in preds.iterrows():
            geom = plots.loc[pn, "geometry"]
            if not plot_has_imagery(geom, src, readable_bottom_y):
                continue
            note = row.get("method_note") or ""
            status = row["status"]
            conf = row.get("confidence")

            if status == "corrected" and "cross-corr shift" in note:
                bucket = "direct_high_conf" if (conf or 0) >= 0.4 else "direct_low_conf"
            elif status == "corrected" and "interpolated" in note:
                bucket = "interpolated"
            elif status == "flagged" and "area_ratio" in note:
                bucket = "flagged_area"
            elif status == "flagged":
                bucket = "flagged_signal"
            else:
                continue

            if len(buckets[bucket]) < n_each:
                buckets[bucket].append(pn)

        print("Generating diagnostic images...")
        for bucket, pns in buckets.items():
            for pn in pns:
                official_geom = plots.loc[pn, "geometry"]
                pred_geom = preds.loc[pn, "geometry"]
                status = preds.loc[pn, "status"]
                conf = preds.loc[pn, "confidence"]
                try:
                    out = draw_compare(pn, official_geom, pred_geom, status, conf, src, out_dir)
                    print(f"  [{bucket}] {out}")
                except Exception as e:
                    print(f"  [{bucket}] plot {pn}: skipped ({type(e).__name__})")

    print(f"\nSaved diagnostics to {out_dir}/")
    print("Legend: red = official (input) boundary, green = corrected prediction")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/34855_vadnerbhairav_chandavad_nashik")
