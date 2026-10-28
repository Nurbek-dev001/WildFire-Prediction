"""Predeclared observation-outage sensitivity; no changes to primary evaluation."""

import json
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from wildfire_kz.data import checksum, dump_json
from wildfire_kz.evaluation import metrics
from wildfire_kz.independent import RUN

plan = RUN / "outage_sensitivity_plan.json"
if not plan.exists():
    if (RUN / "label_access.json").exists():
        raise PermissionError("Sensitivity must be registered before new outcomes")
    dump_json(
        plan,
        {
            "registered_utc": datetime.now(UTC).isoformat(),
            "labels_accessed": False,
            "source": "https://landweb.modaps.eosdis.nasa.gov/knownissue?sensor=VIIRS",
            "source_issue": "TM_NPP_L1B_25315, November 11 2025 SNPP outage; some lost data unrecoverable",
            "exclude_utc_dates": ["2025-11-11", "2025-11-12"],
            "interpretation": "Conservative whole-day secondary sensitivity. Primary all-year detection-target results remain unchanged; missing satellite observations do not establish absence of fire.",
            "threshold_selection_performed": False,
            "code_sha256": checksum(__import__("pathlib").Path(__file__)),
        },
    )
    print("Outage sensitivity registered before label access")
elif (RUN / "evaluation.json").exists():
    p = json.loads(plan.read_text())
    frame = pd.read_parquet(RUN / "predictions.parquet")
    f = frame[~frame.day.dt.strftime("%Y-%m-%d").isin(p["exclude_utc_dates"])]
    primary = json.loads((RUN / "evaluation.json").read_text())
    result = metrics(
        f.label.to_numpy(),
        f.probability.to_numpy(),
        f.weight.to_numpy(),
        primary["threshold"],
        np.full(len(f), primary["metrics"]["prevalence"]),
    )
    dump_json(
        RUN / "outage_sensitivity.json",
        {
            "plan_sha256": checksum(plan),
            "excluded_rows": len(frame) - len(f),
            "primary_unchanged": True,
            "metrics": result,
            "not_verified_ground_fire_absence": True,
        },
    )
    print(json.dumps(result))
