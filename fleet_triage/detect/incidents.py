"""Turn findings into incidents: deduplicate, group, explain, rate severity and impact.

The grouping rules are what keep on-call quiet:

* one incident per tower (a power warning that turns into an outage stays the same incident and escalates);
* one incident per firmware version;
* otherwise one incident per failure mode per farm;
* collars that go quiet on a tower that is down are part of the tower incident, not alerts of their own;
* a collar that goes quiet while it is already in an incident stays in that incident;
* drain and GPS-fix signals on collars in a known firmware cohort are part of the firmware incident;
* anomaly signals on a collar whose firmware changed in the last three days wait for the cohort check;
* an anomaly on a collar that already sits in an incident corroborates it instead of raising another.
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np

from ..sim.fleet import Fleet
from .model import SEVERITIES, TYPE_META, Finding, Incident

QUIET_HOURS = {"tower": 6, "anomaly": 24}
DEFAULT_QUIET = 48
FW_HOLD_HOURS = 72
ORDER = {"tower_outage": 0, "tower_power_low": 0, "firmware_bad": 1}


def _sev_index(s: str) -> int:
    return SEVERITIES.index(s)


def _severity(inc: Incident) -> str:
    n, farms = len(inc.devices), len(inc.farms)
    if inc.type == "tower_outage":
        return "critical" if n >= 20 else "high"
    if inc.type == "tower_power_low":
        return "medium"
    if inc.type == "firmware_bad":
        return "critical" if n >= 100 or farms >= 3 else "high"
    base = _sev_index(TYPE_META[inc.type]["base"])
    if n >= 5 or farms >= 2:
        base += 1
    if inc.sources == {"anomaly"}:
        base -= 1  # unconfirmed by a rule: one level lower
    return SEVERITIES[max(0, min(base, 3))]


class IncidentBuilder:
    def __init__(self, fleet: Fleet):
        self.fleet = fleet
        self.incidents: list[Incident] = []
        self.open: dict[str, Incident] = {}
        self.member_of: dict[int, set[str]] = defaultdict(set)  # device -> open incident keys
        dev_fw = fleet.firmware
        changed = np.concatenate([np.zeros((fleet.n_devices, 1), bool), dev_fw[:, 1:] != dev_fw[:, :-1]], axis=1)
        self.last_fw_change = np.maximum.accumulate(np.where(changed, np.arange(fleet.hours)[None, :], -10_000), axis=1)
        self.dev_tower = fleet.device_tower
        self.dev_farm = fleet.device_farm

    # ---- helpers -----------------------------------------------------------------------------
    def _title(self, inc: Incident) -> str:
        f = self.fleet
        n = len(inc.devices)
        farm_names = sorted(f.farms[i].name for i in inc.farms)
        where = farm_names[0] if len(farm_names) == 1 else f"{len(farm_names)} farms"
        label = TYPE_META[inc.type]["label"]
        if inc.type in ("tower_outage", "tower_power_low"):
            tw = f.towers[next(iter(inc.towers))]
            farm = f.farms[tw.farm_idx].name
            if inc.type == "tower_power_low":
                return f"{tw.id} {tw.name} on {farm}: battery low, outage likely"
            return f"{tw.id} {tw.name} on {farm} offline: {n} collars silent"
        if inc.type == "firmware_bad":
            return f"Firmware {inc.version} regression: {n} collars on {len(inc.farms)} farms"
        return f"{label} on {where}: {n} collar{'s' if n != 1 else ''}"

    def _open_incident(self, key: str, ftype: str, hour: int) -> Incident:
        inc = Incident(
            id=f"INC-{len(self.incidents) + 1:04d}",
            type=ftype,
            key=key,
            title="",
            severity="low",
            opened_hour=hour,
            last_hour=hour,
        )
        self.incidents.append(inc)
        self.open[key] = inc
        return inc

    def _add(self, inc: Incident, f: Finding, devices: list[int]) -> None:
        inc.last_hour = f.hour
        inc.sources.add(f.source)
        inc.rules.add(f.rule)
        for d in devices:
            if d not in inc.devices:
                inc.devices[d] = f.hour
                inc.farms.add(int(self.dev_farm[d]))
                self.member_of[d].add(inc.key)
        if f.tower_idx is not None:
            inc.towers.add(f.tower_idx)
            inc.farms.add(self.fleet.towers[f.tower_idx].farm_idx)
        if len(inc.evidence) < 4 or f.rule not in {e["rule"] for e in inc.evidence}:
            inc.evidence.append({"hour": f.hour, "rule": f.rule, "source": f.source, "detail": f.detail})
            inc.evidence = inc.evidence[:8]
        self._refresh(inc, f.hour)

    def _refresh(self, inc: Incident, hour: int) -> None:
        new = _severity(inc)
        if not inc.notifications:
            inc.severity = new
            inc.title = self._title(inc)
            inc.notifications.append({"hour": hour, "kind": "opened", "severity": new, "title": inc.title})
        elif _sev_index(new) > _sev_index(inc.severity):
            inc.severity = new
            inc.title = self._title(inc)
            inc.notifications.append({"hour": hour, "kind": "escalated", "severity": new, "title": inc.title})
        else:
            inc.title = self._title(inc)

    def _absorb(self, inc: Incident, f: Finding, devices: list[int]) -> None:
        inc.absorbed += 1
        before = len(inc.devices)
        self._add(inc, f, devices)
        if len(inc.devices) == before:
            inc.evidence = inc.evidence[:8]

    def _resolve_quiet(self, hour: int) -> None:
        for key, inc in list(self.open.items()):
            quiet = QUIET_HOURS.get(key.split(":")[0], DEFAULT_QUIET)
            if hour - inc.last_hour > quiet:
                inc.resolved_hour = inc.last_hour + 1
                inc.notifications.append(
                    {"hour": hour, "kind": "resolved", "severity": inc.severity, "title": inc.title}
                )
                del self.open[key]
                for d in inc.devices:
                    self.member_of[d].discard(key)

    def _open_member(self, d: int, types: set[str]) -> Incident | None:
        for key in self.member_of.get(d, ()):
            inc = self.open.get(key)
            if inc is not None and inc.type in types:
                return inc
        return None

    # ---- main ------------------------------------------------------------------------------------
    def feed(self, findings: list[Finding]) -> list[Incident]:
        by_hour: dict[int, list[Finding]] = defaultdict(list)
        for f in findings:
            by_hour[f.hour].append(f)
        for hour in sorted(by_hour):
            self._resolve_quiet(hour)
            batch = sorted(by_hour[hour], key=lambda x: (ORDER.get(x.type, 2), x.source == "anomaly"))
            for f in batch:
                self._route(f)
        return self.incidents

    def _route(self, f: Finding) -> None:
        if f.type in ("tower_outage", "tower_power_low"):
            key = f"tower:{f.tower_idx}"
            inc = self.open.get(key) or self._open_incident(key, f.type, f.hour)
            if f.type == "tower_outage" and inc.type == "tower_power_low":
                inc.type = "tower_outage"  # the warning came true: same incident, now an outage
            if f.type == "tower_power_low" and inc.type == "tower_outage":
                return
            self._add(inc, f, f.devices())
            return
        if f.type == "firmware_bad":
            key = f"firmware:{f.version}"
            inc = self.open.get(key) or self._open_incident(key, f.type, f.hour)
            inc.version = f.version
            self._add(inc, f, f.devices())
            return

        d = f.device_idx
        assert d is not None
        tower_key = f"tower:{self.dev_tower[d]}"
        tower_inc = self.open.get(tower_key)
        if tower_inc is not None and tower_inc.type == "tower_outage" and f.type in ("device_offline", "anomaly"):
            self._absorb(tower_inc, f, [d])
            return
        fw_inc = self._open_member(d, {"firmware_bad"})
        if fw_inc is not None and f.type in ("battery_fade", "gps_drift", "anomaly") and f.feature != "hdop":
            self._absorb(fw_inc, f, [])
            return
        if f.source == "anomaly" and f.hour - self.last_fw_change[d, f.hour - 1] <= FW_HOLD_HOURS:
            return  # wait for the firmware cohort check
        if f.type == "device_offline":
            hw = self._open_member(d, {"water_ingress", "battery_fade", "gps_drift", "firmware_bad"})
            if hw is not None:
                self._absorb(hw, f, [d])
                return
        if f.source == "anomaly":
            existing = self._open_member(d, set(TYPE_META))
            if existing is not None:
                self._absorb(existing, f, [d])
                return
        key = f"{'anomaly' if f.type == 'anomaly' else f.type}:farm{self.dev_farm[d]}"
        inc = self.open.get(key) or self._open_incident(key, f.type, f.hour)
        self._add(inc, f, [d])


def build_incidents(fleet: Fleet, findings: list[Finding]) -> list[Incident]:
    return IncidentBuilder(fleet).feed(findings)
