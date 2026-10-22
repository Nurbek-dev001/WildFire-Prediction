"""Final-only evaluation of a hash-frozen public hindcast experiment."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import geopandas as gpd
import joblib
import numpy as np
import pandas as pd

from wildfire_kz.data import checksum, dump_json
from wildfire_kz.data.public_predictors import ROOT, complete, geography, log, permitted
from wildfire_kz.data.public_study import RUN, industrial_cells, record_table, table
from wildfire_kz.evaluation import cluster_draws, metrics, reliability, top_capture


def weighted_ap_sorted(
    y: np.ndarray, w: np.ndarray, order: np.ndarray, endpoints: np.ndarray
) -> float:
    """Exact stepwise AP including score ties, with order cached across bootstrap draws."""
    positive = np.cumsum((w * y)[order])
    total_positive = positive[-1]
    if total_positive <= 0:
        return float("nan")
    total = np.cumsum(w[order])[endpoints]
    tp = positive[endpoints]
    precision = np.divide(tp, total, out=np.zeros_like(tp), where=total > 0)
    return float(np.sum(np.diff(np.r_[0, tp]) * precision) / total_positive)


def bootstrap(
    frame: pd.DataFrame,
    predictions: dict[str, np.ndarray],
    selected: str,
    destination: Path,
    resamples: int = 1000,
    boundaries: dict[str, list[float]] | None = None,
) -> None:
    """Pair the same 100 km × 30 day cluster draws for every frozen model."""
    y, w = frame.label.to_numpy(), frame.weight.to_numpy()
    draws = cluster_draws(frame, resamples, 100000, 30, 42)
    weight_by_cluster = np.bincount(draws.codes, weights=w)
    denominator = draws.multiplicities @ weight_by_cluster
    estimates: dict[str, dict[str, np.ndarray]] = {}
    for name, p in predictions.items():
        order = np.argsort(-p, kind="stable")
        endpoints = np.r_[np.flatnonzero(np.diff(p[order]) != 0), len(p) - 1]
        squared_by_cluster = np.bincount(draws.codes, weights=w * (p - y) ** 2)
        brier = (draws.multiplicities @ squared_by_cluster) / denominator
        ap = np.array([weighted_ap_sorted(y, w * draw, order, endpoints) for draw in draws])
        estimates[name] = {"average_precision": ap, "brier": brier}
        if boundaries is not None:
            edges = np.array(boundaries[name])
            bins = len(edges) - 1
            assigned = np.clip(np.searchsorted(edges, p, side="right") - 1, 0, bins - 1)
            encoded = draws.codes * bins + assigned
            size = draws.multiplicities.shape[1] * bins
            by_cluster = np.bincount(encoded, weights=w, minlength=size).reshape(-1, bins)
            positive_by_cluster = np.bincount(encoded, weights=w * y, minlength=size).reshape(
                -1, bins
            )
            total = draws.multiplicities @ by_cluster
            positive = draws.multiplicities @ positive_by_cluster
            frequencies = np.divide(
                positive, total, out=np.full_like(total, np.nan), where=total > 0
            )
            calibration = []
            for b in range(bins):
                mask = assigned == b
                values = frequencies[:, b]
                values = values[np.isfinite(values)]
                calibration.append(
                    {
                        "bin": b,
                        "lower": edges[b],
                        "upper": edges[b + 1],
                        "count": int(mask.sum()),
                        "weight": float(w[mask].sum()),
                        "predicted": float(np.average(p[mask], weights=w[mask]))
                        if mask.any()
                        else None,
                        "observed": float(np.average(y[mask], weights=w[mask]))
                        if mask.any()
                        else None,
                        "ci_lower": float(np.quantile(values, 0.025)) if len(values) else None,
                        "ci_upper": float(np.quantile(values, 0.975)) if len(values) else None,
                        "valid_resamples": len(values),
                        "bin_definition": "frozen_2022_weighted_probability_deciles",
                    }
                )
            pd.DataFrame(calibration).to_csv(
                destination / f"calibration_intervals_{name}.csv", index=False
            )
        log(f"Final bootstrap {name}: {resamples} paired cluster draws complete")
    rows = []
    for name in estimates:
        for metric, values in estimates[name].items():
            good = values[np.isfinite(values)]
            rows.append(
                {
                    "model": name,
                    "metric": metric,
                    "lower": float(np.quantile(good, 0.025)),
                    "upper": float(np.quantile(good, 0.975)),
                    "valid_resamples": len(good),
                    "requested_resamples": resamples,
                }
            )
            if name != selected:
                differences = estimates[selected][metric] - values
                good = differences[np.isfinite(differences)]
                rows.append(
                    {
                        "model": f"{selected} minus {name}",
                        "metric": metric,
                        "lower": float(np.quantile(good, 0.025)),
                        "upper": float(np.quantile(good, 0.975)),
                        "valid_resamples": len(good),
                        "requested_resamples": resamples,
                    }
                )
    pd.DataFrame(rows).to_csv(destination / "cluster_intervals.csv", index=False)


def map_frequencies(
    frame: pd.DataFrame, p: np.ndarray, boundaries: list[float], name: str
) -> list[dict[str, Any]]:
    """Respect deduplicated frozen quantiles, including constant-score baselines."""
    classes = np.searchsorted(boundaries, p, side="right")
    records = []
    for code in range(len(boundaries) + 1):
        mask = classes == code
        weights = frame.weight.to_numpy()[mask]
        mass = float(weights.sum())
        records.append(
            {
                "model": name,
                "class": code + 1,
                "lower_inclusive": [0.0, *boundaries][code],
                "upper_bound": [*boundaries, 1.0][code],
                "upper_bound_inclusive": code == len(boundaries),
                "sample_rows": int(mask.sum()),
                "weighted_cell_days": mass,
                "mean_prediction": float(np.average(p[mask], weights=weights)) if mass else None,
                "observed_frequency": float(
                    np.average(frame.label.to_numpy()[mask], weights=weights)
                )
                if mass
                else None,
                "area_km2_days": float(np.sum(frame.area_km2.to_numpy()[mask] * weights)),
            }
        )
    return records


def evaluate(*, resamples: int = 1000) -> None:
    release = RUN / "release.json"
    permitted([2023, 2024], release)
    destination = RUN / "evaluate"
    destination.mkdir(parents=True, exist_ok=True)
    frozen = json.loads((RUN / "frozen.json").read_text())
    models = joblib.load(RUN / "models.joblib")
    calibrators = joblib.load(RUN / "calibrators.joblib")
    feature_paths = [table(year, training=False, release=release) for year in [2023, 2024]]
    feature_hashes = {path.name: checksum(path) for path in feature_paths}
    frame = pd.concat([pd.read_parquet(path) for path in feature_paths], ignore_index=True)
    frame = frame.loc[~frame.cell_id.isin(industrial_cells())].reset_index(drop=True)
    grid, _, _ = geography()
    regions = gpd.read_parquet(ROOT / "data/real/normalized/regions.parquet").to_crs(grid.crs)
    points = gpd.GeoDataFrame(
        {"cell_id": grid.cell_id}, geometry=grid.representative_point(), crs=grid.crs
    )
    joined = gpd.sjoin(points, regions[["region", "geometry"]], how="left", predicate="intersects")
    lookup = joined[~joined.index.duplicated()].set_index("cell_id").region
    frame["region"] = frame.cell_id.map(lookup)
    if frame.region.isna().any():
        raise ValueError("Final evaluation cells have unassigned reporting regions")
    columns = [
        "cell_id",
        "day",
        "label",
        "weight",
        "x",
        "y_coord",
        "area_km2",
        "landcover",
        "region",
    ]
    predictions = {}
    for name, model in models.items():
        path = destination / f"predictions_{name}.parquet"
        metadata = (
            json.loads(path.with_suffix(".sha256.json").read_text()) if complete(path) else {}
        )
        if (
            metadata.get("release_sha256") == checksum(release)
            and metadata.get("feature_tables_sha256") == feature_hashes
        ):
            saved = pd.read_parquet(path)
            if not saved[["cell_id", "day"]].equals(frame[["cell_id", "day"]]):
                raise ValueError("Final prediction keys changed")
            predictions[name] = saved.probability.to_numpy()
        else:
            inference_started = time.perf_counter()
            p = calibrators[name].predict(model.predict(frame))
            inference_seconds = time.perf_counter() - inference_started
            predictions[name] = p
            record_table(
                path,
                frame[columns].assign(probability=p),
                {
                    "synthetic": False,
                    "release_sha256": checksum(release),
                    "model": name,
                    "inference_seconds": inference_seconds,
                    "inference_rows": len(frame),
                    "feature_tables_sha256": feature_hashes,
                },
            )
    reference = predictions["seasonal"]
    rows, combined, strata, map_classes = [], {}, [], []
    for name, p in predictions.items():
        threshold = frozen["thresholds"][name]
        summary = metrics(frame.label.to_numpy(), p, frame.weight.to_numpy(), threshold, reference)
        combined[name] = summary
        boundaries = frozen["map_boundaries"][name]
        map_classes.extend(map_frequencies(frame, p, boundaries, name))
        rows.append({"model": name, "period": "2023–2024", "threshold": threshold, **summary})
        for year in [2023, 2024]:
            mask = frame.day.dt.year.to_numpy() == year
            rows.append(
                {
                    "model": name,
                    "period": str(year),
                    "threshold": threshold,
                    **metrics(
                        frame.label.to_numpy()[mask],
                        p[mask],
                        frame.weight.to_numpy()[mask],
                        threshold,
                        reference[mask],
                    ),
                }
            )
        for dimension, groups in {
            "month": frame.day.dt.month,
            "region": frame.region,
            "landcover": frame.landcover,
        }.items():
            for group in sorted(groups.unique()):
                mask = groups.eq(group).to_numpy()
                strata.append(
                    {
                        "model": name,
                        "dimension": dimension,
                        "group": group,
                        "sample_rows": int(mask.sum()),
                        "positive_rows": int(frame.label.to_numpy()[mask].sum()),
                        **metrics(
                            frame.label.to_numpy()[mask],
                            p[mask],
                            frame.weight.to_numpy()[mask],
                            threshold,
                            reference[mask],
                        ),
                    }
                )
        reliability(frame.label.to_numpy(), p, frame.weight.to_numpy()).to_csv(
            destination / f"reliability_{name}.csv", index=False
        )
        top_capture(frame, p, [0.05, 0.1, 0.2]).to_csv(
            destination / f"top_capture_{name}.csv", index=False
        )
        log(
            f"FINAL {name}: AP={summary['average_precision']:.6f}, ROC-AUC={summary['roc_auc']:.6f}"
        )
    pd.DataFrame(rows).to_csv(destination / "metrics.csv", index=False)
    pd.DataFrame(strata).to_csv(destination / "stratified_metrics.csv", index=False)
    pd.DataFrame(map_classes).to_csv(destination / "map_class_frequencies.csv", index=False)
    cache_path = destination / "bootstrap_cache.json"
    prediction_hashes = {
        name: checksum(destination / f"predictions_{name}.parquet") for name in models
    }
    cache_key = {
        "release_sha256": checksum(release),
        "resamples": resamples,
        "prediction_hashes": prediction_hashes,
    }
    cache = json.loads(cache_path.read_text()) if cache_path.is_file() else {}
    valid_cache = (
        cache.get("key") == cache_key
        and bool(cache.get("outputs"))
        and all(
            (destination / name).is_file() and checksum(destination / name) == digest
            for name, digest in cache.get("outputs", {}).items()
        )
    )
    if not valid_cache:
        bootstrap(
            frame,
            predictions,
            frozen["selected_model"],
            destination,
            resamples,
            frozen["reliability_boundaries"],
        )
        outputs = [destination / "cluster_intervals.csv"] + list(
            destination.glob("calibration_intervals_*.csv")
        )
        dump_json(cache_path, {"key": cache_key, "outputs": {p.name: checksum(p) for p in outputs}})
    report: dict[str, Any] = {
        "synthetic": False,
        "variant": "public_reprocessed_hindcast",
        "release_sha256": checksum(release),
        "selected_model": frozen["selected_model"],
        "selection_fixed_before_test": True,
        "test_years": [2023, 2024],
        "rows": len(frame),
        "positive_rows": int(frame.label.sum()),
        "weighted_cell_days": float(frame.weight.sum()),
        "metrics": combined,
        "bootstrap_resamples": resamples,
        "operational_validation": False,
        "completed_utc": datetime.now(UTC).isoformat(),
        "feature_tables_sha256": feature_hashes,
        "outputs": {p.name: checksum(p) for p in destination.glob("*.csv")},
    }
    dump_json(destination / "complete.json", report)
    permitted([2023, 2024], release)
    log("Final evaluation complete; original model selection and hashes remain unchanged")
