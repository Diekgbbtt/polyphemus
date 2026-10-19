"""T7 (#380): a dry mocked run through the prompt's pass protocol.

The live edge - the LLM - is a scripted model emitting the REAL tool calls the
production prompt tells the hunter to make: the five phase-summary notes, the
batched all-`hypothesised` set write, the well-formedness note, and the terminal
promote/declass set write. The real harness, the real pass tracker, and the real
per-project `HunterMemoryStore` ride, so the artifact read back is the prompt's
protocol executed end to end, not a live-model quality claim.

The set is checked for the properties the prompt promises: a well-formed,
disjoint spec set over the slice; every body the reduced D4 surface; the drops
applied only at the terminal write; the mixed status set refused.
"""
from __future__ import annotations

from polymerhus.attack.hunting.spec_contract import SKILL_PROCEDURE_FIELDS
from tests.hunting_fixtures import (
    HUNT_KEY,
    PROJECT,
    UNIT_ID,
    _answer,
    _hunter_payload,
    _tool_call,
    build_hunter_agent,
    build_memory_store,
)

URL = "http://soupmarket.shop/"


def _phase_note(phase, *, action="append", body=None):
    return _tool_call("notes", {
        "command": "write", "action": action,
        "note_name": f"phase:{phase}", "kind": "phase_summary",
        "body": body or f"the {phase} pass output",
    })


def _spec(status, fault, strategy, *, symptom, assumption, rationale):
    """One entry of the batched `specs` set at the reduced D4 surface (S3 8.6):
    the target identity, the observable symptoms, the assumptions, the
    vulnerability-level rationale, and the typed provenance with the seven-field
    skill-procedure excerpt."""
    return {
        "status": status,
        "fault_keyword": fault,
        "strategy_keyword": strategy,
        "target_identity": {"url": URL, "unit_id": UNIT_ID},
        "verification_symptoms": [symptom],
        "assumptions": [assumption],
        "rationale": rationale,
        "provenance": {
            "loop_id": "loop-1",
            "unit_id": UNIT_ID,
            "canonical_class": "IDOR",
            "web_vulnerability_class": "idor",
            "baseline_ref": "GET /api/a",
            "skill_procedure": {
                field: f"the class skill's {field} excerpt"
                for field in SKILL_PROCEDURE_FIELDS
            },
        },
    }


def _generated():
    """The three disjoint sub-slices the discrimination yields: the direct
    lookup, the signed-URL delivery, and the share-route precondition."""
    return [
        _spec(
            "hypothesised", "id_unbound", "direct_read",
            symptom="another tenant's item body is returned to the caller",
            assumption="the lookup authorises the caller against the item's owner",
            rationale="The lookup trusts the caller's item id; an unbound read "
                      "manifests as another tenant's item body.",
        ),
        _spec(
            "hypothesised", "id_unbound", "signed_url",
            symptom="a signed URL minted from the item id returns another "
                    "tenant's object",
            assumption="the signed URL is scoped to the caller's tenant",
            rationale="The object store trusts the URL's scope, while the item "
                      "id crosses the boundary unbound.",
        ),
        _spec(
            "hypothesised", "share_route", "mint_url",
            symptom="a viewer obtains a share URL for an item it cannot read",
            assumption="the share route checks readability before minting",
            rationale="The share route trusts the caller's item id and may mint "
                      "a delivery capability the lookup would refuse.",
        ),
    ]


def _set_write(specs):
    return _tool_call("hunts_store", {"command": "write", "specs": specs})


def _run(tmp_path, steps):
    store = build_memory_store(tmp_path)
    return store, build_hunter_agent(store, steps=steps)(_hunter_payload())


def test_the_dry_run_produces_a_well_formed_persisted_spec_set(tmp_path):
    """The prompt's protocol end to end: ground, slice, collect, discriminate,
    generate the whole set, check well-formedness, verify, and apply the drops
    at the terminal write."""
    generated = _generated()
    steps = [
        _phase_note("grounding", body="Frame explicit; failure modes: the lookup "
                    "ownership check, the signed-URL scope, the share-route "
                    "readability check."),
        _phase_note("slice", body="Report-id authorisation over the direct "
                    "download and the signed-URL delivery; boundary on the "
                    "effective request item and the delivery behaviour."),
        _tool_call("kb_query", {"scenario_id": "item-lookup",
                                "attack_goal": "instance mining",
                                "concern": "object storage"}),
        _phase_note("collect", body="Instances: direct lookup, signed-URL "
                    "redirect (payload-vector classes); share-route minting "
                    "(advanced technique); viewer session (chaining)."),
        _phase_note("discriminate", body="Separate on authorisation source x "
                    "delivery behaviour; narrow on the item id, broad on the "
                    "two delivery routes."),
        _set_write(generated),                          # the GENERATE exit
        _phase_note("well_formedness", body="No overlap: the direct read, the "
                    "signed URL, and the share route own disjoint sub-slices. "
                    "Coverage basis: both delivery routes and the minting "
                    "precondition are named. Planned drop: the share-route spec "
                    "if the viewer mint probe proves the route absent."),
        _set_write([
            {**generated[0], "status": "ratified"},
            {**generated[1], "status": "ratified"},
            {**generated[2], "status": "dropped"},
        ]),                                             # the VERIFY-CLAIMS exit
    ]
    store, result = _run(tmp_path, steps)

    assert result["state"] == "complete"
    assert "state: complete" in result["feedback"]
    assert "ratified: id-unbound_direct-read" in result["feedback"]

    produced = (tmp_path / PROJECT / "hunting" / "hunter" / "test-specs"
                / HUNT_KEY / "produced")
    # the derived identities are the file-name stems; the set is disjoint
    names = {path.stem for path in produced.glob("*.yaml")}
    assert names == {
        "id-unbound_direct-read", "id-unbound_signed-url",
        "share-route_mint-url"}
    assert store.read_spec(PROJECT, HUNT_KEY,
                           "id-unbound_direct-read")["status"] == "ratified"
    assert store.read_spec(PROJECT, HUNT_KEY,
                           "id-unbound_signed-url")["status"] == "ratified"
    assert store.read_spec(PROJECT, HUNT_KEY,
                           "share-route_mint-url")["status"] == "dropped"

    # every persisted body is the reduced D4 at its status
    for spec in store.read_specs(PROJECT, HUNT_KEY):
        assert spec["target_identity"] == {"url": URL, "unit_id": UNIT_ID}
        assert spec["verification_symptoms"]
        assert spec["assumptions"] and spec["rationale"]
        assert set(spec["provenance"]["skill_procedure"]) == set(
            SKILL_PROCEDURE_FIELDS)
        for retired in ("payload_vector_space", "interpretation_guidance",
                        "testing_pattern", "spec_id"):
            assert retired not in spec
    # the generated draft set was the whole set in ONE write: the terminal write
    # upserted the three identities in place, it did not create a fourth
    assert len(list(produced.glob("*.yaml"))) == 3

    # the five note exits persisted as the hunter-only phase kind
    notes = store.read_notes(PROJECT)
    phase = {n["note_name"]: n for n in notes if n["kind"] == "phase_summary"}
    assert set(phase) == {
        "phase:grounding", "phase:slice", "phase:collect",
        "phase:discriminate", "phase:well_formedness"}
    assert "Planned drop" in phase["phase:well_formedness"]["body"]


def test_a_mixed_status_set_is_refused_and_never_moves_the_tracker(tmp_path):
    """The store protocol is unambiguous: a set mixing `hypothesised` with a
    terminal status is not a lifecycle shape. It persists nothing, closes no
    pass, and leaves the generated draft intact; the correct terminal write then
    lands."""
    generated = _generated()[:2]
    mixed = [{**generated[0], "status": "ratified"},
             {**generated[1], "status": "hypothesised"}]
    correct = [{**generated[0], "status": "ratified"},
               {**generated[1], "status": "dropped"}]
    steps = [
        _phase_note("grounding"),
        _phase_note("slice"),
        _phase_note("collect"),
        _phase_note("discriminate"),
        _set_write(generated),
        _phase_note("well_formedness"),
        _set_write(mixed),        # refused: the tracker must stay in VERIFY-CLAIMS
        _answer("still verifying"),
    ]
    store, result = _run(tmp_path, steps)

    assert result["state"] == "verify_claims"
    assert "state: complete" not in result["feedback"]
    assert [s["status"] for s in store.read_specs(PROJECT, HUNT_KEY)] == [
        "hypothesised", "hypothesised"]

    # the correct terminal write closes the chain
    store, result = _run(tmp_path / "second", steps[:-2] + [_set_write(correct)])
    assert result["state"] == "complete"
    assert {name: store.read_spec(PROJECT, HUNT_KEY, name)["status"]
            for name in ("id-unbound_direct-read", "id-unbound_signed-url")} == {
        "id-unbound_direct-read": "ratified",
        "id-unbound_signed-url": "dropped",
    }
