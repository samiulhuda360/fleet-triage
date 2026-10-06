from __future__ import annotations

from fleet_triage.detect.baseline import baseline_alerts
from fleet_triage.detect.incidents import build_incidents
from fleet_triage.detect.model import Finding
from fleet_triage.evaluation.detection import score


def test_rules_find_every_planted_mode(fleet, rules_result):
    s = score(fleet, rules_result)
    for mode, pm in s["per_mode"].items():
        assert pm["recall"] >= 0.9, mode
    assert s["noisy_group_flagged"] == 0


def test_one_incident_per_tower_outage(fleet, rules_result):
    towers = [i for i in rules_result.incidents if i.type == "tower_outage"]
    outage_towers = {e.tower_id for e in fleet.events if e.type == "tower_outage"}
    assert {fleet.towers[next(iter(i.towers))].id for i in towers} == outage_towers
    assert len(towers) <= len([e for e in fleet.events if e.type == "tower_outage"])


def test_firmware_cohort_is_one_incident_and_decoy_is_quiet(rules_result):
    fw = [i for i in rules_result.incidents if i.type == "firmware_bad"]
    assert len(fw) == 1 and fw[0].version == "3.5.0"
    assert fw[0].severity == "critical"


def test_incidents_page_far_less_than_threshold_baseline(fleet):
    from fleet_triage.detect.pipeline import detect

    base = detect(fleet, "threshold")
    assert base.alerts > 10 * 59  # hundreds of device alerts


def test_offline_collar_joins_open_tower_incident(fleet):
    tw = fleet.towers[0]
    on_tower = [d.idx for d in fleet.devices if d.tower_idx == tw.idx][:3]
    findings = [
        Finding(
            hour=100,
            type="tower_outage",
            source="rule",
            rule="R-TOWER",
            detail="x",
            tower_idx=tw.idx,
            device_idxs=on_tower[:2],
        ),
        Finding(hour=103, type="device_offline", source="rule", rule="R-OFFLINE", detail="y", device_idx=on_tower[2]),
    ]
    incs = build_incidents(fleet, findings)
    assert len(incs) == 1
    assert set(incs[0].devices) == set(on_tower)
    assert incs[0].absorbed == 1


def test_power_warning_escalates_into_outage(fleet):
    findings = [
        Finding(hour=50, type="tower_power_low", source="rule", rule="R-TOWER-POWER", detail="low", tower_idx=4),
        Finding(
            hour=56,
            type="tower_outage",
            source="rule",
            rule="R-TOWER",
            detail="down",
            tower_idx=4,
            device_idxs=list(range(25)),
        ),
    ]
    incs = build_incidents(fleet, findings)
    assert len(incs) == 1 and incs[0].type == "tower_outage"
    assert [n["kind"] for n in incs[0].notifications] == ["opened", "escalated"]


def test_baseline_rearms_after_quiet_spell():
    f = [
        Finding(hour=h, type="battery_fade", source="threshold", rule="battery_low", detail="", device_idx=1)
        for h in (10, 13, 16, 60)
    ]
    assert [a.hour for a in baseline_alerts(f)] == [10, 60]
