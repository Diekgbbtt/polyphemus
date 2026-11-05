"""Integration tier: one v5 model walks from the assessment to the dispatch queue.

Catalogue: `docs/design/cvss4-risk-scoring-spec.md` "Testing Decisions" - the
coverage shape's integration row (the `assess_impact` tool over the real store,
then one `decide` walk with a one-threat unit and a four-threat unit) joined to
its E2E row (one scripted modeller walk that writes the assessment, reads the
score back, and dispatches the threat through the queue). Impact map section 11
is the migration this walks: schema 5, the derived score, the mirrored threat.

Everything below the scripted actor is production code: a temporary project
root, the real `ThreatModelStore`, the real `assess_impact` tool, the real
produced-threat inbox read, the mover's own validity predicate, and the real
pure queue. The LLM edge is a scripted actor - no model provider runs.

The expected scores are the CVSS 4.0 base scores of the VECTORS, read from
independent sources and never recomputed with `risk_score`:

- 9.3 `critical` - the stored-XSS walkthrough vector, the NVD CVSS v4.0
  calculator's and CVE-2025-3651's score for
  `CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:P/VC:H/VI:H/VA:N/SC:H/SI:H/SA:N`;
- 6.9 and 5.3 `medium` - the NVD CVSS v4.0 calculator's score for the same
  vectors;
- 2.0 `low` - the CVSS 4.0 calculator's score for the same vector;
- 5.1 `medium` - the FIRST CVSS v4.0 Examples document, the stored-XSS "impact
  to the vulnerable application" variant of CVE-2022-24682.

The band is not a row field: it is the standard CVSS band of the score, and the
walkthrough reads it where the run reads it (the threat item and the profile).
"""
from __future__ import annotations

import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any, Sequence

from polymerhus.attack.hunting.mover import ThreatItem, threat_item
from polymerhus.attack.hunting.pipeline_sync import (
    SyncFacts,
    SyncMode,
    ThreatMeta,
    UnitMeta,
    decide,
    hunt_rank,
    order_threats,
)
from polymerhus.attack.hunting.risk_score import SeverityBand, severity_band
from polymerhus.attack.hunting.threat_model import ModelState
from polymerhus.attack.hunting.threat_model_store import ThreatModelStore
from polymerhus.attack.hunting.threat_modeller_tools import (
    ModellerAssessImpactTool,
)

PROJECT = "cvss4-walkthrough"
RUN = "run-1"

# The one-threat unit: a stored XSS in the article comment renderer. It is
# SECOND in intake, so a queue that admitted it first could only be ordering by
# risk - the intake position would put the four-threat unit ahead.
ARTICLE_UNIT = "Service:article-comments"
ARTICLE_UNIT_NAME = "Service-article-comments"
ARTICLE_INTAKE = 2

# The four-threat unit: FIRST in intake, one vulnerability with four assessed
# manners, every one of them below the article threat.
PROFILE_UNIT = "Service:profile-settings"
PROFILE_UNIT_NAME = "Service-profile-settings"
PROFILE_INTAKE = 1

ARTICLE_DISPATCH = f"{ARTICLE_UNIT_NAME}__threat-1"

# The article unit's row: a stored XSS that executes in another reader's
# session. `UI:P` is the reader opening the article they came to read, `AC:L` is
# the absence of a sanitizer on that render path, `PR:N` is the anonymous
# commenter, and `VC:H/VI:H` is the session credential the script reads and the
# page it rewrites. `VA:N` is the application staying up.
ARTICLE_FACTORS = {
    "attack_vector": "network",
    "attack_complexity": "low",
    "attack_requirements": "none",
    "privileges_required": "none",
    "user_interaction": "passive",
    "confidentiality": "high",
    "integrity": "high",
    "availability": "none",
}
ARTICLE_VECTOR = (
    "CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:P/VC:H/VI:H/VA:N/SC:H/SI:H/SA:N"
)
ARTICLE_RISK = 9.3

ARTICLE_ARGS = {
    "id": "IA-1",
    "vulnerability_ref": "V-1",
    "disposition": "threat",
    "impact_description": (
        "The stored script runs in every reader's session that opens the "
        "article: the reader's session credential is readable and a comment "
        "authored from that session can be rewritten in the reader's name."
    ),
    "exploitability_description": (
        "An unauthenticated commenter stores the payload; the server "
        "concatenates the stored body into the article page and renders it to "
        "every reader who opens the article, which is the routine reading flow "
        "and needs no action beyond reading; no sanitizer runs on that path."
    ),
    "capability": "run script in another reader's session",
    "capability_id": "P-1",
    "capability_path": [],
    "evidence_refs": ["POST /articles/1/comments", "GET /articles/1"],
    "factors": ARTICLE_FACTORS,
}

# The four-threat unit's rows in the order the model WRITES them: ascending
# risk, so the store's risk-descending normalisation is what puts them in
# dispatch rank rather than the write order.
SECOND_UNIT_ROWS: tuple[dict[str, Any], ...] = (
    {
        "args": {
            "id": "IA-1",
            "capability_id": "P-1",
            "impact_description": (
                "An administrator reads one access-log line outside their "
                "tenant."
            ),
            "exploitability_description": (
                "An administrator supplies a crafted filter; the export path "
                "has no tenant check, and the preview needs one deliberate "
                "click."
            ),
            "capability": "read one access-log line of another tenant",
            "factors": {
                "attack_vector": "network",
                "attack_complexity": "high",
                "attack_requirements": "present",
                "privileges_required": "high",
                "user_interaction": "passive",
                "confidentiality": "low",
                "integrity": "none",
                "availability": "none",
            },
        },
        "risk": 2.0,
        "band": SeverityBand.LOW,
        "vector": (
            "CVSS:4.0/AV:N/AC:H/AT:P/PR:H/UI:P/VC:L/VI:N/VA:N/SC:L/SI:N/SA:N"
        ),
    },
    {
        "args": {
            "id": "IA-2",
            "capability_id": "P-2",
            "impact_description": (
                "The crafted profile link runs script in the reader's session: "
                "the reader's own draft text is readable and editable."
            ),
            "exploitability_description": (
                "An unauthenticated attacker sends a crafted profile link; the "
                "renderer trusts the fragment, but the victim must click the "
                "link."
            ),
            "capability": "run script in one reader's session after a click",
            "factors": {
                "attack_vector": "network",
                "attack_complexity": "low",
                "attack_requirements": "none",
                "privileges_required": "none",
                "user_interaction": "active",
                "confidentiality": "low",
                "integrity": "low",
                "availability": "none",
            },
        },
        "risk": 5.1,
        "band": SeverityBand.MEDIUM,
        "vector": (
            "CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:A/VC:L/VI:L/VA:N/SC:L/SI:L/SA:N"
        ),
    },
    {
        "args": {
            "id": "IA-3",
            "capability_id": "P-3",
            "impact_description": (
                "One unpublished draft body is disclosed to a caller outside "
                "its owner's account."
            ),
            "exploitability_description": (
                "An unauthenticated caller names the draft id; the preview "
                "renderer returns the body without an ownership check, on a "
                "routine read."
            ),
            "capability": "read one private draft body",
            "factors": {
                "attack_vector": "network",
                "attack_complexity": "low",
                "attack_requirements": "none",
                "privileges_required": "none",
                "user_interaction": "passive",
                "confidentiality": "low",
                "integrity": "none",
                "availability": "none",
            },
        },
        "risk": 5.3,
        "band": SeverityBand.MEDIUM,
        "vector": (
            "CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:P/VC:L/VI:N/VA:N/SC:L/SI:N/SA:N"
        ),
    },
    {
        "args": {
            "id": "IA-4",
            "capability_id": "P-4",
            "impact_description": (
                "The saved card note of another user is disclosed to an "
                "anonymous caller."
            ),
            "exploitability_description": (
                "An unauthenticated caller calls the notes read with a "
                "guessable note id; the handler looks the note up by id alone, "
                "with no precondition and no victim action."
            ),
            "capability": "read another user's saved card note",
            "factors": {
                "attack_vector": "network",
                "attack_complexity": "low",
                "attack_requirements": "none",
                "privileges_required": "none",
                "user_interaction": "none",
                "confidentiality": "low",
                "integrity": "none",
                "availability": "none",
            },
        },
        "risk": 6.9,
        "band": SeverityBand.MEDIUM,
        "vector": (
            "CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:L/VI:N/VA:N/SC:L/SI:N/SA:N"
        ),
    },
)

# The queue the two units must produce: the one-threat 9.3 unit first despite
# being second in intake, then the four-threat unit's own risk order. No unit
# boundary appears in the list.
EXPECTED_QUEUE = [
    ARTICLE_DISPATCH,
    f"{PROFILE_UNIT_NAME}__threat-1",
    f"{PROFILE_UNIT_NAME}__threat-2",
    f"{PROFILE_UNIT_NAME}__threat-3",
    f"{PROFILE_UNIT_NAME}__threat-4",
]


def _evidence(ref: str) -> dict:
    return {"kind": "request", "ref": ref}


def _gate_sections() -> dict[ModelState, dict]:
    """The gate payloads both units are modelled with.

    The literal is the same for both units: every symbol in a model document is
    per-document, so the two units carry their own `IA-*`/`P-*` rows on this
    shared id skeleton. The order is the workflow order, so the last write
    leaves the document at `PRIOR_ART` - the state the assessment write
    accepts.
    """
    return {
        ModelState.UNIT_TECHNICAL_SHARP: {
            "technical_sharpening": {
                "interface_agreements": [{
                    "id": "IA-1",
                    "statement": (
                        "The comment form accepts a body from an anonymous "
                        "caller."
                    ),
                    "confidence": "OBSERVED",
                    "evidences": [_evidence("POST /articles/1/comments")],
                }],
                "control_flows": [{
                    "id": "CF-1",
                    "statement": (
                        "The handler authorises the caller before it stores "
                        "the body."
                    ),
                    "confidence": "INFERRED",
                    "evidences": [_evidence("framework default")],
                }],
                "data_flows": [{
                    "id": "DF-1",
                    "statement": (
                        "The stored body is concatenated into the article "
                        "page."
                    ),
                    "confidence": "OBSERVED",
                    "evidences": [_evidence("GET /articles/1")],
                }],
            },
        },
        ModelState.TRUST_MODELLED: {
            "trust_model": {
                "trust_agreements": [{
                    "id": "TA-1",
                    "boundary": "anonymous commenter -> stored comment body",
                    "interface_agreement_refs": ["IA-1"],
                    "statement": "The render path trusts the stored body as markup.",
                    "confidence": "INFERRED",
                    "evidences": [_evidence("GET /articles/1")],
                }],
                "dynamic_state_trust": {
                    "states": [{
                        "id": "DS-1",
                        "variables": ["comment_body"],
                        "confidence": "OBSERVED",
                        "evidences": [_evidence("POST /articles/1/comments")],
                    }],
                },
            },
        },
        ModelState.TRUST_ASSUMPTIONS_WRITTEN: {
            "assumptions": [{
                "id": "AS-1",
                "statement": "The render path escapes nothing on the article page.",
                "fault": {
                    "id": "F-1",
                    "label": "unescaped stored markup",
                    "description": (
                        "The stored comment body reaches the article page as "
                        "markup."
                    ),
                },
                "boundary_ref": "TA-1",
                "confidence": "ASSUMED",
                "evidences": [_evidence("note:article-render")],
            }],
        },
        ModelState.VULNERABILITIES_WRITTEN: {
            "vulnerabilities": [{
                "id": "V-1",
                "fault_ref": "F-1",
                "canonical_class": "CrossSiteScripting",
                "web_vulnerability_class": "stored-xss",
                "characterisation": (
                    "A stored comment body runs as script in another reader's "
                    "session."
                ),
                "evidences": [_evidence("GET /articles/1")],
            }],
        },
        ModelState.PRIOR_ART: {
            "prior_art": {
                "queries": [
                    {
                        "kind": "threat",
                        "filters": [{
                            "path": "threat.web_vulnerability_class",
                            "regex": "stored-xss",
                            "flags": "i",
                        }],
                        "result_count": 0,
                    },
                    {
                        "kind": "vulnerability",
                        "filters": [{
                            "path": "canonical_class",
                            "regex": "CrossSiteScripting",
                            "flags": "i",
                        }],
                        "result_count": 0,
                    },
                    {
                        "kind": "precursor",
                        "filters": [{
                            "path": "capability",
                            "regex": "session",
                            "flags": "i",
                        }],
                        "result_count": 0,
                    },
                ],
                "reused": [],
                "notes": "No prior model held a stored-XSS claim for this unit.",
            },
        },
    }


class _ScriptedModeller:
    """The scripted stand-in for the modeller's LLM edge.

    No model provider runs: the actor holds the `assess_impact` args a modeller
    would emit, in the order it would emit them, and replays each through the
    REAL tool bound to the real store. The response is the tool's own envelope -
    the actor never sees or feeds back a score.
    """

    def __init__(self, calls: Sequence[dict]):
        self._calls = list(calls)

    def assess(self, tool: ModellerAssessImpactTool) -> list[dict]:
        return [tool.invoke(dict(call)) for call in self._calls]


def _write_gates(store: ThreatModelStore, unit_id: str) -> None:
    """The five model-facing gates below the assessment write.

    The last gate leaves the document at `PRIOR_ART`, the state the assessment
    write accepts; the caller observes that before the tool call.
    """
    for state, sections in _gate_sections().items():
        store.write_sections(PROJECT, unit_id, state, sections, run_id=RUN)


def _assess(
    store: ThreatModelStore, unit_id: str, rows: Sequence[dict],
) -> list[dict]:
    """Replay the scripted actor's rows through the REAL `assess_impact` tool.

    Returns the merged tool calls: the per-document referential frame plus each
    row's own id, prose, capability, factors, and evidence. The success envelope
    is asserted for every call; the actor never sees or feeds back a score.
    """
    calls = [
        {
            "vulnerability_ref": "V-1",
            "disposition": "threat",
            "capability_path": [],
            "evidence_refs": ["GET /articles/1"],
            **row,
        }
        for row in rows
    ]
    tool = ModellerAssessImpactTool(
        store=store, project_id=PROJECT, unit_id=unit_id, run_id=RUN)
    for response in _ScriptedModeller(calls).assess(tool):
        assert response["ok"] is True
        # The success envelope carries the coverage signal (2026-11-05) and
        # never echoes the derived score, the vector, or a factor echo.
        assert set(response) == {"ok", "hint", "residual_vulnerabilities"}
        assert not ({"risk", "risk_vector", "factors"} & set(response))
    return calls


def _complete(
    store: ThreatModelStore, unit_id: str, calls: Sequence[dict],
) -> None:
    """The COMPLETED write: one threat per assessment row, in the row order the
    caller supplied, so the store's risk-descending ranking has something to
    reorder."""
    threats = [
        {
            "fault_ref": "F-1",
            "vulnerability_ref": "V-1",
            "canonical_class": "CrossSiteScripting",
            "web_vulnerability_class": "stored-xss",
            "impact_ref": call["id"],
            "enabling_precursors": list(call["capability_path"]),
            "evidences": [_evidence("GET /articles/1")],
        }
        for call in calls
    ]
    store.write_sections(
        PROJECT, unit_id, ModelState.COMPLETED, {"threats": threats}, run_id=RUN)


def _assert_completion_clean(
    store: ThreatModelStore, unit_id: str,
) -> dict:
    """The COMPLETED model's completion check is clean and it is consumable."""
    model = store.read_model(PROJECT, unit_id)
    assert model["state"] == ModelState.COMPLETED.value
    validation = model["validation"]
    assert validation["valid"] is True
    assert validation["missing"] == []
    assert validation["unclosed"] == []
    assert validation["referential_errors"] == []
    assert validation["class_findings"] == []
    # The consumability predicate the mover reads: the produced inbox returns
    # the unit with its threat files, never a model the store would refuse.
    entries = {
        entry["unit_id"]: entry
        for entry in store.read_produced_threats(PROJECT)
    }
    assert unit_id in entries
    assert entries[unit_id]["threats"]
    return model


def _threat_items(store: ThreatModelStore) -> list[ThreatItem]:
    """The produced inbox read, through the mover's own validity predicate."""
    items: list[ThreatItem] = []
    for entry in store.read_produced_threats(PROJECT):
        for threat in entry["threats"]:
            item = threat_item(
                project_id=PROJECT,
                unit_id=entry["unit_id"],
                unit_name=entry["unit_name"],
                threat_id=threat["threat_id"],
                record=threat["record"],
                run_id=RUN,
                model=entry["model"],
            )
            assert item is not None, threat["threat_id"]
            items.append(item)
    return items


def _queue_metas(store: ThreatModelStore) -> tuple[ThreatMeta, ...]:
    """The queue metadata as the sync gate builds it: the COMPLETED model's
    mirrored threat risk, the unit's intake position, and the dispatch rank."""
    units = [
        UnitMeta(unit_name=ARTICLE_UNIT_NAME, unit_id=ARTICLE_UNIT,
                 intake_position=ARTICLE_INTAKE),
        UnitMeta(unit_name=PROFILE_UNIT_NAME, unit_id=PROFILE_UNIT,
                 intake_position=PROFILE_INTAKE),
    ]
    metas: list[ThreatMeta] = []
    for unit in units:
        model = store.read_model(PROJECT, unit.unit_id)
        assert model["state"] == ModelState.COMPLETED.value
        for threat in model["threats"]:
            dispatch = f"{unit.unit_name}__{threat['id']}"
            metas.append(ThreatMeta(
                dispatch_id=dispatch,
                unit_name=unit.unit_name,
                risk=float(threat["risk"]),
                intake_position=unit.intake_position,
                rank=hunt_rank(dispatch),
            ))
    return tuple(metas)


def test_one_v5_model_walks_from_the_assessment_to_the_dispatch_queue():
    """The whole chain on real artefacts: a v5 model at `PRIOR_ART`, the
    `assess_impact` write deriving the vector's score, the COMPLETED threat file
    mirroring it, the clean completion check, and the pure queue admitting the
    one-threat 9.3 unit before a four-threat unit that is earlier in intake."""
    with tempfile.TemporaryDirectory(prefix="cvss4-walkthrough-") as root:
        root_path = Path(root)
        store = ThreatModelStore(root_dir=root_path)

        # 1. The article unit's model, written up to PRIOR_ART.
        _write_gates(store, ARTICLE_UNIT)
        assert store.read_model(PROJECT, ARTICLE_UNIT)["state"] == (
            ModelState.PRIOR_ART.value)
        assert (root_path / PROJECT / "hunting" / "threat_modeller").is_dir()

        # 2. The assessment row the tool wrote: the score and the mirrored
        # vector are the CVSS 4.0 values of the authored factors, and the state
        # advanced on the first successful write.
        article_calls = _assess(store, ARTICLE_UNIT, [ARTICLE_ARGS])
        model = store.read_model(PROJECT, ARTICLE_UNIT)
        assert model["state"] == ModelState.IMPACT_ASSESSED.value
        assert len(model["impact_assessment"]) == 1
        row = model["impact_assessment"][0]
        assert row["id"] == "IA-1"
        assert row["risk"] == ARTICLE_RISK
        assert row["risk_vector"] == ARTICLE_VECTOR
        assert severity_band(row["risk"]) is SeverityBand.CRITICAL

        # 3. The COMPLETED threat file references the row and mirrors its
        # float risk; the retired likelihood / confidence / impact-weight
        # vocabulary is absent from the threat record.
        _complete(store, ARTICLE_UNIT, article_calls)
        article_model = _assert_completion_clean(store, ARTICLE_UNIT)
        assert article_model["risk_profile"]["total"] == ARTICLE_RISK
        assert article_model["risk_profile"]["breakdown"]["critical"] == 1
        files = store.read_threat_files(PROJECT, ARTICLE_UNIT)
        assert [record["threat_id"] for record in files] == ["threat-1"]
        record = files[0]
        assert record["dispatch_id"] == ARTICLE_DISPATCH
        assert isinstance(record["risk"], float)
        assert record["risk"] == ARTICLE_RISK
        assert record["impact"]["impact_ref"] == "IA-1"
        assert record["impact"]["risk"] == ARTICLE_RISK
        assert record["impact"]["risk_vector"] == ARTICLE_VECTOR
        for retired in (
            "likelihood", "likelihood_rationale", "risk_factors", "confidence",
            "impact", "impact_weight",
        ):
            assert retired not in record["threat"]

        # 4. The four-threat unit, written ascending, so the store's
        # risk-descending normalisation is what ranks it.
        _write_gates(store, PROFILE_UNIT)
        profile_calls = _assess(
            store, PROFILE_UNIT, [entry["args"] for entry in SECOND_UNIT_ROWS])
        persisted_rows = store.read_model(PROJECT, PROFILE_UNIT)[
            "impact_assessment"]
        for entry in SECOND_UNIT_ROWS:
            row = next(
                persisted for persisted in persisted_rows
                if persisted["id"] == entry["args"]["id"]
            )
            assert row["risk"] == entry["risk"]
            assert row["risk_vector"] == entry["vector"]
            assert severity_band(row["risk"]) is entry["band"]

        _complete(store, PROFILE_UNIT, profile_calls)

        # The store renumbered the four threats into risk-descending rank, so
        # the dispatch rank carries the score and not the write order.
        profile_model = _assert_completion_clean(store, PROFILE_UNIT)
        assert [threat["risk"] for threat in profile_model["threats"]] == [
            6.9, 5.3, 5.1, 2.0]
        assert [threat["id"] for threat in profile_model["threats"]] == [
            "threat-1", "threat-2", "threat-3", "threat-4"]
        assert profile_model["risk_profile"] == {
            "total": 19.3,
            "breakdown": {
                "none": 0, "low": 1, "medium": 3, "high": 0, "critical": 0,
            },
        }

        # 5. The global queue: every promoted threat, ordered by risk. The
        # article unit is SECOND in intake and still heads it.
        items = _threat_items(store)
        assert len(items) == 5
        assert {item.dispatch_id for item in items} == set(EXPECTED_QUEUE)
        article_item = next(
            item for item in items if item.dispatch_id == ARTICLE_DISPATCH)
        assert article_item.risk == ARTICLE_RISK
        assert article_item.band == SeverityBand.CRITICAL.value

        metas = _queue_metas(store)
        assert [meta.dispatch_id for meta in order_threats(metas)] == (
            EXPECTED_QUEUE)

        units = [
            UnitMeta(unit_name=PROFILE_UNIT_NAME, unit_id=PROFILE_UNIT,
                     intake_position=PROFILE_INTAKE),
            UnitMeta(unit_name=ARTICLE_UNIT_NAME, unit_id=ARTICLE_UNIT,
                     intake_position=ARTICLE_INTAKE),
        ]
        facts = SyncFacts(threats=metas)
        admitted = decide(SyncMode.BATCHED, items, units, facts)
        assert admitted == {ARTICLE_DISPATCH}

        # No per-unit cap: the queue holds all four of the profile unit's
        # threats, and draining it admits each one in its risk turn.
        remaining = list(items)
        drained: list[str] = []
        for _ in range(len(items)):
            chosen = decide(SyncMode.BATCHED, remaining, units, facts)
            assert len(chosen) == 1
            dispatch = next(iter(chosen))
            drained.append(dispatch)
            remaining = [
                item for item in remaining if item.message_id != dispatch]
            facts = replace(
                facts, terminal_hunts=facts.terminal_hunts | {dispatch})
        assert drained == EXPECTED_QUEUE

    # 6. The temporary project root is gone: the walkthrough left nothing
    # behind outside its own temp tree.
    assert not root_path.exists()
