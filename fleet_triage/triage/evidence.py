"""Pull the device data behind a ticket: collar readings, farm and tower state, and open incidents.

Everything here is a fact read from telemetry at the ticket's arrival time. The facts are shown to the person
reviewing the ticket, given to the model as its only source of device detail, and used by the guard that rejects
drafts quoting numbers or collars that are not in this list.
"""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass, field

import numpy as np

from ..detect.features import FleetFeatures
from ..detect.model import TYPE_META, Incident
from ..sim.fleet import Fleet
from .linking import Link


@dataclass
class FleetContext:
    fleet: Fleet
    feats: FleetFeatures
    incidents: list[Incident]

    def incidents_at(self, hour: int, farm_idx: int | None = None, grace: int = 24) -> list[Incident]:
        out = []
        for inc in self.incidents:
            if inc.opened_hour > hour:
                continue
            if inc.resolved_hour is not None and inc.resolved_hour + grace < hour:
                continue
            if farm_idx is not None and farm_idx not in inc.farms:
                continue
            out.append(inc)
        return out


@dataclass
class Evidence:
    collars: list[dict] = field(default_factory=list)
    farm: dict | None = None
    incidents: list[dict] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)
    signals: dict[str, float] = field(default_factory=dict)  # suspected category -> strength 0..1

    def numbers(self) -> set[str]:
        return set(re.findall(r"\d+(?:\.\d+)?", " ".join(self.facts)))


def _r(x: float | None, nd: int = 1) -> float | None:
    if x is None or not np.isfinite(x):
        return None
    return round(float(x), nd)


def gather(ctx: FleetContext, link: Link, hour: int) -> Evidence:
    f, F = ctx.fleet, ctx.feats
    ev = Evidence()
    t = max(hour, 25)
    when = f.hour_to_time(hour).strftime("%d %b %H:00")
    ev.facts.append(f"Ticket received {when}.")
    if link.farm_idx is None:
        return ev

    farm = f.farms[link.farm_idx]
    rows = np.where(f.device_farm == link.farm_idx)[0]
    silent = F.hours_silent(t)
    reporting = int((silent[rows] < 3).sum())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        batt_now = np.nanmedian(_last(f.battery, F, t)[rows])
        batt_before = np.nanmedian(_last(f.battery, F, t - 72)[rows])
        sig72 = f.signal_dbm[rows, max(0, t - 72) : t]
        sig_med = float(np.nanmedian(sig72))
        sig_sd = float(np.nanmedian(np.nanstd(sig72, axis=1)))
    day = min(t // 24, f.farm_cloud.shape[1] - 1)
    sun3 = float(np.mean(f.farm_cloud[link.farm_idx, max(0, day - 2) : day + 1]))
    towers = []
    for tw in (tw for tw in f.towers if tw.farm_idx == link.farm_idx):
        online = bool(f.tower_online[tw.idx, t - 1])
        tb = _r(f.tower_battery[tw.idx, t - 1], 0) if online else None
        towers.append({"id": tw.id, "name": tw.name, "online": online, "battery_pct": tb})
    ev.farm = {
        "id": farm.id,
        "name": farm.name,
        "farmer": farm.farmer,
        "terrain": farm.terrain,
        "collars": len(rows),
        "reporting_last_3h": reporting,
        "median_battery_pct": _r(batt_now, 0),
        "median_battery_3_days_ago_pct": _r(batt_before, 0),
        "sunshine_last_3_days": round(sun3, 2),
        "median_signal_dbm": round(sig_med, 0),
        "signal_spread_db": round(sig_sd, 1),
        "towers": towers,
    }
    ev.facts.append(
        f"{farm.name} ({farm.id}): {reporting} of {len(rows)} collars reported in the last 3 hours; "
        f"median battery {_r(batt_now, 0)} % now vs {_r(batt_before, 0)} % three days ago."
    )
    ev.facts.append(f"Sunshine over the last 3 days at {farm.name}: {sun3 * 100:.0f} % of a clear sky.")
    for tw in towers:
        state = f"online, battery {tw['battery_pct']} %" if tw["online"] else "OFFLINE (no heartbeat)"
        ev.facts.append(f"Tower {tw['id']} {tw['name']}: {state}.")

    # incidents touching this farm
    for inc in ctx.incidents_at(hour, link.farm_idx):
        on_farm = [d for d in inc.devices if f.devices[d].farm_idx == link.farm_idx]
        item = {
            "id": inc.id,
            "type": inc.type,
            "severity": inc.severity,
            "title": inc.title,
            "status": "open" if inc.resolved_hour is None or inc.resolved_hour > hour else "recently resolved",
            "collars_on_farm": len(on_farm),
            "kb": TYPE_META[inc.type]["kb"],
        }
        ev.incidents.append(item)
        ev.facts.append(
            f"Incident {inc.id} ({item['status']}, {inc.severity}): {inc.title}; {len(on_farm)} collars on this farm."
        )

    # mentioned collars
    for d in link.device_idxs[:5]:
        ev.collars.append(_collar(ctx, d, t, hour))
    for c in ev.collars:
        ev.facts.append(_collar_fact(c))

    _signals(ctx, ev, link, hour)
    return ev


def _last(arr: np.ndarray, F: FleetFeatures, t: int) -> np.ndarray:
    t = max(t, 1)
    last = F.last_report[:, t - 1]
    vals = arr[np.arange(arr.shape[0]), np.maximum(last, 0)]
    return np.where(last >= 0, vals, np.nan)


def _collar(ctx: FleetContext, d: int, t: int, hour: int) -> dict:
    f, F = ctx.fleet, ctx.feats
    dev = f.devices[d]
    silent = int(F.hours_silent(t)[d])
    last = int(F.last_report[d, t - 1])
    sig24 = F.r_signal.mean(t - 24, t, 3)[d]
    sig_ref = F.r_signal.mean(t - 168, t - 48, 12)[d]
    inc_ids = [i.id for i in ctx.incidents_at(hour) if d in i.devices and i.devices[d] <= hour]
    return {
        "id": dev.id,
        "firmware": f.firmware_versions[int(f.firmware[d, t - 1])],
        "tower": f.towers[dev.tower_idx].id,
        "tower_online": bool(f.tower_online[dev.tower_idx, t - 1]),
        "hours_since_report": silent,
        "last_report": f.hour_to_time(last).strftime("%d %b %H:00") if last >= 0 else None,
        "battery_pct": _r(f.battery[d, last], 0) if last >= 0 else None,
        "night_drain_pct_per_h": _r(F.r_drain.mean(t - 72, t, 8)[d], 2),
        "night_drain_before": _r(F.r_drain.mean(t - 240, t - 120, 8)[d], 2),
        "gps_fix_pct": _r(F.r_fix.mean(t - 24, t, 3)[d] * 100, 0),
        "hdop": _r(F.r_hdop.mean(t - 24, t, 3)[d], 1),
        "hdop_before": _r(F.r_hdop.mean(t - 168, t - 72, 12)[d], 1),
        "temp_vs_farm_c": _r(F.r_temp_resid.mean(t - 24, t, 3)[d], 1),
        "signal_vs_normal_db": _r(sig24 - sig_ref, 1),
        "incidents": inc_ids,
    }


def _collar_fact(c: dict) -> str:
    parts = [f"Collar {c['id']} (firmware {c['firmware']}, tower {c['tower']}):"]
    if c["hours_since_report"] >= 3:
        parts.append(f"no report for {c['hours_since_report']} h (last {c['last_report']});")
    else:
        parts.append("reporting;")
    if c["battery_pct"] is not None:
        parts.append(f"battery {c['battery_pct']} %;")
    if c["night_drain_pct_per_h"] is not None:
        parts.append(f"night drain {c['night_drain_pct_per_h']} %/h (was {c['night_drain_before']});")
    if c["gps_fix_pct"] is not None:
        parts.append(f"GPS fix {c['gps_fix_pct']} %, HDOP {c['hdop']} (was {c['hdop_before']});")
    if c["temp_vs_farm_c"] is not None:
        parts.append(f"temperature {c['temp_vs_farm_c']:+} C vs the farm;")
    if c["signal_vs_normal_db"] is not None:
        parts.append(f"signal {c['signal_vs_normal_db']:+} dB vs its normal;")
    if c["incidents"]:
        parts.append("in incident " + ", ".join(c["incidents"]) + ".")
    return " ".join(parts)


INCIDENT_TO_CATEGORY = {
    "tower_outage": "tower_outage",
    "firmware_bad": "firmware_bad",
    "battery_fade": "battery_fade",
    "water_ingress": "water_ingress",
    "gps_drift": "gps_drift",
}


def _signals(ctx: FleetContext, ev: Evidence, link: Link, hour: int) -> None:
    """What the data suggests, as category strengths. Collar-level evidence beats farm-level evidence."""
    s: dict[str, float] = {}
    collar_incs = {i for c in ev.collars for i in c["incidents"]}
    for item in ev.incidents:
        cat = INCIDENT_TO_CATEGORY.get(item["type"])
        if cat is None or item["collars_on_farm"] == 0:
            continue
        strength = 1.0 if item["id"] in collar_incs else 0.6
        s[cat] = max(s.get(cat, 0), strength)
    # the collar's own readings, read the way the knowledge base describes each failure
    for c in ev.collars:
        drain, before = c["night_drain_pct_per_h"], c["night_drain_before"] or 0.28
        if drain is not None and drain > 0.5 and drain > 1.5 * before and c["firmware"] != "3.5.0":
            s["battery_fade"] = max(s.get("battery_fade", 0), 0.9)
        if c["hdop"] is not None and c["hdop"] > 2.8 and c["hdop"] - (c["hdop_before"] or c["hdop"]) > 1.0:
            s["gps_drift"] = max(s.get("gps_drift", 0), 0.9)
        if (c["temp_vs_farm_c"] or 0) > 3 and (c["signal_vs_normal_db"] or 0) < -4:
            s["water_ingress"] = max(s.get("water_ingress", 0), 0.9)
    farm = ev.farm or {}
    no_fault = not any(k in s for k in ("tower_outage", "firmware_bad"))
    if farm and no_fault:
        dropped = (farm.get("median_battery_3_days_ago_pct") or 0) - (farm.get("median_battery_pct") or 0)
        if farm["sunshine_last_3_days"] < 0.45 and dropped > 5 and farm["reporting_last_3h"] >= 0.8 * farm["collars"]:
            s["weather_low_charge"] = max(s.get("weather_low_charge", 0), 0.6)
        if farm["median_signal_dbm"] < -98 and farm["signal_spread_db"] > 4.5:
            s["poor_coverage"] = max(s.get("poor_coverage", 0), 0.6)
    if ev.collars and not s:
        healthy = all(c["hours_since_report"] < 3 and not c["incidents"] for c in ev.collars)
        if healthy:
            s["healthy_collars"] = 1.0
    ev.signals = s
