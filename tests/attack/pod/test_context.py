"""Unit tier: the in-memory context-management component - the experiment log,
the dedup ledger, the filtered agent context, the
BaseMessage id stamping (D84-4), and (D84-2) the pod-owned canonical spec hash
+ HuntSession address derivation. The interim token-aware `curate_messages`
compaction is removed (D84-13: #95's shared `CompactionManager` replaces it)."""
from polymerhus.attack.hunting.pod.context import (
    ExperimentLog,
    _dicts_to_lc,
    _lc_to_dicts,
)
from polymerhus.attack.hunting.pod.pod_memory import PodMemoryStore, spec_identifier
from polymerhus.attack.hunting.pod.types import (
    Interpretation,
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
    log.record_variant(VariantSpec(ref="v1", parent_ref="v0", spec={}))
    log.record_interpretation(Interpretation(variant="v0", classification="symptom-absent",
                                             note="no reflection"))
    ctx = log.triager_context({"target_identity": "svc"},
                              RawObservation(status=200, body="hi"))
    assert "v0" in ctx and "v1" in ctx           # sees what was tried
    assert "never mine a duplicate" in ctx.lower()


def test_runner_context_lists_executed_signatures():
    log = ExperimentLog()
    log.mark_executed("sig-abc")
    ctx = log.runner_context({"target_identity": "svc"}, feedback="vary the encoding",
                             iteration=2, budget=8)
    assert "sig-abc" in ctx
    assert "vary the encoding" in ctx
    assert "Lap 2" in ctx


def test_canonical_spec_hash_is_deterministic_and_shared_with_the_hunter():
    """D84-2: the canonical spec fingerprint is owned by the pod; the parent
    hunting agent's experiment-log key uses the SAME hash (the #164 rewrite
    dropped its `_canonical_hash` re-export - the pod's `canonical_spec_hash`
    is the single source, kept byte-identical so the pod's spec keys and the
    parent's experiment log never drift). Deterministic across calls and
    insensitive to dict key order (equal dicts hash equal, C9)."""
    from polymerhus.attack.hunting.pod.context import canonical_spec_hash

    spec_a = {"verification_symptoms": ["a"],
              "payload_vector_space": {"method": "GET", "params": {"a": 1}}}
    spec_b = {"target_identity": "svc", "assumptions": [], "rationale": "r"}

    for spec in (spec_a, spec_b):
        first = canonical_spec_hash(spec)
        assert first == canonical_spec_hash(spec)      # stable across calls
        assert len(first) == 64                        # sha256 hexdigest

    # Key order never changes the hash (C9: an identical spec is never
    # dispatched twice), and two distinct specs never collide.
    shuffled = {"payload_vector_space": {"params": {"a": 1}, "method": "GET"},
                "verification_symptoms": ["a"]}
    assert canonical_spec_hash(spec_a) == canonical_spec_hash(shuffled)
    assert canonical_spec_hash(spec_a) != canonical_spec_hash(spec_b)


def test_start_run_clears_stale_summaries_across_all_on_file_orders(tmp_path):
    """D84-37 / the consolidated code-review finding: a re-run must NOT serve a
    prior run's `experiment_summary` for ANY order the new run does not reach
    with a fresh P3 write. `start_run` clears the stale summary from every
    on-file order, not just order 0, so the persisted log is the current truth
    (a budget/triager terminate mid-stretch at a higher order cannot leak the
    old order's summary to the Triager)."""
    store = PodMemoryStore(tmp_path)
    spec_id = spec_identifier("sqli", "blind")
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
    """D84-2: `_pod_session_address` derives the pod's `HuntSession` address with
    the canonical spec hash as the per-spec discriminator and the given role, so
    concurrent pod sessions on one hunt never collide (#94); an empty hunt_id
    defaults to "" rather than shifting the address."""
    from polymerhus.attack.hunting.pod.context import canonical_spec_hash
    from polymerhus.attack.hunting.pod.pod import _pod_session_address

    spec = {"target_identity": "svc", "payload_vector_space": {"method": "GET"}}
    addr = _pod_session_address("run-1", "hunt-A", spec, "pod_runner")

    assert addr.role_id == "pod_runner"
    assert addr.spec == canonical_spec_hash(spec)
    assert addr.run_id == "run-1"
    assert addr.hunt_id == "hunt-A"
    assert addr.thread_id.startswith("run-1:hunt-A:")
    # The spec hash discriminates the thread: two specs on one hunt diverge.
    other = _pod_session_address("run-1", "hunt-A",
                                 {"target_identity": "svc",
                                  "payload_vector_space": {"method": "POST"}},
                                 "pod_runner")
    assert addr.thread_id != other.thread_id
    # A missing hunt_id never shifts the address (empty discriminators are dropped).
    assert _pod_session_address("run-1", "", spec, "pod_triager").hunt_id == ""
