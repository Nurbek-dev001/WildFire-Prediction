"""Five buffered geographic refits of the fixed recipe, using only years <=2022.

This is a development transfer audit: globally chosen historical hyperparameters
are held fixed, so it is not a new fully nested independent benchmark.
"""

import gc
import json
from datetime import UTC, datetime

import numpy as np
import pandas as pd
from scipy.special import logit
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from wildfire_kz import model_upgrade as mu
from wildfire_kz.calibration import fit_sigmoid
from wildfire_kz.data import checksum, dump_json
from wildfire_kz.data.public_predictors import geography, log
from wildfire_kz.data.public_study import FEATURES
from wildfire_kz.evaluation import metrics
from wildfire_kz.public_experiment import config, fit
from wildfire_kz.splits import spatial_folds
from wildfire_kz.stacked_model import StackedFireModel

RUN = mu.ROOT / "runs/spatial_audit_v1"


def main():
    RUN.mkdir(exist_ok=True)
    plan = {
        "created_utc": datetime.now(UTC).isoformat(),
        "synthetic": False,
        "training_max_year": 2021,
        "calibration_and_evaluation_year": 2022,
        "folds": 5,
        "block_m": 100000,
        "buffer_m": 25000,
        "selection": "no search; frozen original XGBoost parameters, C=1, blend=0.5",
        "limitation": "Historical hyperparameters selected globally through 2021; conditional development transfer audit, not fully nested independent spatial test.",
        "history": "Past-only detections may be observed in held regions, as at deployment; no held-region outcomes enter estimator fitting.",
        "test_2023_2025_used": False,
    }
    if not (RUN / "plan.json").exists():
        dump_json(RUN / "plan.json", plan)
    grid = geography()[0].copy()
    grid["cell_wkt"] = grid.geometry.to_wkt()
    params = json.loads((mu.OLD / "tuning.json").read_text())["xgboost"]["selected"]
    cfg = config()
    cfg.models.threads = 4
    industrial = set(json.loads((mu.OLD / "industrial_cells.json").read_text())["cell_ids"])
    frames = {y: pd.read_parquet(mu.RUN / f"features/{y}_train.parquet") for y in range(2015, 2022)}
    needed = ["cell_id", "day", "label", "weight", *FEATURES, *mu.HISTORY, "x", "y_coord"]
    training = pd.concat(
        [f.loc[~f.cell_id.isin(industrial), needed] for f in frames.values()], ignore_index=True
    )
    del frames
    gc.collect()
    calibration = pd.read_parquet(mu.RUN / "features/2022_evaluation.parquet")
    calibration = calibration[~calibration.cell_id.isin(industrial)].copy()
    results = []
    for fold, ti, vi in spatial_folds(grid, 100000, 5, 25000):
        path = RUN / f"{fold}.json"
        if path.exists():
            results.extend(json.loads(path.read_text())["metrics"])
            continue
        allowed = set(grid.iloc[ti].cell_id)
        held = set(grid.iloc[vi].cell_id)
        train = training[training.cell_id.isin(allowed)]
        cal = calibration[calibration.cell_id.isin(allowed)].copy()
        test = calibration[calibration.cell_id.isin(held)].copy()
        if train.day.dt.year.max() > 2021 or not cal.day.dt.year.eq(2022).all():
            raise PermissionError("Temporal boundary violated")
        log(f"{fold}: {len(train)} training, {len(cal)} calibration, {len(test)} spatial test rows")
        meta_x = []
        meta_y = []
        meta_w = []
        for year in [2019, 2020, 2021]:
            earlier = train[train.day.dt.year < year]
            valid = pd.read_parquet(mu.RUN / f"features/{year}_evaluation.parquet")
            valid = valid[valid.cell_id.isin(allowed) & ~valid.cell_id.isin(industrial)]
            base = fit("xgboost", earlier, cfg, dict(params))
            x = valid[mu.HISTORY].copy()
            x["baseline_logit"] = logit(np.clip(base.predict(valid), 1e-7, 1 - 1e-7))
            meta_x.append(x)
            meta_y.append(valid.label)
            meta_w.append(valid.weight)
            del base, valid, earlier
            gc.collect()
            log(f"{fold}: chronological stack inputs {year} complete")
        x = pd.concat(meta_x, ignore_index=True)
        y = pd.concat(meta_y, ignore_index=True)
        w = pd.concat(meta_w, ignore_index=True).to_numpy()
        meta = make_pipeline(
            StandardScaler(), LogisticRegression(C=1, max_iter=2000, random_state=42)
        )
        meta.fit(x, y, logisticregression__sample_weight=w / w.mean())
        del x, y, w, meta_x, meta_y, meta_w
        gc.collect()
        base = fit("xgboost", train, cfg, dict(params))
        stack = StackedFireModel(base, meta, 0.5)
        raw = base.predict(cal)
        bc, bt = fit_sigmoid(cal, raw, 2022)
        bp = mu.published_probability(bc.predict(raw))
        original = metrics(
            cal.label.to_numpy(),
            bp,
            cal.weight.to_numpy(),
            bt,
            np.full(len(cal), np.average(cal.label, weights=cal.weight)),
        )
        raw = stack.predict_proba(cal)[:, 1]
        sc, _ = fit_sigmoid(cal, raw, 2022)
        sp = mu.published_probability(sc.predict(raw))
        threshold = mu.operating_point(
            cal.label.to_numpy(), sp, cal.weight.to_numpy(), original["precision"]
        )["threshold"]
        frozen = {
            "fold": fold,
            "calibration_rows": len(cal),
            "test_rows": len(test),
            "baseline_threshold": bt,
            "stack_threshold": threshold,
            "parameters": params,
            "train_cell_count": len(allowed),
            "held_cell_count": len(held),
            "buffer_m": 25000,
        }
        # Freeze each fold's parameters and threshold before its held-region outcomes are scored.
        dump_json(RUN / f"{fold}_frozen.json", frozen)
        reference = np.full(len(test), np.average(cal.label, weights=cal.weight))
        records = []
        for name, prob, t in [
            ("xgboost", mu.published_probability(bc.predict(base.predict(test))), bt),
            (
                "xgboost_stack",
                mu.published_probability(sc.predict(stack.predict_proba(test)[:, 1])),
                threshold,
            ),
        ]:
            records.append(
                {
                    "fold": fold,
                    "model": name,
                    "rows": len(test),
                    **metrics(test.label.to_numpy(), prob, test.weight.to_numpy(), t, reference),
                }
            )
        result = {
            "synthetic": False,
            "plan_sha256": checksum(RUN / "plan.json"),
            "frozen_sha256": checksum(RUN / f"{fold}_frozen.json"),
            "metrics": records,
        }
        dump_json(path, result)
        results.extend(records)
        log(f"{fold}: spatial scoring complete")
        del base, stack, meta, train, cal, test
        gc.collect()
    pd.DataFrame(results).to_csv(RUN / "metrics.csv", index=False)
    dump_json(
        RUN / "complete.json",
        {
            "synthetic": False,
            "folds": 5,
            "maximum_year": 2022,
            "metrics_sha256": checksum(RUN / "metrics.csv"),
            "independent_nested_spatial_test": False,
            "reason": plan["limitation"],
        },
    )


if __name__ == "__main__":
    main()
