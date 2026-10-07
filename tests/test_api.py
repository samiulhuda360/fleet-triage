from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fleet_triage.api.app import create_app
from fleet_triage.api.state import build_state


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    state = build_state(seed=7, triage_mode="rules", state_dir=tmp_path_factory.mktemp("state"))
    with TestClient(create_app(state)) as c:
        yield c


def test_overview(client):
    o = client.get("/api/overview").json()
    assert o["kpis"]["collars"] == 2000
    assert o["kpis"]["open_incidents"] > 0
    assert len(o["series"]["time"]) == 240
    assert len(o["farms"]) == 40


def test_overview_replays_an_earlier_hour(client):
    during_storm = client.get("/api/overview", params={"at": 320}).json()
    assert during_storm["kpis"]["towers_online"] < 60


def test_incident_list_and_detail(client):
    items = client.get("/api/incidents").json()
    fw = next(i for i in items if i["type"] == "firmware_bad")
    d = client.get(f"/api/incidents/{fw['id']}").json()
    assert d["kb_article"]["id"] == "KB-03"
    assert d["notifications"][0]["kind"] == "opened"
    assert d["series"]["reporting_pct"]
    assert client.get("/api/incidents/INC-9999").status_code == 404


def test_device_drilldown(client):
    picks = client.get("/api/devices").json()
    assert picks
    d = client.get(f"/api/devices/{picks[0]['id']}").json()
    assert len(d["series"]["battery"]) == 720
    assert d["incidents"]
    assert client.get("/api/devices/C-00000").status_code == 404


def test_triage_queue_and_decision_sends_nothing(client):
    q = client.get("/api/tickets").json()
    assert len(q) == 75 and all(t["status"] == "awaiting review" for t in q)
    t = client.get("/api/tickets/D-08").json()
    assert t["suggestion"]["article_id"] == "KB-02"
    r = client.post("/api/tickets/D-08/decision", json={"action": "approve", "draft": "Edited reply"}).json()
    assert r["sent"] is False and r["decision"]["draft"] == "Edited reply"
    assert client.get("/api/tickets/D-08").json()["status"] == "approve"
    assert client.post("/api/tickets/D-08/decision", json={"action": "send-now"}).status_code == 422


def test_mock_webhook_and_alert_formats(client):
    slack = client.get("/api/alerts", params={"format": "slack"}).json()
    assert slack and "blocks" in slack[0]
    client.post("/api/mock/webhook", json=slack[0])
    assert client.get("/api/mock/webhook").json()[-1] == slack[0]
