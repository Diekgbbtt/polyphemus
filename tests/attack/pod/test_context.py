"""Unit tier: the in-memory context-management component - the experiment log,
the dedup ledger, the filtered agent context, the
BaseMessage id stamping (D84-4), and (D84-2/Q13) the HuntSession address
derivation on the semantic `<fault>_<strategy>` spec id. The interim
token-aware `curate_messages` compaction is removed (D84-13: #95's shared
`CompactionManager` replaces it)."""
from polymerhus.attack.hunting.pod.context import (
    ExperimentLog,
    _dicts_to_lc,
    _lc_to_dicts,
    compose_divergence_delta,
    compose_terminal_delta,
    compose_triage_delta,
    compose_triager_delta,
)
from polymerhus.attack.hunting.pod.pod_memory import PodMemoryStore, spec_identifier
from polymerhus.attack.hunting.pod.types import (
    Interpretation,
    KbObservation,
    RawObservation,
    VariantSpec,
)


# --- D84-4: BaseMessage + add_messages id stamping -----------------------------

def test_dicts_to_lc_stamps_ids_for_add_messages_merge_semantics():
    """D84-4: `_dicts_to_lc` stamps every message with a deterministic id over
    (role, content), so the channel's `add_messages` reducer merges duplicate
    content (dedup-under-same-id) while changed content appends in order."""
    from langgraph.graph.message import add_messages

    a = _dicts_to_lc([{"role": "ai", "content": "same"}])
    b = _dicts_to_lc([{"role": "ai", "content": "same"}])
    assert a[0].id == b[0].id                       # identical content - identical id
    assert [m.id for m in add_messages(a, b)] == [a[0].id]   # merged, not stacked

    c = _dicts_to_lc([{"role": "ai", "content": "other"}])
    assert a[0].id != c[0].id                       # changed content - fresh id, appends
    assert [m.content for m in add_messages(a, c)] == ["same", "other"]

    # The role is part of the identity: same content under a different role differs.
    d = _dicts_to_lc([{"role": "human", "content": "same"}])
    assert a[0].id != d[0].id


def test_lc_to_dicts_views_carry_a_stable_id_and_honour_explicit_ones():
    """The seam-facing views stay `{role, content}` dicts while carrying the
    channel id: re-converting a view through `_dicts_to_lc` reproduces the SAME
    id, an id-less BaseMessage is stamped to the same deterministic id, and an
    explicit dict id overrides the stamp - so a seam-side re-statement still
    dedups under `add_messages`."""
    from langchain_core.messages import HumanMessage

    lc = _dicts_to_lc([{"role": "human", "content": "go"}])
    view = _lc_to_dicts(lc)[0]
    assert view["role"] == "human" and view["content"] == "go"
    assert view["id"] == lc[0].id                    # the stamped id survives the view
    assert _dicts_to_lc([view])[0].id == lc[0].id    # ... and the round trip

    # An id-less BaseMessage is stamped to the same deterministic id.
    assert _lc_to_dicts([HumanMessage(content="go")])[0]["id"] == lc[0].id

    # An explicit id wins over the deterministic stamp.
    assert _dicts_to_lc(
        [{"role": "human", "content": "go", "id": "custom-1"}])[0].id == "custom-1"


def test_dedup_ledger_marks_and_reports():
    log = ExperimentLog()
    assert not log.has_executed("sig-1")
    log.mark_executed("sig-1")
    log.mark_executed("sig-1")  # idempotent
    assert log.has_executed("sig-1")
    assert log.executed == ["sig-1"]


def test_variant_refs_expose_every_tried_variant():
    log = ExperimentLog()
    log.record_variant(VariantSpec(ref="v0", spec={}))
    log.record_variant(VariantSpec(ref="v1", parent_ref="v0", spec={}))
    log.record_variant(VariantSpec(ref="v1", parent_ref="v0", spec={}))  # dup ref ignored
    assert log.variant_refs() == ["v0", "v1"]


def test_triager_context_surfaces_prior_variants_for_non_duplication():
    log = ExperimentLog()
    log.record_variant(VariantSpec(ref="v0", spec={}))
    log.record_variant(VariantSpec(ref="v1", parent_ref="v0"))
    log.record_interpretation(Interpretation(variant="v0", classification="symptom-absent",
                                             note="no reflection"))
    ctx = log.triager_context({"target_identity": {"url": "http://svc/", "unit_id": "svc"}},
                              RawObservation(status=200, body="hi"))
    assert "v0" in ctx and "v1" in ctx           # sees what was tried
    assert "never mine a duplicate" in ctx.lower()


def test_triager_context_carries_variant_bases_and_executed_probes():
    """S5 8.6 step 2: the executed procedure comes from the D6 trail - the
    variant bases (the duplicate guard's first half) and the probe commands."""
    log = ExperimentLog()
    log.record_variant(VariantSpec(
        ref="v1", parent_ref="v0", declined_attribute="bypass-technique",
        spec={"rationale": "swap the id in the signed URL"}))
    log.record_observation(RawObservation(
        variant_ref="v1", request={"command": "curl -k https://svc/item/2"}, status=404))
    ctx = log.triager_context({"target_identity": {"url": "http://svc/", "unit_id": "svc"}},
                              None)
    assert "bypass-technique" in ctx
    assert "swap the id in the signed URL" in ctx
    assert "curl -k https://svc/item/2" in ctx


def test_runner_context_lists_executed_signatures():
    log = ExperimentLog()
    log.mark_executed("sig-abc")
    ctx = log.runner_context({"target_identity": {"url": "http://svc/", "unit_id": "svc"}}, feedback="vary the encoding",
                             iteration=2, budget=8)
    assert "sig-abc" in ctx
    assert "vary the encoding" in ctx
    assert "Lap 2" in ctx


def _spec_with_typed_procedure() -> dict:
    return {
        "target_identity": {"url": "http://svc/", "unit_id": "svc"},
        "discriminators": [
            {"axis": "actor", "value": "viewer"},
            {"axis": "state", "value": "post-delete"},
        ],
        "skill_concretised_procedure": {
            "recon_action": "the role check trusts the session",
            "bypass_technique": "swap the role cookie",
            "payload_vector": "the role cookie name, no encoding",
            "technology_misconfiguration": "the gateway trusts the client role",
            "pro_tips": "confirm the authenticated landing",
        },
        "provenance": {"threat_id": "threat-1"},
    }


def test_triager_context_renders_the_typed_procedure_once():
    """CL-3 context-only dedup: the typed concretisation is the one rendering;
    the full spec JSON no longer repeats `skill_concretised_procedure`."""
    log = ExperimentLog()
    ctx = log.triager_context(_spec_with_typed_procedure(), None)
    assert ctx.count("## Skill procedure") == 1
    assert "skill_concretised_procedure" not in ctx
    assert "the role check trusts the session" in ctx


def test_runner_context_projects_the_typed_procedure_out_of_the_spec_json():
    log = ExperimentLog()
    ctx = log.runner_context(_spec_with_typed_procedure(), feedback="", iteration=1,
                             budget=3)
    assert "skill_concretised_procedure" not in ctx
    assert "the role check trusts the session" not in ctx


# --- the staged triage deltas --------------------------------------------------

def _staged_log_and_spec(tmp_path):
    store = PodMemoryStore(tmp_path)
    spec_id = spec_identifier("sqli", [{"axis": "technique", "value": "blind"}, {"axis": "payload-vector", "value": "boolean"}])
    store.write_experiment_log(spec_id, 1, {"order": 1, "variant_ref": "v1",
                                            "raw_observations": [],
                                            "kb_observations": [],
                                            "interpretations": [], "executed": []})
    store.write_variant_summary(spec_id, 1, "the consolidated stretch note")
    log = ExperimentLog(store=store, spec_id=spec_id)
    log.record_variant(VariantSpec(ref="v0", spec={}))
    log.record_variant(VariantSpec(
        ref="v1", parent_ref="v0", declined_attribute="bypass-technique",
        spec={"rationale": "swap the marker in the reflected field"}))
    log.record_observation(RawObservation(
        variant_ref="v1", request={"command": "curl -k https://svc/search?q=marker"},
        status=404))
    log.record_kb_observation(KbObservation(
        variant_ref="v1", query="reflected markers", source=None, degraded=True))
    log.record_interpretation(Interpretation(
        variant="v0", classification="symptom-absent", note="not reflected"))
    spec = _spec_with_typed_procedure()
    spec["verification_symptoms"] = ["reflects the marker"]
    spec["assumptions"] = ["the session cookie is the only auth factor"]
    observation = RawObservation(variant_ref="v1", status=404, body="not found")
    return store, spec_id, log, spec, observation


def test_the_triage_delta_is_compact(tmp_path):
    """Stage A reads the note, the symptoms, the identity, the assumptions, and
    the observation - and nothing the first-pass check does not need: no typed
    procedure, no variants, no probe trail, no interpretations, no memory
    key-list."""
    store, spec_id, log, spec, observation = _staged_log_and_spec(tmp_path)
    delta = compose_triage_delta(log, spec, observation, store=store,
                                 spec_id=spec_id, order=1)
    assert "the consolidated stretch note" in delta
    assert "## Verification symptoms" in delta
    assert "reflects the marker" in delta
    assert "## Target identity" in delta
    assert "http://svc/" in delta
    assert "## Assumptions" in delta
    assert "the session cookie" in delta
    assert "## Latest observation" in delta
    assert "## Skill procedure" not in delta
    assert "## Variants already tried" not in delta
    assert "## Probes executed" not in delta
    assert "## Recent interpretations" not in delta
    assert "Pod experiment memory" not in delta


def test_the_divergence_delta_adds_the_typed_procedure_and_the_probes(tmp_path):
    store, spec_id, log, spec, observation = _staged_log_and_spec(tmp_path)
    delta = compose_divergence_delta(log, spec, observation, store=store,
                                     spec_id=spec_id, order=1)
    assert "## Skill procedure" in delta
    assert "the role check trusts the session" in delta
    assert "## Probes executed" in delta
    assert "curl -k https://svc/search?q=marker" in delta
    # Divergence is a procedure comparison, not a duplicate check.
    assert "## Variants already tried" not in delta
    assert "## Recent interpretations" not in delta


def test_the_terminal_delta_carries_the_trail_and_the_kb_flags(tmp_path):
    store, spec_id, log, spec, observation = _staged_log_and_spec(tmp_path)
    delta = compose_terminal_delta(log, spec, observation, store=store,
                                   spec_id=spec_id, order=1)
    assert "## Probes executed" in delta
    assert "curl -k https://svc/search?q=marker" in delta
    assert "## Variants already tried" in delta
    assert "bypass-technique" in delta
    assert "## KB observations" in delta
    assert "degraded=True" in delta
    assert "## Recent interpretations" in delta
    # The terminal stage does not need the procedure diff material.
    assert "## Skill procedure" not in delta


def test_the_full_triager_delta_stays_full(tmp_path):
    store, spec_id, log, spec, observation = _staged_log_and_spec(tmp_path)
    delta = compose_triager_delta(log, spec, observation, store=store,
                                  spec_id=spec_id, order=1)
    assert "## Skill procedure" in delta
    assert "## Variants already tried" in delta
    assert "## Probes executed" in delta
    assert "## Recent interpretations" in delta
    assert "Pod experiment memory" in delta


def test_start_run_clears_stale_summaries_across_all_on_file_orders(tmp_path):
    """D84-37 / the consolidated code-review finding: a re-run must NOT serve a
    prior run's `experiment_summary` for ANY order the new run does not reach
    with a fresh P3 write. `start_run` clears the stale summary from every
    on-file order, not just order 0, so the persisted log is the current truth
    (a budget/triager terminate mid-stretch at a higher order cannot leak the
    old order's summary to the Triager)."""
    store = PodMemoryStore(tmp_path)
    spec_id = spec_identifier("sqli", [{"axis": "technique", "value": "blind"}, {"axis": "payload-vector", "value": "boolean"}])
    store.write_experiment_log(spec_id, 0, {"order": 0, "variant_ref": "v0",
                                            "raw_observations": [], "kb_observations": [],
                                            "interpretations": [], "executed": []})
    store.write_experiment_log(spec_id, 1, {"order": 1, "variant_ref": "v1",
                                            "raw_observations": [], "kb_observations": [],
                                            "interpretations": [], "executed": []})
    store.write_variant_summary(spec_id, 0, "stale summary for order 0")
    store.write_variant_summary(spec_id, 1, "stale summary for order 1")

    log = ExperimentLog(store=store, spec_id=spec_id)
    log.start_run()

    assert store.read_experiment_log(spec_id, 0).get("experiment_summary") is None
    assert store.read_experiment_log(spec_id, 1).get("experiment_summary") is None


def test_pod_session_address_derives_a_per_spec_hunt_session():
    """D84-2/Q13: `_pod_session_address` derives the pod's `HuntSession` address
    with the semantic `<fault>_<strategy>` spec id (the #164 hunter's
    `SpecItem.spec_id`, ADR #169 Q13 - never a content hash) as the per-spec
    discriminator and the given role, so concurrent pod sessions on one hunt
    never collide (#94); an empty hunt_id defaults to "" rather than shifting
    the address."""
    from polymerhus.attack.hunting.pod.pod import _pod_session_address

    spec_id = spec_identifier("sqli", [{"axis": "technique", "value": "blind"}, {"axis": "payload-vector", "value": "boolean"}])
    addr = _pod_session_address("run-1", "hunt-A", spec_id, "pod_runner")

    assert addr.role_id == "pod_runner"
    assert addr.spec == spec_id
    assert addr.run_id == "run-1"
    assert addr.hunt_id == "hunt-A"
    assert addr.thread_id.startswith("run-1:hunt-A:")
    # The semantic spec id discriminates the thread: two specs on one hunt
    # diverge (per concurrent pod instance - Q13).
    other = _pod_session_address("run-1", "hunt-A",
                                 spec_identifier("xss", [{"axis": "technique", "value": "reflected"}, {"axis": "payload-vector", "value": "html"}]),
                                 "pod_runner")
    assert addr.thread_id != other.thread_id
    # A missing hunt_id never shifts the address (empty discriminators are dropped).
    assert _pod_session_address("run-1", "", spec_id, "pod_triager").hunt_id == ""
