import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from wildfire_kz.config import Config
from wildfire_kz.data import AccessGuard
from wildfire_kz.events import link_events, risk_set
from wildfire_kz.grid import build_grid


def toy():
    return pd.DataFrame(
        {
            "cell_id": ["a"] * 4,
            "confidence": ["n", "h", "n", "l"],
            "x": [0, 1500, 3000, 0],
            "y_coord": [0] * 4,
            "timestamp": pd.to_datetime(
                ["2020-01-01T12:00Z", "2020-01-03T12:00Z", "2020-01-05T12:00Z", "2020-01-08T12:00Z"]
            ),
        }
    )


def test_transitive_events_and_earliest():
    events = link_events(toy())
    assert len(events) == 3
    assert events.event_id.nunique() == 1
    assert events.is_first.tolist() == [True, False, False]
    assert link_events(toy(), window_hours=47).event_id.nunique() == 3
    assert link_events(toy(), radius_m=1499).event_id.nunique() == 3


def test_past_exclusion():
    events = link_events(toy())
    days = pd.date_range("2020-01-01", "2020-01-08", tz="UTC")
    risk = risk_set(pd.DataFrame({"cell_id": ["a"]}), events, days)
    assert risk.eligible.tolist() == [True, False, False, False, False, False, False, True]
    assert risk.label.sum() == 1


def test_test_guard():
    with pytest.raises(PermissionError):
        AccessGuard(Config()).check([2023])
    AccessGuard(Config(), final=True).check([2023, 2024])


def test_stable_equal_area_grid():
    crs = Config().grid.crs
    boundary = gpd.GeoDataFrame(geometry=[box(0, 0, 10000, 5000)], crs=crs)
    a = build_grid(boundary, crs, 5000)
    b = build_grid(boundary, crs, 5000)
    assert a.cell_id.tolist() == b.cell_id.tolist()
    assert a.area_km2.tolist() == [25, 25]
    with pytest.raises(ValueError):
        build_grid(boundary, "EPSG:3857", 5000)
