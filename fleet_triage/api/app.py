"""FastAPI backend for the fleet dashboard: overview, incidents, collar drill-down, triage queue and alert hook."""

from __future__ import annotations

import json
import time
from collections import Counter
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import numpy as np
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..alerts.notify import incident_payload, notifications, render
from ..detect.model import SEVERITIES, TYPE_META, Incident
from ..triage.kb import by_id, load_kb
from .state import ROOT, AppState, build_state

WEB_DIST = ROOT / "web" / "dist"
RESULTS = ROOT / "results"


class Decision(BaseModel):
    """A person's decision on a triage suggestion. Recording it sends nothing."""

    action: Literal["approve", "escalate", "reject"]
    draft: str | None = Field(default=None, max_length=5000)
    note: str | None = Field(default=None, max_length=1000)


def _clean(a: np.ndarray, nd: int = 2) -> list[float | None]:
    return [None if not np.isfinite(v) else round(float(v), nd) for v in a]


def create_app(state: AppState | None = None) -> FastAPI:
    holder: dict[str, AppState] = {}

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        holder["s"] = state or build_state()
        yield

    app = FastAPI(title="Fleet Triage API", version="1.0.0", lifespan=lifespan)

    def S() -> AppState:
        return holder["s"]

    def t_iso(h: int) -> str:
        return S().fleet.hour_to_time(int(h)).isoformat()

    def default_at(at: int | None) -> int:
        hours = S().fleet.hours
        return hours - 1 if at is None else max(0, min(int(at), hours - 1))

    def status_at(inc: Incident, at: int) -> str:
        return "resolved" if inc.resolved_hour is not None and inc.resolved_hour <= at else "open"

    def severity_at(inc: Incident, at: int) -> str:
        sev = inc.notifications[0]["severity"] if inc.notifications else inc.severity
        for n in inc.notifications:
            if n["hour"] <= at and n["kind"] in ("opened", "escalated"):
                sev = n["severity"]
        return sev

    def inc_summary(inc: Incident, at: int) -> dict:
        s = S()
        return {
            "id": inc.id,
            "type": inc.type,
            "type_label": TYPE_META[inc.type]["label"],
            "title": inc.title,
            "severity": severity_at(inc, at),
            "status": status_at(inc, at),
            "opened_at": t_iso(inc.opened_hour),
            "opened_hour": inc.opened_hour,
            "resolved_at": t_iso(inc.resolved_hour) if inc.resolved_hour is not None else None,
            "last_at": t_iso(inc.last_hour),
            "collars": sum(1 for h in inc.devices.values() if h <= at),
            "farms": sorted(s.fleet.farms[f].name for f in inc.farms),
            "towers": sorted(s.fleet.towers[t].id for t in inc.towers),
            "sources": sorted(inc.sources),
            "absorbed": inc.absorbed,
            "kb": TYPE_META[inc.type]["kb"] or None,
        }

    def visible(at: int) -> list[Incident]:
        return [i for i in S().incidents if i.opened_hour <= at]

    # ---- fleet ------------------------------------------------------------------------------------
    @app.get("/api/health")
    def health() -> dict:
        s = S()
        return {"ok": True, "seed": s.fleet.seed, "collars": s.fleet.n_devices, "triage_mode": s.triage_mode}

    @app.get("/api/overview")
    def overview(at: int | None = None) -> dict:
        s, f = S(), S().fleet
        at = default_at(at)
        recent = f.reported[:, max(0, at - 2) : at + 1].any(axis=1)
        open_incs = [i for i in visible(at) if status_at(i, at) == "open"]
        sev = Counter(severity_at(i, at) for i in open_incs)
        in_incident = {d for i in open_incs if i.type != "tower_power_low" for d in i.devices}
        farm_rows = []
        for fm in f.farms:
            rows = f.device_farm == fm.idx
            incs = [i for i in open_incs if fm.idx in i.farms]
            worst = max((SEVERITIES.index(severity_at(i, at)) for i in incs), default=-1)
            farm_rows.append(
                {
                    "id": fm.id,
                    "name": fm.name,
                    "region": fm.region,
                    "terrain": fm.terrain,
                    "collars": int(rows.sum()),
                    "reporting_pct": round(float(recent[rows].mean() * 100), 1),
                    "open_incidents": len(incs),
                    "worst_severity": SEVERITIES[worst] if worst >= 0 else None,
                }
            )
        hours = list(range(0, f.hours, 3))
        open_series = [
            sum(
                1
                for i in s.incidents
                if i.opened_hour <= h and not (i.resolved_hour is not None and i.resolved_hour <= h)
            )
            for h in hours
        ]
        alerts = sum(1 for i in s.incidents for n in i.notifications if n["kind"] != "resolved" and n["hour"] <= at)
        queue = [t for t in s.tickets if t.received_hour <= at]
        return {
            "as_of": t_iso(at),
            "at": at,
            "hours": f.hours,
            "start": t_iso(0),
            "kpis": {
                "collars": f.n_devices,
                "reporting": int(recent.sum()),
                "reporting_pct": round(float(recent.mean() * 100), 1),
                "collars_in_incidents": len(in_incident),
                "towers": len(f.towers),
                "towers_online": int(f.tower_online[:, at].sum()),
                "farms": len(f.farms),
                "farms_affected": sum(1 for r in farm_rows if r["open_incidents"]),
                "open_incidents": len(open_incs),
                "alerts_sent": alerts,
                "signals_grouped": sum(1 for x in s.result.findings if x.hour <= at),
                "tickets_waiting": sum(1 for t in queue if t.id not in s.decisions),
            },
            "severity_counts": {k: sev.get(k, 0) for k in reversed(SEVERITIES)},
            "series": {
                "time": [t_iso(h) for h in hours],
                "hour": hours,
                "reporting_pct": _clean(s.reporting_pct[hours], 1),
                "median_battery": _clean(s.median_battery[hours], 1),
                "open_incidents": open_series,
            },
            "farms": farm_rows,
            "top_incidents": [
                inc_summary(i, at)
                for i in sorted(open_incs, key=lambda i: (-SEVERITIES.index(severity_at(i, at)), -len(i.devices)))[:6]
            ],
        }

    # ---- incidents --------------------------------------------------------------------------------
    @app.get("/api/incidents")
    def incidents(at: int | None = None, status: Literal["all", "open", "resolved"] = "all") -> list[dict]:
        at = default_at(at)
        out = [inc_summary(i, at) for i in visible(at)]
        if status != "all":
            out = [x for x in out if x["status"] == status]
        return sorted(out, key=lambda x: (x["status"] != "open", -SEVERITIES.index(x["severity"]), -x["opened_hour"]))

    @app.get("/api/incidents/{iid}")
    def incident(iid: str, at: int | None = None) -> dict:
        s, f = S(), S().fleet
        inc = s.incident(iid)
        if inc is None:
            raise HTTPException(404, "incident not found")
        at = default_at(at)
        members = sorted(inc.devices.items(), key=lambda x: x[1])
        rows = np.array([d for d, _ in members], dtype=int)
        lo, hi = max(0, inc.opened_hour - 72), min(f.hours, (inc.resolved_hour or inc.last_hour) + 48)
        hours = list(range(lo, hi))
        series = {}
        if len(rows):
            import warnings

            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                series = {
                    "time": [t_iso(h) for h in hours],
                    "reporting_pct": _clean(f.reported[rows][:, lo:hi].mean(axis=0) * 100, 1),
                    "median_battery": _clean(np.nanmedian(f.battery[rows][:, lo:hi], axis=0), 1),
                    "median_gps_fix": _clean(np.nanmedian(f.gps_fix[rows][:, lo:hi], axis=0) * 100, 1),
                }
        kb = by_id(load_kb()).get(TYPE_META[inc.type]["kb"])
        notes = []
        for n in inc.notifications:
            p = incident_payload(f, inc, n["kind"], n["hour"], n["severity"])
            notes.append(
                {"at": t_iso(n["hour"]), "kind": n["kind"], "severity": n["severity"], "slack": render(p, "slack")}
            )
        return {
            **inc_summary(inc, at),
            "evidence": [{**e, "at": t_iso(e["hour"])} for e in inc.evidence],
            "rules": sorted(inc.rules),
            "devices": [
                {
                    "id": f.devices[d].id,
                    "farm": f.farms[f.devices[d].farm_idx].name,
                    "tower": f.towers[f.devices[d].tower_idx].id,
                    "joined_at": t_iso(h),
                }
                for d, h in members[:300]
            ],
            "notifications": notes,
            "series": series,
            "kb_article": {"id": kb.id, "title": kb.title, "body": kb.body} if kb else None,
        }

    # ---- devices ----------------------------------------------------------------------------------
    @app.get("/api/devices")
    def devices(q: str = "", limit: int = 20) -> list[dict]:
        s, f = S(), S().fleet
        q = q.strip().upper()
        if q:
            hits = [d for d in f.devices if q in d.id or q.lstrip("C-") in d.id]
        else:  # collars that sit in incidents, one or two per failure mode, as quick picks
            seen: Counter[str] = Counter()
            hits = []
            for inc in s.incidents:
                if inc.type in ("tower_power_low",) or seen[inc.type] >= 2:
                    continue
                d = next(iter(inc.devices), None)
                if d is not None:
                    seen[inc.type] += 1
                    hits.append(f.devices[d])
        out = []
        for d in hits[:limit]:
            out.append(
                {
                    "id": d.id,
                    "farm": f.farms[d.farm_idx].name,
                    "tower": f.towers[d.tower_idx].id,
                    "incidents": [i.type for i in s.incidents if d.idx in i.devices],
                }
            )
        return out

    @app.get("/api/devices/{did}")
    def device(did: str) -> dict:
        s, f = S(), S().fleet
        idx = f.device_index()
        if did not in idx:
            raise HTTPException(404, "collar not found")
        d = idx[did]
        dev = f.devices[d]
        rows = f.device_farm == dev.farm_idx
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            farm_med = {
                k: _clean(np.nanmedian(f.metric(k)[rows], axis=0), 2)
                for k in ("battery", "temp_c", "signal_dbm", "hdop")
            }
        fw = f.firmware[d]
        changes = [
            {"at": t_iso(h), "version": f.firmware_versions[int(fw[h])]}
            for h in range(1, f.hours)
            if fw[h] != fw[h - 1]
        ]
        incs = [
            {**inc_summary(i, f.hours - 1), "joined_at": t_iso(i.devices[d])} for i in s.incidents if d in i.devices
        ]
        return {
            "id": dev.id,
            "farm": {"id": f.farms[dev.farm_idx].id, "name": f.farms[dev.farm_idx].name},
            "tower": {"id": f.towers[dev.tower_idx].id, "name": f.towers[dev.tower_idx].name},
            "firmware_now": f.firmware_versions[int(fw[-1])],
            "firmware_changes": changes,
            "incidents": incs,
            "series": {
                "time": [t_iso(h) for h in range(f.hours)],
                "battery": _clean(f.battery[d], 1),
                "solar_ma": _clean(f.solar_ma[d], 0),
                "signal_dbm": _clean(f.signal_dbm[d], 1),
                "temp_c": _clean(f.temp_c[d], 1),
                "gps_fix": _clean(f.gps_fix[d] * 100, 1),
                "hdop": _clean(f.hdop[d], 2),
                "uplink": _clean(f.uplink[d] * 100, 0),
                "tower_online": [int(x) for x in f.tower_online[dev.tower_idx]],
                "farm_battery": farm_med["battery"],
                "farm_temp_c": farm_med["temp_c"],
                "farm_signal_dbm": farm_med["signal_dbm"],
                "farm_hdop": farm_med["hdop"],
            },
        }

    # ---- triage -----------------------------------------------------------------------------------
    def ticket_row(t) -> dict:
        s = S()
        sug = s.suggestions[t.id]
        dec = s.decisions.get(t.id)
        return {
            "id": t.id,
            "received_at": t_iso(t.received_hour),
            "sender": t.sender,
            "subject": t.subject,
            "farm": sug.link["farm_name"],
            "category": sug.category,
            "article_id": sug.article_id,
            "escalate": sug.escalate,
            "guard_hits": len(sug.guard_hits),
            "mode": sug.mode,
            "status": dec["action"] if dec else "awaiting review",
        }

    @app.get("/api/tickets")
    def tickets() -> list[dict]:
        return [ticket_row(t) for t in reversed(S().tickets)]

    @app.get("/api/tickets/{tid}")
    def ticket(tid: str) -> dict:
        s = S()
        t = next((x for x in s.tickets if x.id == tid), None)
        if t is None:
            raise HTTPException(404, "ticket not found")
        sug = s.suggestions[tid].to_dict()
        kb = by_id(load_kb())[sug["article_id"]]
        return {
            **ticket_row(t),
            "body": t.body,
            "suggestion": sug,
            "article": {"id": kb.id, "title": kb.title, "body": kb.body},
            "decision": s.decisions.get(tid),
        }

    @app.post("/api/tickets/{tid}/decision")
    def decide(tid: str, body: Decision) -> dict:
        s = S()
        if tid not in s.suggestions:
            raise HTTPException(404, "ticket not found")
        s.decisions[tid] = {
            "action": body.action,
            "draft": body.draft if body.draft is not None else s.suggestions[tid].draft,
            "note": body.note,
            "decided_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        s.save_decisions()
        return {"ok": True, "sent": False, "decision": s.decisions[tid]}

    @app.get("/api/kb")
    def kb_list() -> list[dict]:
        return [{"id": a.id, "title": a.title, "category": a.category, "escalate": a.escalate} for a in load_kb()]

    # ---- alerts -----------------------------------------------------------------------------------
    @app.get("/api/alerts")
    def alerts(fmt: Literal["json", "slack", "telegram"] = Query("json", alias="format")) -> list[dict]:
        s = S()
        return [render(p, fmt) for p in notifications(s.fleet, s.incidents)]

    @app.post("/api/mock/webhook")
    async def mock_webhook(request: Request) -> dict:
        S().webhook_inbox.append(await request.json())
        return {"ok": True, "received": len(S().webhook_inbox)}

    @app.get("/api/mock/webhook")
    def mock_inbox() -> list[dict]:
        return S().webhook_inbox

    @app.get("/api/evaluation")
    def evaluation() -> dict:
        out = {}
        for name in ("detection", "triage", "triage_no_model"):
            p = RESULTS / f"{name}.json"
            if p.exists():
                out[name] = json.loads(p.read_text(encoding="utf-8"))
        return out

    # ---- dashboard --------------------------------------------------------------------------------
    if WEB_DIST.exists():
        app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            target = WEB_DIST / path
            if path and target.is_file() and Path(target).resolve().is_relative_to(WEB_DIST.resolve()):
                return FileResponse(target)
            return FileResponse(WEB_DIST / "index.html")

    return app


app = create_app()
