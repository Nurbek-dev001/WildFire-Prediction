"""Canadian Fire Weather Index system on the daily ERA5 grid, plus simple dryness counts.

Van Wagner (1987) equations, applied to daily values: maximum temperature as the
noon temperature, daily mean relative humidity, daily mean 10 m wind and the UTC-day
precipitation total. Daily means stand in for the noon observations the system was
designed for, so absolute index values are approximate; only their ranking is used.
Codes start at the standard spring values on 2014-01-01 and run continuously
without overwintering adjustments.
"""

from __future__ import annotations

import numpy as np

# Day-length factors for DMC and DC at northern mid-latitudes, January..December.
DMC_DAY_LENGTH = np.array(
    [6.5, 7.5, 9.0, 12.8, 13.9, 13.9, 12.4, 10.9, 9.4, 8.0, 7.0, 6.0], dtype="float64"
)
DC_DAY_LENGTH = np.array(
    [-1.6, -1.6, -1.6, 0.9, 3.8, 5.8, 6.4, 5.0, 2.4, 0.4, -1.6, -1.6], dtype="float64"
)
NAMES = ["ffmc", "dmc", "dc", "isi", "bui", "fwi", "dry_days", "precip_30d", "precip_60d"]


class FireWeather:
    """Advance one day at a time; `state()` returns every index after the last step."""

    def __init__(self, shape: tuple[int, int]):
        self.ffmc = np.full(shape, 85.0)
        self.dmc = np.full(shape, 6.0)
        self.dc = np.full(shape, 15.0)
        self.isi = np.zeros(shape)
        self.bui = np.zeros(shape)
        self.fwi = np.zeros(shape)
        self.dry_days = np.zeros(shape)
        self.rain: list[np.ndarray] = []  # last 60 daily precipitation grids

    def step(
        self, temp: np.ndarray, rh: np.ndarray, wind_ms: np.ndarray, precip: np.ndarray, month: int
    ) -> None:
        t = np.nan_to_num(np.asarray(temp, dtype="float64"), nan=0.0)
        h = np.clip(np.nan_to_num(np.asarray(rh, dtype="float64"), nan=50.0), 0, 100)
        w = np.clip(np.nan_to_num(np.asarray(wind_ms, dtype="float64"), nan=0.0), 0, None) * 3.6
        r = np.clip(np.nan_to_num(np.asarray(precip, dtype="float64"), nan=0.0), 0, None)

        # Fine Fuel Moisture Code.
        mo = 147.2 * (101 - self.ffmc) / (59.5 + self.ffmc)
        rf = r - 0.5
        wet = r > 0.5
        rf_safe = np.where(wet, rf, 1.0)
        gain = 42.5 * rf_safe * np.exp(-100 / (251 - mo)) * (1 - np.exp(-6.93 / rf_safe))
        mo = np.where(
            wet,
            np.where(mo > 150, mo + gain + 0.0015 * (mo - 150) ** 2 * np.sqrt(rf_safe), mo + gain),
            mo,
        )
        mo = np.minimum(mo, 250)
        ed = (
            0.942 * h**0.679
            + 11 * np.exp((h - 100) / 10)
            + 0.18 * (21.1 - t) * (1 - np.exp(-0.115 * h))
        )
        ew = (
            0.618 * h**0.753
            + 10 * np.exp((h - 100) / 10)
            + 0.18 * (21.1 - t) * (1 - np.exp(-0.115 * h))
        )
        ko = 0.424 * (1 - (h / 100) ** 1.7) + 0.0694 * np.sqrt(w) * (1 - (h / 100) ** 8)
        kd = ko * 0.581 * np.exp(0.0365 * t)
        k1 = 0.424 * (1 - ((100 - h) / 100) ** 1.7) + 0.0694 * np.sqrt(w) * (
            1 - ((100 - h) / 100) ** 8
        )
        kw = k1 * 0.581 * np.exp(0.0365 * t)
        m = np.where(
            mo > ed,
            ed + (mo - ed) * 10 ** (-kd),
            np.where(mo < ew, ew - (ew - mo) * 10 ** (-kw), mo),
        )
        self.ffmc = np.clip(59.5 * (250 - m) / (147.2 + m), 0, 101)

        # Duff Moisture Code.
        td = np.maximum(t, -1.1)
        rk = 1.894 * (td + 1.1) * (100 - h) * DMC_DAY_LENGTH[month - 1] * 1e-6
        re = 0.92 * r - 1.27
        mo_d = 20 + np.exp(5.6348 - self.dmc / 43.43)
        dmc_safe = np.maximum(self.dmc, 1e-6)
        b = np.where(
            self.dmc <= 33,
            100 / (0.5 + 0.3 * self.dmc),
            np.where(self.dmc <= 65, 14 - 1.3 * np.log(dmc_safe), 6.2 * np.log(dmc_safe) - 17.2),
        )
        mr = mo_d + 1000 * re / (48.77 + b * re)
        pr = np.where(
            r > 1.5, np.maximum(244.72 - 43.43 * np.log(np.maximum(mr - 20, 1e-6)), 0), self.dmc
        )
        self.dmc = np.maximum(pr + 100 * rk, 0)

        # Drought Code.
        tc = np.maximum(t, -2.8)
        pe = np.maximum((0.36 * (tc + 2.8) + DC_DAY_LENGTH[month - 1]) / 2, 0)
        rd = 0.83 * r - 1.27
        qr = 800 * np.exp(-self.dc / 400) + 3.937 * rd
        dr = np.where(r > 2.8, np.maximum(400 * np.log(800 / np.maximum(qr, 1e-6)), 0), self.dc)
        self.dc = dr + pe

        # Initial Spread, Buildup and Fire Weather indices.
        f_w = np.exp(0.05039 * w)
        fm = 147.2 * (101 - self.ffmc) / (59.5 + self.ffmc)
        f_f = 91.9 * np.exp(-0.1386 * fm) * (1 + fm**5.31 / 4.93e7)
        self.isi = 0.208 * f_w * f_f
        denom = np.maximum(self.dmc + 0.4 * self.dc, 1e-6)
        u = np.where(
            self.dmc <= 0.4 * self.dc,
            0.8 * self.dmc * self.dc / denom,
            self.dmc - (1 - 0.8 * self.dc / denom) * (0.92 + (0.0114 * self.dmc) ** 1.7),
        )
        self.bui = np.maximum(u, 0)
        f_d = np.where(
            self.bui <= 80,
            0.626 * self.bui**0.809 + 2,
            1000 / (25 + 108.64 * np.exp(-0.023 * self.bui)),
        )
        bb = 0.1 * self.isi * f_d
        self.fwi = np.where(
            bb > 1, np.exp(2.72 * (0.434 * np.log(np.maximum(bb, 1.0))) ** 0.647), bb
        )

        self.dry_days = np.where(r >= 1.0, 0, self.dry_days + 1)
        self.rain.append(r)
        if len(self.rain) > 60:
            self.rain.pop(0)

    def state(self) -> dict[str, np.ndarray]:
        stack = np.stack(self.rain)
        return {
            "ffmc": self.ffmc,
            "dmc": self.dmc,
            "dc": self.dc,
            "isi": self.isi,
            "bui": self.bui,
            "fwi": self.fwi,
            "dry_days": self.dry_days,
            "precip_30d": stack[-30:].sum(axis=0),
            "precip_60d": stack.sum(axis=0),
        }
