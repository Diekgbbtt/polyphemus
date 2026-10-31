"""Unit tier: the prior-art query over the real threat-model store (ticket 437).

The query contract of S2 section 7: a `hunts_store` `cmd='query'` with a
required `kind`, a non-empty `filters` list of `{path, regex, flags}`, and a
`limit`. The filters are AND, each is a `re.search` over the value at the
dotted path, `*` iterates a list, a dict value is matched on its JSON string,
and a missing path is no match. An empty filter list, an invalid regex, and an
unknown path are coded teaching rejections.

Every test drives the REAL `ThreatModelStore` on a temporary project root and
the REAL bound tool surface; the records are known-good literals, never a
recomputation through the implementation.
"""
from __future__ import annotations

import yaml

from polymerhus.attack.hunting.threat_model import ModelState
from polymerhus.attack.hunting.threat_model_store import (
    ThreatModelStore,
    sanitise_unit_name,
)
from polymerhus.attack.hunting.threat_modeller_tools import (
    ModellerTools,
    build_modeller_tool_surface,
)

from tests.hunting_fixtures import produce_model

PROJECT = "proj-1"
OTHER_PROJECT = "proj-2"
RUN = "run-1"
PRIOR_RUN = "run-0"

SIGN_IN = "Service:sign-in"
ADMIN = "Service:admin-console"
CATALOGUE = "Service:catalogue-and-discovery"
UNBOUND = "Service:boundary-probe"
OTHER = "Service:other-project-unit"

# The known-good capability/procedure literals (S2 section 7's example).
SESSION_CAPABILITY = "recover a live session from the dump"
SESSION_PROCEDURE = "read live session material from the process dump"
CREDENTIAL_CAPABILITY = "exchange the credential for a session token"
CREDENTIAL_PROCEDURE = (
    "mint a token from the credential the caller presents")
ITEM_CAPABILITY = "read another tenant's item"
ITEM_PROCEDURE = (
    "resolve the item by the identifier the caller supplies")
ITEM_DAMAGE = (
    "An anonymous caller reads another tenant's item from the catalogue "
    "database."
)


def _seed_in_progress(
    store: ThreatModelStore,
    *,
    unit: str,
    capability: str,
    procedure: str,
    project: str = PROJECT,
    evidence_refs: tuple[str, ...] = ("exec:api-35",),
    canonical_class: str = "session-fixation",
    web_vulnerability_class: str = "session-management",
    statement: str = "The handler assumes the session is fresh after login.",
    fault_label: str = "session reuse across the login boundary",
    disposition: str = "precursor",
    damage: str = (
        "The attacker reads live session material from the process dump."),
) -> None:
    """One produced, IN-PROGRESS model (state IMPACT_ASSESSED): the store's own
    gate writes carry the assumptions, the vulnerabilities, and the impact rows
    with their precursor entities. A produced model may be partial, and the
    query must still read it."""
    row = {
        "id": "ia-1",
        "vulnerability_ref": "v-1",
        "disposition": disposition,
        "impact_description": damage,
        "exploitability_description": (
            "One unauthenticated request reaches the handler."),
        "capability": capability,
        "capability_id": "p-1",
        "capability_path": [],
        "evidence_refs": list(evidence_refs),
        "factors": {
            "attack_vector": "network",
            "attack_complexity": "low",
            "attack_requirements": "none",
            "privileges_required": "none",
            "user_interaction": "none",
            "confidentiality": "none",
            "integrity": "none",
            "availability": "none",
        },
        "risk": 0.0,
        "risk_vector": (
            "CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:N/VI:N/VA:N/SC:N/SI:N/SA:N"),
    }
    store.write_sections(project, unit, ModelState.TRUST_ASSUMPTIONS_WRITTEN, {
        "assumptions": [{
            "id": "as-1",
            "statement": statement,
            "fault": {
                "id": "f-1",
                "label": fault_label,
                "description": "The handler trusts the supplied value.",
            },
            "boundary_ref": "ta-1",
            "confidence": "ASSUMED",
            "evidences": [{"kind": "note", "ref": "note:prior"}],
        }],
    }, run_id=PRIOR_RUN)
    path = store.write_sections(project, unit, ModelState.VULNERABILITIES_WRITTEN, {
        "vulnerabilities": [{
            "id": "v-1",
            "fault_ref": "f-1",
            "canonical_class": canonical_class,
            "web_vulnerability_class": web_vulnerability_class,
            "characterisation": "The prior unit characterises this class.",
            "confidence": "INFERRED",
            "evidences": [{"kind": "request", "ref": "GET /prior"}],
        }],
    }, run_id=PRIOR_RUN)
    # The `assess_impact` tool (ticket #406) is the sole writer of a v5 row;
    # this fixture seeds the document it will write.
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["state"] = ModelState.IMPACT_ASSESSED.value
    document["impact_assessment"] = [row]
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


def _seed_completed(store: ThreatModelStore, *, unit: str = CATALOGUE) -> None:
    """One COMPLETED model with its threat file, through the real seven-gate
    ladder (the shared worked example: the tenant item read)."""
    produce_model(store, project_id=PROJECT, unit_id=unit, run_id=PRIOR_RUN)


def _query_tool(store: ThreatModelStore, *, unit: str = UNBOUND):
    tools = ModellerTools(threat_store=store, project_id=PROJECT, run_id=RUN)
    return build_modeller_tool_surface(PROJECT, unit, tools)["hunts_store"]


def _query(store: ThreatModelStore, *, unit: str = UNBOUND, **args) -> dict:
    return _query_tool(store, unit=unit).invoke({"cmd": "query", **args})


def _two_prior_units(store: ThreatModelStore) -> None:
    _seed_in_progress(
        store, unit=SIGN_IN, capability=SESSION_CAPABILITY,
        procedure=SESSION_PROCEDURE)
    _seed_in_progress(
        store, unit=ADMIN, capability=CREDENTIAL_CAPABILITY,
        procedure=CREDENTIAL_PROCEDURE,
        canonical_class="credential-reuse",
        statement="The handler assumes the credential is single-use.",
        fault_label="credential accepted without a freshness check",
        damage="The attacker replays the credential to mint a session token.")


def _write_raw_consumed(
    tmp_path, unit: str, document: dict, *, project: str = PROJECT,
) -> None:
    """A hand-written consumed model document: the missing-path fixture needs a
    record that omits an optional key, which the typed gate write never does."""
    name = sanitise_unit_name(unit)
    directory = (
        tmp_path / project / "hunting" / "threat_modeller" / "consumed" / name)
    directory.mkdir(parents=True)
    (directory / f"{name}.yaml").write_text(
        yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


# --- the filter semantics -----------------------------------------------------

def test_the_query_applies_and_across_filters_and_matches_each_value(tmp_path):
    """Two filters are AND: a record needs at least one matching value at EACH
    path. The credential precursor matches the capability filter but not the
    procedure filter, so only the session precursor survives."""
    store = ThreatModelStore(root_dir=tmp_path)
    _two_prior_units(store)

    result = _query(store, kind="precursor", filters=[
        {"path": "capability", "regex": "SESSION|CREDENTIAL", "flags": "i"},
        {"path": "impact_description", "regex": "dump", "flags": ""},
    ])

    assert result["count"] == 1
    assert result["truncated"] is False
    match = result["matches"][0]
    assert match["unit_id"] == SIGN_IN
    assert match["record_id"] == "ia-1"
    assert match["matched"] == [
        {"path": "capability", "value": SESSION_CAPABILITY},
        {"path": "impact_description", "value": "The attacker reads live session material from the process dump."},
    ]


def test_the_flags_select_case_sensitivity(tmp_path):
    store = ThreatModelStore(root_dir=tmp_path)
    _two_prior_units(store)
    filters = [{"path": "capability", "regex": "SESSION FROM THE DUMP"}]

    insensitive = _query(store, kind="precursor", filters=[
        {**filters[0], "flags": "i"}])
    sensitive = _query(store, kind="precursor", filters=[
        {**filters[0], "flags": ""}])

    assert insensitive["count"] == 1
    assert sensitive["count"] == 0


def test_the_star_traverses_a_list_of_records(tmp_path):
    """`impact.evidence_refs` is a list; `*` iterates it and matches one ref."""
    store = ThreatModelStore(root_dir=tmp_path)
    _seed_completed(store)

    result = _query(store, kind="threat", filters=[
        {"path": "threat.evidences.*.ref", "regex": "catalogue", "flags": "i"}])

    assert result["count"] == 1
    match = result["matches"][0]
    assert match["unit_id"] == CATALOGUE
    assert match["record_id"] == "threat-1"
    assert match["matched"][0]["path"] == "threat.evidences.*.ref"


def test_a_missing_path_is_no_match_not_a_rejection(tmp_path):
    """A catalog path that the record does not carry is a no match; an unknown
    path is the rejection (tested below)."""
    store = ThreatModelStore(root_dir=tmp_path)
    _write_raw_consumed(tmp_path, OTHER, {
        "schema_version": 4,
        "unit_id": OTHER,
        "unit_kind": "service",
        "run_id": PRIOR_RUN,
        "state": "COMPLETED",
        # the assumption omits boundary_ref entirely
        "assumptions": [{
            "id": "as-1",
            "statement": "The handler trusts the boundary marker.",
            "fault": {
                "id": "f-1",
                "label": "unverified boundary marker",
                "description": "The handler never re-checks the marker.",
            },
            "confidence": "ASSUMED",
            "evidences": [],
        }],
    })

    missing = _query(store, kind="assumption", filters=[
        {"path": "boundary_ref", "regex": "."}])
    present = _query(store, kind="assumption", filters=[
        {"path": "statement", "regex": "trusts"}])

    assert missing["count"] == 0
    assert present["count"] == 1
    assert present["matches"][0]["record_id"] == "as-1"


def test_a_dict_value_is_matched_on_its_json_string(tmp_path):
    """A path that resolves to a dict (the assumption's fault) is searched on
    its JSON string, not on a Python repr."""
    store = ThreatModelStore(root_dir=tmp_path)
    _write_raw_consumed(tmp_path, OTHER, {
        "schema_version": 4,
        "unit_id": OTHER,
        "state": "COMPLETED",
        "assumptions": [{
            "id": "as-1",
            "statement": "The handler trusts the boundary marker.",
            "fault": {
                "id": "f-1",
                "label": "unverified boundary marker",
                "description": "The handler never re-checks the marker.",
            },
            "confidence": "ASSUMED",
            "evidences": [],
        }],
    })

    result = _query(store, kind="assumption", filters=[
        {"path": "fault", "regex": '"label": "unverified boundary marker"'}])

    assert result["count"] == 1
    assert result["matches"][0]["matched"][0]["path"] == "fault"


# --- the coded teaching rejections -------------------------------------------

def test_an_invalid_regex_is_a_coded_teaching_rejection(tmp_path):
    store = ThreatModelStore(root_dir=tmp_path)
    _two_prior_units(store)

    result = _query(store, kind="precursor", filters=[
        {"path": "capability", "regex": "session["}])

    assert result["ok"] is False
    assert result["error"] == "hunts_store_query_rejected"
    assert result["fields"] == ["filters[0].regex"]
    assert result["rejected"] is True
    assert "session[" in result["detail"]


def test_an_unknown_path_is_a_coded_teaching_rejection(tmp_path):
    store = ThreatModelStore(root_dir=tmp_path)
    _two_prior_units(store)

    result = _query(store, kind="precursor", filters=[
        {"path": "canonical_class", "regex": "session"}])

    assert result["ok"] is False
    assert result["error"] == "hunts_store_query_rejected"
    assert result["fields"] == ["filters[0].path"]
    assert "canonical_class" in result["detail"]
    assert "capability" in result["detail"]


def test_an_empty_filter_list_is_a_coded_teaching_rejection(tmp_path):
    """An empty filter list dumps the store, so it is refused - both an omitted
    list and an explicitly empty one."""
    store = ThreatModelStore(root_dir=tmp_path)
    _two_prior_units(store)

    omitted = _query(store, kind="precursor")
    empty = _query(store, kind="precursor", filters=[])

    for result in (omitted, empty):
        assert result["ok"] is False
        assert result["error"] == "hunts_store_query_rejected"
        assert result["fields"] == ["filters"]
        assert "filter" in result["detail"]


def test_a_missing_or_unknown_kind_is_a_coded_teaching_rejection(tmp_path):
    store = ThreatModelStore(root_dir=tmp_path)
    filters = [{"path": "capability", "regex": "session"}]

    missing = _query(store, filters=filters)
    unknown = _query(store, kind="loop", filters=filters)

    for result in (missing, unknown):
        assert result["ok"] is False
        assert result["error"] == "hunts_store_query_rejected"
        assert result["fields"] == ["kind"]
    for kind in ("threat", "vulnerability", "precursor", "assumption", "impact"):
        assert kind in unknown["detail"]


# --- the scope: the project, the bound unit, both families --------------------

def test_the_query_excludes_the_bound_unit_unless_a_unit_id_filter_names_it(
        tmp_path):
    store = ThreatModelStore(root_dir=tmp_path)
    _two_prior_units(store)
    filters = [{"path": "capability", "regex": "session|credential",
                "flags": "i"}]

    excluded = _query(store, unit=SIGN_IN, kind="precursor", filters=filters)
    named = _query(store, unit=SIGN_IN, kind="precursor", filters=[
        *filters, {"path": "unit_id", "regex": "^Service:sign-in$"}])

    assert [match["unit_id"] for match in excluded["matches"]] == [ADMIN]
    assert [match["unit_id"] for match in named["matches"]] == [SIGN_IN]
    assert named["matches"][0]["record_id"] == "ia-1"


def test_the_query_reads_produced_and_consumed_and_returns_the_state(tmp_path):
    """A produced model may be partial (IMPACT_ASSESSED here); a consumed model
    is complete. Both are read, and each match carries its model's state."""
    store = ThreatModelStore(root_dir=tmp_path)
    _seed_in_progress(
        store, unit=SIGN_IN, capability=SESSION_CAPABILITY,
        procedure=SESSION_PROCEDURE)
    _seed_completed(store)
    assert store.consume_threat(PROJECT, CATALOGUE, "threat-1") is True

    precursor = _query(store, kind="precursor", filters=[
        {"path": "capability", "regex": "session", "flags": "i"}])
    threat = _query(store, kind="threat", filters=[
        {"path": "impact.capability", "regex": "item", "flags": "i"}])

    assert {match["unit_id"]: match["state"] for match in precursor["matches"]} == {
        SIGN_IN: ModelState.IMPACT_ASSESSED.value,
    }
    assert {match["unit_id"]: match["state"] for match in threat["matches"]} == {
        CATALOGUE: ModelState.COMPLETED.value,
    }


def test_the_query_is_project_scoped(tmp_path):
    store = ThreatModelStore(root_dir=tmp_path)
    _seed_in_progress(
        store, unit=SIGN_IN, capability=SESSION_CAPABILITY,
        procedure=SESSION_PROCEDURE)
    _seed_in_progress(
        store, project=OTHER_PROJECT, unit=OTHER,
        capability="recover a live session from the other project",
        procedure="read the other project's dump")

    result = _query(store, kind="precursor", filters=[
        {"path": "capability", "regex": "session"}])

    assert [match["unit_id"] for match in result["matches"]] == [SIGN_IN]


# --- the result shape --------------------------------------------------------

def test_the_matched_pairs_and_the_summary_shape(tmp_path):
    """The result names the unit, the record, the kind, the label, the class,
    the disposition, the summary, the state, the evidence refs, and the
    matched path/value pairs - never a full model."""
    store = ThreatModelStore(root_dir=tmp_path)
    _seed_in_progress(store, unit=SIGN_IN, capability=ITEM_CAPABILITY,
                      procedure=ITEM_PROCEDURE)

    result = _query(store, kind="precursor", filters=[
        {"path": "capability", "regex": f"^{ITEM_CAPABILITY}$"}])

    match = result["matches"][0]
    assert set(match) == {
        "unit_id", "record_id", "kind", "label", "web_vulnerability_class",
        "disposition", "summary", "state", "evidence_refs", "matched",
    }
    assert match["kind"] == "precursor"
    assert match["label"] == ITEM_CAPABILITY
    assert match["summary"] == "The attacker reads live session material from the process dump."
    assert match["disposition"] == "precursor"
    assert match["web_vulnerability_class"] == ""
    assert match["evidence_refs"] == ["exec:api-35"]
    assert match["matched"] == [
        {"path": "capability", "value": ITEM_CAPABILITY}]
    assert "precursors" not in match
    assert "threats" not in match
    assert "impact_assessment" not in match


def test_each_kind_reads_its_view(tmp_path):
    store = ThreatModelStore(root_dir=tmp_path)
    _two_prior_units(store)
    _seed_completed(store)

    vulnerability = _query(store, kind="vulnerability", filters=[
        {"path": "canonical_class", "regex": "session"}])["matches"][0]
    assumption = _query(store, kind="assumption", filters=[
        {"path": "fault.label", "regex": "authorisation"}])["matches"][0]
    impact = _query(store, kind="impact", filters=[
        {"path": "impact_description", "regex": "tenant"}])["matches"][0]

    assert vulnerability["label"] == "session-fixation"
    assert vulnerability["web_vulnerability_class"] == "session-management"
    assert vulnerability["disposition"] is None
    assert vulnerability["summary"] == (
        "The prior unit characterises this class.")

    assert assumption["label"] == (
        "improper authorisation on the item lookup")
    assert assumption["summary"] == "The handler omits the ownership check."

    assert impact["label"] == "threat"
    assert impact["disposition"] == "threat"
    assert impact["summary"] == ITEM_DAMAGE


def test_the_threat_view_merges_the_threat_file_with_the_impact_row(tmp_path):
    """The threat view is the threat file plus the model's impact row, so a
    filter can name the capability, its key, and the damage."""
    store = ThreatModelStore(root_dir=tmp_path)
    _seed_completed(store)

    result = _query(store, kind="threat", filters=[
        {"path": "impact.capability", "regex": "tenant"},
        {"path": "impact.capability_id", "regex": "::p-1$"},
        {"path": "impact.impact_description", "regex": "another tenant's item"},
    ])

    assert result["count"] == 1
    match = result["matches"][0]
    assert match["label"] == "IDOR"
    assert match["web_vulnerability_class"] == "idor"
    assert match["disposition"] == "threat"
    assert match["summary"] == ITEM_DAMAGE
    assert [pair["path"] for pair in match["matched"]] == [
        "impact.capability",
        "impact.capability_id",
        "impact.impact_description",
    ]


def test_the_limit_truncates_and_reports_it(tmp_path):
    store = ThreatModelStore(root_dir=tmp_path)
    _two_prior_units(store)
    _seed_completed(store)
    filters = [{"path": "capability", "regex": "session|item|credential",
                "flags": "i"}]

    capped = _query(store, kind="precursor", filters=filters, limit=1)
    full = _query(store, kind="precursor", filters=filters, limit=50)

    assert capped["count"] == 1
    assert capped["truncated"] is True
    assert len(capped["matches"]) == 1
    assert full["count"] == 2
    assert full["truncated"] is False
    assert len(full["matches"]) == 2
