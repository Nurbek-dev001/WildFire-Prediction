# Explanation compatibility decision, before final test access

On 2026-10-20 the six estimator families were exercised on a small synthetic
software fixture. No real study model or 2023–2024 observation was used.
The installed CatBoost Lossguide model's native Regular SHAP values did not
sum to its raw prediction (maximum error 0.3257 on that fixture). Its native
Exact and Independent SHAP modes reject non-symmetric trees. Approximate native
attributions summed correctly but are not substituted under an exact TreeSHAP
label.

If CatBoost is selected by development validation, explanations therefore use
model-agnostic permutation SHAP: 10 forward/reverse feature permutations,
seed 42, and 128 background rows sampled with replacement proportional to
the design weights from the actual final training rows in 2015–2021.
The background is saved with its keys and values. This estimates Shapley
values by Monte Carlo and is explicitly labelled approximate. Additivity is
checked against the unchanged CatBoost raw margin. Calibration remains outside
the explanation.

Random Forest and XGBoost retain TreeSHAP; linear and seasonal baselines use
their exact additive output decomposition. No explanation determines model
selection or changes probabilities, calibration, thresholds, or test metrics.
The explanation implementation is sealed with the metric implementation before
final-year materialisation. Actual compatibility-check results and package
versions are retained in `runs/public_hindcast/software_checks/`.

References: [CatBoost SHAP output](https://catboost.ai/docs/en/concepts/shap-values),
[CatBoost feature importance API](https://catboost.ai/docs/en/concepts/python-reference_catboost_get_feature_importance),
[SHAP permutation estimator](https://shap.readthedocs.io/en/stable/generated/shap.PermutationExplainer.html).
