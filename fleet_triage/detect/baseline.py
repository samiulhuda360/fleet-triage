"""Threshold-only baseline: static limits on the latest reading of each collar and tower.

This is what a first monitoring setup usually looks like. Each crossing raises a device alert; there is no
per-device history, no farm or tower context and no grouping.
"""

from __future__ import annotations

import numpy as np

from ..sim.fleet import Fleet
from .features import FleetFeatures
from .model import CHECK_EVERY, FIRST_CHECK, Finding

THRESHOLDS = {
    "battery_low": ("battery", "<", 20.0, "battery_fade"),
    "temp_high": ("temp_c", ">", 30.0, "water_ingress"),
    "gps_fix_low": ("gps_fix", "<", 0.6, "gps_drift"),
    "hdop_high": ("hdop", ">", 5.0, "gps_drift"),
    "signal_low": ("signal_dbm", "<", -110.0, "weak_signal"),
}
SILENT_HOURS = 6
TOWER_SILENT_HOURS = 2
TOWER_BATTERY_LOW = 15.0


def _latest(arr: np.ndarray, last_report: np.ndarray, t: int) -> np.ndarray:
    last = last_report[:, t - 1]
    vals = arr[np.arange(arr.shape[0]), np.maximum(last, 0)]
    fresh = (last >= 0) & (last >= t - 3)
    return np.where(fresh, vals, np.nan)


def run_baseline(fleet: Fleet, feats: FleetFeatures | None = None) -> list[Finding]:
    feats = feats or FleetFeatures(fleet)
    out: list[Finding] = []
    for t in range(FIRST_CHECK, fleet.hours + 1, CHECK_EVERY):
        for rule, (metric, op, limit, ftype) in THRESHOLDS.items():
            v = _latest(fleet.metric(metric), feats.last_report, t)
            with np.errstate(invalid="ignore"):
                hit = v < limit if op == "<" else v > limit
            for d in np.where(hit)[0]:
                out.append(
                    Finding(
                        hour=t,
                        type=ftype,
                        source="threshold",
                        rule=rule,
                        detail=f"{metric} {v[d]:.1f} {op} {limit}",
                        device_idx=int(d),
                        value=float(v[d]),
                    )
                )
        silent = feats.hours_silent(t)
        for d in np.where(silent >= SILENT_HOURS)[0]:
            out.append(
                Finding(
                    hour=t,
                    type="device_offline",
                    source="threshold",
                    rule="no_report",
                    detail=f"no report for {int(silent[d])} h",
                    device_idx=int(d),
                    value=float(silent[d]),
                )
            )
        for j in range(len(fleet.towers)):
            lo = max(0, t - TOWER_SILENT_HOURS)
            if (fleet.tower_online[j, lo:t] == 0).all():
                out.append(
                    Finding(
                        hour=t,
                        type="tower_outage",
                        source="threshold",
                        rule="tower_heartbeat",
                        detail="tower heartbeat missing",
                        tower_idx=j,
                    )
                )
            elif fleet.tower_battery[j, t - 1] < TOWER_BATTERY_LOW:
                out.append(
                    Finding(
                        hour=t,
                        type="tower_power_low",
                        source="threshold",
                        rule="tower_battery_low",
                        detail=f"tower battery {fleet.tower_battery[j, t - 1]:.0f} %",
                        tower_idx=j,
                    )
                )
    return out


def baseline_alerts(findings: list[Finding], rearm_hours: int = 24) -> list[Finding]:
    """One alert per (device or tower, rule) when it starts firing; re-armed after a quiet spell."""
    last_seen: dict[tuple, int] = {}
    alerts: list[Finding] = []
    for f in sorted(findings, key=lambda x: x.hour):
        key = (f.device_idx, f.tower_idx, f.rule)
        prev = last_seen.get(key)
        if prev is None or f.hour - prev > rearm_hours:
            alerts.append(f)
        last_seen[key] = f.hour
    return alerts
