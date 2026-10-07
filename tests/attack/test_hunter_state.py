"""Unit tier: the state-graph hunter's payload-shape consumer (#313).

The hunter memory is a status-varying schema: a non-`specified` write is a
hypothesis-only FaultItem draft; a `specified` write is the typed
`TestImplementationSpec` base (`target_identity` / `verification_symptoms` /
`testing_pattern` / `assumptions` / `payload_vector_space` + the two NL fields),
carrying the file-name identity keywords `fault_keyword` / `strategy_keyword`.
The passive state machine consumes that payload, so it must derive the
canonical semantic spec id `<fault_keyword>_<strategy_keyword>` - never an empty
identity that collapses every ratified spec under one key.
"""
from __future__ import annotations

from polymerhus.attack.hunting.hunter_state import push_transition


def _typed_specified(**extra) -> dict:
    body = {
        "target_identity": {"url": "http://t/", "unit_id": "Service:slug:a"},
        "verification_symptoms": ["state-changing request accepted"],
        "testing_pattern": "cross-site form submission",
        "assumptions": ["authenticated session"],
        "payload_vector_space": {"method": "POST", "path": "/x"},
        "rationale": "r", "interpretation_guidance": "g",
        "status": "specified",
        "fault_keyword": "csrf", "strategy_keyword": "probe",
    }
    body.update(extra)
    return body


def test_specify_derives_the_semantic_identity_from_the_typed_payload():
    """#313 - the typed specified payload carries no `spec_id`; the state machine
    derives the canonical `<fault>_<strategy>` identity from the file-name
    identity keywords instead of yielding an empty id."""
    state = push_transition({}, "specify", _typed_specified())
    specs = state.get("ratified_specs") or []
    assert len(specs) == 1
    assert specs[0]["spec_id"] == "csrf_probe"
    assert specs[0]["strategy"] == "probe"
    assert specs[0]["status"] == "specified"


def test_distinct_typed_specs_keep_distinct_identities():
    """#313 - the empty-identity regression collided every specified payload
    under `spec_id == ""` (the upsert key), so a second spec overwrote the
    first. Distinct keywords must yield distinct entries."""
    state = push_transition({}, "specify", _typed_specified())
    state = push_transition(
        state, "specify",
        _typed_specified(fault_keyword="idor", strategy_keyword="enum"),
    )
    ids = [s["spec_id"] for s in state["ratified_specs"]]
    assert ids == ["csrf_probe", "idor_enum"]


def test_explicit_spec_id_still_wins_over_the_derived_identity():
    """Backward compatibility: a payload carrying an explicit `spec_id` keeps it
    (the derived identity is only a fallback)."""
    state = push_transition({}, "specify", _typed_specified(spec_id="S1"))
    assert state["ratified_specs"][0]["spec_id"] == "S1"


def test_derived_identity_sanitises_like_the_file_stem():
    """#313 - the derived `spec_id` sanitises each keyword the same way the
    store's file-name stem does (banned separator chars -> `-`), so the
    in-memory identity equals the persisted stem for any keyword."""
    state = push_transition(
        {}, "specify",
        _typed_specified(fault_keyword="a_b", strategy_keyword="c"),
    )
    assert state["ratified_specs"][0]["spec_id"] == "a-b_c"


def test_banned_chars_do_not_collide_two_distinct_pairs():
    """#313 - without sanitisation, `('a_b','c')` and `('a','b_c')` both derived
    `a_b_c` and collided under one upsert key; the sanitised derivation keeps
    them distinct, matching the two distinct file stems."""
    state = push_transition(
        {}, "specify",
        _typed_specified(fault_keyword="a_b", strategy_keyword="c"),
    )
    state = push_transition(
        state, "specify",
        _typed_specified(fault_keyword="a", strategy_keyword="b_c"),
    )
    ids = [s["spec_id"] for s in state["ratified_specs"]]
    assert ids == ["a-b_c", "a_b-c"]
