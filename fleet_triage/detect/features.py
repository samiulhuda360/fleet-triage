"""Causal window features over the fleet's hourly telemetry.

Every feature at check hour ``t`` uses only data from hours before ``t``, so alerts carry a realistic detection
time. Window means are computed from cumulative sums, which keeps a full 30-day replay fast.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np

from ..sim.fleet import Fleet

NIGHT_HOURS = {18, 19, 20, 21, 22, 23, 0, 1, 2, 3, 4, 5, 6}


class Rolling:
    """O(1) NaN-aware window sums over the time axis of an (N, T) array."""

    def __init__(self, x: np.ndarray):
        valid = ~np.isnan(x)
        zero = np.zeros((x.shape[0], 1))
        self.s = np.concatenate([zero, np.cumsum(np.where(valid, x, 0.0), axis=1)], axis=1)
        self.c = np.concatenate([zero, np.cumsum(valid, axis=1)], axis=1)

    def count(self, t0: int, t1: int) -> np.ndarray:
        t0 = max(t0, 0)
        return self.c[:, t1] - self.c[:, t0]

    def mean(self, t0: int, t1: int, min_count: int = 1) -> np.ndarray:
        """Mean over hours [t0, t1); NaN where fewer than ``min_count`` values exist."""
        t0 = max(t0, 0)
        n = self.c[:, t1] - self.c[:, t0]
        s = self.s[:, t1] - self.s[:, t0]
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.where(n >= min_count, s / np.maximum(n, 1), np.nan)

    def mean_rows(self, rows: np.ndarray, t0: np.ndarray, t1: np.ndarray, min_count: int = 1) -> np.ndarray:
        """Per-row windows: the mean of row ``rows[i]`` over hours [t0[i], t1[i])."""
        t0 = np.clip(t0, 0, None)
        n = self.c[rows, t1] - self.c[rows, t0]
        s = self.s[rows, t1] - self.s[rows, t0]
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.where(n >= min_count, s / np.maximum(n, 1), np.nan)


@dataclass
class FleetFeatures:
    fleet: Fleet

    def __post_init__(self) -> None:
        f = self.fleet
        hod = np.arange(f.hours) % 24
        night = np.isin(hod, list(NIGHT_HOURS))
        both_night = night[1:] & night[:-1]
        drop = -(f.battery[:, 1:] - f.battery[:, :-1])
        # a reading at 0 % hides further drain, so ignore steps that touch the floor
        floor = (f.battery[:, 1:] <= 0.5) | (f.battery[:, :-1] <= 0.5)
        drain = np.where(both_night[None, :] & ~floor, drop, np.nan)
        self.night_drain = np.concatenate([np.full((f.n_devices, 1), np.nan), drain], axis=1)

        # residual against the farm median at the same hour removes weather and time-of-day effects
        farm = f.device_farm
        self.temp_resid = np.full_like(f.temp_c, np.nan)
        self.solar_ratio = np.full_like(f.solar_ma, np.nan)
        for fi in range(len(f.farms)):
            rows = farm == fi
            if not rows.any():
                continue
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN hours during an outage
                med_t = np.nanmedian(f.temp_c[rows], axis=0)
                med_s = np.nanmedian(f.solar_ma[rows], axis=0)
            self.temp_resid[rows] = f.temp_c[rows] - med_t
            with np.errstate(all="ignore"):
                self.solar_ratio[rows] = np.where(med_s > 20, f.solar_ma[rows] / med_s, np.nan)

        self.r_drain = Rolling(self.night_drain)
        self.r_fix = Rolling(f.gps_fix)
        self.r_hdop = Rolling(f.hdop)
        self.r_temp_resid = Rolling(self.temp_resid)
        self.r_signal = Rolling(f.signal_dbm)
        self.r_uplink = Rolling(f.uplink)
        self.r_solar_ratio = Rolling(self.solar_ratio)
        self.r_reported = Rolling(np.where(f.reported, 1.0, 0.0))

        # last report hour as of each hour (for silence)
        rep = f.reported
        idx = np.where(rep, np.arange(f.hours)[None, :], -1)
        self.last_report = np.maximum.accumulate(idx, axis=1)  # last hour <= t with a report

    def hours_silent(self, t: int) -> np.ndarray:
        """Hours since the last report, as seen at the start of hour ``t``."""
        if t == 0:
            return np.zeros(self.fleet.n_devices)
        last = self.last_report[:, t - 1]
        return np.where(last >= 0, t - last - 1, t)

    def window_vector(self, t: int, w: int = 24) -> dict[str, np.ndarray]:
        """The per-device feature vector over the trailing ``w`` hours, used by the anomaly layer."""
        return {
            "night_drain": self.r_drain.mean(t - w, t, min_count=5),
            "gps_fix": self.r_fix.mean(t - w, t, min_count=6),
            "hdop": self.r_hdop.mean(t - w, t, min_count=6),
            "temp_resid": self.r_temp_resid.mean(t - w, t, min_count=6),
            "signal": self.r_signal.mean(t - w, t, min_count=6),
            "uplink": self.r_uplink.mean(t - w, t, min_count=1),
            "solar_ratio": self.r_solar_ratio.mean(t - w, t, min_count=3),
        }


FEATURE_NAMES = ["night_drain", "gps_fix", "hdop", "temp_resid", "signal", "uplink", "solar_ratio"]
