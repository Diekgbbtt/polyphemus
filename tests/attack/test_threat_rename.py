"""Contract tier: the ranked research artifact is a threat, not a loop.

The operator retired "loop" as the domain name on 2026-10-25. This test is the
rename guard: the public entity, the model section, the derived id, and the
store seam all carry the new vocabulary, and the stored document carries no
`loops` key.
"""
from __future__ import annotations

from polymerhus.attack.hunting.threat_model import (
    Threat,
    UnitThreatModel,
    normalise_threats,
)
from polymerhus.attack.hunting.threat_model_store import ThreatModelStore
from tests.hunting_fixtures import produce_model, threat_row

PROJECT = "proj-1"
RUN = "run-1"
UNIT = "Service:slug:a"


def test_the_public_entity_and_normaliser_use_the_threat_name():
    assert Threat.__name__ == "Threat"
    assert callable(normalise_threats)
    fields = UnitThreatModel.model_fields
    assert "threats" in fields
    assert "loops" not in fields


def test_a_completed_model_stores_threats_and_emits_threat_files(tmp_path):
    store = ThreatModelStore(tmp_path)
    produce_model(
        store, project_id=PROJECT, unit_id=UNIT, run_id=RUN,
        threats=[threat_row()],
    )

    model = store.read_model(PROJECT, UNIT)
    assert model["schema_version"] == 2
    assert [threat["id"] for threat in model["threats"]] == ["threat-1"]
    assert "loops" not in model

    records = store.read_threat_files(PROJECT, UNIT)
    assert [record["threat_id"] for record in records] == ["threat-1"]
    assert records[0]["threat"]["id"] == "threat-1"
