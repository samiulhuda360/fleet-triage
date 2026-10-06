"""Run a detection method over a fleet replay and return findings, incidents and the alerts that would page."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ..sim.fleet import Fleet
from .anomaly import run_anomaly
from .baseline import baseline_alerts, run_baseline
from .features import FleetFeatures
from .incidents import build_incidents
from .model import Finding, Incident

Method = Literal["threshold", "rules", "rules+anomaly"]
METHODS: list[Method] = ["threshold", "rules", "rules+anomaly"]


@dataclass
class DetectionResult:
    method: Method
    findings: list[Finding]
    incidents: list[Incident] = field(default_factory=list)
    alerts: int = 0  # notifications that would reach a person (opened + escalated)

    def device_flags(self) -> dict[int, list[tuple[int, str]]]:
        """Device idx -> [(hour, type)] for every time the method said this collar has a problem."""
        flags: dict[int, list[tuple[int, str]]] = {}
        if self.method == "threshold":
            for f in self.findings:
                if f.type in ("tower_power_low", "weak_signal") and f.device_idx is None:
                    continue
                for d in f.devices():
                    flags.setdefault(d, []).append((f.hour, f.type))
            return flags
        for inc in self.incidents:
            if inc.type == "tower_power_low":
                continue
            for d, h in inc.devices.items():
                flags.setdefault(d, []).append((h, inc.type))
        return flags


def detect(fleet: Fleet, method: Method = "rules+anomaly", feats: FleetFeatures | None = None) -> DetectionResult:
    from .rules import run_rules

    feats = feats or FleetFeatures(fleet)
    if method == "threshold":
        findings = run_baseline(fleet, feats)
        alerts = baseline_alerts(findings)
        return DetectionResult(method, findings, alerts=len(alerts))
    findings = run_rules(fleet, feats)
    if method == "rules+anomaly":
        findings += run_anomaly(fleet, feats, seed=fleet.seed)
    incidents = build_incidents(fleet, findings)
    alerts = sum(1 for i in incidents for n in i.notifications if n["kind"] in ("opened", "escalated"))
    return DetectionResult(method, findings, incidents, alerts)
