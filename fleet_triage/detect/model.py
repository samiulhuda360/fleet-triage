"""Shared types for detection: findings (one signal about a device or cohort) and incidents (what people see)."""

from __future__ import annotations

from dataclasses import dataclass, field

CHECK_EVERY = 3  # hours between detection runs
FIRST_CHECK = 24

# Failure modes that the knowledge base documents, plus operational types the detector can raise.
FAILURE_TYPES = ["tower_outage", "firmware_bad", "battery_fade", "water_ingress", "gps_drift"]
TYPE_META: dict[str, dict[str, str]] = {
    "tower_outage": {"label": "Tower outage", "kb": "KB-01", "base": "high"},
    "battery_fade": {"label": "Battery fade", "kb": "KB-02", "base": "medium"},
    "firmware_bad": {"label": "Firmware regression", "kb": "KB-03", "base": "high"},
    "water_ingress": {"label": "Water ingress", "kb": "KB-04", "base": "high"},
    "gps_drift": {"label": "GPS drift", "kb": "KB-05", "base": "medium"},
    "device_offline": {"label": "Collar offline", "kb": "KB-04", "base": "medium"},
    "tower_power_low": {"label": "Tower power low", "kb": "KB-01", "base": "medium"},
    "weak_signal": {"label": "Weak signal", "kb": "KB-06", "base": "low"},
    "anomaly": {"label": "Unexplained anomaly", "kb": "", "base": "low"},
}
SEVERITIES = ["low", "medium", "high", "critical"]


@dataclass
class Finding:
    hour: int
    type: str
    source: str  # threshold | rule | cohort | anomaly
    rule: str
    detail: str
    device_idx: int | None = None
    tower_idx: int | None = None
    device_idxs: list[int] | None = None  # cohort findings (a tower's silent collars, a firmware version)
    version: str | None = None
    value: float = 0.0
    feature: str | None = None

    def devices(self) -> list[int]:
        if self.device_idxs is not None:
            return self.device_idxs
        return [self.device_idx] if self.device_idx is not None else []


@dataclass
class Incident:
    id: str
    type: str
    key: str
    title: str
    severity: str
    opened_hour: int
    last_hour: int
    resolved_hour: int | None = None
    devices: dict[int, int] = field(default_factory=dict)  # device idx -> first hour it joined
    farms: set[int] = field(default_factory=set)
    towers: set[int] = field(default_factory=set)
    sources: set[str] = field(default_factory=set)
    rules: set[str] = field(default_factory=set)
    evidence: list[dict] = field(default_factory=list)  # first few findings, for people
    absorbed: int = 0  # findings merged in instead of raising their own alert
    notifications: list[dict] = field(default_factory=list)
    version: str | None = None

    @property
    def status(self) -> str:
        return "resolved" if self.resolved_hour is not None else "open"
