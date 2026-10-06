"""Link a ticket to a farm, collars and towers in the fleet registry."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..sim.fleet import Fleet

COLLAR_RE = re.compile(r"\bC-?(\d{5})\b", re.I)
BARE_NUM_RE = re.compile(r"(?<![\w-])(\d{5})\b")


@dataclass
class Link:
    farm_idx: int | None
    device_idxs: list[int] = field(default_factory=list)
    tower_idxs: list[int] = field(default_factory=list)
    how: list[str] = field(default_factory=list)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", s.lower())


def link_ticket(fleet: Fleet, sender: str, text: str) -> Link:
    by_email = {fm.email.lower(): fm.idx for fm in fleet.farms}
    idx = fleet.device_index()
    how: list[str] = []
    farm = by_email.get(sender.lower())
    if farm is not None:
        how.append(f"sender {sender} is the contact for {fleet.farms[farm].id}")
    else:
        t = _norm(text)
        named = [fm.idx for fm in fleet.farms if _norm(fm.name) in t]
        if len(named) == 1:
            farm = named[0]
            how.append(f"farm named in the text: {fleet.farms[farm].name}")

    explicit = set(COLLAR_RE.findall(text))
    # a bare five-digit number counts only if it is a collar registered to the sender's farm
    bare = {
        n
        for n in BARE_NUM_RE.findall(text)
        if f"C-{n}" in idx and (farm is None or fleet.devices[idx[f"C-{n}"]].farm_idx == farm)
    }
    devices = sorted(idx[f"C-{n}"] for n in explicit | bare if f"C-{n}" in idx)
    if devices:
        how.append("collar ids in the text: " + ", ".join(fleet.devices[d].id for d in devices))
        owners = {fleet.devices[d].farm_idx for d in devices}
        if farm is None and len(owners) == 1:
            farm = owners.pop()
            how.append(f"farm taken from the collars: {fleet.farms[farm].id}")
        elif farm is not None:
            foreign = [d for d in devices if fleet.devices[d].farm_idx != farm]
            if foreign:
                how.append(
                    "ignored collars registered to another farm: " + ", ".join(fleet.devices[d].id for d in foreign)
                )
                devices = [d for d in devices if d not in foreign]

    towers: list[int] = []
    if farm is not None:
        low = text.lower()
        towers = [t.idx for t in fleet.towers if t.farm_idx == farm and t.name.lower() in low]
        if towers:
            how.append("tower named in the text: " + ", ".join(fleet.towers[t].id for t in towers))
    if farm is None:
        how.append("no farm found: needs a person to identify the customer")
    return Link(farm, devices, towers, how)
