"""Seeded simulator for a fleet of GPS livestock collars and solar base towers.

It produces hourly telemetry for about 30 days and plants failure modes with ground truth:

* ``battery_fade``   cell degradation: capacity falls and self-discharge rises, so night drain climbs.
* ``tower_outage``   a tower stops sending heartbeats and every collar on it loses uplink. Storms flatten
                     towers with weak batteries; one tower also gets a sudden backhaul fault.
* ``firmware_bad``   a staged rollout of version 3.5.0 raises battery drain and drops GPS fixes.
* ``water_ingress``  the enclosure takes on water: temperature and signal go wrong, then the collar dies.
* ``gps_drift``      a GPS module degrades: HDOP climbs and fixes slowly get worse.
* ``noisy_healthy``  a hill farm with poor coverage and noisy readings that is *not* failing. It exists to
                     measure false positives.

The weather also produces a storm across one region (low solar charge, colder, rain fade on signal), which
is a shared effect the detectors must not mistake for device faults. A harmless firmware rollout (3.4.2)
is a decoy for the firmware cohort check.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np

from .fleet import Device, Farm, Fleet, GroundTruthEvent, Tower
from .names import (
    FARM_FIRST,
    FARM_SECOND,
    FIRMWARE_BAD,
    FIRMWARE_DECOY,
    FIRMWARE_LEGACY,
    FIRMWARE_STABLE,
    FIRMWARE_VERSIONS,
    FIRST_NAMES,
    LAST_NAMES,
    REGIONS,
    TOWER_SPOTS,
)

START = datetime(2026, 7, 6, 0, 0)
HOURS = 720
N_FARMS = 40
N_TOWERS = 60
N_DEVICES = 2000

# Battery physics (percent per hour). A healthy collar drains ~0.28 %/h and a clear day charges ~10 %.
BASE_DRAIN = 0.28
CHARGE_PER_MA = 0.0125
PANEL_MA = 120.0
FW_BAD_DRAIN = 1.7
FW_BAD_GPS = 0.17


def _sunshine(hours: np.ndarray) -> np.ndarray:
    hod = (hours % 24) + 0.5
    s = np.sin(np.pi * (hod - 7.0) / 10.5)
    return np.where((hod > 7.0) & (hod < 17.5), np.clip(s, 0, None), 0.0)


def simulate(seed: int = 7, hours: int = HOURS) -> Fleet:
    rng = np.random.default_rng(seed)
    t_axis = np.arange(hours)
    days = hours // 24
    hod = t_axis % 24
    sun = _sunshine(t_axis)

    # ---- registry ----------------------------------------------------------------------------
    first = rng.permutation(FARM_FIRST)[:N_FARMS]
    farms: list[Farm] = []
    for i in range(N_FARMS):
        region = REGIONS[i % len(REGIONS)]
        terrain = rng.choice(["flat", "rolling", "hill"], p=[0.35, 0.4, 0.25])
        fn, ln = FIRST_NAMES[i], LAST_NAMES[(i * 7 + seed) % len(LAST_NAMES)]
        farms.append(
            Farm(
                idx=i,
                id=f"F-{i + 1:02d}",
                name=f"{first[i]} {FARM_SECOND[int(rng.integers(len(FARM_SECOND)))]}",
                region=region,
                terrain=str(terrain),
                farmer=f"{fn} {ln}",
                email=f"{fn.lower()}.{ln.lower()}@example.com",
            )
        )

    tower_farm = list(range(N_FARMS)) + sorted(rng.choice(N_FARMS, N_TOWERS - N_FARMS, replace=False).tolist())
    tower_farm.sort()
    towers: list[Tower] = []
    spot_count: dict[int, int] = {}
    for j, f in enumerate(tower_farm):
        k = spot_count.get(f, 0)
        spot_count[f] = k + 1
        spot = TOWER_SPOTS[(k + f) % len(TOWER_SPOTS)]
        towers.append(Tower(idx=j, id=f"T-{j + 1:02d}", name=f"{spot} tower", farm_idx=f))
    farm_towers = {f: [t.idx for t in towers if t.farm_idx == f] for f in range(N_FARMS)}

    weights = rng.uniform(0.4, 1.6, N_FARMS)
    herd = np.floor(weights / weights.sum() * N_DEVICES).astype(int)
    herd[: N_DEVICES - herd.sum()] += 1
    devices: list[Device] = []
    for f in range(N_FARMS):
        for _ in range(herd[f]):
            tw = int(rng.choice(farm_towers[f]))
            i = len(devices)
            devices.append(Device(idx=i, id=f"C-{10001 + i}", farm_idx=f, tower_idx=tw))
    n = len(devices)
    m = len(towers)
    dev_farm = np.array([d.farm_idx for d in devices])
    dev_tower = np.array([d.tower_idx for d in devices])
    farm_region = np.array([REGIONS.index(f.region) for f in farms])
    farm_terrain = np.array([f.terrain for f in farms])

    # ---- weather -----------------------------------------------------------------------------
    region_cloud = np.clip(0.75 + 0.18 * rng.standard_normal((len(REGIONS), days)), 0.2, 1.0)
    storm_region = int(rng.integers(len(REGIONS)))
    storm_day = int(rng.integers(8, 12))
    storm_days = [storm_day, storm_day + 1, storm_day + 2]
    region_cloud[storm_region, storm_days] = rng.uniform(0.06, 0.16, 3)
    farm_cloud = np.clip(region_cloud[farm_region] + 0.06 * rng.standard_normal((N_FARMS, days)), 0.04, 1.0).astype(
        np.float32
    )
    storm_hours = np.zeros(hours, dtype=bool)
    storm_hours[storm_day * 24 : (storm_day + 3) * 24] = True

    region_temp_offset = 2.0 * rng.standard_normal((len(REGIONS), days))
    region_temp_offset[storm_region, storm_days] -= 3.0
    farm_temp_bias = rng.standard_normal(N_FARMS)
    diurnal = 4.0 * np.sin(2 * np.pi * (hod - 9) / 24)
    # ambient per farm-hour
    ambient = 9.0 + diurnal[None, :] + region_temp_offset[farm_region][:, t_axis // 24] + farm_temp_bias[:, None]
    farm_storm = (farm_region == storm_region)[:, None] & storm_hours[None, :]

    # ---- per-device parameters ---------------------------------------------------------------
    eff = np.clip(1 + 0.08 * rng.standard_normal(n), 0.75, 1.25)
    drain = np.clip(BASE_DRAIN * (1 + 0.08 * rng.standard_normal(n)), 0.2, 0.36)
    hill = farm_terrain[dev_farm] == "hill"
    sig0 = np.where(hill, rng.uniform(-104, -88, n), rng.uniform(-98, -76, n))
    sig_sd = np.full(n, 2.2)
    temp_sd = np.full(n, 0.9)
    fix0 = np.clip(0.96 + 0.015 * rng.standard_normal(n), 0.9, 0.995)
    fix_sd = np.full(n, 0.02)
    hdop0 = np.clip(1.2 + 0.18 * rng.standard_normal(n), 0.8, 1.7)
    hdop_sd = np.full(n, 0.12)
    battery0 = rng.uniform(65, 98, n)

    # ---- choose where failures go (disjoint device pools) ------------------------------------
    events: list[GroundTruthEvent] = []
    hill_farms = [f for f in range(N_FARMS) if farm_terrain[f] == "hill"]
    noisy_farm = int(rng.choice(hill_farms)) if hill_farms else 0

    storm_farm_towers = [t.idx for t in towers if farm_region[t.farm_idx] == storm_region]
    storm_farm_towers = [t for t in storm_farm_towers if towers[t].farm_idx != noisy_farm]
    weak_tower = int(rng.choice(storm_farm_towers))
    other_towers = [t.idx for t in towers if farm_region[t.farm_idx] != storm_region and t.farm_idx != noisy_farm]
    fault_tower = int(rng.choice(other_towers))
    fault_start = int(rng.integers(380, 560))
    fault_len = int(rng.integers(10, 20))

    excluded_farms = {noisy_farm, towers[weak_tower].farm_idx, towers[fault_tower].farm_idx}
    candidate_farms = [f for f in range(N_FARMS) if f not in excluded_farms]
    fw_farms = sorted(rng.choice(candidate_farms, 6, replace=False).tolist())
    decoy_pool = [f for f in candidate_farms if f not in fw_farms]
    decoy_farms = sorted(rng.choice(decoy_pool, 8, replace=False).tolist())
    clean_farms = [f for f in candidate_farms if f not in fw_farms]
    pool = rng.permutation([d.idx for d in devices if d.farm_idx in clean_farms])
    fade_dev = np.sort(pool[:25])
    ingress_dev = np.sort(pool[25:37])
    drift_dev = np.sort(pool[37:52])

    # firmware timeline (per device code, as an index into FIRMWARE_VERSIONS)
    fw_code = np.full((n, hours), FIRMWARE_VERSIONS.index(FIRMWARE_STABLE), dtype=np.uint8)
    legacy = rng.random(n) < 0.15
    fw_code[legacy] = FIRMWARE_VERSIONS.index(FIRMWARE_LEGACY)
    decoy_start = int(rng.integers(150, 220))
    for d in np.where(np.isin(dev_farm, decoy_farms))[0]:
        h = decoy_start + int(rng.integers(0, 18))
        fw_code[d, h:] = FIRMWARE_VERSIONS.index(FIRMWARE_DECOY)
    rollout = int(rng.integers(260, 330))
    fw_update = np.full(n, -1)
    for d in np.where(np.isin(dev_farm, fw_farms))[0]:
        h = rollout + int(rng.integers(0, 18))
        fw_update[d] = h
        fw_code[d, h:] = FIRMWARE_VERSIONS.index(FIRMWARE_BAD)

    # noisy-but-healthy farm
    noisy = dev_farm == noisy_farm
    sig0[noisy] = rng.uniform(-107, -100, noisy.sum())
    sig_sd[noisy] = 6.0
    temp_sd[noisy] = 2.2
    fix_sd[noisy] = 0.05
    hdop_sd[noisy] = 0.35

    # failure schedules
    fade_start = {int(d): int(rng.integers(72, 450)) for d in fade_dev}
    fade_len = {int(d): int(rng.integers(8, 14)) * 24 for d in fade_dev}
    ingress_start = {int(d): int(rng.integers(96, 600)) for d in ingress_dev}
    ingress_len = {int(d): int(rng.integers(24, 60)) for d in ingress_dev}
    drift_start = {int(d): int(rng.integers(96, 520)) for d in drift_dev}
    drift_len = {int(d): int(rng.integers(5, 9)) * 24 for d in drift_dev}

    capacity = np.ones((n, hours))
    drain_mult = np.ones((n, hours))
    for d in fade_dev:
        s, ln = fade_start[int(d)], fade_len[int(d)]
        frac = np.clip((t_axis - s) / ln, 0, None)
        capacity[d] = np.clip(1 - 0.92 * np.minimum(frac, 1.2) ** 1.5, 0.08, 1)
        drain_mult[d] = 1 + 1.5 * np.minimum(frac, 1.0)
    bad_fw = fw_code == FIRMWARE_VERSIONS.index(FIRMWARE_BAD)
    drain_mult = np.where(bad_fw, drain_mult * FW_BAD_DRAIN, drain_mult)

    temp_add = np.zeros((n, hours))
    sig_add = np.zeros((n, hours))
    dead_from = np.full(n, hours + 1)
    for d in ingress_dev:
        s, ln = ingress_start[int(d)], ingress_len[int(d)]
        span = np.arange(s, min(s + ln, hours))
        frac = (span - s) / ln
        temp_add[d, span] = 2 + 8 * frac + (rng.random(len(span)) < 0.2) * rng.uniform(4, 9, len(span))
        sig_add[d, span] = -(6 + 8 * frac)
        dead_from[d] = s + ln
    hdop_add = np.zeros((n, hours))
    fix_drop = np.zeros((n, hours))
    for d in drift_dev:
        s, ln = drift_start[int(d)], drift_len[int(d)]
        frac = np.clip((t_axis - s) / ln, 0, 1)
        hdop_add[d] = 5.0 * frac
        fix_drop[d] = 0.12 * frac
    fix_drop += np.where(bad_fw, FW_BAD_GPS, 0.0)

    # ---- towers ------------------------------------------------------------------------------
    tower_cap = np.clip(1 + 0.1 * rng.standard_normal(m), 0.8, 1.2)
    tower_cap[weak_tower] = 0.42
    tower_drain = 1.1
    tower_batt = np.zeros((m, hours))
    tower_solar = np.zeros((m, hours))
    tower_online = np.ones((m, hours), dtype=np.uint8)
    tb = rng.uniform(85, 100, m)
    t_farm = np.array([t.farm_idx for t in towers])
    t_up = np.ones(m, dtype=bool)
    for h in range(hours):
        cloud = farm_cloud[t_farm, h // 24] * np.clip(1 + 0.1 * rng.standard_normal(m), 0.5, 1.5)
        watts = 120 * sun[h] * cloud
        tb = np.clip(tb + (0.065 * watts - tower_drain) / tower_cap, 0, 100)
        # a tower browns out at 0 % and restarts once the battery is back above 20 %
        t_up = np.where(t_up, tb > 0.5, tb > 20)
        tower_batt[:, h] = tb
        tower_solar[:, h] = watts
        tower_online[:, h] = t_up
    tower_online[fault_tower, fault_start : fault_start + fault_len] = 0

    # ---- collars -----------------------------------------------------------------------------
    out = {
        k: np.full((n, hours), np.nan, dtype=np.float32)
        for k in ["battery", "solar_ma", "signal_dbm", "temp_c", "gps_fix", "hdop"]
    }
    uplink = np.zeros((n, hours), dtype=np.float32)
    batt = battery0.copy()
    powered = np.ones(n, dtype=bool)
    for h in range(hours):
        day = h // 24
        cloud = farm_cloud[dev_farm, day] * np.clip(1 + 0.1 * rng.standard_normal(n), 0.5, 1.5)
        solar = np.clip(PANEL_MA * eff * sun[h] * cloud * (1 + 0.05 * rng.standard_normal(n)), 0, None)
        dbatt = (CHARGE_PER_MA * solar - drain * drain_mult[:, h]) / capacity[:, h]
        batt = np.clip(batt + dbatt, 0, 100)
        powered = np.where(powered, batt > 0.5, batt > 5)
        alive = powered & (h < dead_from)

        rain_fade = np.where(farm_storm[dev_farm, h], -3.0, 0.0)
        signal = sig0 + rain_fade + sig_add[:, h] + sig_sd * rng.standard_normal(n)
        temp = ambient[dev_farm, h] + 6.0 + temp_add[:, h] + temp_sd * rng.standard_normal(n)
        fix = np.clip(fix0 - fix_drop[:, h] + fix_sd * rng.standard_normal(n), 0, 1)
        hd = hdop0 + hdop_add[:, h] + np.abs(hdop_sd * rng.standard_normal(n))

        p_up = 1 / (1 + np.exp(-(signal + 111) / 2.5))
        attempts = rng.binomial(4, np.clip(p_up, 0, 1))
        attempts = np.where(alive & (tower_online[dev_tower, h] == 1), attempts, 0)
        ok = attempts > 0
        uplink[:, h] = attempts / 4
        # the fuel gauge reading carries a little measurement noise
        reading = np.clip(batt + 0.25 * rng.standard_normal(n), 0, 100)
        out["battery"][ok, h] = np.round(reading[ok], 1)
        out["solar_ma"][ok, h] = solar[ok]
        out["signal_dbm"][ok, h] = signal[ok]
        out["temp_c"][ok, h] = temp[ok]
        out["gps_fix"][ok, h] = fix[ok]
        out["hdop"][ok, h] = hd[ok]

    tower_batt_obs = np.where(tower_online == 1, tower_batt, np.nan).astype(np.float32)
    tower_solar_obs = np.where(tower_online == 1, tower_solar, np.nan).astype(np.float32)

    # ---- ground truth ------------------------------------------------------------------------
    def dev_ids(idx) -> list[str]:
        return [devices[int(i)].id for i in idx]

    def farm_ids(idx) -> list[str]:
        return sorted({farms[int(dev_farm[i])].id for i in idx})

    for tw in range(m):
        down = tower_online[tw] == 0
        if not down.any():
            continue
        edges = np.diff(np.concatenate([[0], down.astype(int), [0]]))
        starts, ends = np.where(edges == 1)[0], np.where(edges == -1)[0]
        on_tower = np.where(dev_tower == tw)[0]
        for s, e in zip(starts.tolist(), ends.tolist(), strict=True):
            backhaul = tw == fault_tower and s == fault_start
            note = (
                "Backhaul radio fault; tower heartbeat lost with a healthy battery."
                if backhaul
                else "Tower battery ran flat after days of low sun; it restarts once the panel recharges it."
            )
            events.append(
                GroundTruthEvent(
                    event_id=f"GT-TOWER-{towers[tw].id}-{s}",
                    type="tower_outage",
                    is_failure=True,
                    start_hour=s,
                    end_hour=e,
                    device_ids=dev_ids(on_tower),
                    device_start_hours=[s] * len(on_tower),
                    farm_ids=[farms[towers[tw].farm_idx].id],
                    tower_id=towers[tw].id,
                    note=note,
                )
            )
    fw_devs = np.where(fw_update >= 0)[0]
    events.append(
        GroundTruthEvent(
            event_id=f"GT-FW-{FIRMWARE_BAD}",
            type="firmware_bad",
            is_failure=True,
            start_hour=int(fw_update[fw_devs].min()),
            end_hour=None,
            device_ids=dev_ids(fw_devs),
            device_start_hours=[int(fw_update[d]) for d in fw_devs],
            farm_ids=farm_ids(fw_devs),
            note=f"Version {FIRMWARE_BAD}: battery drain x{FW_BAD_DRAIN}, GPS fix rate -{FW_BAD_GPS}.",
        )
    )
    for d in fade_dev:
        events.append(_single("battery_fade", devices[int(d)], farms, fade_start[int(d)], None))
    for d in ingress_dev:
        s = ingress_start[int(d)]
        events.append(_single("water_ingress", devices[int(d)], farms, s, s + ingress_len[int(d)]))
    for d in drift_dev:
        events.append(_single("gps_drift", devices[int(d)], farms, drift_start[int(d)], None))
    noisy_idx = np.where(noisy)[0]
    events.append(
        GroundTruthEvent(
            event_id=f"GT-NOISY-{farms[noisy_farm].id}",
            type="noisy_healthy",
            is_failure=False,
            start_hour=0,
            end_hour=None,
            device_ids=dev_ids(noisy_idx),
            device_start_hours=[0] * len(noisy_idx),
            farm_ids=[farms[noisy_farm].id],
            note="Hill farm with weak, noisy coverage. Healthy collars; any alert here is a false positive.",
        )
    )
    events.append(
        GroundTruthEvent(
            event_id="GT-STORM",
            type="storm",
            is_failure=False,
            start_hour=storm_day * 24,
            end_hour=(storm_day + 3) * 24,
            device_ids=[],
            device_start_hours=[],
            farm_ids=[f.id for f in farms if farm_region[f.idx] == storm_region],
            note=f"Three days of heavy cloud and rain over {REGIONS[storm_region]}. Shared weather, not a fault.",
        )
    )
    events.append(
        GroundTruthEvent(
            event_id=f"GT-FW-{FIRMWARE_DECOY}",
            type="firmware_decoy",
            is_failure=False,
            start_hour=decoy_start,
            end_hour=None,
            device_ids=[],
            device_start_hours=[],
            farm_ids=[farms[f].id for f in decoy_farms],
            note=f"Harmless rollout of {FIRMWARE_DECOY}; the firmware check must not flag it.",
        )
    )

    return Fleet(
        seed=seed,
        start=START,
        hours=hours,
        farms=farms,
        towers=towers,
        devices=devices,
        firmware_versions=list(FIRMWARE_VERSIONS),
        battery=out["battery"],
        solar_ma=out["solar_ma"],
        signal_dbm=out["signal_dbm"],
        temp_c=out["temp_c"],
        gps_fix=out["gps_fix"],
        hdop=out["hdop"],
        uplink=uplink,
        firmware=fw_code,
        tower_battery=tower_batt_obs,
        tower_solar_w=tower_solar_obs,
        tower_online=tower_online,
        farm_cloud=farm_cloud,
        events=events,
    )


def _single(kind: str, dev: Device, farms: list[Farm], start: int, end: int | None) -> GroundTruthEvent:
    return GroundTruthEvent(
        event_id=f"GT-{kind.upper()}-{dev.id}",
        type=kind,
        is_failure=True,
        start_hour=start,
        end_hour=end,
        device_ids=[dev.id],
        device_start_hours=[start],
        farm_ids=[farms[dev.farm_idx].id],
    )
