"""Unit tier: the fault-KB curation script - the offline transform (#66, spec
section 5), asserted over a fixture XML slice + a fixture OWASP seed.

The curation script is a pure function (files in -> catalogue list out),
unit-testable with a fixture slice of the cwec XML - no DB, no network, no
LLM. The spec-mandated stage assertions (spec section 11, first bullet):

  * the walk pulls the FULL View-1000 child set of the seeds (R-a);
  * the filter drops non-web ids and deprecated ids;
  * the abstract->concrete replacement fires (Pillar/Class -> smallest-id
    Base/Variant descendant already in the collected set);
  * dedupe holds (a descendant reached through several seeds is one entry);
  * the emitted YAML is deterministic (same inputs -> byte-identical output).

The fixture slice:
  CWE-1 (Pillar)        -> CWE-2 (Class) -> CWE-3 (Base, web) -> CWE-5 (Variant, web)
                       |               `-> CWE-4 (Base, hardware)   `-> CWE-6 (Variant, web)
                       `-> CWE-7 (Base, web) -> CWE-8 (Base, web, DEPRECATED)
Seeded: A01 -> [1, 7]  (7 is seeded directly AND reached through 1 - the
dual-reach dedupe case).
"""
import textwrap
from pathlib import Path

import pytest
import yaml

from tools.hunting.curate_fault_kb import (
    _abstract_to_concrete,
    _children_map,
    curate,
    emit_catalogue,
    fold_authoring,
    load_authoring,
    load_seed,
    parse_catalogue,
    walk_descendants,
)

_NS = "{http://cwe.mitre.org/cwe-7}"


# --- fixture builders ----------------------------------------------------------

def _weakness(cwe_id, name, abstraction, *, status="Draft",
              parents=(), description="d", tech_classes=(), tech_names=()):
    """One <Weakness> element of the fixture slice (the parse surface of
    `parse_catalogue`: the fields the script reads)."""
    related = "".join(
        f'<Related_Weakness Nature="ChildOf" CWE_ID="{p}" View_ID="1000"/>'
        for p in parents)
    platforms = ""
    if tech_classes or tech_names:
        techs = "".join(
            f'<Technology Class="{c}"/>' for c in tech_classes)
        techs += "".join(f'<Technology Name="{n}"/>' for n in tech_names)
        platforms = f"<Applicable_Platforms>{techs}</Applicable_Platforms>"
    return (f'<Weakness ID="{cwe_id}" Name="{name}" Abstraction="{abstraction}" '
            f'Status="{status}">'
            f"<Description>{description}</Description>"
            f"<Extended_Description><p>ext {name}</p></Extended_Description>"
            f'<Alternate_Term>term-{cwe_id}</Alternate_Term>'
            f'<Related_Attack_Pattern CAPEC_ID="{cwe_id}"/>'
            f"<Likelihood_Of_Exploit>High</Likelihood_Of_Exploit>"
            f"<Common_Consequence><Scope>Integrity</Scope>"
            f"<Impact>Modify data</Impact></Common_Consequence>"
            f"{related}{platforms}</Weakness>")


def _fixture_xml(tmp_path):
    """The fixture slice as a catalogue XML file (namespace cwe-7)."""
    body = "".join([
        _weakness(1, "Pillar Root", "Pillar", parents=[]),
        _weakness(2, "Class Mid", "Class", parents=[1]),
        _weakness(3, "Base Web", "Base", parents=[2],
                  tech_classes=["Web Based"]),
        _weakness(4, "Base Hardware", "Base", parents=[2],
                  tech_names=["Processor Hardware"]),
        _weakness(5, "Variant Web A", "Variant", parents=[3],
                  tech_classes=["Web Based"]),
        _weakness(6, "Variant Web B", "Variant", parents=[3],
                  tech_classes=["Web Based"]),
        _weakness(7, "Base Seeded", "Base", parents=[1],
                  tech_classes=["Web Based"]),
        _weakness(8, "Base Deprecated", "Base", parents=[7],
                  tech_classes=["Web Based"], status="Deprecated"),
    ])
    xml_path = tmp_path / "fixture-catalogue.xml"
    xml_path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Catalogue xmlns="http://cwe.mitre.org/cwe-7">\n'
        f"{body}\n</Catalogue>\n",
        encoding="utf-8")
    return xml_path


def _fixture_seed(tmp_path):
    seed_path = tmp_path / "fixture-seed.yaml"
    seed_path.write_text(
        yaml.safe_dump({"mapped_cwes": {"A01": [1, 7]}}), encoding="utf-8")
    return seed_path


# --- the walk (spec 5.2, the R-a mitigation) ------------------------------------

def test_walk_pulls_the_full_child_set(tmp_path):
    index = parse_catalogue(_fixture_xml(tmp_path))
    children = _children_map(index)
    assert children[1] == frozenset({2, 7})
    # 4 is a Class's child, 5/6 are grandchildren, 8 is a great-grandchild:
    # the walk goes to ANY depth, never hand-picked children.
    assert walk_descendants({1}, children) == frozenset({1, 2, 3, 4, 5, 6, 7, 8})


def test_walk_keeps_the_seed_itself(tmp_path):
    index = parse_catalogue(_fixture_xml(tmp_path))
    children = _children_map(index)
    # a seeded Base with no children must survive the walk
    assert walk_descendants({7}, children) == frozenset({7, 8})


# --- the filter (spec 5.3) ------------------------------------------------------

def test_curate_filters_non_web_and_deprecated(tmp_path):
    entries = curate(_fixture_xml(tmp_path), _fixture_seed(tmp_path))
    ids = {e["fault_id"] for e in entries}
    # CWE-4 is explicit non-web (Processor Hardware); CWE-8 is deprecated
    assert ids == {"CWE-3", "CWE-5", "CWE-6", "CWE-7"}


# --- the abstract->concrete replacement (spec 5.4) ------------------------------

def test_curate_replaces_abstract_with_smallest_id_concrete(tmp_path):
    entries = curate(_fixture_xml(tmp_path), _fixture_seed(tmp_path))
    ids = {e["fault_id"] for e in entries}
    # the Pillar and the Class are gone; their smallest-id Base/Variant
    # descendants in the collected set stand in their place
    assert "CWE-1" not in ids and "CWE-2" not in ids
    assert "CWE-3" in ids and "CWE-5" in ids
    # the emitted abstraction reflects the replacement (no abstract survives)
    assert all(e["abstraction"] in ("Base", "Variant") for e in entries)


def test_abstract_without_concrete_descendant_stays(tmp_path):
    # an abstract with NO concrete descendant in the collected set must be
    # kept (fail-open recall, spec 5.4): CWE-2 (Class) alone has no
    # Base/Variant to be replaced with.
    index = parse_catalogue(_fixture_xml(tmp_path))
    children = _children_map(index)
    replaced = _abstract_to_concrete({2}, index, children)
    assert 2 in replaced  # no concrete descendant in the set: keep, fail-open


# --- dedupe (spec 5.4) ----------------------------------------------------------

def test_curate_dedupes_multi_seed_reach(tmp_path):
    # CWE-7 is seeded directly AND a descendant of the seeded CWE-1: it must
    # appear exactly once
    entries = curate(_fixture_xml(tmp_path), _fixture_seed(tmp_path))
    assert [e["fault_id"] for e in entries].count("CWE-7") == 1


# --- the authoring fold (spec 5.6) ----------------------------------------------

def test_fold_authoring_applies_omit_and_nl(tmp_path):
    entries = curate(_fixture_xml(tmp_path), _fixture_seed(tmp_path))
    authoring = {
        "CWE-3": {"nl": "Rendered output.", "enum_kinds": ["WebPresentation"]},
        "CWE-5": {"omit": True, "omit_reason": "fixture"},
    }
    folded = fold_authoring(entries, authoring)
    ids = {e["fault_id"] for e in folded}
    assert "CWE-5" not in ids
    entry = next(e for e in folded if e["fault_id"] == "CWE-3")
    assert entry["applies_if"]["nl"] == "Rendered output."
    assert entry["enum_kinds"] == ["WebPresentation"]


def test_fold_authoring_rejects_unknown_system_kind(tmp_path):
    entries = curate(_fixture_xml(tmp_path), _fixture_seed(tmp_path))
    authoring = {"CWE-3": {"nl": "Rendered.", "enum_kinds": ["NotAKind"]}}
    with pytest.raises(ValueError, match="not in SYSTEM_KINDS"):
        fold_authoring(entries, authoring)


def test_fold_authoring_rejects_absent_id(tmp_path):
    entries = curate(_fixture_xml(tmp_path), _fixture_seed(tmp_path))
    authoring = {"CWE-999": {"omit": True}}
    with pytest.raises(ValueError, match="does not contain it"):
        fold_authoring(entries, authoring)


def test_load_authoring_late_omit_overrides_earlier_entry(tmp_path):
    """The relevance-filter layer: a later file (sorted by name) may override
    an earlier authored entry with an omit marker; the entry is dropped."""
    d = tmp_path / "authoring"
    d.mkdir()
    (d / "01-range.yaml").write_text(
        "entries:\n  CWE-3:\n    nl: 'Rendered output.'\n")
    (d / "10-relevance.yaml").write_text(
        "entries:\n  CWE-3:\n    omit: true\n    omit_reason: 'fixture'\n")
    authoring = load_authoring(d)
    assert authoring["CWE-3"] == {"omit": True, "omit_reason": "fixture"}


def test_load_authoring_late_non_omit_duplicate_still_rejected(tmp_path):
    d = tmp_path / "authoring"
    d.mkdir()
    (d / "01-range.yaml").write_text(
        "entries:\n  CWE-3:\n    nl: 'Rendered output.'\n")
    (d / "10-relevance.yaml").write_text(
        "entries:\n  CWE-3:\n    nl: 'Other output.'\n")
    with pytest.raises(ValueError, match="duplicate authoring"):
        load_authoring(d)


# --- determinism (spec 5.7) ------------------------------------------------------

def test_emit_catalogue_is_deterministic(tmp_path):
    entries = curate(_fixture_xml(tmp_path), _fixture_seed(tmp_path))
    assert emit_catalogue(entries) == emit_catalogue(entries)


def test_curate_is_deterministic(tmp_path):
    xml, seed = _fixture_xml(tmp_path), _fixture_seed(tmp_path)
    assert curate(xml, seed) == curate(xml, seed)


def test_load_seed_reads_the_mapping(tmp_path):
    seed = load_seed(_fixture_seed(tmp_path))
    assert seed == {"A01": (1, 7)}
