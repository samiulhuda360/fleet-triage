"""Ticket triage: link, pull device data, suggest the known-issue article, decide escalation, draft a reply.

Three modes share the same linking and evidence:

* ``bm25``  - text retrieval only: the top BM25 article decides the category and its default escalation.
* ``rules`` - BM25 plus keyword rules plus what the device data says. This is the path with no model key.
* ``llm``   - the model reads the ticket, the facts and the top candidates and returns structured JSON; guards
              then check the article, the escalation floor and the draft. Any guard failure falls back to the
              rules result for that field.

Nothing is sent. Every suggestion waits for a person to approve, edit, escalate or reject it.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Literal

from ..detect.model import TYPE_META
from .bm25 import BM25
from .evidence import Evidence, FleetContext, gather
from .guards import check_draft
from .kb import Article, by_category, by_id, load_kb
from .linking import Link, link_ticket
from .llm import LLMClient
from .tickets import Ticket

Mode = Literal["bm25", "rules", "llm"]
HARDWARE = {"tower_outage", "firmware_bad", "battery_fade", "water_ingress", "gps_drift"}

KEYWORDS: dict[str, list[str]] = {
    "billing": [r"invoice", r"\bbill", r"charged", r"refund", r"subscription", r"cancel", r"paying"],
    "account_access": [
        r"log ?in",
        r"password",
        r"reset email",
        r"locked out",
        r"into the app",
        r"farm account",
        r"add (my|him|her|staff)\b",
        r"see (where )?the (cows|herd)",
    ],
    "alert_settings": [r"notification", r"\balerts?\b", r"\btexts?\b", r"turn some off", r"one a day", r"instead"],
    "setup_howto": [r"how do (i|you)", r"\bpair", r"new collars", r"moving", r"\bmove the", r"run-off"],
    "collar_fit": [r"loose", r"tight", r"strap", r"rubbing", r"lying in", r"crack", r"caught in"],
    "firmware_bad": [r"update", r"firmware", r"\d\.\d\.\d", r"software"],
    "tower_outage": [
        r"tower",
        r"half (the|my) herd",
        r"all at once",
        r"same time",
        r"heap of",
        r"big chunk",
        r"most of (our|the)",
    ],
    "water_ingress": [r"creek", r"river", r"water", r"\bfog", r"swamp", r"trough", r"really (high|hot)"],
    "gps_drift": [r"road", r"neighbou?r'?s paddock", r"jump", r"scribble", r"wander", r"wrong", r"accuracy"],
    "battery_fade": [r"\bflat\b", r"hold charge", r"overnight", r"every night", r"\bdies\b", r"on the way out"],
    "weather_low_charge": [r"storm", r"grey", r"cloud", r"\brain", r"weather", r"\bsun"],
    "poor_coverage": [r"\bhill", r"gull(y|ies)", r"ridge", r"reception", r"signal", r"patchy", r"in and out"],
}
ESCALATE_WORDS = [
    r"refund",
    r"charged twice",
    r"overcharg",
    r"cancel",
    r"crack",
    r"broken",
    r"damaged",
    r"can'?t get into",
    r"locked out",
    r"second month",
]

REPLY_TEXT = {
    "tower_outage": "The collars themselves are fine. The tower that relays their messages is offline, so positions "
    "in the app are stale until it is back, and reporting resumes on its own once the tower recovers.",
    "battery_fade": "This looks like the collar's battery cell wearing out. It is a hardware fault, not anything on "
    "the farm, and it will not come right with better weather.",
    "firmware_bad": "This is a known software issue in firmware 3.5.0 that affects a group of collars, not your farm "
    "or your animals. Our engineering team owns the fix and we will keep you posted through support.",
    "water_ingress": "The pattern in the data matches water getting into the collar. It needs to come off the "
    "animal and be returned, as it cannot be repaired on the farm.",
    "gps_drift": "The collar's GPS module is wearing out, so its positions are unreliable. The animal itself is very "
    "likely with the rest of the mob.",
    "poor_coverage": "This is a coverage limitation on hill country rather than a faulty collar. Collars drop in and "
    "out behind ridges and in gullies and always come back. If you want better reception on the worst blocks we "
    "can talk about a coverage survey.",
    "weather_low_charge": "Nothing is wrong with the collars. They charge from a small solar panel, so a run of grey "
    "days lowers the charge across the whole herd, and it recovers with a couple of sunny days.",
    "collar_fit": "Collars should sit snug with two fingers between the strap and the neck and the panel on top. A "
    "replacement strap can be ordered through the farm app.",
    "account_access": "Use Forgot password on the sign-in page and check the spam folder for the reset link, which "
    "lasts one hour. The farm owner can add staff under Settings, then People, then Invite.",
    "billing": "Billing follows the number of active collars on the last day of the month, and invoices are under "
    "Settings, then Billing.",
    "setup_howto": "New collars pair in the farm app under Herd, then Add collars, by scanning the QR code on each "
    "collar. Moving a mob needs no tower changes if the new paddock is in range of a tower on the farm.",
    "alert_settings": "Notifications are under Settings, then Alerts. Each alert type can go to the app, a text or "
    "an email, and to different people, and low-battery alerts can be set to a daily digest.",
}


@dataclass
class Suggestion:
    ticket_id: str
    mode: str
    category: str
    article_id: str
    article_title: str
    candidates: list[dict]
    escalate: bool
    escalation_reason: str
    draft: str
    link: dict
    evidence: dict
    related_incidents: list[str]
    guard_hits: list[str] = field(default_factory=list)
    fell_back: list[str] = field(default_factory=list)
    llm: dict | None = None
    status: str = "awaiting review"

    def to_dict(self) -> dict:
        return asdict(self)


class Triage:
    def __init__(self, ctx: FleetContext, client: LLMClient | None = None):
        self.ctx = ctx
        self.kb = load_kb()
        self.kb_by_id = by_id(self.kb)
        self.kb_by_cat = by_category(self.kb)
        self.index = BM25([a.search_text for a in self.kb])
        self.client = client

    # ---- shared steps ----------------------------------------------------------------------------
    def _rank(self, text: str, ev: Evidence | None, use_rules: bool) -> list[tuple[Article, float]]:
        raw = self.index.scores(text)
        top = max(raw) or 1.0
        low = text.lower()
        out = []
        for a, s in zip(self.kb, raw, strict=True):
            score = s / top
            if use_rules:
                hits = sum(1 for p in KEYWORDS.get(a.category, []) if re.search(p, low))
                score += min(hits, 3) * 0.3
                if ev is not None:
                    score += 1.5 * ev.signals.get(a.category, 0.0)
                    if ev.signals.get("healthy_collars") and a.category in HARDWARE:
                        score -= 0.8
            out.append((a, round(score, 3)))
        return sorted(out, key=lambda x: -x[1])

    def _escalate_rules(self, art: Article, text: str, ev: Evidence) -> tuple[bool, str]:
        low = text.lower()
        word = next((p for p in ESCALATE_WORDS if re.search(p, low)), None)
        if word:
            return True, f"ticket asks for something support cannot decide alone ({word.strip(chr(92) + 'b')})"
        severe = [i for i in ev.incidents if i["severity"] in ("high", "critical") and i["collars_on_farm"] > 0]
        severe.sort(key=lambda i: i["kb"] != art.id)  # the incident that matches the article first
        if art.category in HARDWARE:
            if severe:
                return True, f"linked to {severe[0]['id']} ({severe[0]['severity']}); {art.id} says escalate"
            return True, f"{art.id} is a hardware fault that needs field operations"
        return False, f"{art.id} can be answered by support"

    def _draft(self, t: Ticket, art: Article, escalate: bool, ev: Evidence) -> str:
        first = (ev.farm or {}).get("farmer", "there").split()[0]
        lines = [f"Hi {first},", "", f"Thanks for getting in touch. {_data_sentence(art.category, ev)}".strip()]
        lines += ["", REPLY_TEXT[art.category]]
        if escalate:
            team = "accounts team" if art.category in ("billing", "account_access") else "field operations team"
            lines += ["", f"I have passed the details to our {team}, who will be in touch."]
        lines += ["", "Kind regards,", "Fleet support"]
        return "\n".join(lines)

    # ---- main ----------------------------------------------------------------------------------------
    def suggest(self, t: Ticket, mode: Mode = "rules") -> Suggestion:
        link = link_ticket(self.ctx.fleet, t.sender, t.text)
        ev = gather(self.ctx, link, t.received_hour)
        ranked = self._rank(t.text, ev, use_rules=mode != "bm25")
        art = ranked[0][0]
        if mode == "bm25":
            esc, why = art.escalate, f"{art.id} default"
        else:
            esc, why = self._escalate_rules(art, t.text, ev)
        draft = self._draft(t, art, esc, ev)
        sug = self._build(t, mode, art, ranked, esc, why, draft, link, ev)
        if mode == "llm":
            self._apply_llm(sug, t, ranked, ev, link)
        return sug

    def _build(self, t, mode, art, ranked, esc, why, draft, link: Link, ev: Evidence) -> Suggestion:
        f = self.ctx.fleet
        return Suggestion(
            ticket_id=t.id,
            mode=mode,
            category=art.category,
            article_id=art.id,
            article_title=art.title,
            candidates=[{"id": a.id, "title": a.title, "score": s} for a, s in ranked[:4]],
            escalate=esc,
            escalation_reason=why,
            draft=draft,
            link={
                "farm_id": f.farms[link.farm_idx].id if link.farm_idx is not None else None,
                "farm_name": f.farms[link.farm_idx].name if link.farm_idx is not None else None,
                "device_ids": [f.devices[d].id for d in link.device_idxs],
                "tower_ids": [f.towers[x].id for x in link.tower_idxs],
                "how": link.how,
            },
            evidence={"facts": ev.facts, "collars": ev.collars, "farm": ev.farm, "signals": ev.signals},
            related_incidents=[i["id"] for i in ev.incidents if i["collars_on_farm"] > 0],
            guard_hits=check_draft(draft, ev, t.text),
        )

    def _apply_llm(self, sug: Suggestion, t: Ticket, ranked, ev: Evidence, link: Link) -> None:
        if self.client is None:
            sug.fell_back.append("no model client: rules result kept")
            return
        cands = [a for a, _ in ranked[:5]]
        system, user = build_prompt(t, cands, ev, sug.link)
        out, meta = self.client.complete_json(system, user)
        sug.llm = {
            "cached": meta.cached,
            "live": meta.live,
            "latency_s": meta.latency_s,
            "prompt_tokens": meta.prompt_tokens,
            "completion_tokens": meta.completion_tokens,
            "error": meta.error,
        }
        if out is None:
            sug.fell_back.append(f"model unavailable or invalid JSON ({meta.error or 'parse'}): rules result kept")
            return
        art = self.kb_by_id.get(str(out.get("article_id", "")).strip())
        if art is None:
            sug.fell_back.append(f"article {out.get('article_id')!r} not in the knowledge base: rules article kept")
        else:
            sug.article_id, sug.article_title, sug.category = art.id, art.title, art.category
        esc = out.get("escalate")
        if isinstance(esc, bool):
            sug.escalate = esc
            sug.escalation_reason = str(out.get("escalation_reason", ""))[:300] or "model decision"
        else:
            sug.fell_back.append("escalation missing: rules decision kept")
        # escalation floor: a hardware fault with a serious linked incident always goes to a person in field ops
        severe = [i for i in ev.incidents if i["severity"] in ("high", "critical") and i["collars_on_farm"] > 0]
        if not sug.escalate and sug.category in HARDWARE and severe:
            sug.escalate = True
            sug.escalation_reason = f"guard: linked to {severe[0]['id']} ({severe[0]['severity']})"
            sug.guard_hits.append("escalation floor applied")
        draft = str(out.get("reply_draft", "")).strip()
        hits = check_draft(draft, ev, t.text) if draft else ["empty draft"]
        if hits:
            sug.guard_hits = [h for h in sug.guard_hits if h == "escalation floor applied"] + hits
            sug.fell_back.append("draft failed the guards: template draft used")
            art_now = self.kb_by_id[sug.article_id]
            sug.draft = self._draft(t, art_now, sug.escalate, ev)
        else:
            sug.draft = draft
            sug.guard_hits = [h for h in sug.guard_hits if h == "escalation floor applied"]


def _data_sentence(cat: str, ev: Evidence) -> str:
    farm = ev.farm or {}
    c = ev.collars[0] if ev.collars else None
    inc = next((i for i in ev.incidents if i["kb"] == TYPE_META.get(_inc_type(cat), {}).get("kb")), None)
    ref = " Our monitoring had already picked this up." if inc else ""
    if cat == "tower_outage":
        down = [tw for tw in farm.get("towers", []) if not tw["online"]]
        if down:
            return f"Tower {down[0]['id']} ({down[0]['name']}) on your farm has no heartbeat right now.{ref}"
        return f"Our monitoring has been tracking your farm's towers.{ref}"
    if cat == "battery_fade" and c and c["night_drain_pct_per_h"] is not None:
        return (
            f"Collar {c['id']} is using {c['night_drain_pct_per_h']} %/h of battery overnight, against "
            f"{c['night_drain_before']} %/h before.{ref}"
        )
    if cat == "water_ingress" and c:
        if c["hours_since_report"] >= 3:
            return f"Collar {c['id']} last reported {c['last_report']} while the rest of the herd is reporting.{ref}"
        return f"Collar {c['id']} is reading {c['temp_vs_farm_c']} C warmer than the herd.{ref}"
    if cat == "gps_drift" and c and c["hdop"] is not None:
        return (
            f"Collar {c['id']} shows a position error score (HDOP) of {c['hdop']}, "
            f"against {c['hdop_before']} earlier.{ref}"
        )
    if cat == "firmware_bad":
        fw = c["firmware"] if c else "3.5.0"
        return f"Your collars are on firmware {fw}.{ref}"
    if cat == "weather_low_charge" and farm:
        return (
            f"Sunshine at {farm['name']} over the last three days was {farm['sunshine_last_3_days'] * 100:.0f} % of a "
            f"clear sky, and {farm['reporting_last_3h']} of {farm['collars']} collars are still reporting."
        )
    if cat == "poor_coverage" and farm:
        return f"Signal across {farm['name']} is weak and variable, which is typical for hill country."
    return ""


def _inc_type(cat: str) -> str:
    return cat if cat in HARDWARE else ""


SYSTEM_PROMPT = """You triage support tickets for a fleet of GPS livestock collars and solar base towers.
A person reviews everything you produce; nothing is sent automatically.

Return one JSON object with exactly these keys:
  "category": one of the candidate articles' categories,
  "article_id": the id of the best matching candidate article (for example "KB-03"),
  "escalate": true or false,
  "escalation_reason": one short sentence,
  "reply_draft": a short, plain reply to the farmer (under 120 words),
  "facts_used": a list of the fact sentences you relied on.

Rules:
- Choose the article from the candidates only. Use the device facts to decide between candidates: the data
  outweighs the farmer's guess (for example a collar the farmer blames on the weather may show battery fade).
- Escalate hardware faults (tower outage, battery fade, firmware 3.5.0, water ingress, GPS drift), cracked or
  damaged collars, billing disputes, refunds, cancellations and lost account access. Do not escalate how-to
  questions, expected behaviour (weather, hill coverage) or simple account and billing questions.
- In the draft, only mention collar ids, towers, incidents, versions and numbers that appear in the facts or
  the ticket. Never promise a fix, a replacement, a refund, a credit, a date or a time frame.
- Do not quote internal incident ids or rule names to the farmer; they are for staff.
- Sign off as "Fleet support"."""


def build_prompt(t: Ticket, cands: list[Article], ev: Evidence, link: dict) -> tuple[str, str]:
    user = {
        "ticket": {"from": t.sender, "subject": t.subject, "body": t.body},
        "linked": {"farm": link.get("farm_name"), "collars": link.get("device_ids"), "how": link.get("how")},
        "facts": ev.facts,
        "candidate_articles": [
            {
                "id": a.id,
                "category": a.category,
                "title": a.title,
                "symptoms": a.section("Symptoms"),
                "data_signature": a.section("What the data shows"),
                "escalate_by_default": a.escalate,
            }
            for a in cands
        ],
    }
    return SYSTEM_PROMPT, json.dumps(user, indent=1)
