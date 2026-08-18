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
  * the FOLD-FAMILY relation: for each selection-tier fault_id, the folded
    fault_ids captured under it (the parent -> reflection-material map the
    hunt-orchestrator's graph logic consumes);
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
    load_fold_families,
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

def test_load_fault_entries_filters_folded_variants(tmp_path):
    # the selection tier excludes folded entries (fold_parent set): the fold
    # parent is their capture; the variant content stays in the materialisation
    # facet only
    path = _write_catalogue(tmp_path, [
        _entry_yaml(),
        _entry_yaml(fault_id="CWE-42", name="XSS Path Equivalent",
                    fold_parent="CWE-79",
                    applies_if={"nl": "Equivalent path.", "predicate": None},
                    enum_kinds=[]),
    ])
    entries = load_fault_entries(path)
    assert {e.fault_id for e in entries} == {"CWE-89"}


def test_load_materialisation_serves_folded_variants_with_fold_parent(tmp_path):
    # the materialisation facet keeps ALL entries by own id - a folded variant
    # stays addressable as a recipe, carrying the fold_parent pointer
    path = _write_catalogue(tmp_path, [
        _entry_yaml(),
        _entry_yaml(fault_id="CWE-42", name="XSS Path Equivalent",
                    fold_parent="CWE-89",
                    applies_if={"nl": "Equivalent path.", "predicate": None},
                    enum_kinds=[],
                    materialisation={
                        "description": "A path-equivalent injection.",
                        "common_consequences": ["Data corruption"],
                    }),
    ])
    by_id = load_materialisation(path)
    assert set(by_id) == {"CWE-42", "CWE-89"}
    assert by_id["CWE-42"].fold_parent == "CWE-89"
    assert by_id["CWE-89"].fold_parent is None
    assert by_id["CWE-42"].common_consequences == ("Data corruption",)


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


# --- the fold-family relation -------------------------------------------------

def test_load_fold_families_maps_capture_to_its_folded_faults(tmp_path):
    # a folded entry's fold_parent is the selection-tier capture; the map
    # attaches the folded recipes to it, sorted, never by write order
    path = _write_catalogue(tmp_path, [
        _entry_yaml(),
        _entry_yaml(fault_id="CWE-42", name="Path Equivalent",
                    fold_parent="CWE-89",
                    applies_if={"nl": "Equivalent path.", "predicate": None},
                    enum_kinds=[]),
        _entry_yaml(fault_id="CWE-564", name="ORM Query Injection",
                    fold_parent="CWE-89",
                    applies_if={"nl": "ORM query.", "predicate": None},
                    enum_kinds=[]),
    ])
    families = load_fold_families(path)
    assert families["CWE-89"] == ("CWE-42", "CWE-564")


def test_load_fold_families_includes_leaf_parents_with_empty_tuple(tmp_path):
    # every selection-tier fault is a key - a leaf parent carries an empty
    # tuple, so the orchestrator's graph logic iterates the tier uniformly
    path = _write_catalogue(tmp_path, [
        _entry_yaml(),
        _entry_yaml(fault_id="CWE-79", name="XSS",
                     applies_if={"nl": "Rendered output.", "predicate": None},
                     enum_kinds=["WebPresentation"]),
    ])
    families = load_fold_families(path)
    assert set(families) == {"CWE-79", "CWE-89"}
    assert families["CWE-79"] == ()
    assert families["CWE-89"] == ()


def test_load_fold_families_skips_dangling_fold_parent(tmp_path):
    # a recipe whose fold_parent is not a selection-tier entry is skipped
    # (per-entry fail-open), never surfaced as a bogus family key
    path = _write_catalogue(tmp_path, [
        _entry_yaml(),
        _entry_yaml(fault_id="CWE-42", name="Path Equivalent",
                    fold_parent="CWE-99",
                    applies_if={"nl": "Equivalent path.", "predicate": None},
                    enum_kinds=[]),
    ])
    families = load_fold_families(path)
    assert families == {"CWE-89": ()}


def test_load_fold_families_fails_open_to_empty_on_missing_file():
    assert load_fold_families("/nonexistent/fault-kb.yaml") == {}


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
