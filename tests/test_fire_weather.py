import numpy as np

from wildfire_kz.fire_weather import FireWeather


def test_matches_van_wagner_reference_day():
    # First day of the standard cffdrs test series: 17 C, 42% RH, 25 km/h, no rain, April.
    fw = FireWeather((1, 1))
    fw.step(
        np.full((1, 1), 17.0), np.full((1, 1), 42.0), np.full((1, 1), 25 / 3.6), np.zeros((1, 1)), 4
    )
    s = fw.state()
    expected = {
        "ffmc": 87.6929,
        "dmc": 8.5450,
        "dc": 19.0130,
        "isi": 10.8534,
        "bui": 8.4904,
        "fwi": 10.0997,
    }
    for name, value in expected.items():
        assert abs(float(s[name][0, 0]) - value) < 0.01, name


def test_rain_lowers_codes_and_resets_dry_days():
    fw = FireWeather((1, 1))
    for _ in range(20):
        fw.step(
            np.full((1, 1), 30.0), np.full((1, 1), 20.0), np.full((1, 1), 5.0), np.zeros((1, 1)), 7
        )
    dry = fw.state()
    fw.step(
        np.full((1, 1), 20.0), np.full((1, 1), 80.0), np.full((1, 1), 2.0), np.full((1, 1), 20.0), 7
    )
    wet = fw.state()
    assert dry["dry_days"][0, 0] == 20 and wet["dry_days"][0, 0] == 0
    assert wet["ffmc"][0, 0] < dry["ffmc"][0, 0]
    assert wet["dmc"][0, 0] < dry["dmc"][0, 0]
    assert wet["precip_30d"][0, 0] == 20
