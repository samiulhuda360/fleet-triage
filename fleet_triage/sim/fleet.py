"""The fleet data model: registry (farms, towers, collars), hourly telemetry arrays and ground truth."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

DEVICE_METRICS = ["battery", "solar_ma", "signal_dbm", "temp_c", "gps_fix", "hdop", "uplink"]
TOWER_METRICS = ["tower_battery", "tower_solar_w", "tower_online"]


@dataclass(frozen=True)
class Farm:
    idx: int
    id: str
    name: str
    region: str
    terrain: str  # flat | rolling | hill
    farmer: str
    email: str


@dataclass(frozen=True)
class Tower:
    idx: int
    id: str
    name: str
    farm_idx: int


@dataclass(frozen=True)
class Device:
    idx: int
    id: str
    farm_idx: int
    tower_idx: int


@dataclass
class GroundTruthEvent:
    """A planted failure (or the planted noisy-but-healthy group, which is not a failure)."""

    event_id: str
    type: str
    is_failure: bool
    start_hour: int
    end_hour: int | None
    device_ids: list[str]
    device_start_hours: list[int]
    farm_ids: list[str]
    tower_id: str | None = None
    note: str = ""


@dataclass
class Fleet:
    seed: int
    start: datetime
    hours: int
    farms: list[Farm]
    towers: list[Tower]
    devices: list[Device]
    firmware_versions: list[str]
    # (N, T) float32, NaN when the collar sent nothing that hour; uplink is 0..1 and never NaN
    battery: np.ndarray
    solar_ma: np.ndarray
    signal_dbm: np.ndarray
    temp_c: np.ndarray
    gps_fix: np.ndarray
    hdop: np.ndarray
    uplink: np.ndarray
    firmware: np.ndarray  # (N, T) uint8 index into firmware_versions
    # (M, T): battery and solar are NaN without a heartbeat; online is 1 when the heartbeat arrived
    tower_battery: np.ndarray
    tower_solar_w: np.ndarray
    tower_online: np.ndarray
    farm_cloud: np.ndarray  # (F, days) daily sunshine factor from the weather feed, 1 = clear sky
    events: list[GroundTruthEvent] = field(default_factory=list)

    # ---- convenience -------------------------------------------------------------------------
    @property
    def n_devices(self) -> int:
        return len(self.devices)

    @property
    def device_farm(self) -> np.ndarray:
        return np.array([d.farm_idx for d in self.devices], dtype=np.int16)

    @property
    def device_tower(self) -> np.ndarray:
        return np.array([d.tower_idx for d in self.devices], dtype=np.int16)

    @property
    def reported(self) -> np.ndarray:
        return ~np.isnan(self.battery)

    def hour_to_time(self, hour: int) -> datetime:
        return self.start + timedelta(hours=int(hour))

    def device_index(self) -> dict[str, int]:
        return {d.id: d.idx for d in self.devices}

    def metric(self, name: str) -> np.ndarray:
        return getattr(self, name)

    # ---- persistence -------------------------------------------------------------------------
    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        meta = {
            "seed": self.seed,
            "start": self.start.isoformat(),
            "hours": self.hours,
            "farms": [asdict(f) for f in self.farms],
            "towers": [asdict(t) for t in self.towers],
            "devices": [asdict(d) for d in self.devices],
            "firmware_versions": self.firmware_versions,
            "events": [asdict(e) for e in self.events],
        }
        arrays = {name: getattr(self, name) for name in [*DEVICE_METRICS, *TOWER_METRICS]}
        np.savez_compressed(
            path,
            meta=np.array(json.dumps(meta)),
            firmware=self.firmware,
            farm_cloud=self.farm_cloud,
            **{k: v.astype(np.float16) if k != "tower_online" else v for k, v in arrays.items()},
        )

    @classmethod
    def load(cls, path: Path) -> Fleet:
        with np.load(path) as z:
            meta = json.loads(str(z["meta"]))
            arrays = {k: z[k] for k in z.files if k != "meta"}
        for k in [*DEVICE_METRICS, "tower_battery", "tower_solar_w"]:
            arrays[k] = arrays[k].astype(np.float32)
        return cls(
            seed=meta["seed"],
            start=datetime.fromisoformat(meta["start"]),
            hours=meta["hours"],
            farms=[Farm(**f) for f in meta["farms"]],
            towers=[Tower(**t) for t in meta["towers"]],
            devices=[Device(**d) for d in meta["devices"]],
            firmware_versions=meta["firmware_versions"],
            events=[GroundTruthEvent(**e) for e in meta["events"]],
            **arrays,
        )
