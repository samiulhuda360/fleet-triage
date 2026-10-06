"""Alert hook: send incident notifications to a webhook, deduplicated, in plain JSON, Slack or Telegram format.

Only incidents notify, never single findings. A notification goes out when an incident opens, when its severity
rises and when it resolves. A ledger of fingerprints (incident, kind, severity) makes sending idempotent, so a
replay or a retry never pages twice for the same thing.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Literal

import httpx

from ..detect.model import TYPE_META, Incident
from ..sim.fleet import Fleet

Format = Literal["json", "slack", "telegram"]
SEVERITY_MARK = {"critical": "[CRITICAL]", "high": "[HIGH]", "medium": "[MEDIUM]", "low": "[LOW]"}


def incident_payload(fleet: Fleet, inc: Incident, kind: str, hour: int, severity: str | None = None) -> dict:
    farms = sorted(fleet.farms[i].name for i in inc.farms)
    return {
        "event": f"incident.{kind}",
        "incident_id": inc.id,
        "type": inc.type,
        "severity": severity or inc.severity,
        "title": inc.title,
        "at": fleet.hour_to_time(hour).isoformat(),
        "opened_at": fleet.hour_to_time(inc.opened_hour).isoformat(),
        "impact": {
            "collars": len(inc.devices),
            "farms": len(inc.farms),
            "farm_names": farms[:10],
            "towers": sorted(fleet.towers[t].id for t in inc.towers),
        },
        "kb_article": TYPE_META[inc.type]["kb"] or None,
        "evidence": [e["detail"] for e in inc.evidence[:3]],
    }


def format_slack(p: dict) -> dict:
    head = f"{SEVERITY_MARK[p['severity']]} {p['title']}"
    impact = p["impact"]
    lines = [
        f"*{p['event'].split('.')[-1].title()}* {p['incident_id']} - {impact['collars']} collars, "
        f"{impact['farms']} farm(s)",
        *[f"- {e}" for e in p["evidence"]],
    ]
    if p["kb_article"]:
        lines.append(f"Known issue: {p['kb_article']}")
    return {
        "text": head,
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": head[:150]}},
            {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}},
        ],
    }


def format_telegram(p: dict, chat_id: str = "-100000000") -> dict:
    impact = p["impact"]
    text = "\n".join(
        [
            f"{SEVERITY_MARK[p['severity']]} {p['title']}",
            f"{p['event']} {p['incident_id']}: {impact['collars']} collars on {impact['farms']} farm(s)",
            *[f"- {e}" for e in p["evidence"]],
        ]
    )
    return {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}


def render(p: dict, fmt: Format) -> dict:
    if fmt == "slack":
        return format_slack(p)
    if fmt == "telegram":
        return format_telegram(p)
    return p


class WebhookNotifier:
    def __init__(
        self,
        url: str,
        fmt: Format = "json",
        client: httpx.Client | None = None,
        ledger_path: Path | None = None,
        retries: int = 3,
    ):
        self.url = url
        self.fmt = fmt
        self.client = client or httpx.Client(timeout=10)
        self.ledger_path = ledger_path
        self.retries = retries
        self.sent: set[str] = set()
        if ledger_path and ledger_path.exists():
            self.sent = set(json.loads(ledger_path.read_text(encoding="utf-8")))

    def _save(self) -> None:
        if self.ledger_path:
            self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
            self.ledger_path.write_text(json.dumps(sorted(self.sent)), encoding="utf-8")

    def send(self, payload: dict) -> str:
        """Returns 'sent', 'duplicate' or 'failed'."""
        fp = f"{payload['incident_id']}:{payload['event']}:{payload['severity']}"
        if fp in self.sent:
            return "duplicate"
        body = render(payload, self.fmt)
        for attempt in range(self.retries):
            try:
                r = self.client.post(self.url, json=body)
                if r.status_code < 500:
                    r.raise_for_status()
                    self.sent.add(fp)
                    self._save()
                    return "sent"
            except httpx.HTTPStatusError:
                return "failed"
            except httpx.TransportError:
                pass
            time.sleep(0.2 * (2**attempt))
        return "failed"


def notifications(fleet: Fleet, incidents: Iterable[Incident], until_hour: int | None = None) -> list[dict]:
    """Every notification the incident stream produced, in time order, as payloads."""
    out = []
    for inc in incidents:
        for n in inc.notifications:
            if until_hour is None or n["hour"] <= until_hour:
                out.append((n["hour"], incident_payload(fleet, inc, n["kind"], n["hour"], n["severity"])))
    return [p for _, p in sorted(out, key=lambda x: x[0])]
