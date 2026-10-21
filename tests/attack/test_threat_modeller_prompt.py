"""The threat modeller's reference-ID contract.

The completion check rejects an unresolved reference and archives the unit, so
the prompt and the `hunts_store` tool description must teach the same namespace
discipline. The 2026-10-21 white-jotter run lost four units because the model
put prose in `maps_to_fault` and control/data-flow IDs in
`interface_agreement_refs`; these tests pin the fix.
"""
from polymerhus.attack.hunting.llm import _modeller_skill
from polymerhus.attack.hunting.threat_modeller_tools import (
    _HUNTS_STORE_DESCRIPTION,
)


def test_the_modeller_prompt_teaches_the_reference_id_contract():
    prompt = _modeller_skill()

    assert "Reference fields" in prompt
    # The two fields that broke the white-jotter run.
    assert "interface_agreement_refs" in prompt
    assert "maps_to_fault" in prompt
    assert "never control flows (`CF-*`) or data flows (`DF-*`)" in prompt
    assert "never prose" in prompt
    # The full namespace table, so no other reference drifts the same way.
    for token in (
        "`F-*`", "`V-*`", "`FM-*`", "`IA-*`", "`TA-*`", "`TR-*`",
    ):
        assert token in prompt


def test_the_hunts_store_description_names_the_reference_fields():
    assert "interface_agreement_refs" in _HUNTS_STORE_DESCRIPTION
    assert "maps_to_fault" in _HUNTS_STORE_DESCRIPTION
    assert "ID" in _HUNTS_STORE_DESCRIPTION
