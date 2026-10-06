"""Time-series anomaly detection, per collar and per cohort.

Two detectors run at every check on 24-hour window features:

* **Per collar**: a robust z-score of each feature against the collar's own history (median and MAD of its
  window features from two to seven days earlier). This catches slow drifts early because each collar is
  compared with itself, and it stays quiet on collars that are always noisy.
* **Per cohort**: an IsolationForest over features expressed as residuals from the farm median at the same
  check, so shared weather and terrain cancel out. It is fitted once on the first days of data.

A collar is flagged only when it stays anomalous on two consecutive checks. Each flag names the feature that
moved most in the "bad" direction, which maps to a suspected failure mode.
"""

from __future__ import annotations

import warnings

import numpy as np
from sklearn.ensemble import IsolationForest

from ..sim.fleet import Fleet
from .features import FEATURE_NAMES, FleetFeatures
from .model import CHECK_EVERY, FIRST_CHECK, Finding

# +1 means "higher is worse", -1 means "lower is worse"
BAD_DIRECTION = {
    "night_drain": 1,
    "gps_fix": -1,
    "hdop": 1,
    "temp_resid": 1,
    "signal": -1,
    "uplink": -1,
    "solar_ratio": -1,
}
MAD_FLOOR = {
    "night_drain": 0.03,
    "gps_fix": 0.01,
    "hdop": 0.08,
    "temp_resid": 0.3,
    "signal": 1.0,
    "uplink": 0.04,
    "solar_ratio": 0.05,
}
SUSPECT = {
    "night_drain": "battery_fade",
    "gps_fix": "gps_drift",
    "hdop": "gps_drift",
    "temp_resid": "water_ingress",
    "signal": "anomaly",
    "uplink": "anomaly",
    "solar_ratio": "anomaly",
}
Z_DEVICE = 7.0
HISTORY = (168, 48)  # history window for the per-collar baseline: from t-168 to t-48
IF_TRAIN = (48, 144)  # hours whose checks train the IsolationForest
IF_QUANTILE = 0.999
CONSECUTIVE = 2
IF_MIN_Z = 5.0  # the forest's outlier must also be far out on at least one feature


def _matrix(feats: FleetFeatures, t: int) -> np.ndarray:
    v = feats.window_vector(t, 24)
    return np.stack([v[k] for k in FEATURE_NAMES], axis=1)  # (N, F)


def _farm_residual(x: np.ndarray, farm: np.ndarray, n_farms: int, floor: np.ndarray) -> np.ndarray:
    """Robust z of each collar against its own farm at the same check (median and MAD of the farm)."""
    out = np.full_like(x, np.nan)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        for f in range(n_farms):
            rows = farm == f
            if rows.any():
                med = np.nanmedian(x[rows], axis=0)
                mad = np.nanmedian(np.abs(x[rows] - med), axis=0) * 1.4826
                out[rows] = (x[rows] - med) / np.maximum(mad, floor)
    return out


def _suspect(scores: np.ndarray) -> tuple[str, str, float]:
    """Pick the suspected mode from per-feature bad-direction scores of one collar."""
    k = int(np.nanargmax(scores))
    feat = FEATURE_NAMES[k]
    t_i, s_i = FEATURE_NAMES.index("temp_resid"), FEATURE_NAMES.index("signal")
    # hot against the farm and weak against itself together is the water-ingress signature
    if feat in ("signal", "uplink", "temp_resid") and scores[t_i] > 3 and scores[s_i] > 2:
        return "water_ingress", feat, float(scores[k])
    return SUSPECT[feat], feat, float(scores[k])


def run_anomaly(fleet: Fleet, feats: FleetFeatures | None = None, seed: int = 0) -> list[Finding]:
    feats = feats or FleetFeatures(fleet)
    farm = fleet.device_farm
    n_farms = len(fleet.farms)
    direction = np.array([BAD_DIRECTION[k] for k in FEATURE_NAMES], dtype=float)
    floor = np.array([MAD_FLOOR[k] for k in FEATURE_NAMES])

    checks = list(range(FIRST_CHECK, fleet.hours + 1, CHECK_EVERY))
    mats: dict[int, np.ndarray] = {}
    resid: dict[int, np.ndarray] = {}
    forest: IsolationForest | None = None
    if_threshold = np.inf
    streak_dev = np.zeros(fleet.n_devices, dtype=int)
    streak_if = np.zeros(fleet.n_devices, dtype=int)
    out: list[Finding] = []
    med: np.ndarray | None = None
    mad: np.ndarray | None = None

    for t in checks:
        x = _matrix(feats, t)
        mats[t] = x
        resid[t] = _farm_residual(x, farm, n_farms, floor)

        # ---- per collar: robust z against its own history --------------------------------------
        # the per-collar baseline is refreshed once a day; it only needs to follow slow change
        if t % 24 == 0 or med is None:
            hist = [mats[h] for h in checks if t - HISTORY[0] <= h <= t - HISTORY[1] and h in mats]
            if len(hist) >= 8:
                stack = np.stack(hist)  # (H, N, F)
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", RuntimeWarning)
                    med = np.nanmedian(stack, axis=0)
                    mad = np.nanmedian(np.abs(stack - med), axis=0) * 1.4826
        z_bad = np.full_like(x, np.nan)
        if med is not None:
            z_bad = (x - med) / np.maximum(mad, floor) * direction
        with np.errstate(invalid="ignore"):
            dev_hit = np.nanmax(np.where(np.isnan(z_bad), -np.inf, z_bad), axis=1) > Z_DEVICE
        streak_dev = np.where(dev_hit, streak_dev + 1, 0)

        # ---- per cohort: IsolationForest on farm residuals --------------------------------------
        if forest is None and t >= IF_TRAIN[1]:
            train = np.concatenate([resid[h] for h in checks if IF_TRAIN[0] <= h <= IF_TRAIN[1]])
            train = train[np.isfinite(train).all(axis=1)]
            forest = IsolationForest(n_estimators=150, random_state=seed).fit(train)
            if_threshold = float(np.quantile(-forest.score_samples(train), IF_QUANTILE))
        if_hit = np.zeros(fleet.n_devices, dtype=bool)
        r = resid[t]
        if forest is not None:
            ok = np.isfinite(r).all(axis=1)
            if ok.any():
                score = np.full(fleet.n_devices, -np.inf)
                score[ok] = -forest.score_samples(r[ok])
                cz = np.nanmax(r * direction, axis=1)
                if_hit = (score > if_threshold) & (cz > IF_MIN_Z)
        streak_if = np.where(if_hit, streak_if + 1, 0)

        for d in np.where((streak_dev >= CONSECUTIVE) | (streak_if >= CONSECUTIVE))[0]:
            if streak_dev[d] >= CONSECUTIVE:
                scores, how = z_bad[d], "own history"
            else:
                scores, how = r[d] * direction, "farm cohort"
            ftype, feat, z = _suspect(np.where(np.isnan(scores), -np.inf, scores))
            out.append(
                Finding(
                    hour=t,
                    type=ftype,
                    source="anomaly",
                    rule="A-DEVICE-Z" if how == "own history" else "A-COHORT-IF",
                    detail=f"{feat} {z:.1f} robust SDs from its {how} (24 h window)",
                    device_idx=int(d),
                    value=z,
                    feature=feat,
                )
            )
        # keep memory bounded
        for h in [h for h in mats if h < t - HISTORY[0] - CHECK_EVERY and h > IF_TRAIN[1]]:
            mats.pop(h, None)
            resid.pop(h, None)
    return out
