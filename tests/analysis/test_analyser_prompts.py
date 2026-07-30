"""WI-2: the analyser's remaining legacy ASSIGNMENT prompt (`pod._assignment_prompt`).

`pod._data_modelling_prompt` (and the two tests here that exercised it,
`test_data_modelling_prompt_asks_for_observed_fields_only` /
`test_data_modelling_prompt_does_not_reintroduce_likely_fields` /
`test_data_modelling_prompt_pins_existing_identities`) was RETIRED by #48
section 11 step 5 (ratified 2026-07-30): the legacy two-pass no longer proposes
data at all, because `data_modeller.py` (the chunk-fed path, now the default via
`resolve_supervisor_enabled`'s flipped default) owns that responsibility. Its
"observed fields only, never speculative" contract is mechanised instead at
`tests/analysis/test_data_modeller.py::test_fields_observed_only` and
`tests/integration/test_data_modeller_contracts.py::test_D7_fields_observed_only`
/ `test_D9_fields_omitted_when_none_observed`, via `bind_fields_to_observed`
(gate 5) rather than a prompt-text assertion - the invariant is CODE now, not
prose (DPL-DEC-07).

The DataItem model no longer carries a speculative `likely_fields`; observed
fields go into an evidence-bound `fields` list (AMV-10).
"""
from polymerhus.analysis.pod import _assignment_prompt


# --- FR-INVENTORY (AST-INV-02): the assignment prompt pins existing identities --

def test_assignment_prompt_pins_existing_identities():
    """AST-INV-02: the assignment prompt renders the EXISTING L1 IDENTITIES block
    at the TOP with a reuse instruction and the exact keys, so the analyser reuses
    `sign-in` rather than coining `signin`/`login`."""
    inv = {"services": ["sign-in"], "systems": ["CDN:cloudflare"], "data_items": ["loyalty_ledger"]}
    p = _assignment_prompt({"nodes": []}, [], inventory=inv)
    assert "EXISTING L1 IDENTITIES" in p
    # the exact keys are rendered verbatim (machine-legible bullet list)
    assert "sign-in" in p
    assert "CDN:cloudflare" in p
    assert "loyalty_ledger" in p
    # the reuse instruction that gives the block its teeth
    assert "reuse" in p.lower() and "synonym" in p.lower()
    # the block is at the TOP - before the controlled-vocabulary section
    assert p.index("EXISTING L1 IDENTITIES") < p.index("CONTROLLED VOCABULARIES")


# --- FR-TYPESEP-a (AST-TYPE-01): system facts are edges, not Service props ---

def test_assignment_prompt_forbids_system_facts_on_service():
    """AST-TYPE-01 / AST-MODEL-04: the assignment prompt names rendering_model/
    navigation_model and instructs an EXPOSED_VIA edge to a WebPresentation System
    (not a Service prop, and NOT the deleted RENDERED_BY), plus the paradigm/
    perimeter mappings, with the Stage-3 DFS rationale."""
    p = _assignment_prompt({"nodes": []}, [], inventory={})
    # the rule heading makes the constraint explicit
    assert "SYSTEM FACTS ARE EDGES" in p
    # the spine slots that must NOT be Service props (none appear in the vocab)
    assert "rendering_model" in p
    assert "navigation_model" in p
    assert "api_paradigm" in p
    assert "perimeter" in p
    # rendering_model/navigation_model -> EXPOSED_VIA a WebPresentation System
    # (the corrected model); the deleted RENDERED_BY edge must NOT be mentioned
    assert "WebPresentation" in p
    assert "EXPOSED_VIA" in p
    assert "RENDERED_BY" not in p
    # emitted via the system_edges channel, and the DFS rationale is stated
    assert "system_edges" in p
    assert "DFS" in p or "depth-first" in p.lower()
