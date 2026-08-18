"""Unit tier: the fault-KB loader - the two-facet read of the phase-1
catalogue (#66, spec section 6).

The loader is a pure function (file in -> `FaultEntry` tuple + content map),
unit-testable with a fixture catalogue - no DB, no network, no LLM. The three
contracts under assertion:

  * the MATCHING facet: each YAML entry projected into `fault_source.FaultEntry`
    with the typed predicate parsed back into the #63 `TypedPredicate` and
    VALIDATED (a malformed predicate is a hard error surfaced by the loader's
    own read-time validation, never silently dropped);
  * the MATERIALISATION facet: rich NL content by `fault_id`;
  * fail-open: a missing or malformed catalogue yields an EMPTY KB (never an
    exception to the caller), and a malformed entry is skipped with a logged
    diagnostic while the rest stay usable (per-entry fail-open).

Expected values are taken from the spec (section 4 schema, section 6 contract),
never recomputed the way the code computes them.
"""
import pytest

from polymerhus.attack.hunting.fault_kb import (
    FaultMaterialisation,
    load_fault_entries,
    load_materialisation,
)
from polymerhus.attack.hunting.predicate import ClauseForm


# --- fixture catalogues --------------------------------------------------------

def _entry_yaml(**overrides):
    base = {
        "fault_id": "CWE-89",
        "name": "SQL Injection",
        "abstraction": "Base",
        "owasp_2025": ["A05"],
        "applies_if": {
            "nl": "The unit builds an SQL statement from externally influenced input.",
            "predicate": {
                "target": "Both",
                "clauses": [
                    {"form": "reachable-via", "key": "EXPOSED_VIA",
                     "values": ["RESTApi", "GraphQLApi"]},
                ],
            },
        },
        "enum_kinds": ["RESTApi", "GraphQLApi"],
        "materialisation": {
            "description": "The product constructs all or part of an SQL command.",
            "extended_description": "Extended text.",
            "alternate_terms": ["SQLi"],
            "related_attack_patterns": ["CAPEC-66"],
            "likelihood": "High",
            "common_consequences": ["Read application data"],
        },
    }
    base.update(overrides)
    return base


def _write_catalogue(tmp_path, entries):
    import yaml
    path = tmp_path / "fault-kb.yaml"
    path.write_text(yaml.safe_dump(entries), encoding="utf-8")
    return str(path)


# --- the matching facet --------------------------------------------------------

def test_load_fault_entries_projects_every_yaml_entry(tmp_path):
    path = _write_catalogue(tmp_path, [
        _entry_yaml(),
        _entry_yaml(fault_id="CWE-79", name="XSS",
                     applies_if={"nl": "Rendered output.", "predicate": None},
                     enum_kinds=["WebPresentation"]),
    ])
    entries = load_fault_entries(path)
    assert {e.fault_id for e in entries} == {"CWE-79", "CWE-89"}


def test_load_fault_entries_parses_and_validates_the_typed_predicate(tmp_path):
    path = _write_catalogue(tmp_path, [_entry_yaml()])
    entry = load_fault_entries(path)[0]
    assert entry.predicate is not None
    assert entry.predicate.target == "Both"
    clause = entry.predicate.clauses[0]
    assert clause.form is ClauseForm.REACHABLE_VIA
    assert clause.key == "EXPOSED_VIA"
    assert clause.values == ("RESTApi", "GraphQLApi")


def test_load_fault_entries_keeps_enum_kinds_and_null_predicate(tmp_path):
    path = _write_catalogue(tmp_path, [
        _entry_yaml(fault_id="CWE-79",
                    applies_if={"nl": "Rendered output.", "predicate": None},
                    enum_kinds=["WebPresentation"]),
    ])
    entry = load_fault_entries(path)[0]
    assert entry.predicate is None
    assert entry.enum_kinds == frozenset({"WebPresentation"})


def test_load_fault_entries_rejects_unknown_system_kind(tmp_path):
    path = _write_catalogue(tmp_path, [
        _entry_yaml(enum_kinds=["NotAKind"]),
    ])
    # per-entry fail-open: the entry is skipped, the empty tuple is returned
    assert load_fault_entries(path) == ()


def test_load_fault_entries_skips_malformed_entry_keeps_rest(tmp_path):
    path = _write_catalogue(tmp_path, [
        _entry_yaml(),
        {"fault_id": "CWE-999", "applies_if": {"predicate": "not-a-mapping"}},
    ])
    entries = load_fault_entries(path)
    assert [e.fault_id for e in entries] == ["CWE-89"]


def test_load_fault_entries_surfaces_malformed_predicate(tmp_path):
    # an invalid clause form is a curation-time hard error, surfaced by the
    # loader's own validation - never silently dropped
    bad = _entry_yaml()
    bad["applies_if"]["predicate"]["clauses"][0]["form"] = "contains-text"
    path = _write_catalogue(tmp_path, [bad])
    assert load_fault_entries(path) == ()


# --- the materialisation facet -------------------------------------------------

def test_load_materialisation_returns_content_by_fault_id(tmp_path):
    path = _write_catalogue(tmp_path, [
        _entry_yaml(),
        _entry_yaml(fault_id="CWE-79", name="XSS",
                     applies_if={"nl": "Rendered output.", "predicate": None},
                     enum_kinds=[],
                     materialisation={"description": "XSS text"}),
    ])
    by_id = load_materialisation(path)
    assert set(by_id) == {"CWE-79", "CWE-89"}
    materialisation = by_id["CWE-89"]
    assert isinstance(materialisation, FaultMaterialisation)
    assert materialisation.name == "SQL Injection"
    assert materialisation.alternate_terms == ("SQLi",)
    assert materialisation.related_attack_patterns == ("CAPEC-66",)
    assert materialisation.likelihood == "High"


# --- fail-open -----------------------------------------------------------------

def test_load_fault_entries_fails_open_to_empty_on_missing_file():
    assert load_fault_entries("/nonexistent/fault-kb.yaml") == ()


def test_load_materialisation_fails_open_to_empty_on_missing_file():
    assert load_materialisation("/nonexistent/fault-kb.yaml") == {}


def test_load_fault_entries_fails_open_to_empty_on_malformed_yaml(tmp_path):
    path = tmp_path / "fault-kb.yaml"
    path.write_text("not: [valid: yaml", encoding="utf-8")
    assert load_fault_entries(str(path)) == ()


def test_load_fault_entries_fails_open_to_empty_on_non_list_yaml(tmp_path):
    path = tmp_path / "fault-kb.yaml"
    path.write_text("just: a-mapping", encoding="utf-8")
    assert load_fault_entries(str(path)) == ()
