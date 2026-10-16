"""Event linking (2 km / 48 h), earliest-detection labelling and FIRMS QC on toy cases."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from wildfire_kz.config.schema import FirmsSource
from wildfire_kz.events.firms import QCCounts, deduplicate, parse_acq_datetime, read_firms
from wildfire_kz.events.linking import earliest_detection, link_detections


def _link(points: list[tuple[float, float, float]], km: float = 2.0, h: float = 48.0) -> np.ndarray:
    arr = np.asarray(points, dtype=float)
    return link_detections(arr[:, 0], arr[:, 1], arr[:, 2], km, h, window_days=2)


def test_pair_within_2km_and_48h_is_linked() -> None:
    lab = _link([(0, 0, 0), (1500, 0, 30)])
    assert lab[0] == lab[1]


def test_boundaries_are_inclusive() -> None:
    lab = _link([(0, 0, 0), (2000, 0, 48)])  # exactly 2 km and exactly 48 h
    assert lab[0] == lab[1]


def test_too_far_in_space_is_not_linked() -> None:
    lab = _link([(0, 0, 0), (2001, 0, 1)])
    assert lab[0] != lab[1]


def test_too_far_in_time_is_not_linked() -> None:
    lab = _link([(0, 0, 0), (100, 0, 48.01)])
    assert lab[0] != lab[1]


def test_transitive_chain_forms_one_event() -> None:
    # A-B 1.8 km/40 h, B-C 1.8 km/40 h; A-C 3.6 km/80 h are linked through B
    lab = _link([(0, 0, 0), (1800, 0, 40), (3600, 0, 80)])
    assert len(set(lab)) == 1


def test_window_boundaries_do_not_split_events() -> None:
    # detections straddle the 2-day processing window used internally
    pts = [(0, 0, 47.0), (500, 0, 49.0), (1000, 0, 95.0)]
    lab = _link(pts)
    assert len(set(lab)) == 1


def test_sensitivity_settings_change_linkage() -> None:
    pts = [(0, 0, 0), (2500, 0, 10)]
    assert len(set(_link(pts, km=2.0))) == 2
    assert len(set(_link(pts, km=3.0))) == 1
    pts_t = [(0, 0, 0), (100, 0, 60)]
    assert len(set(_link(pts_t, h=48))) == 2
    assert len(set(_link(pts_t, h=72))) == 1


def test_event_ids_are_chronological_and_deterministic() -> None:
    lab = _link([(50_000, 0, 100), (0, 0, 0), (100, 0, 5)])
    assert lab[1] == lab[2] == 0 and lab[0] == 1


def test_earliest_detection_defines_the_positive() -> None:
    t0 = pd.Timestamp("2019-05-01 20:40")
    df = pd.DataFrame(
        {
            "event_id": [0, 0, 0, 1],
            "acq_datetime": [t0 + pd.Timedelta(hours=12), t0, t0 + pd.Timedelta(hours=36), t0],
            "confidence_rank": [0, 1, 0, 1],
            "frp": [9.0, 1.0, 50.0, 2.0],
            "cell_id": [11, 10, 12, 99],
        }
    )
    first = earliest_detection(df)
    ev0 = first.loc[first["event_id"] == 0].iloc[0]
    assert ev0["acq_datetime"] == t0 and ev0["cell_id"] == 10
    assert len(first) == 2


def test_tie_break_prefers_high_confidence_then_frp() -> None:
    t0 = pd.Timestamp("2020-07-01 08:40")
    df = pd.DataFrame(
        {
            "event_id": [0, 0, 0],
            "acq_datetime": [t0, t0, t0],
            "confidence_rank": [1, 0, 0],
            "frp": [99.0, 3.0, 7.0],
            "cell_id": [1, 2, 3],
        }
    )
    assert earliest_detection(df).iloc[0]["cell_id"] == 3


def test_acq_time_parsing_is_utc_hhmm() -> None:
    t = parse_acq_datetime(pd.Series(["2020-01-02"]), pd.Series([5]))
    assert t.iloc[0] == pd.Timestamp("2020-01-02 00:05")
    with pytest.raises(ValueError):
        parse_acq_datetime(pd.Series(["2020-01-02"]), pd.Series([2460]))


def _csv(tmp_path, conf: list[object]):  # type: ignore[no-untyped-def]
    n = len(conf)
    df = pd.DataFrame(
        {
            "latitude": [50.0] * n,
            "longitude": [70.0 + i for i in range(n)],
            "acq_date": ["2020-06-01"] * n,
            "acq_time": [840] * n,
            "confidence": conf,
            "satellite": ["N"] * n,
            "instrument": ["VIIRS"] * n,
            "frp": [1.0] * n,
            "type": [0] * n,
        }
    )
    p = tmp_path / "f.csv"
    df.to_csv(p, index=False)
    return p


def test_viirs_confidence_categories_low_dropped(tmp_path) -> None:  # type: ignore[no-untyped-def]
    qc = QCCounts()
    out = read_firms([_csv(tmp_path, ["l", "n", "h", "n"])], FirmsSource(source_id="x"), qc)
    assert sorted(out["confidence"]) == ["h", "n", "n"]
    assert qc.counts["dropped_low_confidence"] == 1


def test_modis_style_percent_confidence_is_rejected(tmp_path) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValueError, match="categorical"):
        read_firms([_csv(tmp_path, [85, 30])], FirmsSource(source_id="x"), QCCounts())


def test_firms_config_rejects_percent_thresholds() -> None:
    with pytest.raises(ValueError):
        FirmsSource(source_id="x", keep_confidence=["80"])


def test_exact_duplicates_removed() -> None:
    t = pd.Timestamp("2020-06-01 08:40")
    df = pd.DataFrame(
        {"latitude": [50.00001, 50.00001, 50.1], "longitude": [70.0] * 3, "acq_datetime": [t, t, t]}
    )
    qc = QCCounts()
    assert len(deduplicate(df, 4, qc)) == 2 and qc.counts["dropped_duplicates"] == 1
