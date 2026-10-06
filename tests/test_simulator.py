from __future__ import annotations

import numpy as np

from fleet_triage.sim.fleet import Fleet
from fleet_triage.sim.simulator import simulate


def test_shape_and_registry(fleet):
    assert fleet.n_devices == 2000
    assert len(fleet.towers) == 60
    assert len(fleet.farms) == 40
    assert fleet.battery.shape == (2000, 720)
    assert all(f.email.endswith("@example.com") for f in fleet.farms)


def test_same_seed_same_fleet():
    a, b = simulate(11, hours=360), simulate(11, hours=360)
    assert np.array_equal(np.nan_to_num(a.battery), np.nan_to_num(b.battery))
    assert [e.event_id for e in a.events] == [e.event_id for e in b.events]


def test_ground_truth_covers_every_mode(fleet):
    types = {e.type for e in fleet.events}
    for t in ["battery_fade", "tower_outage", "firmware_bad", "water_ingress", "gps_drift", "noisy_healthy"]:
        assert t in types
    assert not next(e for e in fleet.events if e.type == "noisy_healthy").is_failure


def test_tower_outage_silences_its_collars(fleet):
    ev = next(e for e in fleet.events if e.type == "tower_outage")
    idx = fleet.device_index()
    rows = [idx[d] for d in ev.device_ids]
    assert not fleet.reported[rows, ev.start_hour : ev.end_hour].any()


def test_bad_firmware_lowers_gps_fix(fleet):
    ev = next(e for e in fleet.events if e.type == "firmware_bad")
    idx = fleet.device_index()
    d, s = idx[ev.device_ids[0]], ev.device_start_hours[0]
    before = np.nanmean(fleet.gps_fix[d, s - 48 : s])
    after = np.nanmean(fleet.gps_fix[d, s + 24 : s + 72])
    assert after < before - 0.1


def test_save_and_load_roundtrip(tmp_path):
    f = simulate(3, hours=360)
    f.save(tmp_path / "f.npz")
    g = Fleet.load(tmp_path / "f.npz")
    assert g.seed == 3 and g.hours == 360 and len(g.events) == len(f.events)
    assert np.allclose(np.nan_to_num(f.battery), np.nan_to_num(g.battery), atol=0.1)
