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
    _fold_target,
    curate,
    emit_catalogue,
    fold_authoring,
    fold_variants,
    load_authoring,
    load_seed,
    parse_catalogue,
    promote_captures,
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


def _mini_catalogue(tmp_path, weaknesses):
    """A standalone catalogue XML (same namespace) built from _weakness
    fragments - for fold-shape assertions that the main fixture lacks."""
    xml_path = tmp_path / "mini-catalogue.xml"
    xml_path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Catalogue xmlns="http://cwe.mitre.org/cwe-7">\n'
        f"{''.join(weaknesses)}\n</Catalogue>\n",
        encoding="utf-8")
    return xml_path


def _mini_seed(tmp_path, cwes):
    seed_path = tmp_path / "mini-seed.yaml"
    seed_path.write_text(
        yaml.safe_dump({"mapped_cwes": {"A01": cwes}}), encoding="utf-8")
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


# --- the fold (selection tier vs materialisation tier) --------------------------

def _folded_entries(xml_path, seed_path):
    """curate() + fold_variants(), the same composition main() runs."""
    index = parse_catalogue(xml_path)
    return fold_variants(curate(xml_path, seed_path), index)


def test_fold_marks_variants_with_nearest_base(tmp_path):
    entries = _folded_entries(_fixture_xml(tmp_path), _fixture_seed(tmp_path))
    by_id = {e["fault_id"]: e for e in entries}
    # CWE-5/CWE-6 are Variants of the retained Base CWE-3: they fold into it
    # (the catalogue keeps them as recipes, fold_parent names the capture)
    assert by_id["CWE-5"]["fold_parent"] == "CWE-3"
    assert by_id["CWE-6"]["fold_parent"] == "CWE-3"
    # Bases are captures: fold_parent null (selection-tier entries)
    assert by_id["CWE-3"]["fold_parent"] is None
    assert by_id["CWE-7"]["fold_parent"] is None


def test_fold_skips_variant_waypoints_lands_on_base(tmp_path):
    # CWE-11 (Variant) -> CWE-12 (Variant) -> CWE-10 (Base): the chain must
    # land on the retained Base, NOT the intermediate Variant
    xml = _mini_catalogue(tmp_path, [
        _weakness(10, "Base Ten", "Base", parents=[], tech_classes=["Web Based"]),
        _weakness(11, "Variant Eleven", "Variant", parents=[10],
                  tech_classes=["Web Based"]),
        _weakness(12, "Variant Twelve", "Variant", parents=[11],
                  tech_classes=["Web Based"]),
    ])
    entries = _folded_entries(xml, _mini_seed(tmp_path, [10]))
    by_id = {e["fault_id"]: e for e in entries}
    assert by_id["CWE-12"]["fold_parent"] == "CWE-10"
    assert by_id["CWE-11"]["fold_parent"] == "CWE-10"
    assert by_id["CWE-10"]["fold_parent"] is None


def test_fold_orphan_without_retained_ancestor_stays(tmp_path):
    # CWE-13 (Variant) hangs under the Pillar CWE-1 which is NOT retained:
    # the Pillar is replaced by its smallest-id concrete descendant CWE-13
    # (abstract->concrete, spec 5.4), and 13 has no retained Base/Class
    # ancestor -> fold_parent null, the entry STAYS in the selection tier
    # (fail-open recall)
    xml = _mini_catalogue(tmp_path, [
        _weakness(1, "Pillar Root", "Pillar", parents=[]),
        _weakness(10, "Base Ten", "Base", parents=[],
                  tech_classes=["Web Based"]),
        _weakness(13, "Variant Thirteen", "Variant", parents=[1],
                  tech_classes=["Web Based"]),
    ])
    entries = _folded_entries(xml, _mini_seed(tmp_path, [1, 10]))
    by_id = {e["fault_id"]: e for e in entries}
    assert "CWE-13" in by_id
    assert by_id["CWE-13"]["fold_parent"] is None


def test_fold_target_is_deterministic_and_cycle_safe(tmp_path):
    index = parse_catalogue(_fixture_xml(tmp_path))
    # CWE-5's parent chain (5 -> 3 -> 2 -> 1) has no cycles; direct parent
    # CWE-3 is the nearest retained Base
    assert _fold_target(5, in_catalogue={3, 5, 6, 7}, index=index) == 3
    # a cycle (a parent pointing back) must terminate, not hang: fold_target
    # is callable on an id absent from in_catalogue (orphan case) and returns
    # None only when no retained Base/Class ancestor exists
    assert _fold_target(3, in_catalogue={5, 6}, index=index) is None


def test_fold_keeps_split_variants_in_the_selection_tier(tmp_path):
    # a SPLIT verdict (overlap critic): the variant is a distinct fault class
    # even though a View-1000 capture exists - keep_separate forces fold
    # _parent null
    entries = _folded_entries(_fixture_xml(tmp_path), _fixture_seed(tmp_path))
    index = parse_catalogue(_fixture_xml(tmp_path))
    entries = fold_variants(entries, index, keep_separate=frozenset({6}))
    by_id = {e["fault_id"]: e for e in entries}
    assert by_id["CWE-6"]["fold_parent"] is None
    assert by_id["CWE-5"]["fold_parent"] == "CWE-3"


# --- promotion (the overlap-critic's PROMOTE-AND-FOLD verdicts) ------------------

def test_promote_captures_adds_absent_capture(tmp_path):
    # CWE-2 (Class) is replaced by its concrete descendants in curate(): it
    # is absent from the curated set, so promote_captures ADDS it as a
    # selection capture (extracted like any other entry)
    authoring = {"CWE-2": {"promote": True, "nl": "x",
                           "enum_kinds": ["WebPresentation"]}}
    entries = curate(_fixture_xml(tmp_path), _fixture_seed(tmp_path))
    index = parse_catalogue(_fixture_xml(tmp_path))
    promoted = promote_captures(entries, index, authoring)
    by_id = {e["fault_id"]: e for e in promoted}
    assert "CWE-2" in by_id
    assert by_id["CWE-2"]["abstraction"] == "Class"
    assert by_id["CWE-2"]["materialisation"]["description"] == "d"


def test_promote_captures_skips_already_curated_id(tmp_path):
    # CWE-3 is already curated (a retained Base): its promotion is just the
    # web-relevance-omit reversal - the marker must not duplicate it
    authoring = {"CWE-3": {"promote": True, "nl": "x",
                           "enum_kinds": ["WebPresentation"]}}
    entries = curate(_fixture_xml(tmp_path), _fixture_seed(tmp_path))
    index = parse_catalogue(_fixture_xml(tmp_path))
    promoted = promote_captures(entries, index, authoring)
    assert [e["fault_id"] for e in promoted].count("CWE-3") == 1


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


def test_load_authoring_split_merges_into_prior_entry(tmp_path):
    """The fold-amendments layer: a later pure-split marker merges into the
    prior entry, keeping its matching facet and marking the fold-split."""
    d = tmp_path / "authoring"
    d.mkdir()
    (d / "01-range.yaml").write_text(
        "entries:\n  CWE-3:\n    nl: 'Rendered output.'\n"
        "    enum_kinds: [WebPresentation]\n")
    (d / "70-amend.yaml").write_text(
        "entries:\n  CWE-3:\n    split: true\n")
    authoring = load_authoring(d)
    assert authoring["CWE-3"] == {"nl": "Rendered output.",
                                  "enum_kinds": ["WebPresentation"],
                                  "split": True}


def test_load_authoring_promote_reverses_an_omit(tmp_path):
    """The PROMOTE-AND-FOLD layer: a later promote spec supersedes an omit
    (the overlap-critic verdict reverses a web-relevance omission) and keeps
    its own matching facet."""
    d = tmp_path / "authoring"
    d.mkdir()
    (d / "01-range.yaml").write_text(
        "entries:\n  CWE-3:\n    nl: 'Rendered output.'\n")
    (d / "10-relevance.yaml").write_text(
        "entries:\n  CWE-3:\n    omit: true\n    omit_reason: 'fixture'\n")
    (d / "70-amend.yaml").write_text(
        "entries:\n  CWE-3:\n    promote: true\n"
        "    nl: 'The unit validates input via the framework.'\n"
        "    enum_kinds: [RESTApi]\n")
    authoring = load_authoring(d)
    assert authoring["CWE-3"] == {"promote": True,
                                  "nl": "The unit validates input via the framework.",
                                  "enum_kinds": ["RESTApi"]}


def test_load_authoring_split_on_omit_rejected(tmp_path):
    d = tmp_path / "authoring"
    d.mkdir()
    (d / "10-relevance.yaml").write_text(
        "entries:\n  CWE-3:\n    omit: true\n    omit_reason: 'fixture'\n")
    (d / "70-amend.yaml").write_text(
        "entries:\n  CWE-3:\n    split: true\n")
    with pytest.raises(ValueError, match="contradictory"):
        load_authoring(d)


def test_load_authoring_generalise_merges_into_prior_entry(tmp_path):
    """The squeeze-generalise layer: a later `generalise` spec merges into the
    prior entry, keeping its authored matching facet (nl/enum_kinds) and adding
    the materialisation name/description overrides."""
    d = tmp_path / "authoring"
    d.mkdir()
    (d / "01-range.yaml").write_text(
        "entries:\n  CWE-3:\n    nl: 'Rendered output.'\n"
        "    enum_kinds: [WebPresentation]\n")
    (d / "81-squeeze.yaml").write_text(
        "entries:\n  CWE-3:\n    generalise: true\n"
        "    name: 'Rewritten Name'\n"
        "    description: 'Rewritten description.'\n")
    authoring = load_authoring(d)
    assert authoring["CWE-3"] == {"nl": "Rendered output.",
                                  "enum_kinds": ["WebPresentation"],
                                  "generalise": True,
                                  "name": "Rewritten Name",
                                  "description": "Rewritten description."}


def test_load_authoring_generalise_on_omit_rejected(tmp_path):
    d = tmp_path / "authoring"
    d.mkdir()
    (d / "10-relevance.yaml").write_text(
        "entries:\n  CWE-3:\n    omit: true\n    omit_reason: 'fixture'\n")
    (d / "81-squeeze.yaml").write_text(
        "entries:\n  CWE-3:\n    generalise: true\n"
        "    name: 'Rewritten Name'\n")
    with pytest.raises(ValueError, match="contradictory"):
        load_authoring(d)


def test_fold_authoring_generalise_rewrites_materialisation(tmp_path):
    """The de-frameworking application: a generalised entry keeps its matching
    facet and gets its materialisation name/description (and optionally a
    nulled extended_description) rewritten."""
    entries = curate(_fixture_xml(tmp_path), _fixture_seed(tmp_path))
    authoring = {
        "CWE-3": {
            "nl": "Rendered output.",
            "enum_kinds": ["WebPresentation"],
            "generalise": True,
            "name": "Neutral Name",
            "description": "Neutral description.",
            "extended_description": None,
        },
    }
    folded = fold_authoring(entries, authoring)
    entry = next(e for e in folded if e["fault_id"] == "CWE-3")
    assert entry["name"] == "Neutral Name"
    assert entry["materialisation"]["description"] == "Neutral description."
    assert entry["materialisation"]["extended_description"] is None
    assert entry["applies_if"]["nl"] == "Rendered output."
    assert entry["enum_kinds"] == ["WebPresentation"]


# --- fold_to (the operator's taxonomy corrections) ----------------------------

def test_load_authoring_fold_to_merges_into_prior_entry(tmp_path):
    """The 82-operator-relevance layer: a later pure `fold_to` marker merges
    into the prior entry, keeping its matching facet and naming the forced
    capture."""
    d = tmp_path / "authoring"
    d.mkdir()
    (d / "01-range.yaml").write_text(
        "entries:\n  CWE-3:\n    nl: 'Rendered output.'\n"
        "    enum_kinds: [WebPresentation]\n")
    (d / "82-relevance.yaml").write_text(
        "entries:\n  CWE-3:\n    fold_to: 'CWE-7'\n")
    authoring = load_authoring(d)
    assert authoring["CWE-3"] == {"nl": "Rendered output.",
                                  "enum_kinds": ["WebPresentation"],
                                  "fold_to": "CWE-7"}


def test_load_authoring_fold_to_on_omit_rejected(tmp_path):
    """A fold_to for an OMITTED fault is contradictory: unlike promote, fold_to
    is a taxonomy correction on a kept entry, it never reverses an omission."""
    d = tmp_path / "authoring"
    d.mkdir()
    (d / "10-relevance.yaml").write_text(
        "entries:\n  CWE-3:\n    omit: true\n    omit_reason: 'fixture'\n")
    (d / "82-relevance.yaml").write_text(
        "entries:\n  CWE-3:\n    fold_to: 'CWE-7'\n")
    with pytest.raises(ValueError, match="contradictory"):
        load_authoring(d)


def test_fold_variants_force_fold_collapses_a_base(tmp_path):
    """A Base/Class captured by `fold_to` folds into the named target
    REGARDLESS of its CWE abstraction: CWE-23 (Base, child of 22) and CWE-41
    (Base, NOT a child of 22 in View-1000 - it hangs under the unretained
    Pillar/Class ref) both land on CWE-22."""
    xml = _mini_catalogue(tmp_path, [
        _weakness(1, "Pillar Root", "Pillar", parents=[]),
        _weakness(22, "Base Parent", "Base", parents=[],
                  tech_classes=["Web Based"]),
        _weakness(23, "Base Relative", "Base", parents=[22],
                  tech_classes=["Web Based"]),
        _weakness(41, "Base Equiv", "Base", parents=[1],  # sibling under a
                  tech_classes=["Web Based"]),             # non-retained root
    ])
    index = parse_catalogue(xml)
    entries = curate(xml, _mini_seed(tmp_path, [1, 22]))
    entries = fold_variants(entries, index, force_fold={23: 22, 41: 22})
    by_id = {e["fault_id"]: e for e in entries}
    assert by_id["CWE-22"]["fold_parent"] is None      # the capture stays
    assert by_id["CWE-23"]["fold_parent"] == "CWE-22"  # Base collapsed
    assert by_id["CWE-41"]["fold_parent"] == "CWE-22"  # taxonomy correction


def test_fold_to_jumps_descendants_to_the_forced_target(tmp_path):
    """A folded child of a force-folded Base re-folds to the FORCED target,
    not to the (now-waypoint) parent: CWE-24 (Variant of 23) lands on CWE-22
    even though its View-1000 chain stops at 23."""
    xml = _mini_catalogue(tmp_path, [
        _weakness(22, "Base Parent", "Base", parents=[],
                  tech_classes=["Web Based"]),
        _weakness(23, "Base Relative", "Base", parents=[22],
                  tech_classes=["Web Based"]),
        _weakness(24, "Variant Child", "Variant", parents=[23],
                  tech_classes=["Web Based"]),
    ])
    index = parse_catalogue(xml)
    entries = curate(xml, _mini_seed(tmp_path, [22]))
    entries = fold_variants(entries, index, force_fold={23: 22})
    by_id = {e["fault_id"]: e for e in entries}
    assert by_id["CWE-23"]["fold_parent"] == "CWE-22"
    assert by_id["CWE-24"]["fold_parent"] == "CWE-22"


def test_fold_to_target_absent_from_catalogue_rejected(tmp_path):
    """A fold_to naming a capture absent from the curated catalogue is a hard
    curation error, never a silently-dangling fold_parent."""
    xml = _mini_catalogue(tmp_path, [
        _weakness(22, "Base Parent", "Base", parents=[],
                  tech_classes=["Web Based"]),
        _weakness(23, "Base Relative", "Base", parents=[22],
                  tech_classes=["Web Based"]),
    ])
    index = parse_catalogue(xml)
    entries = curate(xml, _mini_seed(tmp_path, [22]))
    entries = [e for e in entries if e["fault_id"] != "CWE-22"]  # drop target
    with pytest.raises(ValueError, match="absent from the curated catalogue"):
        fold_variants(entries, index, force_fold={23: 22})


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
