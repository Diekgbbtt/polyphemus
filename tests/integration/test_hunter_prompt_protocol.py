"""T7 (#380): a dry mocked run through the prompt's pass protocol.

The live edge - the LLM - is a scripted model emitting the REAL tool calls the
production prompt tells the hunter to make: the five phase-summary notes, one
`hypothesised` write per spec, the well-formedness note, one terminal status
write per spec, and the finalize call. The real harness, the real pass tracker,
and the real per-project `HunterMemoryStore` ride, so the artifact read back is
the prompt's protocol executed end to end, not a live-model quality claim.

The set is checked for the properties the prompt promises: a well-formed,
disjoint spec set over the slice; every body the reduced D4 surface; the drops
applied only at the one-spec terminal writes; a partial set refused at finalize;
a merged identity absorbed without breaking the whole set; and a [D2]
phase-note rewrite that stays trail material.
"""
from __future__ import annotations

from polymerhus.attack.hunting.spec_contract import (
    SKILL_CONCRETISED_PROCEDURE_FIELDS,
)
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
    """One spec at the reduced D4 surface (S3 8.6):
    the target identity, the observable symptoms, the assumptions, the
    vulnerability-level rationale, and the typed provenance with the seven-field
    skill-procedure excerpt."""
    return {
        "status": status,
        "discriminators": [
            {"axis": "fault", "value": fault.replace("_", "-")},
            {"axis": "technique", "value": strategy.replace("_", "-")},
        ],
        "target_identity": {"url": URL, "unit_id": UNIT_ID},
        "verification_symptoms": [symptom],
        "assumptions": [assumption],
        "rationale": rationale,
        "provenance": {
            "threat_id": "threat-1",
            "unit_id": UNIT_ID,
            "canonical_class": "IDOR",
            "web_vulnerability_class": "idor",
            "baseline_ref": "http_01J0000000000000000000000A",
        },
        "skill_concretised_procedure": {
            field: f"the class skill's {field} excerpt"
            for field in SKILL_CONCRETISED_PROCEDURE_FIELDS
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
            rationale="The item lookup treats the client-supplied item id as an "
                      "authorisation input, so the tenant boundary is decided by "
                      "the request.",
        ),
        _spec(
            "hypothesised", "id_unbound", "signed_url",
            symptom="a signed URL minted from the item id returns another "
                    "tenant's object",
            assumption="the signed URL is scoped to the caller's tenant",
            rationale="The object store scopes the delivery capability while the "
                      "item id crosses the trust boundary unbound.",
        ),
        _spec(
            "hypothesised", "share_route", "mint_url",
            symptom="a viewer obtains a share URL for an item it cannot read",
            assumption="the share route checks readability before minting",
            rationale="The share capability is minted from the item id before "
                      "the readability check decides the tenant.",
        ),
    ]


def _write_spec(spec):
    return _tool_call("hunts_store", {"command": "write", "spec": spec})


def _finalize():
    return _tool_call("hunts_store", {"command": "finalize"})


def _run(tmp_path, steps):
    store = build_memory_store(tmp_path)
    return store, build_hunter_agent(store, steps=steps)(_hunter_payload())


def test_the_dry_run_produces_a_well_formed_persisted_spec_set(tmp_path):
    """The prompt's protocol end to end: ground, slice, collect, discriminate,
    generate one spec per call, check well-formedness, verify, apply the drops
    one call per spec, and finalize."""
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
        *[_write_spec(spec) for spec in generated],    # the GENERATE exit
        _phase_note("well_formedness", body="No overlap: the direct read, the "
                    "signed URL, and the share route own disjoint sub-slices. "
                    "Coverage basis: both delivery routes and the minting "
                    "precondition are named. Planned drop: the share-route spec "
                    "if the viewer mint probe proves the route absent."),
        _write_spec({**generated[0], "status": "ratified"}),
        _write_spec({**generated[1], "status": "ratified"}),
        _write_spec({**generated[2], "status": "dropped"}),
        _finalize(),                                    # the VERIFY-CLAIMS exit
    ]
    store, result = _run(tmp_path, steps)

    assert result["state"] == "complete"
    assert "state: complete" in result["feedback"]
    assert "ratified: idor__id-unbound__direct-read" in result["feedback"]

    produced = (tmp_path / PROJECT / "hunting" / "hunter" / "test-specs"
                / HUNT_KEY / "produced")
    # the derived identities are the file-name stems; the set is disjoint
    names = {path.stem for path in produced.glob("*.yaml")}
    assert names == {
        "idor__id-unbound__direct-read", "idor__id-unbound__signed-url",
        "idor__share-route__mint-url"}
    assert store.read_spec(PROJECT, HUNT_KEY,
                           "idor__id-unbound__direct-read")["status"] == "ratified"
    assert store.read_spec(PROJECT, HUNT_KEY,
                           "idor__id-unbound__signed-url")["status"] == "ratified"
    assert store.read_spec(PROJECT, HUNT_KEY,
                           "idor__share-route__mint-url")["status"] == "dropped"

    # every persisted body is the reduced D4 at its status
    for spec in store.read_specs(PROJECT, HUNT_KEY):
        assert spec["target_identity"] == {"url": URL, "unit_id": UNIT_ID}
        assert spec["verification_symptoms"]
        assert spec["assumptions"] and spec["rationale"]
        assert set(spec["skill_concretised_procedure"]) == set(
            SKILL_CONCRETISED_PROCEDURE_FIELDS)
        for retired in ("payload_vector_space", "interpretation_guidance",
                        "testing_pattern", "spec_id"):
            assert retired not in spec
    # the three one-spec writes and the three terminal status writes upserted
    # the same identities in place; no fourth identity appeared
    assert len(list(produced.glob("*.yaml"))) == 3

    # the five note exits persisted as the hunter-only phase kind
    notes = store.read_notes(PROJECT)
    phase = {n["note_name"]: n for n in notes if n["kind"] == "phase_summary"}
    assert set(phase) == {
        "phase:grounding", "phase:slice", "phase:collect",
        "phase:discriminate", "phase:well_formedness"}
    assert "Planned drop" in phase["phase:well_formedness"]["body"]


def test_a_partial_terminal_set_is_refused_until_finalize(tmp_path):
    """A single terminal status write does not close the set. `finalize` while a
    sibling is still hypothesised is a coded rejection: it persists no terminal
    record, moves no state, and leaves the draft intact. The correct sibling
    decision then lets finalize land."""
    generated = _generated()[:2]
    steps = [
        _phase_note("grounding"),
        _phase_note("slice"),
        _phase_note("collect"),
        _phase_note("discriminate"),
        *[_write_spec(spec) for spec in generated],
        _phase_note("well_formedness"),
        _write_spec({**generated[0], "status": "ratified"}),
        _finalize(),              # refused: the sibling is still a draft
    ]
    store, result = _run(tmp_path, steps)

    assert result["state"] == "verify_claims"
    assert "state: complete" not in result["feedback"]
    assert [s["status"] for s in store.read_specs(PROJECT, HUNT_KEY)] == [
        "ratified", "hypothesised"]
    assert store.read_terminal_set(PROJECT, HUNT_KEY) is None

    # the correct sibling decision then finalizes the chain
    correct = steps[:-1] + [
        _write_spec({**generated[1], "status": "dropped"}),
        _finalize(),
    ]
    store, result = _run(tmp_path / "second", correct)
    assert result["state"] == "complete"
    assert {name: store.read_spec(PROJECT, HUNT_KEY, name)["status"]
            for name in ("idor__id-unbound__direct-read", "idor__id-unbound__signed-url")} == {
        "idor__id-unbound__direct-read": "ratified",
        "idor__id-unbound__signed-url": "dropped",
    }
    assert store.read_terminal_set(PROJECT, HUNT_KEY) is not None


def test_a_merge_widens_the_survivor_and_declasses_the_absorbed_identity(tmp_path):
    """S3 8.5 + S4 14.6: a [D2] merge keeps one identity, widens it, and
    carries the absorbed identity as `dropped` at the terminal write.

    S4 14.6 defines `dropped` as "the declass of a verified-unfeasible spec".
    The merge extends that vocabulary: the absorbed identity is declassed for
    overlap, not infeasibility. The extension is forced by the store's
    no-delete, whole-set contract - omitting the absorbed identity from the
    terminal set would leave its produced file `hypothesised` forever, so the
    set would be neither whole nor terminal. The absorbed entry keeps its typed
    body and takes the same terminal status, with the merge reason recorded on
    the `phase:well_formedness` note.
    """
    direct = _spec(
        "hypothesised", "id_unbound", "direct_read",
        symptom="another tenant's item body is returned to the caller",
        assumption="the lookup authorises the caller against the item's owner",
        rationale="The item lookup treats the client-supplied item id as an "
                  "authorisation input, so the tenant boundary is decided by "
                  "the request.",
    )
    signed = _generated()[1]
    export = _spec(
        "hypothesised", "export_route", "export_read",
        symptom="the export route returns another tenant's item body",
        assumption="the export route authorises the item against the caller's tenant",
        rationale="The export route reads the client-supplied item id before "
                  "the tenant check decides the boundary.",
    )
    widened = {
        **direct,
        "verification_symptoms": [direct["verification_symptoms"][0],
                                  export["verification_symptoms"][0]],
        "assumptions": [direct["assumptions"][0], export["assumptions"][0]],
        "rationale": "The item lookup treats the client-supplied item id as an "
                     "authorisation input on both the direct and export routes.",
    }
    steps = [
        _phase_note("grounding", body="Frame explicit; failure modes: the "
                    "lookup ownership check, the export ownership check, the "
                    "signed-URL scope."),
        _phase_note("slice", body="Item-id authorisation over the direct and "
                    "export routes; boundary on the effective request item."),
        _phase_note("collect", body="Instances: direct read and signed-URL "
                    "redirect, both carrying the item id."),
        _phase_note("discriminate", body="Separate on authorisation source x "
                    "route; narrow on the item id, broad on the routes."),
        _write_spec(direct), _write_spec(signed),          # the GENERATE exit
        _phase_note("collect", action="update",             # the [D2] re-entry
                    body="[D2] re-entry: the export route is a new instance; "
                         "re-collect it under the same item-id boundary."),
        _write_spec(direct), _write_spec(signed),
        _write_spec(export),                                # a re-generate write
        _phase_note("well_formedness", body="Merge: the direct-read identity "
                    "widens to name the direct and export routes; the export "
                    "identity is absorbed. No overlap remains; the absorbed "
                    "identity is carried as dropped at the terminal write."),
        _write_spec({**widened, "status": "ratified"}),
        _write_spec({**signed, "status": "ratified"}),
        _write_spec({**export, "status": "dropped"}),
        _finalize(),                                        # the VERIFY exit
    ]
    store = build_memory_store(tmp_path)
    result = build_hunter_agent(store, steps=steps)(_hunter_payload())

    assert result["state"] == "complete"
    produced = (tmp_path / PROJECT / "hunting" / "hunter" / "test-specs"
                / HUNT_KEY / "produced")
    assert {path.stem for path in produced.glob("*.yaml")} == {
        "idor__id-unbound__direct-read", "idor__id-unbound__signed-url",
        "idor__export-route__export-read"}
    # the whole set is terminal: the widened survivor is ratified, the signed
    # sibling survives, and the absorbed identity is declassed - no identity is
    # left in the draft state
    assert {spec["status"] for spec in store.read_specs(PROJECT, HUNT_KEY)} == {
        "ratified", "dropped"}
    survivor = store.read_spec(PROJECT, HUNT_KEY, "idor__id-unbound__direct-read")
    assert survivor["status"] == "ratified"
    assert len(survivor["verification_symptoms"]) == 2
    assert len(survivor["assumptions"]) == 2
    assert store.read_spec(PROJECT, HUNT_KEY,
                           "idor__id-unbound__signed-url")["status"] == "ratified"
    assert store.read_spec(PROJECT, HUNT_KEY,
                           "idor__export-route__export-read")["status"] == "dropped"
    merge_note = [note for note in store.read_notes(PROJECT)
                  if note["note_name"] == "phase:well_formedness"]
    assert len(merge_note) == 1
    assert "absorbed" in merge_note[0]["body"]


def test_a_phase_note_update_on_a_reiteration_is_trail_material(tmp_path):
    """S3 8.5/S4 14.8: a [D2] re-iteration rewrites the same phase note with
    `action=update`; the backward signal is trail material and injects no
    transition hint, so the tracked state never regresses to COLLECT."""
    from polymerhus.attack.hunting.hunter_state import TRANSITION_HINTS  # noqa: PLC0415

    generated = _generated()[:2]
    seen: list = []
    steps = [
        _phase_note("grounding"),
        _phase_note("slice"),
        _phase_note("collect", body="the first instance set"),
        _phase_note("discriminate"),
        *[_write_spec(spec) for spec in generated],
        _phase_note("collect", action="update",
                    body="[D2] re-iteration: the export route is a new instance"),
        _phase_note("well_formedness"),
        _write_spec({**generated[0], "status": "ratified"}),
        _write_spec({**generated[1], "status": "dropped"}),
        _finalize(),
    ]
    store = build_memory_store(tmp_path)
    result = build_hunter_agent(store, steps=steps, seen=seen)(_hunter_payload())

    assert result["state"] == "complete"
    collect_notes = [note for note in store.read_notes(PROJECT)
                     if note["note_name"] == "phase:collect"]
    assert len(collect_notes) == 1                     # rewritten, not appended
    assert collect_notes[0]["body"].startswith("[D2]")

    # step N's tool response arrives as step N+1's input; the update's response
    # carries no transition hint because an earlier pass's signal never exits
    # the current pass (and in particular never moves back to COLLECT).
    update_response = seen[6][-1] or ""
    assert TRANSITION_HINTS["collect"] not in update_response
    assert "<phase-transition-hint>" not in update_response
