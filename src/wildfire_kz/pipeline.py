"""Idempotent, content-addressed research stages with an explicit final-test gate."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import logging
import os
import platform
import random
import shutil
import threading
import time
from pathlib import Path
from typing import Any

import geopandas as gpd
import joblib
import numpy as np
import pandas as pd
import psutil

from wildfire_kz.calibration import fit_sigmoid, map_boundaries
from wildfire_kz.config import Config
from wildfire_kz.data import (
    AccessGuard,
    checksum,
    dump_json,
    ingest,
    read_source,
    write_partitioned,
)
from wildfire_kz.data.store import FeatureStore
from wildfire_kz.evaluation import (
    cluster_draws,
    metrics,
    paired_intervals,
    reliability_intervals,
    top_capture,
)
from wildfire_kz.events import link_events, persistent_hotspots, risk_set
from wildfire_kz.features import COVER, GROUPS, build_features, weather_daily
from wildfire_kz.models import fit_model, train_store_suite, tune
from wildfire_kz.splits import spatial_folds

STAGES = [
    "ingest",
    "grid",
    "events",
    "risk_set",
    "sampling",
    "features",
    "splits",
    "train",
    "calibrate",
    "ablate",
    "evaluate",
    "explain",
    "map",
    "report",
]
LOG = logging.getLogger("wildfire_kz")


def code_digest() -> str:
    """Include implementation content in every cache identity."""
    return hashlib.sha256(
        "".join(checksum(p) for p in sorted(Path(__file__).parent.rglob("*.py"))).encode()
    ).hexdigest()


class PipelineRunner:
    """Run stages transactionally; cache hits require unchanged sources AND outputs."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.root = cfg.output_dir
        self.root.mkdir(parents=True, exist_ok=True)
        random.seed(cfg.seed)
        np.random.seed(cfg.seed)
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    def path(self, stage: str) -> Path:
        return self.root / stage

    def run(self, stage: str, *, force: bool = False) -> dict[str, Any]:
        """Execute one stage; prerequisites must already exist and remain current."""
        if stage not in STAGES:
            raise ValueError(stage)
        index = STAGES.index(stage)
        predecessor = STAGES[index - 1] if index else None
        upstream = None
        if predecessor:
            prerequisite_stamp = self.path(predecessor) / "_stage.json"
            if not prerequisite_stamp.exists():
                raise RuntimeError(f"Run {predecessor} before {stage}, or use run-all")
            upstream = json.loads(prerequisite_stamp.read_text())["fingerprint"]
        source_hashes = {k: checksum(v.path) for k, v in self.cfg.data.sources.items()}
        key = hashlib.sha256(
            json.dumps(
                {
                    "config": self.cfg.model_dump(mode="json"),
                    "source_hashes": source_hashes,
                    "code": code_digest(),
                    "stage": stage,
                    "upstream": upstream,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        destination = self.path(stage)
        stamp_path = destination / "_stage.json"
        if stamp_path.exists() and not force:
            previous = json.loads(stamp_path.read_text())
            if previous["fingerprint"] == key and all(
                (destination / p).is_file() and checksum(destination / p) == value
                for p, value in previous["outputs"].items()
            ):
                LOG.info("%s: cache hit", stage)
                return previous
        temporary = self.root / f".{stage}.working"
        if temporary.exists():
            self._remove(temporary)
        temporary.mkdir()
        started = time.perf_counter()
        peak = [psutil.Process().memory_info().rss]
        stop = threading.Event()

        def monitor() -> None:
            while not stop.wait(0.1):
                peak[0] = max(peak[0], psutil.Process().memory_info().rss)

        worker = threading.Thread(target=monitor, daemon=True)
        worker.start()
        try:
            LOG.info("%s: started (synthetic=%s)", stage, self.cfg.data.synthetic)
            getattr(self, f"stage_{stage}")(temporary)
        except Exception:
            LOG.exception("%s failed; previous successful artifacts preserved", stage)
            raise
        finally:
            stop.set()
            worker.join()
        outputs = {
            str(p.relative_to(temporary)).replace("\\", "/"): checksum(p)
            for p in temporary.rglob("*")
            if p.is_file()
        }
        stamp = {
            "stage": stage,
            "fingerprint": key,
            "seed": self.cfg.seed,
            "synthetic": self.cfg.data.synthetic,
            "seconds": time.perf_counter() - started,
            "peak_rss_bytes": peak[0],
            "outputs": outputs,
        }
        dump_json(temporary / "_stage.json", stamp)
        if destination.exists():
            self._remove(destination)
        temporary.replace(destination)
        LOG.info("%s: complete", stage)
        return stamp

    def _remove(self, path: Path) -> None:
        """Restrict recursive removal to immediate stage folders in the experiment root."""
        resolved = path.resolve()
        if resolved.parent != self.root.resolve() or resolved == self.root.resolve():
            raise ValueError("Refusing cleanup outside the experiment root")
        shutil.rmtree(resolved)

    def run_all(self) -> None:
        """The ordered full run explicitly includes final evaluation."""
        for stage in STAGES:
            self.run(stage)

    def stage_ingest(self, out: Path) -> None:
        ingest(self.cfg, out)
        dump_json(out / "config.json", self.cfg.model_dump(mode="json"))

    def stage_grid(self, out: Path) -> None:
        from wildfire_kz.grid import build_grid

        path = self.cfg.data.sources["boundary"].path
        boundary = gpd.read_parquet(path) if path.suffix == ".parquet" else gpd.read_file(path)
        grid = build_grid(boundary, self.cfg.grid.crs, self.cfg.grid.resolution_m)
        if "regions" in self.cfg.data.sources:
            region_path = self.cfg.data.sources["regions"].path
            regions = (
                gpd.read_parquet(region_path)
                if region_path.suffix == ".parquet"
                else gpd.read_file(region_path)
            )
            regions = regions.to_crs(grid.crs)
            if "region" not in regions:
                raise ValueError("Administrative polygons require a region field")
            centers = grid.copy()
            centers.geometry = grid.geometry.representative_point()
            assigned = gpd.sjoin(
                centers[["cell_id", "geometry"]],
                regions[["region", "geometry"]],
                how="left",
                predicate="intersects",
            )
            if assigned.cell_id.duplicated().any() or assigned.region.isna().any():
                raise ValueError("Region polygons must assign every cell exactly once")
            grid = grid.merge(assigned[["cell_id", "region"]], on="cell_id", validate="one_to_one")
        grid.to_parquet(out / "grid.parquet")
        dump_json(
            out / "crs.json",
            {
                "wkt": grid.crs.to_wkt(),
                "resolution_m": self.cfg.grid.resolution_m,
                "id_scheme": "g{resolution}_{zero-anchored row}_{column}",
            },
        )

    def _events(self, *, final: bool = False) -> pd.DataFrame:
        cfg = self.cfg
        end = max(cfg.splits.test_years) if final else cfg.splits.calibration_year
        detections = read_source(cfg, "detections", end_year=end, final=final)
        if not detections.confidence.isin(["n", "h", "l"]).all():
            raise ValueError("VIIRS confidence must be categorical n/h/l")
        detections = detections[detections.confidence.isin(["n", "h"])].copy()
        grid = gpd.read_parquet(self.path("grid") / "grid.parquet")
        if "cell_id" not in detections:
            points = gpd.GeoDataFrame(
                detections,
                geometry=gpd.points_from_xy(detections.x, detections.y_coord),
                crs=grid.crs,
            )
            detections = gpd.sjoin(points, grid[["cell_id", "geometry"]], predicate="within").drop(
                columns=["geometry", "index_right"]
            )
        if final:
            excluded = set(
                json.loads((self.path("events") / "exclusions.json").read_text())["cells"]
            )
        else:
            static = read_source(cfg, "static", end_year=cfg.splits.development_end)
            static["available_at"] = pd.to_datetime(static.available_at, utc=True)
            static = static[
                static.available_at
                < pd.Timestamp(f"{cfg.splits.development_end + 1}-01-01", tz="UTC")
            ]
            if "nonvegetated" not in static:
                raise ValueError(
                    "Development-dated nonvegetated mask is required for hotspot screening"
                )
            excluded = persistent_hotspots(
                detections,
                static.set_index("cell_id").nonvegetated,
                cfg.splits.development_end,
                cfg.events.hotspot_min_days,
            )
        detections = detections[~detections.cell_id.isin(excluded)]
        events = link_events(detections, cfg.events.radius_m, cfg.events.window_hours)
        events.attrs["excluded"] = sorted(excluded)
        return events

    def stage_events(self, out: Path) -> None:
        cfg = self.cfg
        events = self._events()
        events.to_parquet(out / "detections.parquet", index=False)
        dump_json(
            out / "exclusions.json",
            {
                "cells": events.attrs["excluded"],
                "evidence_end_year": cfg.splits.development_end,
                "reason": "persistent + development nonvegetated",
            },
        )
        rows = []
        for radius in cfg.events.sensitivity_radius_m:
            for hours in cfg.events.sensitivity_hours:
                linked = link_events(events, radius, hours)
                rows.append(
                    {"radius_m": radius, "hours": hours, "events": int(linked.is_first.sum())}
                )
        pd.DataFrame(rows).to_csv(out / "sensitivity.csv", index=False)

    def _risk_months(self, events: pd.DataFrame, years: list[int], *, final: bool = False) -> Any:
        AccessGuard(self.cfg, final=final).check(years)
        grid = gpd.read_parquet(self.path("grid") / "grid.parquet")
        attributes = grid.drop(columns="geometry").copy()
        attributes["cell_wkt"] = grid.geometry.to_wkt()
        # Region labels must be joined from a dated administrative boundary in real work.
        if "region" not in attributes:
            attributes["region"] = [
                f"synthetic_region_{int(x // 300000)}" if self.cfg.data.synthetic else "unassigned"
                for x in attributes.x
            ]
        for year in years:
            for month in range(1, 13):
                start = pd.Timestamp(year=year, month=month, day=1, tz="UTC")
                days = pd.date_range(start, start + pd.offsets.MonthEnd(), freq="D")
                risk = risk_set(grid, events, days, self.cfg.events.exclusion_hours)
                yield risk.merge(attributes, on="cell_id", validate="many_to_one")

    def stage_risk_set(self, out: Path) -> None:
        events = pd.read_parquet(self.path("events") / "detections.parquet")
        counts = []
        for risk in self._risk_months(
            events, list(range(self.cfg.splits.start_year, self.cfg.splits.calibration_year + 1))
        ):
            counts.append(
                {
                    "year": risk.day.dt.year.iloc[0],
                    "month": risk.day.dt.month.iloc[0],
                    "cell_days": len(risk),
                    "eligible": int(risk.eligible.sum()),
                    "positive_eligible": int(risk.loc[risk.eligible, "label"].sum()),
                    "positive_excluded": int(risk.loc[~risk.eligible, "label"].sum()),
                }
            )
            write_partitioned(risk, out / "table")
        pd.DataFrame(counts).to_csv(out / "counts.csv", index=False)

    def stage_sampling(self, out: Path) -> None:
        """Audit sampling allocations; actual sampling is executed inside training folds."""
        cfg = self.cfg
        rows = []
        cover = read_source(cfg, "landcover", end_year=cfg.splits.development_end)
        for year in range(cfg.splits.start_year, cfg.splits.development_end + 1):
            frame = AccessGuard(cfg).read(self.path("risk_set") / "table", [year])
            frame = frame[frame.eligible]
            annual = cover[cover.map_year == year - 1].copy()
            annual["landcover"] = annual[COVER].idxmax(axis=1)
            frame = frame.merge(annual[["cell_id", "landcover"]], on="cell_id", how="left")
            for (month, landcover), group in frame.groupby(
                [frame.day.dt.month, "landcover"], observed=True
            ):
                positives = int(group.label.sum())
                negatives = len(group) - positives
                count = min(
                    negatives,
                    max(
                        cfg.sampling.minimum_negatives,
                        int(np.ceil(positives * cfg.sampling.negative_ratio)),
                    ),
                )
                rows.append(
                    {
                        "year": year,
                        "month": month,
                        "landcover": landcover,
                        "positives": positives,
                        "negatives": negatives,
                        "illustrative_q": count / negatives if negatives else 1.0,
                        "note": "recomputed inside each training fold; calibration/test representative",
                    }
                )
        pd.DataFrame(rows).to_csv(out / "allocation_plan.csv", index=False)

    def _raw_cells(
        self, name: str, cells: list[str], start: pd.Timestamp, end: pd.Timestamp, *, final: bool
    ) -> pd.DataFrame:
        last_year = (end - pd.Timedelta(nanoseconds=1)).year
        AccessGuard(self.cfg, final=final).check(list(range(start.year, last_year + 1)))
        filters: list[tuple[str, str, Any]] = [("cell_id", "in", cells), ("year", "<=", last_year)]
        time_column = {
            "weather": "day" if self.cfg.data.weather_mode == "daily" else "timestamp",
            "vegetation": "interval_start",
        }.get(name)
        if time_column:
            filters.extend([(time_column, ">=", start), (time_column, "<", end)])
        return pd.read_parquet(self.cfg.data.sources[name].path, filters=filters)

    def _feature_month(self, risk: pd.DataFrame, *, final: bool = False) -> Any:
        cfg = self.cfg
        risk = risk[risk.eligible].copy()
        start = risk.day.min() - pd.Timedelta(
            days=max(60, cfg.data.vegetation_fill_days + cfg.data.publication_lag_days + 16)
        )
        end = risk.day.max() + pd.Timedelta(days=1)
        cells = risk.cell_id.unique().tolist()
        for offset in range(0, len(cells), cfg.data.cell_chunk_size):
            chunk = cells[offset : offset + cfg.data.cell_chunk_size]
            sources = {
                name: self._raw_cells(name, chunk, start, end, final=final)
                for name in ["weather", "vegetation", "landcover", "static", "human"]
            }
            daily = weather_daily(
                sources["weather"], cfg.data.weather_mode, cfg.data.weather_lag_days
            )
            frame, features = build_features(
                risk[risk.cell_id.isin(chunk)],
                daily,
                sources["vegetation"],
                sources["landcover"],
                sources["static"],
                sources["human"],
                cfg.data.publication_lag_days,
                cfg.data.vegetation_fill_days,
                cfg.data.historical_roads,
            )
            frame["weight"] = 1.0
            frame["q"] = 1.0
            yield frame, features

    def stage_features(self, out: Path) -> None:
        import pyarrow.parquet as pq

        features: list[str] = []
        for year in range(self.cfg.splits.start_year, self.cfg.splits.calibration_year + 1):
            for month in range(1, 13):
                path = out / "table" / f"year={year}" / f"month={month}"
                path.mkdir(parents=True, exist_ok=True)
                risk = pd.read_parquet(
                    self.path("risk_set") / "table",
                    filters=[("year", "=", year), ("month", "=", month)],
                )
                for index, (frame, batch_features) in enumerate(self._feature_month(risk)):
                    features = batch_features
                    pq.write_table(
                        __import__("pyarrow").Table.from_pandas(
                            frame.drop(columns=["year", "month"], errors="ignore"),
                            preserve_index=False,
                        ),
                        path / f"part-{index}.parquet",
                    )
        dump_json(
            out / "features.json",
            {
                "columns": features,
                "groups": GROUPS,
                "availability": "Every nonmissing feature has feature__asof < target UTC day",
            },
        )

    def _features(self, years: list[int]) -> pd.DataFrame:
        return FeatureStore(self.path("features") / "table", self.cfg, years).sample(training=False)

    def stage_splits(self, out: Path) -> None:
        cfg = self.cfg
        # Split construction requires only keys and coordinates; predictor values remain unused.
        grid = gpd.read_parquet(self.path("grid") / "grid.parquet")
        data = grid.drop(columns="geometry").assign(cell_wkt=grid.geometry.to_wkt())
        folds: list[tuple[str, np.ndarray, np.ndarray]] = []
        manifest: list[dict[str, Any]] = [
            {
                "fold": f"temporal_{y}",
                "train_years": list(range(cfg.splits.start_year, y)),
                "validation_years": [y],
            }
            for y in cfg.splits.validation_years
        ]
        for size in [cfg.splits.block_m] + cfg.splits.sensitivity_block_m:
            folds.extend(spatial_folds(data, size, cfg.splits.spatial_folds, cfg.splits.buffer_m))
        for name, ti, vi in folds:
            records = pd.concat(
                [
                    data.iloc[ti][["cell_id"]].assign(partition="train"),
                    data.iloc[vi][["cell_id"]].assign(partition="validation"),
                ]
            )
            records.to_parquet(out / f"{name}.parquet", index=False)
            manifest.append(
                {
                    "fold": name,
                    "train": len(ti),
                    "validation": len(vi),
                    "sha256": checksum(out / f"{name}.parquet"),
                }
            )
        dump_json(out / "manifest.json", manifest)

    def stage_train(self, out: Path) -> None:
        cfg = self.cfg
        store = FeatureStore(
            self.path("features") / "table",
            cfg,
            list(range(cfg.splits.start_year, cfg.splits.development_end + 1)),
        )
        grid = gpd.read_parquet(self.path("grid") / "grid.parquet")
        cells = grid.drop(columns="geometry").assign(cell_wkt=grid.geometry.to_wkt())
        features = json.loads((self.path("features") / "features.json").read_text())["columns"]
        models, scores, trials, heldout = train_store_suite(store, cells, features, cfg, out)
        joblib.dump(models, out / "models.joblib")
        scores.to_csv(out / "cv.csv", index=False)
        heldout.to_parquet(out / "spatial_heldout_predictions.parquet", index=False)
        dump_json(out / "tuning.json", trials)
        primary = scores[
            ~scores.fold.str.startswith("spatial_")
            | scores.fold.str.startswith(f"spatial_{cfg.splits.block_m}_")
        ]
        ranking = pd.Series(
            {
                str(name): float(np.average(group.weighted_ap, weights=group.validation_weight))
                for name, group in primary.groupby("model")
            }
        ).sort_values(ascending=False)
        margin_models = ranking[ranking.index.isin(["xgboost", "catboost"])]
        dump_json(
            out / "selection.json",
            {
                "selected_model": ranking.index[0],
                "explanation_model": margin_models.index[0] if len(margin_models) else None,
                "criterion": "validation-weighted AP across outer temporal and primary spatial folds",
                "ranking": ranking.to_dict(),
            },
        )

    def stage_calibrate(self, out: Path) -> None:
        cfg = self.cfg
        frame = self._features([cfg.splits.calibration_year])
        frame[["cell_id", "day", "label", "q", "weight"]].to_parquet(
            out / "sample.parquet", index=False
        )
        models = joblib.load(self.path("train") / "models.joblib")
        calibrators, thresholds, boundaries = {}, {}, {}
        for name, model in models.items():
            raw = model.predict(frame)
            calibrator, tau = fit_sigmoid(frame, raw, cfg.splits.calibration_year)
            calibrators[name], thresholds[name] = calibrator, tau
            boundaries[name] = map_boundaries(
                calibrator.predict(raw), cfg.evaluation.map_quantiles, frame.weight.to_numpy()
            )
        joblib.dump(calibrators, out / "calibrators.joblib")
        dump_json(
            out / "frozen.json",
            {
                "thresholds": thresholds,
                "boundaries": boundaries,
                "selection_year": cfg.splits.calibration_year,
            },
        )

    def stage_ablate(self, out: Path) -> None:
        cfg = self.cfg
        name = json.loads((self.path("train") / "selection.json").read_text())["explanation_model"]
        if not name:
            raise ValueError("A margin-producing tree model is required for grouped ablations")
        store = FeatureStore(
            self.path("features") / "table",
            cfg,
            list(range(cfg.splits.start_year, cfg.splits.development_end + 1)),
        )
        train = store.sample(training=True)
        calibration = self._features([cfg.splits.calibration_year])
        full = json.loads((self.path("features") / "features.json").read_text())["columns"]
        models, calibrators, thresholds, trials = {}, {}, {}, {}
        for group in ["anthropogenic", "lagged_weather", "vegetation"]:
            features = [f for f in full if f not in GROUPS[group]]
            params, history = tune(name, store, features, cfg, cfg.splits.validation_years)
            model = fit_model(name, train, features, cfg, params, sampled=True)
            calibrator, tau = fit_sigmoid(
                calibration, model.predict(calibration), cfg.splits.calibration_year
            )
            key = f"without_{group}"
            models[key], calibrators[key], thresholds[key], trials[key] = (
                model,
                calibrator,
                tau,
                history,
            )
        joblib.dump({"models": models, "calibrators": calibrators}, out / "ablations.joblib")
        dump_json(out / "thresholds.json", thresholds)
        dump_json(out / "tuning.json", trials)

    def stage_evaluate(self, out: Path) -> None:
        """First allowed materialization of test labels/predictors after all choices freeze."""
        cfg = self.cfg
        frozen = json.loads((self.path("calibrate") / "frozen.json").read_text())
        dump_json(
            out / "test_release.json",
            {
                "reason": "final evaluation only",
                "seed": cfg.seed,
                "frozen_sha256": checksum(self.path("calibrate") / "frozen.json"),
                "train_sha256": checksum(self.path("train") / "models.joblib"),
                "ablation_sha256": checksum(self.path("ablate") / "ablations.joblib"),
            },
        )
        events = self._events(final=True)
        for risk in self._risk_months(events, cfg.splits.test_years, final=True):
            for frame, _ in self._feature_month(risk, final=True):
                write_partitioned(frame, out / "features")
        frame = FeatureStore(out / "features", cfg, cfg.splits.test_years, final=True).sample(
            training=False
        )
        frame.to_parquet(out / "evaluation_sample.parquet", index=False)
        models = joblib.load(self.path("train") / "models.joblib")
        calibrators = joblib.load(self.path("calibrate") / "calibrators.joblib")
        ablation = joblib.load(self.path("ablate") / "ablations.joblib")
        models.update(ablation["models"])
        calibrators.update(ablation["calibrators"])
        thresholds = frozen["thresholds"] | json.loads(
            (self.path("ablate") / "thresholds.json").read_text()
        )
        predictions, timings = {}, []
        for name, model in models.items():
            start = time.perf_counter()
            predictions[name] = calibrators[name].predict(model.predict(frame))
            timings.append(
                {"model": name, "rows": len(frame), "seconds": time.perf_counter() - start}
            )
        reference = models["seasonal"].predict(frame)
        output = frame[
            ["cell_id", "day", "label", "x", "y_coord", "area_km2", "region", "landcover", "weight"]
        ].copy()
        output["seasonal_reference"] = reference
        for name, probability in predictions.items():
            output[name] = probability
        output.to_parquet(out / "predictions.parquet", index=False)
        pd.DataFrame(timings).to_csv(out / "inference_time.csv", index=False)
        rows, capture = [], []
        for name, p in predictions.items():
            rows.append(
                {
                    "model": name,
                    "stratum": "overall",
                    "value": "all",
                    **metrics(
                        frame.label.to_numpy(),
                        p,
                        frame.weight.to_numpy(),
                        thresholds[name],
                        reference,
                        cfg.evaluation.reliability_bins,
                    ),
                }
            )
            for dimension, values in {
                "year": frame.day.dt.year,
                "month": frame.day.dt.month,
                "region": frame.region,
                "landcover": frame.landcover,
            }.items():
                for value in values.unique():
                    mask = (values == value).to_numpy()
                    rows.append(
                        {
                            "model": name,
                            "stratum": dimension,
                            "value": str(value),
                            **metrics(
                                frame.label.to_numpy()[mask],
                                p[mask],
                                frame.weight.to_numpy()[mask],
                                thresholds[name],
                                reference[mask],
                                cfg.evaluation.reliability_bins,
                            ),
                        }
                    )
            capture.append(top_capture(frame, p, cfg.evaluation.top_fractions).assign(model=name))
        pd.DataFrame(rows).to_csv(out / "metrics.csv", index=False)
        pd.concat(capture).to_csv(out / "top_capture.csv", index=False)
        draws = cluster_draws(
            frame,
            cfg.evaluation.bootstrap_resamples,
            cfg.splits.block_m,
            cfg.evaluation.bootstrap_block_days,
            cfg.seed,
        )
        paired_intervals(
            frame.label.to_numpy(),
            predictions,
            frame.weight.to_numpy(),
            thresholds,
            reference,
            draws,
            cfg.evaluation.confidence_level,
        ).to_csv(out / "paired_intervals.csv", index=False)
        rels = [
            reliability_intervals(
                frame.label.to_numpy(),
                p,
                frame.weight.to_numpy(),
                draws,
                cfg.evaluation.reliability_bins,
                cfg.evaluation.confidence_level,
            ).assign(model=name)
            for name, p in predictions.items()
        ]
        pd.concat(rels).to_csv(out / "reliability.csv", index=False)
        # Class frequencies use calibration-frozen boundaries; test outcomes cannot move them.
        class_rows = []
        for name in frozen["boundaries"]:
            classes = np.digitize(predictions[name], frozen["boundaries"][name]) + 1
            for code in np.unique(classes):
                mask = classes == code
                class_rows.append(
                    {
                        "model": name,
                        "class": int(code),
                        "rows": int(mask.sum()),
                        "observed_frequency": float(
                            np.average(frame.label[mask], weights=frame.weight[mask])
                        ),
                        "mean_probability": float(
                            np.average(predictions[name][mask], weights=frame.weight[mask])
                        ),
                    }
                )
        pd.DataFrame(class_rows).to_csv(out / "class_frequencies.csv", index=False)

    def stage_explain(self, out: Path) -> None:
        from wildfire_kz.explain import explain_model

        cfg = self.cfg
        selected = json.loads((self.path("train") / "selection.json").read_text())[
            "explanation_model"
        ]
        models = joblib.load(self.path("train") / "models.joblib")
        frame = pd.read_parquet(self.path("evaluate") / "evaluation_sample.parquet")
        calibrators = joblib.load(self.path("calibrate") / "calibrators.joblib")
        frame["decision_probability"] = calibrators[selected].predict(
            models[selected].predict(frame)
        )
        frozen = json.loads((self.path("calibrate") / "frozen.json").read_text())
        # Error examples are selected using calibrated operating decisions, while values explain raw margins.
        explain_model(
            models[selected],
            frame,
            frozen["thresholds"][selected],
            out,
            cfg.evaluation.shap_rows,
            cfg.seed,
        )
        dump_json(
            out / "interpretation.json",
            {
                "model": selected,
                "output": "uncalibrated log-odds",
                "meaning": "predictive association, not causal",
                "sampling": "high scores + errors + deterministic random sample",
            },
        )

    def stage_map(self, out: Path) -> None:
        from wildfire_kz.mapping import export_daily

        selected = json.loads((self.path("train") / "selection.json").read_text())["selected_model"]
        model = joblib.load(self.path("train") / "models.joblib")[selected]
        calibration = joblib.load(self.path("calibrate") / "calibrators.joblib")[selected]
        grid = gpd.read_parquet(self.path("grid") / "grid.parquet")
        frozen = json.loads((self.path("calibrate") / "frozen.json").read_text())
        import pyarrow.dataset as ds

        dataset = ds.dataset(self.path("evaluate") / "features", partitioning="hive")
        for year in self.cfg.splits.test_years:
            for month in range(1, 13):
                predictions = []
                scanner = dataset.scanner(
                    filter=(ds.field("year") == year) & (ds.field("month") == month),
                    batch_size=self.cfg.data.chunk_rows,
                )
                for batch in scanner.to_batches():
                    frame = batch.to_pandas()
                    predictions.append(
                        frame[["cell_id", "day"]].assign(
                            probability=calibration.predict(model.predict(frame))
                        )
                    )
                export_daily(
                    grid,
                    pd.concat(predictions),
                    out,
                    self.cfg.grid.resolution_m,
                    frozen["boundaries"][selected],
                    {
                        "seed": str(self.cfg.seed),
                        "model": selected,
                        "synthetic": str(self.cfg.data.synthetic),
                        "manifest_sha256": checksum(self.path("ingest") / "manifest.json"),
                    },
                )

    def stage_report(self, out: Path) -> None:
        from wildfire_kz.reporting import build_report

        packages = {
            d.metadata["Name"]: d.version
            for d in importlib.metadata.distributions()
            if d.metadata["Name"]
        }
        dump_json(
            out / "reproducibility.json",
            {
                "packages": packages,
                "seed": self.cfg.seed,
                "platform": platform.platform(),
                "processor": platform.processor(),
                "cpu_count": os.cpu_count(),
                "ram_bytes": psutil.virtual_memory().total,
                "code_sha256": code_digest(),
                "synthetic": self.cfg.data.synthetic,
                "sources": json.loads((self.path("ingest") / "manifest.json").read_text()),
                "splits": json.loads((self.path("splits") / "manifest.json").read_text()),
            },
        )
        build_report(self.root, out, self.cfg)
