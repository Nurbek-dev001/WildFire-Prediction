"""Causal lag, rolling-window, weighting and sealed-final-input checks."""

import numpy as np
import pandas as pd
import pytest

from wildfire_kz import model_upgrade as mu


@pytest.fixture
def history_grid(monkeypatch):
    grid=pd.DataFrame({"cell_id":[f"g5000_{r}_{c}" for r in range(-2,3) for c in range(-2,3)]})
    monkeypatch.setattr(mu.pd,"read_parquet",lambda *args,**kwargs:grid)
    return grid


def test_history_excludes_future_and_enforces_seven_day_lag(history_grid):
    data=pd.DataFrame({"cell_id":["g5000_0_0","g5000_0_1"],
                       "day":pd.to_datetime(["2020-01-01","2020-01-09"],utc=True)})
    ids=pd.Series(["g5000_0_0"])
    h=mu.FireHistory(data,lag_days=7)
    assert h.get(pd.Timestamp("2020-01-07",tz="UTC"),ids)[mu.HISTORY[0]][0]==0
    actual=h.get(pd.Timestamp("2020-01-08",tz="UTC"),ids)
    past=mu.FireHistory(data.iloc[:1],lag_days=7).get(pd.Timestamp("2020-01-08",tz="UTC"),ids)
    for name in mu.HISTORY:
        np.testing.assert_array_equal(actual[name],past[name])
        assert actual[name][0]==pytest.approx(np.log(2))


def test_rolling_window_removes_expired_detections(history_grid):
    data=pd.DataFrame({"cell_id":["g5000_0_0"],"day":pd.to_datetime(["2020-01-01"],utc=True)})
    h=mu.FireHistory(data,lag_days=7)
    ids=pd.Series(["g5000_0_0"])
    assert h.get(pd.Timestamp("2020-01-14",tz="UTC"),ids)[mu.HISTORY[0]][0]>0
    assert h.get(pd.Timestamp("2020-01-15",tz="UTC"),ids)[mu.HISTORY[0]][0]==0
    with pytest.raises(ValueError,match="chronological"):
        h.get(pd.Timestamp("2020-01-14",tz="UTC"),ids)


def test_final_inputs_require_a_new_frozen_release():
    with pytest.raises(PermissionError,match="sealed"):
        mu.load_history(2023)
    f=pd.DataFrame({"day":pd.to_datetime(["2023-01-01"],utc=True)})
    with pytest.raises(PermissionError,match="freeze"):
        mu.augment(f,None)


def test_refined_history_uses_two_day_lag(history_grid):
    data=pd.DataFrame({"cell_id":["g5000_0_0"],"day":pd.to_datetime(["2020-01-01"],utc=True)})
    h=mu.FireHistory(data)
    ids=pd.Series(["g5000_0_0"])
    assert h.get(pd.Timestamp("2020-01-02",tz="UTC"),ids)[mu.HISTORY[0]][0]==0
    assert h.get(pd.Timestamp("2020-01-03",tz="UTC"),ids)[mu.HISTORY[0]][0]>0


def test_precision_constraint_uses_design_weights():
    y=np.array([1,0,1,0])
    p=np.array([.9,.8,.7,.1])
    result=mu.operating_point(y,p,np.array([1.,100.,1.,1000.]),.10)
    assert result["threshold"]==.9 and result["precision"]==1 and result["recall"]==.5
    assert mu.operating_point(y,p,np.ones(4),.10)["recall"]==1


def test_quantized_published_values_are_exactly_representable():
    p=np.array([0,1e-7,.00123456,.1,1],dtype="float64")
    q=mu.published_probability(p)
    assert q.dtype==np.float32
    np.testing.assert_array_equal(q,q.astype("float16").astype("float32"))
    np.testing.assert_allclose(q,p,atol=3e-8,rtol=.001)
