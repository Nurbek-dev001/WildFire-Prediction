"""Independent raster/browser-payload round trips and full-grid alert burden."""

from __future__ import annotations

import gzip
import json
import struct
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import rowcol

from wildfire_kz.data import checksum, dump_json
from wildfire_kz.data.public_predictors import ROOT, geography, permitted
from wildfire_kz.data.public_study import RUN, outcomes


def verify(destination: Path) -> None:
    release = RUN / "release.json"
    permitted([2023, 2024], release)
    manifest = json.loads((destination / "forecast-manifest.json").read_text())
    expected = pd.date_range("2023-01-01", "2024-12-31").strftime("%Y-%m-%d").tolist()
    if manifest["available_days"] != expected or sorted(manifest["prediction_assets"]) != expected:
        raise ValueError("The complete calendar requires all 731 final-period daily maps")
    frozen = json.loads((RUN / "frozen.json").read_text())
    if (
        manifest["release_sha256"] != checksum(release)
        or manifest["model"] != frozen["selected_model"]
    ):
        raise ValueError("Published manifest and frozen model differ")
    grid, _, _ = geography()
    records = list(struct.iter_unpack("<hhfffH8H", (destination / "cells.bin").read_bytes()))
    platform_ids = pd.Index([f"g5000_{r[0]}_{r[1]}" for r in records])
    order = pd.Index(grid.cell_id).get_indexer(platform_ids)
    if len(order) != len(grid) or (order < 0).any() or len(np.unique(order)) != len(grid):
        raise ValueError("Browser and research grid identities differ")
    area = grid.area_km2.to_numpy()[order]
    first = pd.read_parquet(outcomes(2024, release), columns=["cell_id", "day", "is_first"])
    first = first.loc[first.is_first & first.day.dt.year.isin([2023, 2024])]
    positive_by_day = {
        d.strftime("%Y-%m-%d"): platform_ids.get_indexer(g.cell_id.unique())
        for d, g in first.groupby("day")
    }
    tie_rank = np.empty(len(grid), dtype="int32")
    tie_rank[np.argsort(platform_ids.to_numpy())] = np.arange(len(grid))
    burdens = []
    finite_counts, payload_bytes, raster_bytes = [], 0, 0
    signature = None
    for day in expected:
        proof = manifest["prediction_assets"][day]
        payload = destination / f"predictions/{day}.f32.gz"
        raster_path = RUN / f"maps/probability_{day}.tif"
        if (
            checksum(payload) != proof["payload_sha256"]
            or checksum(raster_path) != proof["raster_sha256"]
        ):
            raise ValueError(f"Map checksum mismatch: {day}")
        values = np.frombuffer(gzip.decompress(payload.read_bytes()), dtype="<f4")
        finite = np.isfinite(values)
        if len(values) != len(grid) or int(finite.sum()) != proof["finite_cells"]:
            raise ValueError(f"Map coverage differs: {day}")
        if ((values[finite] < 0) | (values[finite] > 1)).any():
            raise ValueError("Invalid calibrated probability")
        with rasterio.open(raster_path) as raster:
            current = (raster.crs.to_string(), tuple(raster.transform), raster.shape)
            if (
                raster.count != 2
                or raster.nodata != -9999
                or raster.tags()["release_sha256"] != checksum(release)
            ):
                raise ValueError("GeoTIFF metadata differs from the verified run")
            if signature is None:
                signature = current
                if (
                    raster.crs != grid.crs
                    or raster.transform.a != 5000
                    or raster.transform.e != -5000
                ):
                    raise ValueError("GeoTIFF is not the actual equal-area 5 km lattice")
                rows, cols = rowcol(
                    raster.transform, grid.x.to_numpy()[order], grid.y_coord.to_numpy()[order]
                )
                rows, cols = np.asarray(rows), np.asarray(cols)
            elif current != signature:
                raise ValueError("Daily raster geometry changed")
            probabilities = raster.read(1)[rows, cols]
            classes = raster.read(2)[rows, cols]
            np.testing.assert_allclose(
                np.where(probabilities == -9999, np.nan, probabilities),
                values,
                rtol=0,
                atol=0,
                equal_nan=True,
            )
            np.testing.assert_array_equal(
                classes[finite],
                1
                + np.searchsorted(
                    frozen["map_boundaries"][manifest["model"]], values[finite], side="right"
                ),
            )
            assert (classes[~finite] == -9999).all()
        positive = np.zeros(len(grid), dtype=bool)
        indices = positive_by_day.get(day, np.array([], dtype=int))
        positive[indices[indices >= 0]] = True
        candidates = np.flatnonzero(finite)
        ranked = candidates[np.lexsort((tie_rank[candidates], -values[candidates]))]
        before = np.cumsum(area[ranked]) - area[ranked]
        total_area = float(area[finite].sum())
        for fraction in [0.05, 0.1, 0.2]:
            alerts = ranked[before < fraction * total_area]
            burdens.append(
                {
                    "day": day,
                    "year": int(day[:4]),
                    "nominal_fraction": fraction,
                    "eligible_area_km2": total_area,
                    "alert_area_km2": float(area[alerts].sum()),
                    "positive_cell_days": int(positive[finite].sum()),
                    "captured_positive_cell_days": int(positive[alerts].sum()),
                    "alert_cell_days": len(alerts),
                    "false_alert_cell_days": int((~positive[alerts]).sum()),
                }
            )
        finite_counts.append(int(finite.sum()))
        payload_bytes += payload.stat().st_size
        raster_bytes += raster_path.stat().st_size
    daily = pd.DataFrame(burdens)
    summaries = []
    for period in ["2023", "2024", "2023–2024"]:
        frame = daily if "–" in period else daily[daily.year == int(period)]
        for _, group in frame.groupby("nominal_fraction"):
            fraction = float(group.nominal_fraction.iloc[0])
            totals = group[
                [
                    "eligible_area_km2",
                    "alert_area_km2",
                    "positive_cell_days",
                    "captured_positive_cell_days",
                    "alert_cell_days",
                    "false_alert_cell_days",
                ]
            ].sum()
            summaries.append(
                {
                    "period": period,
                    "nominal_fraction": fraction,
                    **totals.to_dict(),
                    "capture_rate": float(
                        totals.captured_positive_cell_days / totals.positive_cell_days
                    )
                    if totals.positive_cell_days
                    else None,
                    "actual_area_fraction": float(totals.alert_area_km2 / totals.eligible_area_km2),
                    "estimation": "exact full eligible grid; no sampled-negative approximation",
                }
            )
    daily.to_csv(RUN / "maps/full_grid_daily_alert_burden.csv", index=False)
    pd.DataFrame(summaries).to_csv(destination / "full_grid_top_capture.csv", index=False)
    dump_json(
        destination / "export-verification.json",
        {
            "synthetic": False,
            "release_sha256": checksum(release),
            "model": manifest["model"],
            "days": len(expected),
            "grid_cells": len(grid),
            "minimum_finite_cells": min(finite_counts),
            "maximum_finite_cells": max(finite_counts),
            "browser_payload_bytes": payload_bytes,
            "geotiff_bytes": raster_bytes,
            "raster_bands": 2,
            "checks": "all payload/raster SHA-256, exact float32 round trip, grid/CRS/nodata, frozen classes, calendar completeness",
            "exact_alert_burden_sha256": checksum(destination / "full_grid_top_capture.csv"),
            "grid_sha256": checksum(ROOT / "data/real/normalized/grid_5km.parquet"),
        },
    )
    permitted([2023, 2024], release)
