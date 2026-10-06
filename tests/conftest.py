from __future__ import annotations

import pytest

from fleet_triage.detect.features import FleetFeatures
from fleet_triage.detect.pipeline import detect
from fleet_triage.sim.simulator import simulate
from fleet_triage.triage.evidence import FleetContext


@pytest.fixture(scope="session")
def fleet():
    return simulate(7)


@pytest.fixture(scope="session")
def feats(fleet):
    return FleetFeatures(fleet)


@pytest.fixture(scope="session")
def rules_result(fleet, feats):
    return detect(fleet, "rules", feats)


@pytest.fixture(scope="session")
def ctx(fleet, feats, rules_result):
    return FleetContext(fleet, feats, rules_result.incidents)
