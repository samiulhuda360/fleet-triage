from __future__ import annotations

import httpx

from fleet_triage.alerts.notify import WebhookNotifier, format_slack, format_telegram, notifications


def test_notifications_are_time_ordered(fleet, rules_result):
    ps = notifications(fleet, rules_result.incidents)
    assert ps and [p["at"] for p in ps] == sorted(p["at"] for p in ps)
    assert all(p["event"].startswith("incident.") for p in ps)


def test_formats(fleet, rules_result):
    p = notifications(fleet, rules_result.incidents)[0]
    assert "blocks" in format_slack(p)
    assert p["title"] in format_telegram(p)["text"]


def test_webhook_dedup_and_retry(fleet, rules_result, tmp_path):
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        return httpx.Response(503 if len(calls) == 1 else 200)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    n = WebhookNotifier("http://hook.test/in", "slack", client=client, ledger_path=tmp_path / "ledger.json")
    p = notifications(fleet, rules_result.incidents)[0]
    assert n.send(p) == "sent"
    assert len(calls) == 2  # one retry after the 503
    assert n.send(p) == "duplicate"
    again = WebhookNotifier("http://hook.test/in", "slack", client=client, ledger_path=tmp_path / "ledger.json")
    assert again.send(p) == "duplicate"  # the ledger survives a restart
