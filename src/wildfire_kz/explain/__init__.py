"""TreeSHAP in uncalibrated log-odds for margin-producing boosted trees."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import shap
from scipy.special import logit

from wildfire_kz.features import GROUPS
from wildfire_kz.models import FittedModel


def explain_model(
    model: FittedModel,
    frame: pd.DataFrame,
    threshold: float,
    destination: Path,
    rows: int,
    seed: int,
    *,
    render: bool = True,
) -> None:
    """Global/grouped/local explanations; calibration is deliberately outside TreeSHAP."""
    if model.name not in ["xgboost", "catboost"]:
        raise ValueError(
            "Exact TreeSHAP raw log-odds requires XGBoost/CatBoost; RF raw output is probability"
        )
    destination.mkdir(parents=True, exist_ok=True)
    ranked = frame.assign(_p=model.predict(frame)).sort_values("_p", ascending=False)
    decision = ranked["decision_probability"] if "decision_probability" in ranked else ranked._p
    error = ranked[(decision >= threshold) != ranked.label.astype(bool)]
    chosen = (
        pd.concat(
            [
                ranked.head(max(1, rows // 4)),
                error.head(max(1, rows // 4)),
                ranked.sample(min(rows, len(ranked)), random_state=seed),
            ]
        )
        .drop_duplicates(["cell_id", "day"])
        .head(rows)
    )
    x = model.pipeline.named_steps["preprocess"].transform(chosen[model.features])
    tree = model.pipeline.named_steps["estimator"]
    explainer = shap.TreeExplainer(
        tree, model_output="raw", feature_perturbation="tree_path_dependent"
    )
    explanation = explainer(x)
    values = np.asarray(explanation.values)
    margin = logit(np.clip(model.predict(chosen), 1e-7, 1 - 1e-7))
    np.testing.assert_allclose(
        np.asarray(explanation.base_values) + values.sum(axis=1), margin, atol=1e-3
    )
    importance = pd.DataFrame(
        {"feature": model.features, "mean_abs_shap": np.abs(values).mean(axis=0)}
    ).sort_values("mean_abs_shap")
    importance.to_csv(destination / "global.csv", index=False)
    local = chosen[["cell_id", "day", "label", "region", "landcover", "_p"]].reset_index(drop=True)
    local["base_log_odds"] = np.asarray(explanation.base_values)
    local["raw_log_odds"] = margin
    for index, feature in enumerate(model.features):
        local[f"shap_{feature}"] = values[:, index]
    local.to_parquet(destination / "local.parquet", index=False)
    grouped = []
    for dimension in ["region", "landcover"]:
        for group, indices in local.groupby(dimension, observed=True).groups.items():
            for semantic, members in GROUPS.items():
                columns = [model.features.index(f) for f in members if f in model.features]
                if columns:
                    grouped.append(
                        {
                            "dimension": dimension,
                            "group": group,
                            "feature_group": semantic,
                            "mean_abs_group_shap": float(
                                np.abs(
                                    values[np.array(list(indices))][:, columns].sum(axis=1)
                                ).mean()
                            ),
                            "rows": len(indices),
                            "interpretation": "predictive association, not causal",
                        }
                    )
    pd.DataFrame(grouped).to_csv(destination / "grouped.csv", index=False)
    if not render:
        return
    fig, ax = plt.subplots(figsize=(9, 7), constrained_layout=True)
    ax.barh(importance.feature, importance.mean_abs_shap, color="#d87937")
    ax.set_xlabel("Mean absolute TreeSHAP contribution (uncalibrated log-odds)")
    ax.set_title("Predictive associations | " + model.name)
    fig.savefig(destination / "global.png", dpi=160)
    fig.savefig(destination / "global.pdf")
    plt.close(fig)
    for feature in importance.feature.tail(3):
        index = model.features.index(feature)
        fig, ax = plt.subplots(figsize=(6, 4), constrained_layout=True)
        ax.scatter(chosen[feature], values[:, index], s=14, c="#178d91", alpha=0.6)
        ax.set(xlabel=feature, ylabel="TreeSHAP (raw log-odds)", title="Predictive association")
        fig.savefig(destination / f"dependence_{feature}.png", dpi=160)
        plt.close(fig)
