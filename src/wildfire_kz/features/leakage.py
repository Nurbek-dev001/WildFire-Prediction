"""Automated temporal-leakage check for feature tables."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from wildfire_kz.features.registry import FeatureSpec

ASOF_COLUMN = {
    "weather_prior_day": "asof_weather",
    "weather_antecedent": "asof_weather",
    "fire_weather": "asof_weather",
    "vegetation": "asof_vegetation",
    "landcover": "asof_landcover",
    "terrain": "asof_terrain",
    "anthropogenic": "asof_anthropogenic",
    "fire_history": "asof_fire_history",
}


class LeakageError(RuntimeError):
    """A predictor uses information timestamped on or after the target day."""


def check_no_leakage(
    df: pd.DataFrame, specs: list[FeatureSpec], date_col: str = "date"
) -> dict[str, Any]:
    """Verify ``asof < target date`` for every row and every non-deterministic feature group.

    A missing as-of timestamp is accepted only when every feature of that group is missing in
    that row (no information was used). Deterministic (calendar) features must be explicitly
    whitelisted in the registry. Raises :class:`LeakageError` on any violation.
    """
    target = pd.to_datetime(df[date_col]).to_numpy(dtype="datetime64[ns]")
    report: dict[str, Any] = {"n_rows": len(df), "groups": {}}
    problems = []
    groups: dict[str, list[str]] = {}
    for s in specs:
        if s.name in df.columns:
            groups.setdefault(s.group, []).append(s.name)
    for group, names in groups.items():
        if all(s.deterministic for s in specs if s.group == group):
            report["groups"][group] = {"status": "deterministic (exempt)", "features": names}
            continue
        col = ASOF_COLUMN.get(group)
        if col is None or col not in df.columns:
            problems.append(f"group '{group}' has no as-of column")
            continue
        asof = pd.to_datetime(df[col]).to_numpy(dtype="datetime64[ns]")
        nat = np.isnat(asof)
        late = ~nat & (asof >= target)
        has_value = df[names].notna().to_numpy().any(axis=1) if names else np.zeros(len(df), bool)
        unknown = nat & has_value
        report["groups"][group] = {
            "asof_column": col,
            "features": names,
            "violations": int(late.sum()),
            "values_without_asof": int(unknown.sum()),
            "max_asof_minus_target_days": (
                float(((asof[~nat] - target[~nat]) / np.timedelta64(1, "D")).max())
                if (~nat).any()
                else None
            ),
        }
        if late.any() or unknown.any():
            problems.append(
                f"group '{group}': {int(late.sum())} rows with as-of >= target day, "
                f"{int(unknown.sum())} rows with values but no as-of"
            )
    report["passed"] = not problems
    if problems:
        raise LeakageError("temporal leakage detected:\n  " + "\n  ".join(problems))
    return report
