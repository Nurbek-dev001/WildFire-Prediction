import json
from datetime import UTC, date, datetime

import numpy as np
import pytest

from wildfire_kz import forecast_log as fl


def entry(day: str, status: str = "issued", on_time: bool = True) -> dict:
    return {"target_day": day, "status": status, "on_time": on_time}


def test_payload_round_trip_is_exact_and_reproducible():
    p = np.array([0.0, 0.0449, 0.9, np.nan, 1e-5], dtype="float32")
    payload = fl.encode(p)
    assert payload == fl.encode(p)
    assert np.array_equal(fl.decode(payload), p.astype("float16").astype("float32"), equal_nan=True)


def test_issue_window_maps_the_night_to_one_target_day():
    assert fl.target_day(datetime(2027, 3, 1, 23, 40, tzinfo=UTC)) == date(2027, 3, 2)
    assert fl.target_day(datetime(2027, 3, 2, 3, 40, tzinfo=UTC)) == date(2027, 3, 2)
    earliest, deadline = fl.window(date(2027, 3, 2))
    assert earliest == datetime(2027, 3, 1, 23, tzinfo=UTC)
    assert deadline == datetime(2027, 3, 2, 6, tzinfo=UTC)
    assert not fl.last_attempt(date(2027, 3, 2), datetime(2027, 3, 2, 1, 40, tzinfo=UTC))
    assert fl.last_attempt(date(2027, 3, 2), datetime(2027, 3, 2, 3, 40, tzinfo=UTC))


def test_chain_links_entries_and_refuses_a_second_issue(tmp_path):
    log = tmp_path / "log.jsonl"
    first = fl.append(log, entry("2027-03-01"))
    second = fl.append(log, entry("2027-03-02"))
    assert first["previous_sha256"] == fl.GENESIS
    assert second["previous_sha256"] == first["entry_sha256"]
    assert [r["target_day"] for r in fl.read(log)] == ["2027-03-01", "2027-03-02"]
    with pytest.raises(FileExistsError):
        fl.append(log, entry("2027-03-02"))


def test_any_edit_breaks_the_chain(tmp_path):
    log = tmp_path / "log.jsonl"
    fl.append(log, entry("2027-03-01"))
    fl.append(log, entry("2027-03-02"))
    rows = log.read_text().splitlines()
    edited = json.loads(rows[0]) | {"on_time": False}
    log.write_text(json.dumps(edited) + "\n" + rows[1] + "\n")
    with pytest.raises(ValueError, match="chain broken"):
        fl.read(log)
    log.write_text(rows[1] + "\n")
    with pytest.raises(ValueError, match="chain broken"):
        fl.read(log)


def test_summary_counts_on_time_late_and_missed_test_days(tmp_path):
    log = tmp_path / "log.jsonl"
    fl.append(log, entry("2027-02-28"))
    fl.append(log, entry("2027-03-01"))
    fl.append(log, entry("2027-03-02", on_time=False))
    fl.append(log, entry("2027-03-03", status="missed", on_time=False))
    s = fl.summary(fl.read(log), (date(2027, 3, 1), date(2027, 10, 31)))
    assert s == {
        "entries": 4,
        "test_days_total": 245,
        "test_days_on_time": 1,
        "test_days_late": 1,
        "test_days_missed": 1,
        "last": "2027-03-03",
    }
