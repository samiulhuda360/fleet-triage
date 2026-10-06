"""Support tickets: load the written tickets and bind them to the simulated fleet.

Tickets are written in farmers' words with placeholders ({collar}, {farm}, {tower} ...). Binding picks the farm,
collars and time from the simulation's ground truth so each ticket is about something that really happened in the
data, and records the labels the triage is scored on: category, article, escalation, farm and collars.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ..sim.fleet import Fleet, GroundTruthEvent

TICKET_DIR = Path(__file__).resolve().parents[2] / "data" / "tickets"


@dataclass
class Ticket:
    id: str
    split: str  # dev | heldout
    sender: str
    subject: str
    body: str
    received_hour: int
    # labels (never shown to the triage)
    category: str
    article: str
    escalate: bool
    farm_id: str
    device_ids: list[str] = field(default_factory=list)
    related_event: str | None = None

    @property
    def text(self) -> str:
        return f"{self.subject}\n{self.body}"


def load_specs(split: str) -> list[dict]:
    return json.loads((TICKET_DIR / f"{split}.json").read_text(encoding="utf-8"))


def _events(fleet: Fleet, kind: str) -> list[GroundTruthEvent]:
    return sorted((e for e in fleet.events if e.type == kind), key=lambda e: (e.start_hour, e.event_id))


def bind(fleet: Fleet, spec: dict, split: str) -> Ticket:
    f = fleet
    idx = f.device_index()
    farm_by_id = {fm.id: fm for fm in f.farms}
    kind, pick, when = spec["bind"], int(spec["pick"]), int(spec["when"])
    failing = {d for e in f.events if e.is_failure for d in e.device_ids}
    noisy_ev = _events(f, "noisy_healthy")[0]
    storm_ev = _events(f, "storm")[0]
    event: GroundTruthEvent | None = None
    tower_name = ""
    n_affected = 0

    if kind == "tower_outage":
        evs = sorted(_events(f, kind), key=lambda e: -(e.end_hour - e.start_hour))  # longest outages first
        event = evs[pick % len(evs)]
        tower = next(t for t in f.towers if t.id == event.tower_id)
        farm = f.farms[tower.farm_idx]
        tower_name = tower.name
        devices = event.device_ids
        n_affected = len(devices)
        dur = (event.end_hour or f.hours) - event.start_hour
        hour = event.start_hour + min(when, max(dur - 1, 1))
    elif kind == "firmware_bad":
        event = _events(f, kind)[0]
        farms = sorted(event.farm_ids)
        farm = farm_by_id[farms[pick % len(farms)]]
        on_farm = [
            (s, d)
            for d, s in zip(event.device_ids, event.device_start_hours, strict=True)
            if f.devices[idx[d]].farm_idx == farm.idx
        ]
        devices = [d for _, d in sorted(on_farm)]
        n_affected = len(devices)
        hour = min(s for s, _ in on_farm) + when
    elif kind in ("battery_fade", "water_ingress", "gps_drift"):
        evs = _events(f, kind)
        event = evs[pick % len(evs)]
        devices = event.device_ids
        farm = farm_by_id[event.farm_ids[0]]
        n_affected = 1
        base = event.end_hour if kind == "water_ingress" and event.end_hour else event.start_hour
        hour = base + when
    elif kind == "noisy":
        event = noisy_ev
        farm = farm_by_id[noisy_ev.farm_ids[0]]
        devices = noisy_ev.device_ids[pick * 3 :] + noisy_ev.device_ids[: pick * 3]
        hour = when
    elif kind == "storm":
        event = storm_ev
        # farms with their own fault would make the root cause ambiguous, so weather tickets avoid them
        faulty = {fid for e in f.events if e.type in ("tower_outage", "firmware_bad") for fid in e.farm_ids}
        candidates = [fid for fid in sorted(storm_ev.farm_ids) if fid not in faulty] or sorted(storm_ev.farm_ids)
        farm = farm_by_id[candidates[pick % len(candidates)]]
        devices = [d.id for d in f.devices if d.farm_idx == farm.idx and d.id not in failing]
        hour = storm_ev.start_hour + when
    elif kind == "healthy":
        busy = {fid for e in f.events if e.type != "firmware_decoy" for fid in e.farm_ids}
        healthy = [fm for fm in f.farms if fm.id not in busy]
        farm = healthy[pick % len(healthy)]
        devices = [d.id for d in f.devices if d.farm_idx == farm.idx and d.id not in failing]
        hour = when
    else:
        raise ValueError(f"unknown binding {kind}")

    hour = max(0, min(int(hour), f.hours - 1))
    if not tower_name:
        tower_name = next(t.name for t in f.towers if t.farm_idx == farm.idx)
    first = farm.farmer.split()[0]
    collars = list(devices[:3]) + [""] * 3
    values = {
        "collar": collars[0],
        "collar2": collars[1],
        "collar3": collars[2],
        "num": collars[0].removeprefix("C-"),
        "num2": collars[1].removeprefix("C-"),
        "farm": farm.name,
        "tower": tower_name,
        "n": n_affected,
        "first": first,
    }
    raw = spec["subject"] + "\n" + spec["body"]
    mentioned = [
        values[k]
        for k in ("collar", "collar2", "collar3")
        if values[k] and ("{" + k + "}" in raw or (k == "collar" and "{num}" in raw))
    ]
    if "{num2}" in raw and values["collar2"] and values["collar2"] not in mentioned:
        mentioned.append(values["collar2"])
    sender = farm.email if spec.get("sender", "farmer") == "farmer" else f"{first.lower()}.home@example.com"
    return Ticket(
        id=spec["id"],
        split=split,
        sender=sender,
        subject=spec["subject"].format(**values),
        body=spec["body"].format(**values),
        received_hour=hour,
        category=spec["category"],
        article=spec["article"],
        escalate=bool(spec["escalate"]),
        farm_id=farm.id,
        device_ids=sorted(set(mentioned)),
        related_event=event.event_id if event else None,
    )


def load_tickets(fleet: Fleet, splits: tuple[str, ...] = ("dev", "heldout")) -> list[Ticket]:
    return [bind(fleet, spec, split) for split in splits for spec in load_specs(split)]
