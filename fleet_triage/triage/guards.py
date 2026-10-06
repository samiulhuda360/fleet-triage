"""Guards on a draft reply: no promises, and no device facts that the evidence does not contain."""

from __future__ import annotations

import re

from .evidence import Evidence

PROMISES = [
    (
        r"\b(will|'ll)\s+(be\s+)?(fix|fixed|repair|repaired|replace|replaced|resolve|resolved|sort(ed)?)\b",
        "fix promised",
    ),
    (r"\b(refund|credit|reimburse|compensat|free of charge|no charge|money back|discount)\w*", "money promised"),
    (r"\bguarantee\w*|\bpromise\w*|\bdefinitely\b|\bensure you\b", "guarantee"),
    (r"\b(by|before)\s+(tomorrow|tonight|today|monday|tuesday|wednesday|thursday|friday|the weekend|end of)", "date"),
    (r"\bwithin\s+\d+\s*(hours?|days?|weeks?|h)\b", "time frame"),
    (r"\b(we|i)\s+(will|'ll)\s+(send|ship|courier|post)\b", "shipment promised"),
    (r"\bnext\s+(week|update|release)\b", "timeline"),
]
COLLAR_RE = re.compile(r"\bC-\d{5}\b")
TOWER_RE = re.compile(r"\bT-\d{2}\b")
INCIDENT_RE = re.compile(r"\bINC-\d{4}\b")
VERSION_RE = re.compile(r"\b\d+\.\d+\.\d+\b")
MEASURE_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*(%|h\b|hours?\b|dbm\b|db\b|°?c\b|collars?\b|%/h)", re.I)


def check_promises(draft: str) -> list[str]:
    low = draft.lower()
    return [f"promise: {label}" for pat, label in PROMISES if re.search(pat, low)]


def check_facts(draft: str, evidence: Evidence, ticket_text: str) -> list[str]:
    source = " ".join(evidence.facts) + " " + ticket_text
    hits = []
    for rx, what in ((COLLAR_RE, "collar"), (TOWER_RE, "tower"), (INCIDENT_RE, "incident"), (VERSION_RE, "version")):
        allowed = set(rx.findall(source))
        for v in set(rx.findall(draft)) - allowed:
            hits.append(f"invented {what}: {v}")
    allowed_nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", source)]
    for num, unit in MEASURE_RE.findall(draft):
        v = float(num)
        if not any(abs(v - a) <= 0.6 or abs(abs(v) - abs(a)) <= 0.6 for a in allowed_nums):
            hits.append(f"number not in the device data: {num}{unit}")
    return hits


def check_draft(draft: str, evidence: Evidence, ticket_text: str) -> list[str]:
    return check_promises(draft) + check_facts(draft, evidence, ticket_text)
