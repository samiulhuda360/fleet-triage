"""Triage evaluation on 60 development and 15 held-out tickets.

Scores each mode on:

* **category** - the suggested category equals the labelled root cause;
* **article** - the suggested known-issue article is the labelled one (and whether it is in the top three);
* **linking** - the farm is right and the collars named in the ticket were all found, with none extra;
* **incident** - for tickets about a planted failure, an incident of that failure type was linked;
* **escalation** - the escalate / reply-only decision matches the label.

The held-out tickets were written together with the development tickets, before any triage code, and were
never used for tuning keywords, weights or prompts. ``--mode llm`` calls the model only for prompts missing from
the cache; ``--no-live`` replays the cache and never calls a model.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

from ..detect.features import FleetFeatures
from ..detect.pipeline import detect
from ..sim.simulator import simulate
from ..triage.engine import HARDWARE, Mode, Triage
from ..triage.evidence import FleetContext
from ..triage.llm import LLMClient
from ..triage.tickets import Ticket, load_tickets

# Flash-Lite list price per million tokens (input, output), used only for the cost estimate.
PRICE_PER_M = (0.10, 0.40)


def build_context(seed: int = 7) -> FleetContext:
    fleet = simulate(seed)
    feats = FleetFeatures(fleet)
    res = detect(fleet, "rules+anomaly", feats)
    return FleetContext(fleet, feats, res.incidents)


def _incident_ok(ctx: FleetContext, t: Ticket, related: list[str]) -> bool | None:
    if t.category not in HARDWARE:
        return None
    by_id = {i.id: i for i in ctx.incidents}
    return any(by_id[r].type == t.category for r in related if r in by_id)


def score(ctx: FleetContext, tickets: list[Ticket], triage: Triage, mode: Mode) -> dict:
    rows = []
    t0 = time.perf_counter()
    for t in tickets:
        s = triage.suggest(t, mode)
        inc_ok = _incident_ok(ctx, t, s.related_incidents)
        rows.append(
            {
                "id": t.id,
                "category_ok": s.category == t.category,
                "article_ok": s.article_id == t.article,
                "article_top3": t.article in [c["id"] for c in s.candidates[:3]] or s.article_id == t.article,
                "link_ok": s.link["farm_id"] == t.farm_id and sorted(s.link["device_ids"]) == sorted(t.device_ids),
                "incident_ok": inc_ok,
                "escalate_ok": s.escalate == t.escalate,
                "expected": {"category": t.category, "article": t.article, "escalate": t.escalate},
                "got": {"category": s.category, "article": s.article_id, "escalate": s.escalate},
                "guard_hits": s.guard_hits,
                "fell_back": s.fell_back,
                "llm": s.llm,
            }
        )
    n = len(rows)
    inc_rows = [r for r in rows if r["incident_ok"] is not None]

    def acc(k: str, rs: list[dict] = rows) -> float:
        return round(sum(1 for r in rs if r[k]) / len(rs), 3) if rs else 0.0

    llm_rows = [r["llm"] for r in rows if r["llm"]]
    lat = [x["latency_s"] for x in llm_rows if x["latency_s"]]
    ptok = sum(x["prompt_tokens"] for x in llm_rows)
    ctok = sum(x["completion_tokens"] for x in llm_rows)
    out = {
        "mode": mode,
        "tickets": n,
        "category": acc("category_ok"),
        "article": acc("article_ok"),
        "article_top3": acc("article_top3"),
        "linking": acc("link_ok"),
        "incident": acc("incident_ok", inc_rows),
        "incident_tickets": len(inc_rows),
        "escalation": acc("escalate_ok"),
        "drafts_with_guard_hits": sum(1 for r in rows if [h for h in r["guard_hits"] if "floor" not in h]),
        "escalation_floor_applied": sum(1 for r in rows if "escalation floor applied" in r["guard_hits"]),
        "fallbacks": sum(1 for r in rows if r["fell_back"]),
        "runtime_s": round(time.perf_counter() - t0, 1),
        "misses": [
            {"id": r["id"], "expected": r["expected"], "got": r["got"]}
            for r in rows
            if not (r["category_ok"] and r["article_ok"] and r["escalate_ok"])
        ],
    }
    if mode == "llm":
        out["llm_calls"] = {
            "live": sum(1 for x in llm_rows if x["live"]),
            "cached": sum(1 for x in llm_rows if x["cached"]),
            "failed": sum(1 for x in llm_rows if x["error"]),
            "median_latency_s": round(statistics.median(lat), 2) if lat else None,
            "p95_latency_s": round(sorted(lat)[int(0.95 * (len(lat) - 1))], 2) if lat else None,
            "prompt_tokens": ptok,
            "completion_tokens": ctok,
            "est_cost_usd": round(ptok / 1e6 * PRICE_PER_M[0] + ctok / 1e6 * PRICE_PER_M[1], 4),
            "guard_reasons": sorted({h for r in rows for h in r["guard_hits"]}),
        }
    return out


def to_markdown(report: dict) -> str:
    lines = ["# Triage evaluation", ""]
    for split, by_mode in report["splits"].items():
        title = "Development tickets" if split == "dev" else "Held-out tickets (never tuned on)"
        n = next(iter(by_mode.values()))["tickets"]
        lines += [f"## {title} ({n})", ""]
        lines += [
            "| Mode | Category | Article | Article in top 3 | Linking | Incident linked | Escalation "
            "| Drafts failing guards |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for m, s in by_mode.items():
            lines.append(
                f"| {m} | {s['category'] * 100:.1f}% | {s['article'] * 100:.1f}% | {s['article_top3'] * 100:.1f}% "
                f"| {s['linking'] * 100:.1f}% | {s['incident'] * 100:.1f}% ({s['incident_tickets']}) "
                f"| {s['escalation'] * 100:.1f}% | {s['drafts_with_guard_hits']} |"
            )
        lines.append("")
        for m, s in by_mode.items():
            if s["misses"]:
                lines.append(
                    f"Not handled correctly by `{m}`: "
                    + ", ".join(
                        f"{x['id']} (expected {x['expected']['category']}/{x['expected']['article']}/"
                        f"{'escalate' if x['expected']['escalate'] else 'reply'}, got {x['got']['category']}/"
                        f"{x['got']['article']}/{'escalate' if x['got']['escalate'] else 'reply'})"
                        for x in s["misses"]
                    )
                )
                lines.append("")
            if "llm_calls" in s:
                c = s["llm_calls"]
                lines.append(
                    f"Model calls (`{m}`): {c['live']} live, {c['cached']} from cache, {c['failed']} failed; "
                    f"median latency {c['median_latency_s']} s, p95 {c['p95_latency_s']} s; "
                    f"{c['prompt_tokens']} prompt and {c['completion_tokens']} completion tokens, "
                    f"about ${c['est_cost_usd']} at list price. Fallbacks: {s['fallbacks']}; "
                    f"escalation floor applied: {s['escalation_floor_applied']}."
                )
                lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Score triage modes on labelled tickets")
    p.add_argument("--modes", nargs="+", default=["bm25", "rules"], choices=["bm25", "rules", "llm"])
    p.add_argument("--no-live", action="store_true", help="never call a model; replay the cache only")
    p.add_argument("--out", type=Path, default=Path("results"))
    p.add_argument("--no-write", action="store_true")
    a = p.parse_args(argv)
    ctx = build_context()
    client = LLMClient(allow_live=not a.no_live) if "llm" in a.modes else None
    triage = Triage(ctx, client)
    tickets = load_tickets(ctx.fleet)
    report: dict = {"splits": {}}
    for split in ("dev", "heldout"):
        subset = [t for t in tickets if t.split == split]
        report["splits"][split] = {}
        for mode in a.modes:
            s = score(ctx, subset, triage, mode)
            report["splits"][split][mode] = s
            print(
                f"{split:<8} {mode:<6} category {s['category']:.3f} article {s['article']:.3f} "
                f"linking {s['linking']:.3f} incident {s['incident']:.3f} escalation {s['escalation']:.3f} "
                f"guard-failing drafts {s['drafts_with_guard_hits']} ({s['runtime_s']} s)"
            )
    if not a.no_write:
        a.out.mkdir(parents=True, exist_ok=True)
        name = "triage" if "llm" in a.modes else "triage_no_model"
        (a.out / f"{name}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        (a.out / f"{name}.md").write_text(to_markdown(report), encoding="utf-8")


if __name__ == "__main__":
    main()
