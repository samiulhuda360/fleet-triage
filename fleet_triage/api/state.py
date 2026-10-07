"""Application state: the replayed fleet, its incidents and the triage queue, built once at start-up."""

from __future__ import annotations

import json
import os
import warnings
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..detect.features import FleetFeatures
from ..detect.model import Incident
from ..detect.pipeline import DetectionResult, detect
from ..sim.fleet import Fleet
from ..sim.simulator import simulate
from ..triage.engine import Suggestion, Triage
from ..triage.evidence import FleetContext
from ..triage.llm import LLMClient
from ..triage.tickets import Ticket, load_tickets

ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = ROOT / "state"


def load_fleet(seed: int) -> Fleet:
    # Rebuilding from the seed takes about a second and gives exactly the fleet the evaluations score.
    return simulate(seed)


@dataclass
class AppState:
    fleet: Fleet
    feats: FleetFeatures
    result: DetectionResult
    tickets: list[Ticket]
    suggestions: dict[str, Suggestion]
    triage_mode: str
    reporting_pct: np.ndarray
    median_battery: np.ndarray
    decisions: dict[str, dict] = field(default_factory=dict)
    webhook_inbox: list[dict] = field(default_factory=list)
    state_dir: Path = STATE_DIR

    @property
    def incidents(self) -> list[Incident]:
        return self.result.incidents

    def incident(self, iid: str) -> Incident | None:
        return next((i for i in self.incidents if i.id == iid), None)

    def save_decisions(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        (self.state_dir / "decisions.json").write_text(json.dumps(self.decisions, indent=1), encoding="utf-8")


def build_state(seed: int | None = None, triage_mode: str | None = None, state_dir: Path = STATE_DIR) -> AppState:
    seed = int(seed if seed is not None else os.environ.get("FLEET_SEED", 7))
    fleet = load_fleet(seed)
    feats = FleetFeatures(fleet)
    result = detect(fleet, "rules+anomaly", feats)
    ctx = FleetContext(fleet, feats, result.incidents)

    # Model output is replayed from the cache; a live call happens only when TRIAGE_LIVE=1 and a key is set.
    mode = triage_mode or os.environ.get("TRIAGE_MODE", "llm")
    client = LLMClient(allow_live=os.environ.get("TRIAGE_LIVE") == "1") if mode == "llm" else None
    triage = Triage(ctx, client)
    tickets = sorted(load_tickets(fleet), key=lambda t: (t.received_hour, t.id))
    suggestions = {t.id: triage.suggest(t, mode) for t in tickets}  # type: ignore[arg-type]

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        reporting = fleet.reported.mean(axis=0) * 100
        med_batt = np.nanmedian(fleet.battery, axis=0)
    decisions: dict[str, dict] = {}
    path = state_dir / "decisions.json"
    if path.exists():
        decisions = json.loads(path.read_text(encoding="utf-8"))
    return AppState(
        fleet=fleet,
        feats=feats,
        result=result,
        tickets=tickets,
        suggestions=suggestions,
        triage_mode=mode,
        reporting_pct=reporting,
        median_battery=med_batt,
        decisions=decisions,
        state_dir=state_dir,
    )
