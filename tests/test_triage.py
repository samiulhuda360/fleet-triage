from __future__ import annotations

import pytest

from fleet_triage.triage.bm25 import BM25, tokenize
from fleet_triage.triage.engine import Triage
from fleet_triage.triage.evidence import Evidence
from fleet_triage.triage.guards import check_draft, check_promises
from fleet_triage.triage.kb import load_kb
from fleet_triage.triage.linking import link_ticket
from fleet_triage.triage.llm import LLMClient
from fleet_triage.triage.tickets import load_tickets


@pytest.fixture(scope="module")
def tickets(fleet):
    return {t.id: t for t in load_tickets(fleet)}


def test_kb_has_twelve_articles():
    kb = load_kb()
    assert len(kb) == 12 and len({a.category for a in kb}) == 12


def test_ticket_counts(tickets):
    assert sum(t.split == "dev" for t in tickets.values()) == 60
    assert sum(t.split == "heldout" for t in tickets.values()) == 15


def test_bm25_ranks_the_obvious_article():
    kb = load_kb()
    idx = BM25([a.search_text for a in kb])
    s = idx.scores("how do I find my invoice and the number of collars billed")
    assert kb[max(range(len(kb)), key=s.__getitem__)].category == "billing"
    assert "battery" in tokenize("collar went flat")


def test_linking_by_email_and_collar(fleet, tickets):
    t = tickets["D-08"]
    link = link_ticket(fleet, t.sender, t.text)
    assert fleet.farms[link.farm_idx].id == t.farm_id
    assert [fleet.devices[d].id for d in link.device_idxs] == t.device_ids


def test_linking_by_farm_name_from_unknown_sender(fleet, tickets):
    t = tickets["D-03"]
    link = link_ticket(fleet, t.sender, t.text)
    assert fleet.farms[link.farm_idx].id == t.farm_id


def test_promise_guard():
    assert check_promises("We will replace it by tomorrow and refund you.")
    assert not check_promises("I have passed the details to our field operations team.")


def test_fact_guard_rejects_invented_collars_and_numbers():
    ev = Evidence(facts=["Collar C-10001 (firmware 3.4.1, tower T-01): battery 40 %; night drain 0.9 %/h."])
    assert check_draft("Collar C-10001 is at 40 %.", ev, "") == []
    hits = check_draft("Collar C-19999 on firmware 3.5.0 is at 12 %.", ev, "")
    assert any("C-19999" in h for h in hits)
    assert any("3.5.0" in h for h in hits)
    assert any("12" in h for h in hits)


def test_device_data_overrides_the_farmers_guess(ctx, tickets):
    # D-08 asks "is it the cloud?" but the collar's night drain says battery fade
    s = Triage(ctx).suggest(tickets["D-08"], "rules")
    assert s.article_id == "KB-02" and s.escalate
    assert s.status == "awaiting review"
    assert s.guard_hits == []


def test_llm_mode_without_a_model_falls_back(ctx, tickets, tmp_path):
    client = LLMClient(api_key="", cache_dir=tmp_path, allow_live=False)
    s = Triage(ctx, client).suggest(tickets["D-51"], "llm")
    assert s.fell_back and s.article_id == "KB-10"
