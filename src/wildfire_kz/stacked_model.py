"""Chronologically trained score stack; no target-year labels in prediction."""
from dataclasses import dataclass
from typing import Any
import numpy as np
import pandas as pd
from scipy.special import logit
from wildfire_kz.model_upgrade import HISTORY


@dataclass
class StackedFireModel:
    baseline: Any
    meta: Any
    meta_weight: float

    def predict_proba(self,frame: pd.DataFrame) -> np.ndarray:
        baseline=self.baseline.predict(frame)
        inputs=frame[HISTORY].copy()
        inputs['baseline_logit']=logit(np.clip(baseline,1e-7,1-1e-7))
        learned=self.meta.predict_proba(inputs)[:,1]
        p=self.meta_weight*learned+(1-self.meta_weight)*baseline
        return np.column_stack([1-p,p])
