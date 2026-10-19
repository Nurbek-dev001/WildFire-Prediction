"""Final-only predictive associations from the unchanged selected public model."""

from __future__ import annotations

import json
from typing import Any

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.special import logit

from wildfire_kz.data import checksum, dump_json
from wildfire_kz.data.public_predictors import permitted
from wildfire_kz.data.public_study import RUN, industrial_cells, table

GROUPS = {
    "weather": ["tmax", "tmin", "wind", "rh", "precip", "soil_moisture"],
    "antecedent_weather": ["precip_7d", "precip_14d", "temperature_7d", "temperature_14d"],
    "vegetation": ["ndvi", "ndvi_missing", "ndvi_age_days"],
    "cover": ["forest", "grassland", "shrubland", "cropland", "other"],
    "terrain": ["elevation", "slope", "aspect_sin", "aspect_cos"],
    "human": ["population_density", "settlement_distance"],
    "season": ["month_sin", "month_cos"],
}


def contributions(model: Any, frame: pd.DataFrame) -> tuple[list[str], np.ndarray, np.ndarray, str]:
    """Return additive contributions in an explicit, estimator-correct output unit."""
    if model.name == "seasonal":
        margin = logit(model.predict(frame))
        base = np.full(len(frame), logit(model.prior))
        return ["cover_x_month"], (margin - base)[:, None], base, "uncalibrated log-odds"
    x = model.pipeline.named_steps["preprocess"].transform(frame[model.features])
    estimator = model.pipeline.named_steps["estimator"]
    if model.name in ["logistic", "weather_logistic"]:
        values = x * estimator.coef_[0]
        base = np.full(len(x), estimator.intercept_[0])
        margin = estimator.decision_function(x)
        unit = "uncalibrated log-odds"
    else:
        import shap

        explanation = shap.TreeExplainer(
            estimator, model_output="raw", feature_perturbation="tree_path_dependent"
        )(x)
        values, base = np.asarray(explanation.values), np.asarray(explanation.base_values)
        if model.name == "random_forest":
            values, base = values[:, :, 1], base[:, 1]
            margin = estimator.predict_proba(x)[:, 1]
            # RF TreeSHAP raw output is a probability; converting these additive
            # values to log-odds would be mathematically false.
            unit = "uncalibrated probability"
        elif model.name == "xgboost":
            margin = estimator.predict(x, output_margin=True)
            unit = "uncalibrated log-odds"
        else:
            margin = estimator.predict(x, prediction_type="RawFormulaVal")
            unit = "uncalibrated log-odds"
    np.testing.assert_allclose(base + values.sum(axis=1), margin, atol=1e-3, rtol=1e-5)
    return model.features, values, base, unit


def explain() -> None:
    release = RUN / "release.json"
    permitted([2023, 2024], release)
    evaluation = json.loads((RUN / "evaluate/complete.json").read_text())
    if evaluation["release_sha256"] != checksum(release):
        raise ValueError("Explanation requires the matching completed final evaluation")
    for name, digest in evaluation["outputs"].items():
        if checksum(RUN / "evaluate" / name) != digest:
            raise ValueError(f"Final evaluation output changed: {name}")
    frozen = json.loads((RUN / "frozen.json").read_text())
    selected = frozen["selected_model"]
    model = joblib.load(RUN / "models.joblib")[selected]
    frame = pd.concat(
        [pd.read_parquet(table(y, training=False, release=release)) for y in [2023, 2024]],
        ignore_index=True,
    )
    frame = frame.loc[~frame.cell_id.isin(industrial_cells())].reset_index(drop=True)
    predictions = pd.read_parquet(RUN / f"evaluate/predictions_{selected}.parquet")
    if not frame[["cell_id", "day"]].equals(predictions[["cell_id", "day"]]):
        raise ValueError("Explanations and evaluated prediction keys differ")
    frame["region"] = predictions.region
    frame["calibrated_probability"] = predictions.probability
    global_ids = frame.sample(min(400, len(frame)), random_state=42).index.tolist()
    ranked = frame.sort_values("calibrated_probability", ascending=False, kind="stable")
    high_ids = ranked.head(50).index.tolist()
    errors = ranked[
        (ranked.calibrated_probability >= frozen["thresholds"][selected])
        != ranked.label.astype(bool)
    ]
    error_ids = errors.head(50).index.tolist()
    chosen = frame.loc[list(dict.fromkeys(global_ids + high_ids + error_ids))].copy()
    features, values, base, unit = contributions(model, chosen)
    global_mask = chosen.index.isin(global_ids)
    global_weights = chosen.loc[global_mask, "weight"].to_numpy()
    importance = pd.DataFrame(
        {
            "feature": features,
            "weighted_mean_abs_contribution": np.average(
                np.abs(values[global_mask]), axis=0, weights=global_weights
            ),
        }
    ).sort_values("weighted_mean_abs_contribution")
    destination = RUN / "explain"
    destination.mkdir(parents=True, exist_ok=True)
    importance.to_csv(destination / "global.csv", index=False)
    local = chosen[
        ["cell_id", "day", "label", "weight", "region", "landcover", "calibrated_probability"]
    ].reset_index(drop=True)
    local["selection_role"] = [
        "|".join(
            role
            for role, ids in [
                ("global_uniform", global_ids),
                ("high_score", high_ids),
                ("misclassified", error_ids),
            ]
            if index in ids
        )
        for index in chosen.index
    ]
    local["base_output"] = base
    local["uncalibrated_output"] = base + values.sum(axis=1)
    for i, feature in enumerate(features):
        local[f"contribution_{feature}"] = values[:, i]
    local.to_parquet(destination / "local.parquet", index=False)
    grouped = []
    for dimension in ["region", "landcover"]:
        for group in sorted(chosen.loc[global_mask, dimension].unique()):
            mask = global_mask & chosen[dimension].eq(group).to_numpy()
            for semantic, members in GROUPS.items():
                columns = [features.index(f) for f in members if f in features]
                if columns:
                    grouped.append(
                        {
                            "dimension": dimension,
                            "group": group,
                            "feature_group": semantic,
                            "weighted_mean_abs_group_contribution": float(
                                np.average(
                                    np.abs(values[mask][:, columns].sum(axis=1)),
                                    weights=chosen.loc[mask, "weight"],
                                )
                            ),
                            "sample_rows": int(mask.sum()),
                            "unit": unit,
                            "interpretation": "predictive association, not causal; temporal test regions",
                        }
                    )
    pd.DataFrame(
        grouped,
        columns=[
            "dimension",
            "group",
            "feature_group",
            "weighted_mean_abs_group_contribution",
            "sample_rows",
            "unit",
            "interpretation",
        ],
    ).to_csv(destination / "grouped.csv", index=False)
    figure, axis = plt.subplots(figsize=(9, 7.5), layout="constrained")
    axis.barh(importance.feature, importance.weighted_mean_abs_contribution, color="#2d6351")
    axis.set(
        xlabel=f"Weighted mean absolute contribution ({unit})",
        title=f"{selected} | predictive association, not causal",
    )
    axis.spines[["top", "right"]].set_visible(False)
    figure.savefig(destination / "global.png", dpi=180)
    figure.savefig(destination / "global.pdf")
    plt.close(figure)
    for feature in importance.feature.tail(3):
        if feature not in chosen:
            continue
        figure, axis = plt.subplots(figsize=(6.5, 4.5), layout="constrained")
        axis.scatter(
            chosen.loc[global_mask, feature],
            values[global_mask, features.index(feature)],
            s=14,
            color="#2d6351",
            alpha=0.65,
        )
        axis.set(
            xlabel=feature,
            ylabel=f"Contribution ({unit})",
            title="Predictive association | missing inputs imputed on training only",
        )
        figure.savefig(destination / f"dependence_{feature}.png", dpi=160)
        plt.close(figure)
    dump_json(
        destination / "complete.json",
        {
            "synthetic": False,
            "release_sha256": checksum(release),
            "model": selected,
            "method": "TreeSHAP"
            if selected in ["random_forest", "xgboost", "catboost"]
            else "exact additive estimator output",
            "unit": unit,
            "calibration_inside_explanation": False,
            "additivity_verified": True,
            "global_uniform_sample_rows": int(global_mask.sum()),
            "total_explained_rows": len(chosen),
            "global_sampling": "uniform sample of final probability-sampled rows, original design weights retained",
            "interpretation": "predictive association, not causal; no spatial generalisation claim",
            "outputs": {
                p.name: checksum(p) for p in destination.iterdir() if p.name != "complete.json"
            },
        },
    )
    permitted([2023, 2024], release)
