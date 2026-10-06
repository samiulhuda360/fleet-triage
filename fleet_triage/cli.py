"""Command line: simulate a fleet, run detection, list incidents, send alerts, triage tickets, run evaluations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .alerts.notify import WebhookNotifier, notifications, render
from .detect.pipeline import METHODS, detect
from .sim.simulator import simulate


def _detect(a: argparse.Namespace) -> None:
    fleet = simulate(a.seed)
    res = detect(fleet, a.method)
    if a.method == "threshold":
        print(f"{res.alerts} device alerts from {len(res.findings)} threshold crossings")
        return
    print(f"{len(res.incidents)} incidents, {res.alerts} notifications, {len(res.findings)} findings grouped\n")
    for inc in res.incidents:
        status = "open" if inc.resolved_hour is None else "resolved"
        when = fleet.hour_to_time(inc.opened_hour).strftime("%d %b %H:00")
        print(f"{inc.id}  {inc.severity:<8} {status:<8} {when}  {inc.title}")


def _alerts(a: argparse.Namespace) -> None:
    fleet = simulate(a.seed)
    res = detect(fleet, "rules+anomaly")
    payloads = notifications(fleet, res.incidents)
    if not a.webhook:
        for p in payloads[: a.limit]:
            print(json.dumps(render(p, a.format), indent=1))
        print(f"... {len(payloads)} notifications in total")
        return
    notifier = WebhookNotifier(a.webhook, a.format, ledger_path=Path(a.ledger) if a.ledger else None)
    counts: dict[str, int] = {}
    for p in payloads:
        r = notifier.send(p)
        counts[r] = counts.get(r, 0) + 1
    print(counts)


def _triage(a: argparse.Namespace) -> None:
    from .evaluation.triage import build_context
    from .triage.engine import Triage
    from .triage.llm import LLMClient
    from .triage.tickets import load_tickets

    ctx = build_context(a.seed)
    client = LLMClient(allow_live=a.live) if a.mode == "llm" else None
    triage = Triage(ctx, client)
    tickets = {t.id: t for t in load_tickets(ctx.fleet)}
    t = tickets[a.ticket]
    s = triage.suggest(t, a.mode)
    print(f"Ticket {t.id} from {t.sender}\n{t.subject}\n{t.body}\n")
    print(f"Linked: {s.link['farm_name']} {s.link['device_ids']}")
    print("Facts:\n  " + "\n  ".join(s.evidence["facts"]))
    print(f"\nSuggested article: {s.article_id} {s.article_title}")
    print(f"Escalate: {s.escalate} ({s.escalation_reason})")
    print(f"Guard hits: {s.guard_hits or 'none'}   Fallbacks: {s.fell_back or 'none'}")
    print(f"\nDraft (awaiting a person's approval):\n{s.draft}")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="fleet-triage")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("simulate", help="generate a fleet and save it")
    s.add_argument("--seed", type=int, default=7)
    s.add_argument("--out", type=Path, default=Path("data/generated"))

    d = sub.add_parser("detect", help="run a detection method and list incidents")
    d.add_argument("--seed", type=int, default=7)
    d.add_argument("--method", choices=METHODS, default="rules+anomaly")

    al = sub.add_parser("alerts", help="print or send incident notifications")
    al.add_argument("--seed", type=int, default=7)
    al.add_argument("--format", choices=["json", "slack", "telegram"], default="json")
    al.add_argument("--webhook", help="URL to POST notifications to")
    al.add_argument("--ledger", help="file that records sent notifications so they are never sent twice")
    al.add_argument("--limit", type=int, default=3)

    tr = sub.add_parser("triage", help="triage one ticket")
    tr.add_argument("ticket")
    tr.add_argument("--seed", type=int, default=7)
    tr.add_argument("--mode", choices=["bm25", "rules", "llm"], default="rules")
    tr.add_argument("--live", action="store_true", help="allow a live model call (needs AI_API_KEY)")

    a = p.parse_args(argv)
    if a.cmd == "simulate":
        fleet = simulate(a.seed)
        path = a.out / f"fleet_seed{a.seed}.npz"
        fleet.save(path)
        print(f"saved {path} ({fleet.n_devices} collars, {len(fleet.towers)} towers, {fleet.hours} h)")
    elif a.cmd == "detect":
        _detect(a)
    elif a.cmd == "alerts":
        _alerts(a)
    elif a.cmd == "triage":
        _triage(a)


if __name__ == "__main__":
    main()
