"""WI-2: the analyser data-modelling prompt must ask for EVIDENCE-BOUND fields.

The DataItem model no longer carries a speculative `likely_fields`; observed
fields go into an evidence-bound `fields` list, and further attribute discovery is
deferred to a dedicated enrichment activity (AMV-10). These assertions encode that
prompt contract so a future edit cannot silently reintroduce guessed fields.
"""
from polymerhus.analysis.analyser_types import L1DeltaBatch
from polymerhus.analysis.pod import _assignment_prompt, _data_modelling_prompt


def test_data_modelling_prompt_asks_for_observed_fields_only():
    prompt = _data_modelling_prompt({"nodes": []}, L1DeltaBatch())
    low = prompt.lower()
    assert "fields" in low  # the fields channel exists
    assert "observed" in low  # it is scoped to observed fields
    assert "speculative" in low  # and explicitly forbids a speculative list


def test_data_modelling_prompt_does_not_reintroduce_likely_fields():
    prompt = _data_modelling_prompt({"nodes": []}, L1DeltaBatch())
    assert "likely_fields" not in prompt  # the removed concept never returns


# --- FR-INVENTORY (AST-INV-02): both prompts pin the existing L1 identities ---

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


def test_data_modelling_prompt_pins_existing_identities():
    """AST-INV-02: the data-modelling pass (which otherwise drops the L0 slice
    entirely) also carries the un-truncated EXISTING L1 IDENTITIES block + reuse
    instruction, so pass-2 reuses an existing DataItem key instead of a synonym."""
    inv = {"services": ["cart"], "systems": [], "data_items": ["loyalty_ledger"]}
    p = _data_modelling_prompt({"nodes": []}, L1DeltaBatch(), inventory=inv)
    assert "EXISTING L1 IDENTITIES" in p
    # a distinctive key NOT present in the worked example proves the block injected it
    assert "loyalty_ledger" in p
    assert "reuse" in p.lower() and "synonym" in p.lower()
    # rendered at the TOP - before the data-modelling task text
    assert p.index("EXISTING L1 IDENTITIES") < p.index("LOGICAL DATA MODELLING")


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
